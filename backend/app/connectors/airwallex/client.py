"""The Airwallex client: one set of operations over either transport (system brief §10).

`client_from_env()` is the switch: `AIRWALLEX_MODE` picks the transport (`select_transport`),
`AIRWALLEX_API_VERSION` pins the version sent on every call. The client decides nothing about
money. It builds each body from `Money` through `to_provider_decimal`, sends it once, and returns
typed results or raises the typed errors of `errors.py`:
- a timeout, a 5xx or an unreadable success on a POST → `OutcomeUnknown`, never a second POST;
- a 429 → retried here with the same `request_id`, exponential backoff with jitter, at most 3
  attempts; a GET that times out or fails with a 5xx is retried the same way (it moves nothing);
- a 401 → one re-login, then the same request once; a second 401 → `ProviderError(auth_fail)`;
- a replayed `request_id` (`duplicate_request_id`, `request_id_duplicate`, 409, or the
  conversions' `400 invalid_argument` "request_id '…' has been used") → `DuplicateRequest`; the
  caller finds the original with `find_transfer`/`find_conversion`.

The bearer token is cached until 60 s before its 30-minute lifetime ends. No message, log line or
exception built here carries the key, the client id or the token.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import quote as urlquote

from app.finance.schemas import EXPONENT, Money, Receipt, to_provider_decimal

from .errors import ConfigError, DuplicateRequest, OutcomeUnknown, ProviderError
from .transport import Transport, TransportTimeout, api_version_from, select_transport

log = logging.getLogger(__name__)

LOGIN_PATH = "/api/v1/authentication/login"
# The connected-accounts list; the path is our reading of the docs and T15 records the real one.
CONNECTED_PROBE_PATH = "/api/v1/accounts"
TOKEN_LIFETIME_S = 1800
RENEW_BEFORE_S = 60
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 0.5
DUPLICATE_CODES = frozenset({"duplicate_request_id", "request_id_duplicate"})
# The conversions endpoint refuses a replay as `400 invalid_argument` with this message
# (sandbox, api_version 2024-09-27): "request_id '<id>' has been used in the past. ...".
USED_REQUEST_ID = re.compile(r"\brequest_id\b.*\bhas been used\b", re.IGNORECASE | re.DOTALL)
# A quote is refused without its validity (`field_required`); the conversion follows at once.
QUOTE_VALIDITY = "MIN_15"
# `reason` and `reference` are required on a payout; the reason is one of the provider's own.
TRANSFER_REASON = "business_expenses"
CONVERSIONS_PATH = "/api/v1/fx/conversions"

LegMode = Literal["A", "B"]
ConnectedSetting = Literal["auto", "on", "off"]


# -------------------------------------------------------------------------------- leg plan


@dataclass(frozen=True)
class Leg:
    """How one leg kind runs in a mode, and the label its receipt carries."""

    op: str
    label: str
    on_behalf_of: bool = False


FX_OP = "POST /api/v1/fx/quotes/create then POST /api/v1/fx/conversions/create"
LEG_PLAN: dict[str, dict[str, Leg]] = {
    "A": {
        "advance": Leg("POST /api/v1/connected_account_transfers/create",
                       "advance (connected-account transfer)"),
        "repayment": Leg("POST /api/v1/charges/create", "repayment (charge)"),
        "fx": Leg(FX_OP, "FX conversion"),
        "payout": Leg("POST /api/v1/transfers/create", "payout on behalf of borrower-a",
                      on_behalf_of=True),
    },
    "B": {
        "advance": Leg("POST /api/v1/simulation/deposit/create",
                       "advance inflow (sandbox simulation)"),
        "repayment": Leg("none (ledger only)", "repayment (simulated)"),
        "fx": Leg(FX_OP, "FX conversion"),
        "payout": Leg("POST /api/v1/transfers/create", "payout from the operator account"),
    },
}


def leg_plan(mode: LegMode) -> dict[str, Leg]:
    """Advance, repayment, fx and payout for Mode A (connected accounts) or Mode B (fallback)."""
    return dict(LEG_PLAN[mode])


def connected_setting(env: Mapping[str, str] | None = None) -> ConnectedSetting:
    env = os.environ if env is None else env
    setting = env.get("AIRWALLEX_CONNECTED", "").strip().lower() or "auto"
    if setting not in ("auto", "on", "off"):
        raise ConfigError("AIRWALLEX_CONNECTED must be auto, on or off")
    return setting


# ---------------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Balance:
    currency: str
    available: Money
    pending: Money


# Where each object kind keeps the amount it moves (a conversion moves its sell side).
AMOUNT_KEYS = {
    "transfer": ("transfer_amount", "transfer_currency"),
    "conversion": ("sell_amount", "sell_currency"),
    "connected_account_transfer": ("amount", "currency"),
    "charge": ("amount", "currency"),
    "deposit": ("amount", "currency"),
}


@dataclass(frozen=True)
class ProviderObject:
    """A provider object as a create, a GET or a lookup returned it; `amount` is canonical."""

    kind: str
    provider_id: str
    request_id: str | None
    status: str | None
    amount: str | None
    currency: str | None
    raw: dict

    @classmethod
    def parse(cls, kind: str, raw: Any, request_id: str | None = None) -> ProviderObject:
        """`request_id` is the one sent, so an unreadable answer names it."""
        if not isinstance(raw, dict):
            raise OutcomeUnknown(request_id, f"{kind} answer is not an object")
        provider_id = raw.get("id") or raw.get(f"{kind}_id")
        if not isinstance(provider_id, str):
            raise OutcomeUnknown(request_id, f"{kind} answer has no id")
        amount_key, currency_key = AMOUNT_KEYS[kind]
        currency = raw.get(currency_key)
        amount = raw.get(amount_key)
        return cls(
            kind=kind,
            provider_id=provider_id,
            request_id=raw.get("request_id"),
            status=raw.get("status"),
            amount=None if amount is None else provider_amount(amount, currency),
            currency=currency,
            raw=raw,
        )

    @property
    def raw_keys(self) -> list[str]:
        return sorted(self.raw)

    def receipt(
        self,
        *,
        leg_kind: str,
        label: str,
        mode: str,
        observed_at: datetime,
        request_id: str | None = None,
    ) -> Receipt:
        """The C4 receipt for the leg this object carries; `label` comes from `leg_plan`.

        `request_id` is the leg id, needed for an object that has none (a simulated deposit);
        an object that carries one must carry the same."""
        if request_id and self.request_id and request_id != self.request_id:
            raise ValueError("the object belongs to another leg")
        return Receipt(
            provider_id=self.provider_id, request_id=self.request_id or request_id, kind=leg_kind,
            status=self.status, amount=self.amount, currency=self.currency, label=label,
            mode=mode, raw_keys=self.raw_keys, observed_at=observed_at,
        )


def provider_amount(value: Any, currency: str | None) -> str:
    """A provider amount (JSON number or string) as the canonical decimal string; an amount
    with more places than its currency has is refused, never rounded."""
    if isinstance(value, bool) or not isinstance(value, int | str | Decimal):
        raise OutcomeUnknown(None, "a provider amount is not a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise OutcomeUnknown(None, "a provider amount does not parse") from None
    if not number.is_finite():
        raise OutcomeUnknown(None, "a provider amount is not finite")
    if currency in EXPONENT:
        scaled = number.scaleb(EXPONENT[currency])
        if scaled != scaled.to_integral_value():
            raise OutcomeUnknown(None, f"a {currency} amount has more places than the currency")
        number = Decimal(int(scaled)).scaleb(-EXPONENT[currency])  # padded: 1.5 -> 1.50
    return format(number, "f")


def to_money(value: Any, currency: str) -> Money:
    """A provider amount in minor units; one that does not fit the currency is refused."""
    number = Decimal(provider_amount(value, currency)).scaleb(EXPONENT[currency])
    return Money(minor=int(number), currency=currency)


# ----------------------------------------------------------------------------------- client


class AirwallexClient:
    """`AirwallexClient(transport, clock)`: every provider operation the gateway needs."""

    def __init__(
        self,
        transport: Transport,
        clock: Callable[[], float] | None = None,
        *,
        api_version: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.transport = transport
        self.clock = clock or time.monotonic
        self.api_version = api_version or api_version_from()
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._token: str | None = None
        self._renew_at = 0.0

    def __repr__(self) -> str:
        return f"AirwallexClient(mode={self.mode}, api_version={self.api_version})"

    @property
    def mode(self) -> str:
        return self.transport.mode

    # ------------------------------------------------------------------------ auth

    def login(self) -> None:
        """A fresh bearer token; any refusal is `ProviderError(auth_fail)` or retryable."""
        creds = self.transport.credentials
        headers = {"x-client-id": creds.client_id, "x-api-key": creds.api_key,
                   "x-api-version": self.api_version, "Content-Type": "application/json"}
        self._token = None
        try:
            answer = self.transport.send("POST", LOGIN_PATH, None, headers)
        except TransportTimeout:
            raise ProviderError("timeout", None, retryable=True) from None
        log.info("airwallex POST %s -> %s", LOGIN_PATH, answer.status)
        body = answer.json if isinstance(answer.json, dict) else {}
        if answer.status in (401, 403):
            raise ProviderError("auth_fail", answer.status)
        if not 200 <= answer.status < 300:
            retryable = answer.status == 429 or answer.status >= 500
            raise ProviderError(_text(body, "code") or f"http_{answer.status}", answer.status,
                                retryable=retryable)
        token = body.get("token")
        if not isinstance(token, str) or not token:
            raise ProviderError("malformed_body", answer.status, retryable=True)
        self._token = token
        self._renew_at = self.clock() + TOKEN_LIFETIME_S - RENEW_BEFORE_S

    def _ensure_token(self) -> None:
        if self._token is None or self.clock() >= self._renew_at:
            self.login()

    def _scrub(self, text: str) -> str:
        creds = self.transport.credentials
        for secret in (creds.api_key, creds.client_id, self._token):
            if secret:
                text = text.replace(secret, "<hidden>")
        return text

    # --------------------------------------------------------------------- request

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        request_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        failures = 0
        relogged = False
        while True:
            self._ensure_token()
            sent = {"Authorization": f"Bearer {self._token}", "x-api-version": self.api_version,
                    "Content-Type": "application/json", **(headers or {})}
            try:
                answer = self.transport.send(method, path, body, sent)
            except TransportTimeout as lost:
                log.warning("airwallex %s %s request_id=%s -> no answer (after_send=%s)",
                            method, path, request_id, lost.after_send)
                if method != "GET":
                    reason = "timeout after send" if lost.after_send else "timeout"
                    raise OutcomeUnknown(request_id, reason) from None
                answer = None
            if answer is None:  # a GET moves nothing, so it is sent again
                failures = self._retry(failures, ProviderError("timeout", None, retryable=True))
                continue
            status = answer.status
            log.info("airwallex %s %s request_id=%s -> %s", method, path, request_id, status)
            if 200 <= status < 300:
                if isinstance(answer.json, dict | list):
                    return answer.json
                if method != "GET":
                    raise OutcomeUnknown(request_id, f"unreadable {status} body")
                failures = self._retry(
                    failures, ProviderError("malformed_body", status, retryable=True))
                continue
            envelope = answer.json if isinstance(answer.json, dict) else {}
            code = _text(envelope, "code")
            if status == 401:
                if relogged:
                    raise ProviderError("auth_fail", 401)
                relogged = True
                self._token = None
                continue
            if request_id is not None and status == 409:
                raise DuplicateRequest(request_id, in_flight=True, code=code)
            if request_id is not None and _replayed(status, code, envelope):
                raise DuplicateRequest(request_id, in_flight=False, code=code)
            if status >= 500 and method != "GET":
                raise OutcomeUnknown(request_id, f"http {status}")
            if status == 429 or status >= 500:
                fallback = "too_many_requests" if status == 429 else "server_error"
                failures = self._retry(
                    failures, ProviderError(code or fallback, status, retryable=True))
                continue
            raise ProviderError(
                code or f"http_{status}",
                status,
                message=self._scrub(_text(envelope, "message") or ""),
                source=_text(envelope, "source"),
                trace_id=_text(envelope, "trace_id"),
            )

    def _retry(self, failures: int, spent: ProviderError) -> int:
        """Back off before the next attempt, or raise `spent` once the attempts are used up."""
        failures += 1
        if failures >= MAX_ATTEMPTS:
            raise spent
        self._backoff(failures)
        return failures

    def _backoff(self, failures: int) -> None:
        delay = BACKOFF_BASE_S * 2 ** (failures - 1)
        self._sleep(delay + self._rng.uniform(0, delay))

    def _items(self, answer: Any) -> list:
        items = answer.get("items") if isinstance(answer, dict) else answer
        if not isinstance(items, list):
            raise OutcomeUnknown(None, "a list answer has no items")
        return items

    # ----------------------------------------------------------------- operations

    def balances(self, *, on_behalf_of: str | None = None) -> list[Balance]:
        """Current balances; a currency the ledger does not carry is left out."""
        headers = {"x-on-behalf-of": on_behalf_of} if on_behalf_of else None
        found = []
        for item in self._items(self._request("GET", "/api/v1/balances/current", headers=headers)):
            currency = item.get("currency") if isinstance(item, dict) else None
            if currency in EXPONENT:
                found.append(Balance(currency, to_money(item.get("available_amount", 0), currency),
                                     to_money(item.get("pending_amount", 0), currency)))
        return found

    def global_accounts(self) -> list[dict]:
        return self._items(self._request("GET", "/api/v1/global_accounts"))

    def global_account_in(self, currency: str) -> str | None:
        """The id of the first Global Account that takes `currency` (`account_currencies`)."""
        for account in self.global_accounts():
            if isinstance(account, dict) and currency in account_currencies(account):
                account_id = account.get("id")
                if isinstance(account_id, str) and account_id:
                    return account_id
        return None

    def probe_connected(self, setting: ConnectedSetting | None = None) -> LegMode:
        """Mode A only when the connected-accounts list answers 200 with an `ACTIVE` account;
        an account with no status, or none, is not enabled. `on` without one fails."""
        setting = setting or connected_setting()
        if setting == "off":
            return "B"
        try:
            self._ensure_token()
        except ProviderError as refused:
            if refused.code == "auth_fail":
                raise  # bad credentials fail the start; they are not an unclear probe
        try:
            if active_account(self._items(self._request("GET", CONNECTED_PROBE_PATH))):
                return "A"
            answer = "200 with no active connected account"
        except (ProviderError, OutcomeUnknown) as unclear:
            answer = f"{getattr(unclear, 'http', None)} {getattr(unclear, 'code', '')}".strip()
        if setting == "on":
            raise ConfigError(f"AIRWALLEX_CONNECTED=on, but the provider answered {answer}")
        return "B"

    def quote(self, *, sell_currency: str, buy_currency: str, amount: Money) -> dict:
        """An FX quote for `amount`, given in either the sell or the buy currency."""
        body = {"sell_currency": sell_currency, "buy_currency": buy_currency,
                **_side(amount, sell_currency, buy_currency), "validity": QUOTE_VALIDITY}
        return self._request("POST", "/api/v1/fx/quotes/create", body)

    def create_conversion(
        self,
        request_id: str,
        *,
        sell_currency: str,
        buy_currency: str,
        amount: Money,
        quote_id: str | None = None,
    ) -> ProviderObject:
        body = {"request_id": request_id, "sell_currency": sell_currency,
                "buy_currency": buy_currency, **_side(amount, sell_currency, buy_currency)}
        if quote_id is not None:
            body["quote_id"] = quote_id
        return self._create("conversion", f"{CONVERSIONS_PATH}/create", body, request_id)

    def get_conversion(self, conversion_id: str) -> ProviderObject:
        path = f"{CONVERSIONS_PATH}/{urlquote(conversion_id, safe='')}"
        return ProviderObject.parse("conversion", self._request("GET", path))

    def find_conversion(self, request_id: str) -> list[ProviderObject]:
        return self._find("conversion", CONVERSIONS_PATH, request_id)

    def create_transfer(
        self,
        request_id: str,
        *,
        beneficiary_id: str,
        amount: Money,
        reference: str | None = None,
        transfer_method: str = "LOCAL",
        on_behalf_of: str | None = None,
        reason: str = TRANSFER_REASON,
    ) -> ProviderObject:
        """A payout; Mode A sends it on behalf of the connected account. The provider requires a
        reference, so one not given (or empty) is the `request_id`."""
        body = {"request_id": request_id, "beneficiary_id": beneficiary_id,
                "source_currency": amount.currency, "transfer_currency": amount.currency,
                "transfer_amount": to_provider_decimal(amount), "transfer_method": transfer_method,
                "reason": reason, "reference": reference or request_id}
        headers = {"x-on-behalf-of": on_behalf_of} if on_behalf_of else None
        return self._create("transfer", "/api/v1/transfers/create", body, request_id, headers)

    def get_transfer(self, transfer_id: str) -> ProviderObject:
        """Reconciliation's truth: the transfer as the provider holds it now."""
        path = f"/api/v1/transfers/{urlquote(transfer_id, safe='')}"
        return ProviderObject.parse("transfer", self._request("GET", path))

    def find_transfer(self, request_id: str) -> list[ProviderObject]:
        return self._find("transfer", "/api/v1/transfers", request_id)

    def connected_account_transfer(
        self, request_id: str, *, amount: Money, destination: str
    ) -> ProviderObject:
        """Mode A advance: fund the connected account from the platform balance."""
        body = {"request_id": request_id, "amount": to_provider_decimal(amount),
                "currency": amount.currency, "destination": destination}
        return self._create("connected_account_transfer",
                            "/api/v1/connected_account_transfers/create", body, request_id)

    def charge(self, request_id: str, *, amount: Money, source: str) -> ProviderObject:
        """Mode A repayment: charge the connected account."""
        body = {"request_id": request_id, "amount": to_provider_decimal(amount),
                "currency": amount.currency, "source": source}
        return self._create("charge", "/api/v1/charges/create", body, request_id)

    def simulate_deposit(
        self,
        *,
        amount: Money,
        global_account_id: str,
        reference: str | None = None,
        status: str | None = None,
    ) -> ProviderObject:
        """Mode B advance (sandbox only): a deposit into a Global Account in `amount`'s currency.

        `amount` is the converter's string read as a `Decimal`, sent as a JSON number."""
        body: dict[str, Any] = {"amount": Decimal(to_provider_decimal(amount)),
                                "global_account_id": global_account_id}
        if reference is not None:
            body["reference"] = reference
        if status is not None:
            body["status"] = status
        raw = self._request("POST", "/api/v1/simulation/deposit/create", body)
        return ProviderObject.parse("deposit", raw)

    def simulate_transition(
        self, transfer_id: str, next_status: str, *, failure_type: str | None = None
    ) -> ProviderObject:
        """Sandbox only: move a transfer to its next status (`PAID`, or `FAILED`).

        The sandbox moves a payout on by itself (it reads back `PROCESSING` straight after the
        create) and answered a transition with a 500. So a transition that is refused or left
        unknown is read back, and a transfer already at `next_status` is the answer. A refusal
        otherwise stands. An unknown one whose transfer did not move is sent again (it is keyed
        on the transfer and creates nothing), at most `MAX_ATTEMPTS` times, then raises
        `OutcomeUnknown` naming the transfer and the status it holds."""
        body = {"next_status": next_status}
        if failure_type is not None:
            body["failure_type"] = failure_type
        path = f"/api/v1/simulation/transfers/{urlquote(transfer_id, safe='')}/transition"
        before: str | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return ProviderObject.parse("transfer", self._request("POST", path, body))
            except ProviderError:
                now = self.get_transfer(transfer_id)
                if now.status == next_status:
                    return now
                raise
            except OutcomeUnknown as unknown:
                now = self.get_transfer(transfer_id)
                if now.status == next_status:
                    return now
                if attempt == MAX_ATTEMPTS or before not in (None, now.status):
                    raise OutcomeUnknown(
                        None, f"transition to {next_status}: {unknown.reason}, transfer at "
                        f"{now.status}", provider_id=transfer_id) from None
                before = now.status
                self._backoff(attempt)
        raise AssertionError("unreachable")

    def _create(
        self,
        kind: str,
        path: str,
        body: dict,
        request_id: str,
        headers: Mapping[str, str] | None = None,
    ) -> ProviderObject:
        raw = self._request("POST", path, body, request_id=request_id, headers=headers)
        return ProviderObject.parse(kind, raw, request_id)

    def _find(self, kind: str, path: str, request_id: str) -> list[ProviderObject]:
        answer = self._request("GET", f"{path}?request_id={urlquote(request_id, safe='')}")
        return [ProviderObject.parse(kind, item) for item in self._items(answer)]


def active_account(answer: Any) -> str | None:
    """The id of the first `ACTIVE` account in a connected-accounts list (its items, or the
    answer holding them), or None."""
    items = answer.get("items") if isinstance(answer, dict) else answer
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("status") == "ACTIVE":
            account = item.get("id")
            if isinstance(account, str) and account:
                return account
    return None


def account_currencies(account: Mapping[str, Any]) -> list[str]:
    """The currencies a Global Account takes, its own first: `currency` when it carries one (as
    the sandbox did before 2024-09-27), then `required_features[].currency`, then
    `supported_features[].currency` (the 2024-09-27 shape, which has no `currency` key)."""
    found: list[str] = []
    own = account.get("currency")
    candidates = [own] if isinstance(own, str) else []
    for key in ("required_features", "supported_features"):
        features = account.get(key)
        for feature in features if isinstance(features, list) else []:
            if isinstance(feature, dict):
                candidates.append(feature.get("currency"))
    for currency in candidates:
        if isinstance(currency, str) and currency and currency not in found:
            found.append(currency)
    return found


def _replayed(status: int, code: str | None, envelope: Mapping[str, Any]) -> bool:
    """A refusal that says the `request_id` was used before, in any of the provider's spellings."""
    if code in DUPLICATE_CODES:
        return True
    message = _text(envelope, "message") or ""
    return status == 400 and code == "invalid_argument" and bool(USED_REQUEST_ID.search(message))


def _text(envelope: Mapping[str, Any], key: str) -> str | None:
    value = envelope.get(key)
    return value if isinstance(value, str) else None


def _side(amount: Money, sell_currency: str, buy_currency: str) -> dict[str, str]:
    """`buy_amount` or `sell_amount`, by the currency the amount is in; exactly one."""
    if sell_currency == buy_currency:
        raise ValueError("a conversion needs two currencies")
    if amount.currency == buy_currency:
        return {"buy_amount": to_provider_decimal(amount)}
    if amount.currency == sell_currency:
        return {"sell_amount": to_provider_decimal(amount)}
    raise ValueError("the amount is in neither the sell nor the buy currency")


def client_from_env(
    env: Mapping[str, str] | None = None,
    clock: Callable[[], float] | None = None,
    **fake_options: Any,
) -> AirwallexClient:
    """The one switch: the transport `AIRWALLEX_MODE` names, the pinned API version."""
    env = os.environ if env is None else env
    if clock is not None:
        fake_options.setdefault("clock", clock)
    transport = select_transport(env, **fake_options)
    return AirwallexClient(transport, clock, api_version=api_version_from(env))

"""The Airwallex client: one set of operations over either transport (system brief §10).

`client_from_env()` is the switch: `AIRWALLEX_MODE` picks the transport (`select_transport`),
`AIRWALLEX_API_VERSION` pins the version sent on every call. The client decides nothing about
money. It builds each body from `Money` through `to_provider_decimal`, sends it once, and returns
typed results or raises the typed errors of `errors.py`:
- a timeout, a 5xx or an unreadable success on a POST → `OutcomeUnknown`, never a second POST;
- a 429 → retried here with the same `request_id`, exponential backoff with jitter, at most 3
  attempts; a GET that times out or fails with a 5xx is retried the same way (it moves nothing);
- a 401 → one re-login, then the same request once; a second 401 → `ProviderError(auth_fail)`;
- a replayed `request_id` (`duplicate_request_id`, `request_id_duplicate`, 409) →
  `DuplicateRequest`; the caller finds the original with `find_transfer`/`find_conversion`.

The bearer token is cached until 60 s before its 30-minute lifetime ends. No message, log line or
exception built here carries the key, the client id or the token.
"""

from __future__ import annotations

import logging
import os
import random
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

LegMode = Literal["A", "B"]
ConnectedSetting = Literal["auto", "on", "off"]


# -------------------------------------------------------------------------------- leg plan


@dataclass(frozen=True)
class Leg:
    """How one leg kind runs in a mode, and the label its receipt carries."""

    op: str
    label: str
    on_behalf_of: bool = False


FX_OP = "POST /api/v1/fx/quotes/create then POST /api/v1/conversions/create"
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
    def parse(cls, kind: str, raw: Any) -> ProviderObject:
        if not isinstance(raw, dict):
            raise OutcomeUnknown(None, f"{kind} answer is not an object")
        provider_id = raw.get("id") or raw.get(f"{kind}_id")
        if not isinstance(provider_id, str):
            raise OutcomeUnknown(raw.get("request_id"), f"{kind} answer has no id")
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
    """A provider amount (JSON number or string) as the canonical decimal string."""
    if isinstance(value, bool) or not isinstance(value, int | str | Decimal):
        raise OutcomeUnknown(None, "a provider amount is not a number")
    try:
        number = Decimal(str(value))
        if currency in EXPONENT:
            number = number.quantize(Decimal(1).scaleb(-EXPONENT[currency]))
    except InvalidOperation:
        raise OutcomeUnknown(None, "a provider amount does not parse") from None
    if not number.is_finite():
        raise OutcomeUnknown(None, "a provider amount is not finite")
    return format(number, "f")


def to_money(value: Any, currency: str) -> Money:
    """A provider amount in minor units; one that does not fit the currency is refused."""
    number = Decimal(provider_amount(value, currency)).scaleb(EXPONENT[currency])
    if number != number.to_integral_value():
        raise OutcomeUnknown(None, f"a {currency} amount has more places than the currency")
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
            code = body.get("code") if isinstance(body.get("code"), str) else None
            retryable = answer.status == 429 or answer.status >= 500
            raise ProviderError(code or f"http_{answer.status}", answer.status, retryable=retryable)
        token = body.get("token")
        if not isinstance(token, str) or not token:
            raise ProviderError("malformed_body", answer.status, retryable=True)
        self._token = token
        self._renew_at = self.clock() + TOKEN_LIFETIME_S - RENEW_BEFORE_S

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
            if self._token is None or self.clock() >= self._renew_at:
                self.login()
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
                failures += 1
                if failures < MAX_ATTEMPTS:
                    self._backoff(failures)
                    continue
                raise ProviderError("timeout", None, retryable=True) from None
            status = answer.status
            log.info("airwallex %s %s request_id=%s -> %s", method, path, request_id, status)
            if 200 <= status < 300:
                if isinstance(answer.json, dict | list):
                    return answer.json
                if method != "GET":
                    raise OutcomeUnknown(request_id, f"unreadable {status} body")
                failures += 1
                if failures < MAX_ATTEMPTS:
                    self._backoff(failures)
                    continue
                raise ProviderError("malformed_body", status, retryable=True)
            envelope = answer.json if isinstance(answer.json, dict) else {}
            code = envelope.get("code") if isinstance(envelope.get("code"), str) else None
            if status == 401:
                if relogged:
                    raise ProviderError("auth_fail", 401)
                relogged = True
                self._token = None
                continue
            if request_id is not None and status == 409:
                raise DuplicateRequest(request_id, in_flight=True, code=code)
            if request_id is not None and code in DUPLICATE_CODES:
                raise DuplicateRequest(request_id, in_flight=False, code=code)
            if status >= 500 and method != "GET":
                raise OutcomeUnknown(request_id, f"http {status}")
            if status == 429 or status >= 500:
                failures += 1
                if failures < MAX_ATTEMPTS:
                    self._backoff(failures)
                    continue
                fallback = "too_many_requests" if status == 429 else "server_error"
                raise ProviderError(code or fallback, status, retryable=True)
            message = envelope.get("message")
            raise ProviderError(
                code or f"http_{status}",
                status,
                message=self._scrub(message) if isinstance(message, str) else "",
                source=envelope.get("source") if isinstance(envelope.get("source"), str) else None,
                trace_id=(envelope.get("trace_id")
                          if isinstance(envelope.get("trace_id"), str) else None),
            )

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

    def probe_connected(self, setting: ConnectedSetting | None = None) -> LegMode:
        """Mode A only on a clear 200 from the connected-accounts list; `on` without it fails."""
        setting = setting or connected_setting()
        if setting == "off":
            return "B"
        try:
            self._request("GET", CONNECTED_PROBE_PATH)
            return "A"
        except (ProviderError, OutcomeUnknown) as unclear:
            answer = f"{getattr(unclear, 'http', None)} {getattr(unclear, 'code', '')}".strip()
        if setting == "on":
            raise ConfigError(f"AIRWALLEX_CONNECTED=on, but the provider answered {answer}")
        return "B"

    def quote(self, *, sell_currency: str, buy_currency: str, amount: Money) -> dict:
        """An FX quote for `amount`, given in either the sell or the buy currency."""
        body = {"sell_currency": sell_currency, "buy_currency": buy_currency,
                **_side(amount, sell_currency, buy_currency)}
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
        return self._create("conversion", "/api/v1/conversions/create", body, request_id)

    def get_conversion(self, conversion_id: str) -> ProviderObject:
        path = f"/api/v1/conversions/{urlquote(conversion_id, safe='')}"
        return ProviderObject.parse("conversion", self._request("GET", path))

    def find_conversion(self, request_id: str) -> list[ProviderObject]:
        return self._find("conversion", "/api/v1/conversions", request_id)

    def create_transfer(
        self,
        request_id: str,
        *,
        beneficiary_id: str,
        amount: Money,
        reference: str | None = None,
        transfer_method: str = "LOCAL",
        on_behalf_of: str | None = None,
    ) -> ProviderObject:
        """A payout; Mode A sends it on behalf of the connected account."""
        body = {"request_id": request_id, "beneficiary_id": beneficiary_id,
                "source_currency": amount.currency, "transfer_currency": amount.currency,
                "transfer_amount": to_provider_decimal(amount), "transfer_method": transfer_method}
        if reference is not None:
            body["reference"] = reference
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
        """Sandbox only: move a transfer to its next status (`PAID`, or `FAILED`)."""
        body = {"next_status": next_status}
        if failure_type is not None:
            body["failure_type"] = failure_type
        path = f"/api/v1/simulation/transfers/{urlquote(transfer_id, safe='')}/transition"
        return ProviderObject.parse("transfer", self._request("POST", path, body))

    def _create(
        self,
        kind: str,
        path: str,
        body: dict,
        request_id: str,
        headers: Mapping[str, str] | None = None,
    ) -> ProviderObject:
        raw = self._request("POST", path, body, request_id=request_id, headers=headers)
        try:
            return ProviderObject.parse(kind, raw)
        except OutcomeUnknown as unreadable:
            raise OutcomeUnknown(request_id, unreadable.reason) from None

    def _find(self, kind: str, path: str, request_id: str) -> list[ProviderObject]:
        answer = self._request("GET", f"{path}?request_id={urlquote(request_id, safe='')}")
        return [ProviderObject.parse(kind, item) for item in self._items(answer)]


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
    transport = select_transport(env, **fake_options)
    return AirwallexClient(transport, clock, api_version=api_version_from(env))

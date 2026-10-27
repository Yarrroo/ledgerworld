"""The provider's double: an in-memory Airwallex sandbox (design/modules/airwallex/fixtures/).

It speaks the same paths, bodies and envelopes as the sandbox (system brief §10), round-trips every
body through the wire encoding, and keeps state: balances per account, global accounts,
beneficiaries, quotes, conversions, transfers, connected-account transfers, charges and deposits.
What it pins, because the gateway's tests rely on it:
- a replayed `request_id` is REJECTED — `400 duplicate_request_id` (`request_id_duplicate` on
  connected-account transfers), `409` while the first call is held open — never answered with
  the original; the original is found by list-by-`request_id`;
- transfer `SCHEDULED → PROCESSING → SENT → PAID`, `PAID` is not final (`FAILED`, then
  `CANCELLED` five seconds later with the funds back); a skipped transition is refused;
- conversion `SCHEDULED → SETTLED | CANCELLED`, the sell side debited at create;
- request amounts are decimal strings, the deposit simulation's `amount` a JSON number.

Scenarios arm the next request(s) (`times`, None for every one): `happy`, `timeout_after_accept`
(stored, then no answer), `timeout_before_send` (nothing stored), `insufficient_funds`,
`rate_limited`, `auth_fail`, `server_error` (nothing stored), `malformed_body` (stored, then an
HTML body). The FX rate is fixed per seed and is fake; a live rate never enters a test.

The fake holds no credential, so a simulation process may import it; it reaches the rest of the
connector only inside functions, which keeps that import inside the credential fence.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.finance.schemas import EXPONENT, Money, to_decimal

SCENARIOS = (
    "happy", "timeout_after_accept", "timeout_before_send", "insufficient_funds",
    "rate_limited", "auth_fail", "server_error", "malformed_body",
)
PLATFORM = "platform"
CONNECTED_ACCOUNT = "acct-borrower-a"
TOKEN_LIFETIME_S = 1800
FAILED_TO_CANCELLED_S = 5
EPOCH = datetime(2026, 10, 28, tzinfo=UTC)

START = {
    "balances": [
        {"currency": "USD", "available_minor": 10000000},
        {"currency": "EUR", "available_minor": 0},
    ],
    "global_accounts": [{"id": "ga-usd-1", "currency": "USD"}],
    "beneficiaries": [{"id": "ben-payroll-1", "currency": "USD", "allowlisted": True}],
}
TRANSFER_EDGES = frozenset({
    ("SCHEDULED", "PROCESSING"), ("SCHEDULED", "OVERDUE"), ("OVERDUE", "CANCELLED"),
    ("SCHEDULED", "CANCELLATION_REQUESTED"), ("PROCESSING", "CANCELLATION_REQUESTED"),
    ("CANCELLATION_REQUESTED", "CANCELLED"), ("PROCESSING", "SENT"), ("SENT", "PAID"),
    ("PROCESSING", "FAILED"), ("SENT", "FAILED"), ("PAID", "FAILED"), ("FAILED", "CANCELLED"),
})
# USD per unit at seed 0; a seed moves every other currency by seed % 100 basis points.
USD_PER_UNIT = {
    "USD": Decimal(1), "EUR": Decimal("1.1100"), "GBP": Decimal("1.2700"),
    "JPY": Decimal("0.0066"), "AUD": Decimal("0.6600"), "HKD": Decimal("0.1280"),
    "SGD": Decimal("0.7400"), "CNY": Decimal("0.1400"),
}
# Where each collection lives; conversions sit under `fx/`.
COLLECTION_PATHS = {
    "transfers": "/api/v1/transfers", "conversions": "/api/v1/fx/conversions",
    "connected_account_transfers": "/api/v1/connected_account_transfers",
    "charges": "/api/v1/charges",
}
MONEY_CREATES = {f"{path}/create": collection for collection, path in COLLECTION_PATHS.items()}
# How long a quote lasts, in seconds, by the `validity` it was asked for.
QUOTE_VALIDITIES = {"MIN_1": 60, "MIN_15": 900, "MIN_30": 1800, "HR_1": 3600, "HR_4": 14400,
                    "HR_8": 28800, "HR_24": 86400}
# Before this version `/api/v1/transfers` is the connected-account transfer: a payout body is
# refused for its missing `currency`, and the list answers `incorrect_version`.
TRANSFERS_SINCE = "2024-09-27"
LOGIN = "/api/v1/authentication/login"
DECIMAL_STRING = re.compile(r"[0-9]+(\.[0-9]+)?")


class FakeClock:
    """Seconds since the fake's epoch; moves only when told to."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Recorded:
    """One request as the fake received it; login values and the token are hidden."""

    method: str
    path: str
    headers: dict[str, str]
    body: Any
    wire: str


class _Refuse(Exception):
    def __init__(self, status: int, code: str | None, message: str, source: str | None = None):
        self.status, self.code, self.message, self.source = status, code, message, source


class FakeTransport:
    """`FakeTransport(scenario, seed, clock, connected)` — the provider in memory."""

    mode = "fake"

    def __init__(
        self,
        scenario: str = "happy",
        seed: int = 0,
        clock: Callable[[], float] | None = None,
        connected: bool = False,
        *,
        times: int | None = 1,
    ) -> None:
        from .transport import Credentials

        self.seed = seed
        self.clock = clock or FakeClock()
        self.connected = connected
        self.credentials = Credentials("fake-client", "fake-key")
        self.requests: list[Recorded] = []
        self.arm(scenario, times)
        self._inject: list[tuple[int, Any]] = []
        self._held: set[str] = set()
        self._serial = 0
        self._tokens: dict[str, float] = {}
        self.balances: dict[str, dict[str, int]] = {
            PLATFORM: {b["currency"]: b["available_minor"] for b in START["balances"]},
        }
        if connected:
            self.balances[CONNECTED_ACCOUNT] = {}
        self.global_accounts = copy.deepcopy(START["global_accounts"])
        self.beneficiaries = {b["id"]: dict(b) for b in START["beneficiaries"]}
        self.quotes: dict[str, dict] = {}
        self.objects: dict[str, dict[str, dict]] = {
            "transfers": {}, "conversions": {}, "connected_account_transfers": {},
            "charges": {}, "deposits": {},
        }

    # ------------------------------------------------------------------- test controls

    def arm(self, scenario: str, times: int | None = 1) -> None:
        """The scenario answers the next `times` requests it applies to (None: all of them)."""
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario}")
        self._scenario, self._times = scenario, times

    def respond_next(self, status: int, body: Any) -> None:
        """Answer the next request after login with this status and body, unprocessed."""
        self._inject.append((status, body))

    def hold(self, request_id: str) -> None:
        """The next create with this id is stored but its answer never arrives; until
        `release`, a replay of the id is a 409."""
        self._held.add(request_id)

    def release(self, request_id: str) -> None:
        self._held.discard(request_id)

    def expire_tokens(self) -> None:
        """Every issued token stops working: the next call is a 401 credentials_expired."""
        for token in self._tokens:
            self._tokens[token] = float("-inf")

    def advance(self, seconds: float) -> None:
        """Move the fake's clock (a `FakeClock`) and run what fell due."""
        self.clock.advance(seconds)
        self._tick()

    def settle_conversion(self, conversion_id: str) -> dict:
        """The buy side arrives in the account the conversion was made for."""
        return self._finish_conversion(conversion_id, "buy", "SETTLED")

    def cancel_conversion(self, conversion_id: str) -> dict:
        """The sell side returns to the account the conversion was made for."""
        return self._finish_conversion(conversion_id, "sell", "CANCELLED")

    def _finish_conversion(self, conversion_id: str, side: str, status: str) -> dict:
        conv = self._get("conversions", conversion_id)
        if conv["status"] not in ("SCHEDULED", "OVERDUE"):
            raise ValueError(f"conversion {conversion_id} is {conv['status']}")
        self._credit(conv["_account"], conv[f"{side}_currency"], conv[f"_{side}_minor"])
        self._set_status(conv, status)
        return self._public(conv)

    def available(self, currency: str, account: str = PLATFORM) -> int:
        return self.balances.get(account, {}).get(currency, 0)

    def count(self, collection: str, request_id: str) -> int:
        return sum(1 for o in self.objects[collection].values() if o["request_id"] == request_id)

    # ------------------------------------------------------------------------- the wire

    def send(
        self,
        method: str,
        path: str,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        from .transport import Response, TransportTimeout, decode_body, encode_body

        wire = encode_body(json).decode() if json is not None else ""
        body = decode_body(wire) if wire else None
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        route = urlsplit(path).path
        self.requests.append(Recorded(method, path, _hide(headers), json, wire))
        self._tick()

        def answer(status: int, payload: Any) -> Any:
            text = encode_body(payload).decode() if payload is not None else ""
            return Response(status, decode_body(text), {"content-type": "application/json"}, text)

        if route != LOGIN and self._inject:
            return answer(*self._inject.pop(0))
        scenario = self._fires(method, route)
        if scenario == "timeout_before_send":
            raise TransportTimeout(after_send=False)
        try:
            if scenario == "auth_fail":
                raise _Refuse(401, "credentials_invalid", "Invalid credentials")
            if scenario == "rate_limited":
                raise _Refuse(429, "too_many_requests", "Too many requests")
            if scenario == "server_error":
                raise _Refuse(500, "internal_error", "Internal error")
            if scenario == "insufficient_funds":
                raise _Refuse(400, "balance_insufficient", "Insufficient wallet balance",
                              "transfer_amount")
            status, payload = self._handle(method, path, route, body, headers)
        except _Refuse as refusal:
            return answer(refusal.status, self._envelope(refusal))
        if scenario == "timeout_after_accept":
            raise TransportTimeout(after_send=True)
        if scenario == "malformed_body":
            return Response(200, None, {"content-type": "text/html"}, "<html>gateway error</html>")
        held = isinstance(body, Mapping) and body.get("request_id") in self._held
        if held and route in MONEY_CREATES and status == 201:
            raise TransportTimeout(after_send=True)
        return answer(status, payload)

    # ---------------------------------------------------------------------- dispatch

    def _fires(self, method: str, route: str) -> str | None:
        scenario = self._scenario
        if scenario == "happy" or self._times == 0:
            return None
        if scenario == "insufficient_funds":
            applies = method == "POST" and route in MONEY_CREATES
        else:
            applies = scenario == "auth_fail" or route != LOGIN
        if not applies:
            return None
        if self._times is not None:
            self._times -= 1
        return scenario

    def _handle(self, method: str, path: str, route: str, body: Any, headers: dict) -> tuple:
        if route == LOGIN and method == "POST":
            return self._login(headers)
        self._authenticate(headers)
        if route.startswith("/api/v1/transfers") and headers["x-api-version"] < TRANSFERS_SINCE:
            if route == "/api/v1/transfers/create":
                raise _Refuse(400, "field_required", "currency is required", "currency")
            raise _Refuse(400, "incorrect_version", "not served on this API version")
        query = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
        account = self._account(headers)
        if method == "GET":
            if route == "/api/v1/balances/current":
                return 200, self._balances(account)
            if route == "/api/v1/global_accounts":
                return 200, {"items": copy.deepcopy(self.global_accounts), "has_more": False}
            if route == "/api/v1/accounts":
                self._need_connected()
                return 200, {"items": [{"id": CONNECTED_ACCOUNT, "status": "ACTIVE"}],
                             "has_more": False}
            for collection, base in COLLECTION_PATHS.items():
                if route != base and not route.startswith(f"{base}/"):
                    continue
                object_id = route.removeprefix(base).removeprefix("/")
                if "/" in object_id:
                    break
                if object_id:
                    return 200, self._public(self._get(collection, object_id))
                return 200, self._list(collection, query.get("request_id"))
        if method == "POST" and isinstance(body, Mapping):
            if route == "/api/v1/fx/quotes/create":
                return 201, self._quote(body)
            if route in MONEY_CREATES:
                return 201, self._create(MONEY_CREATES[route], body, account)
            if route == "/api/v1/simulation/deposit/create":
                return 201, self._deposit(body)
            match = re.fullmatch(r"/api/v1/simulation/transfers/([^/]+)/transition", route)
            if match:
                return 200, self._transition(match.group(1), body)
        raise _Refuse(404, "resource_not_found", f"no route {method} {route}")

    def _login(self, headers: dict) -> tuple:
        client_id, api_key = headers.get("x-client-id", ""), headers.get("x-api-key", "")
        if (client_id, api_key) != (self.credentials.client_id, self.credentials.api_key):
            raise _Refuse(401, "credentials_invalid", "Invalid credentials")
        self._serial += 1
        token = f"fake-token-{self._serial}"
        self._tokens[token] = self.clock() + TOKEN_LIFETIME_S
        return 201, {"token": token, "expires_at": _iso(self.clock() + TOKEN_LIFETIME_S)}

    def _authenticate(self, headers: dict) -> None:
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme != "Bearer" or token not in self._tokens:
            raise _Refuse(401, "unauthorized", "Missing or unknown access token")
        if self._tokens[token] <= self.clock():
            raise _Refuse(401, "credentials_expired", "Access token expired")
        if not headers.get("x-api-version"):
            raise _Refuse(400, "invalid_argument", "x-api-version is required", "x-api-version")

    def _account(self, headers: dict) -> str:
        on_behalf_of = headers.get("x-on-behalf-of")
        if on_behalf_of is None:
            return PLATFORM
        self._need_connected()
        if on_behalf_of not in self.balances or on_behalf_of == PLATFORM:
            raise _Refuse(400, "invalid_argument", "unknown connected account", "x-on-behalf-of")
        return on_behalf_of

    def _need_connected(self) -> None:
        if not self.connected:
            raise _Refuse(403, "unauthorized", "Connected accounts are not enabled")

    # -------------------------------------------------------------------- operations

    def _balances(self, account: str) -> list[dict]:
        return [
            {"currency": c, "available_amount": _number(m, c), "pending_amount": _number(0, c),
             "reserved_amount": _number(0, c), "total_amount": _number(m, c)}
            for c, m in sorted(self.balances[account].items())
        ]

    def _quote(self, body: Mapping) -> dict:
        if body.get("validity") not in QUOTE_VALIDITIES:
            raise _Refuse(400, "field_required", "validity is required", "validity")
        sell, buy = _currency(body, "sell_currency"), _currency(body, "buy_currency")
        sell_minor, buy_minor, rate = self._price(sell, buy, body)
        self._serial += 1
        quote = {"quote_id": f"quote-{self._serial}", "client_rate": rate,
                 "sell_currency": sell, "buy_currency": buy,
                 "sell_amount": _string(sell_minor, sell), "buy_amount": _string(buy_minor, buy),
                 "validity": body["validity"],
                 "valid_to": _iso(self.clock() + QUOTE_VALIDITIES[body["validity"]])}
        self.quotes[quote["quote_id"]] = quote
        return dict(quote)

    def _price(self, sell: str, buy: str, body: Mapping, rate: Decimal | None = None) -> tuple:
        if sell == buy:
            raise _Refuse(400, "invalid_argument", "sell and buy currencies are equal")
        if ("buy_amount" in body) == ("sell_amount" in body):
            raise _Refuse(400, "invalid_argument", "exactly one of buy_amount or sell_amount")
        rate = rate or self.rate(sell, buy)
        if "buy_amount" in body:
            buy_minor = _minor(body, "buy_amount", buy)
            sell_value = _value(buy_minor, buy) * rate
            sell_minor = _to_minor(sell_value, sell, ROUND_HALF_UP)
        else:
            sell_minor = _minor(body, "sell_amount", sell)
            buy_minor = _to_minor(_value(sell_minor, sell) / rate, buy, ROUND_DOWN)
        return sell_minor, buy_minor, rate

    def rate(self, sell: str, buy: str) -> Decimal:
        """Sell units per buy unit, four places; seed 0 prices EUR at 1.1100 USD."""
        bump = 1 + Decimal(self.seed % 100) / 10000
        per = {c: v if c == "USD" else v * bump for c, v in USD_PER_UNIT.items()}
        return (per[buy] / per[sell]).quantize(Decimal("0.0001"))

    def _create(self, collection: str, body: Mapping, account: str) -> dict:
        request_id = body.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise _Refuse(400, "invalid_argument", "request_id is required", "request_id")
        used = self.count(collection, request_id)
        if used and request_id in self._held:
            raise _Refuse(409, None, "A request with this request_id is in progress")
        if used:
            code = ("request_id_duplicate" if collection == "connected_account_transfers"
                    else "duplicate_request_id")
            raise _Refuse(400, code, "The request_id has been used", "request_id")
        obj = getattr(self, f"_new_{collection}")(body, account)
        self._serial += 1
        obj.update(id=f"{collection[:-1].replace('_', '-')}-{self._serial}",
                   request_id=request_id, created_at=_iso(self.clock()),
                   updated_at=_iso(self.clock()))
        if collection == "conversions":
            obj["conversion_id"] = obj["id"]
        self.objects[collection][obj["id"]] = obj
        return self._public(obj)

    def _new_transfers(self, body: Mapping, account: str) -> dict:
        beneficiary = self.beneficiaries.get(body.get("beneficiary_id"))
        if beneficiary is None:
            raise _Refuse(400, "invalid_argument", "unknown beneficiary", "beneficiary_id")
        for key in ("reason", "reference"):
            if not isinstance(body.get(key), str) or not body[key]:
                raise _Refuse(400, "field_required", f"{key} is required", key)
        currency = _currency(body, "transfer_currency")
        if body.get("source_currency", currency) != currency:
            raise _Refuse(400, "invalid_argument", "the fake pays out in the source currency",
                          "source_currency")
        minor = _minor(body, "transfer_amount", currency)
        self._debit(account, currency, minor, "transfer_amount")
        return {"status": "SCHEDULED", "beneficiary_id": beneficiary["id"],
                "transfer_currency": currency, "source_currency": currency,
                "transfer_amount": _number(minor, currency),
                "source_amount": _number(minor, currency),
                "transfer_method": body.get("transfer_method", "LOCAL"),
                "reason": body["reason"], "reference": body["reference"],
                "_account": account, "_minor": minor}

    def _new_conversions(self, body: Mapping, account: str) -> dict:
        sell, buy = _currency(body, "sell_currency"), _currency(body, "buy_currency")
        rate = None
        if body.get("quote_id") is not None:
            quote = self.quotes.get(body["quote_id"])
            if quote is None or (quote["sell_currency"], quote["buy_currency"]) != (sell, buy):
                raise _Refuse(400, "invalid_argument", "unknown quote", "quote_id")
            rate = quote["client_rate"]
        sell_minor, buy_minor, rate = self._price(sell, buy, body, rate)
        self._debit(account, sell, sell_minor, "sell_amount")
        return {"status": "SCHEDULED", "sell_currency": sell, "buy_currency": buy,
                "sell_amount": _number(sell_minor, sell), "buy_amount": _number(buy_minor, buy),
                "client_rate": rate, "quote_id": body.get("quote_id"),
                "_account": account, "_sell_minor": sell_minor, "_buy_minor": buy_minor}

    def _new_connected_account_transfers(self, body: Mapping, account: str) -> dict:
        self._need_connected()
        destination = body.get("destination")
        if destination not in self.balances or destination == PLATFORM:
            raise _Refuse(400, "invalid_argument", "unknown connected account", "destination")
        currency = _currency(body, "currency")
        minor = _minor(body, "amount", currency)
        self._debit(PLATFORM, currency, minor, "amount")
        self._credit(destination, currency, minor)
        return {"status": "SETTLED", "amount": _number(minor, currency), "currency": currency,
                "destination": destination}

    def _new_charges(self, body: Mapping, account: str) -> dict:
        self._need_connected()
        source = body.get("source")
        if source not in self.balances or source == PLATFORM:
            raise _Refuse(400, "invalid_argument", "unknown connected account", "source")
        currency = _currency(body, "currency")
        minor = _minor(body, "amount", currency)
        self._debit(source, currency, minor, "amount")
        self._credit(PLATFORM, currency, minor)
        return {"status": "SETTLED", "amount": _number(minor, currency), "currency": currency,
                "source": source}

    def _deposit(self, body: Mapping) -> dict:
        account = next((g for g in self.global_accounts if g["id"] == body.get("global_account_id")),
                       None)
        if account is None:
            raise _Refuse(400, "invalid_argument", "unknown global account", "global_account_id")
        amount = body.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int | Decimal):
            raise _Refuse(400, "invalid_argument", "amount is a number", "amount")
        currency = account["currency"]
        minor = _to_minor(Decimal(amount), currency, None)
        if minor <= 0:
            raise _Refuse(400, "invalid_argument", "amount is positive", "amount")
        status = body.get("status") or "SETTLED"
        if status not in ("SETTLED", "PENDING"):
            raise _Refuse(400, "invalid_argument", "status is SETTLED or PENDING", "status")
        if status == "SETTLED":
            self._credit(PLATFORM, currency, minor)
        self._serial += 1
        deposit = {"id": f"deposit-{self._serial}", "request_id": None, "status": status,
                   "global_account_id": account["id"], "amount": _number(minor, currency),
                   "currency": currency, "reference": body.get("reference"),
                   "created_at": _iso(self.clock())}
        self.objects["deposits"][deposit["id"]] = deposit
        return dict(deposit)

    def _transition(self, transfer_id: str, body: Mapping) -> dict:
        transfer = self._get("transfers", transfer_id)
        target = body.get("next_status")
        if (transfer["status"], target) not in TRANSFER_EDGES:
            raise _Refuse(400, "invalid_argument",
                          f"{transfer['status']} cannot move to {target}", "next_status")
        if target == "FAILED":
            transfer["failure_type"] = body.get("failure_type")
            transfer["_failed_at"] = self.clock()
        self._set_status(transfer, target)
        if target == "CANCELLED":
            self._refund(transfer)
        return self._public(transfer)

    def _tick(self) -> None:
        for transfer in self.objects["transfers"].values():
            failed_at = transfer.get("_failed_at")
            if transfer["status"] == "FAILED" and self.clock() - failed_at >= FAILED_TO_CANCELLED_S:
                self._set_status(transfer, "CANCELLED")
                self._refund(transfer)

    # --------------------------------------------------------------------- helpers

    def _refund(self, transfer: dict) -> None:
        self._credit(transfer["_account"], transfer["transfer_currency"], transfer["_minor"])

    def _debit(self, account: str, currency: str, minor: int, source: str) -> None:
        if self.available(currency, account) < minor:
            raise _Refuse(400, "balance_insufficient", "Insufficient wallet balance", source)
        self.balances[account][currency] -= minor

    def _credit(self, account: str, currency: str, minor: int) -> None:
        wallet = self.balances.setdefault(account, {})
        wallet[currency] = wallet.get(currency, 0) + minor

    def _set_status(self, obj: dict, status: str) -> None:
        obj["status"] = status
        obj["updated_at"] = _iso(self.clock())

    def _get(self, collection: str, object_id: str) -> dict:
        obj = self.objects[collection].get(object_id)
        if obj is None:
            raise _Refuse(404, "resource_not_found", f"no {collection[:-1]} {object_id}")
        return obj

    def _list(self, collection: str, request_id: str | None) -> dict:
        items = [self._public(o) for o in self.objects[collection].values()
                 if request_id is None or o["request_id"] == request_id]
        return {"items": items, "has_more": False}

    @staticmethod
    def _public(obj: dict) -> dict:
        return {k: v for k, v in obj.items() if not k.startswith("_")}

    def _envelope(self, refusal: _Refuse) -> dict:
        self._serial += 1
        envelope = {"message": refusal.message, "trace_id": f"fake-trace-{self._serial}"}
        if refusal.code is not None:
            envelope["code"] = refusal.code
        if refusal.source:
            envelope["source"] = refusal.source
        return envelope


def _hide(headers: dict[str, str]) -> dict[str, str]:
    hidden = {"x-client-id", "x-api-key"}
    shown = {k: ("<hidden>" if k in hidden else v) for k, v in headers.items()}
    if "authorization" in shown:
        shown["authorization"] = shown["authorization"].partition(" ")[0] + " <hidden>"
    return shown


def _iso(seconds: float) -> str:
    return (EPOCH + timedelta(seconds=seconds)).isoformat()


def _currency(body: Mapping, key: str) -> str:
    value = body.get(key)
    if value not in EXPONENT:
        raise _Refuse(400, "invalid_argument", f"{key} is not a supported currency", key)
    return value


def _minor(body: Mapping, key: str, currency: str) -> int:
    """A request amount: a decimal string with at most the currency's digits, positive."""
    value = body.get(key)
    if not isinstance(value, str) or not DECIMAL_STRING.fullmatch(value):
        raise _Refuse(400, "invalid_argument", f"{key} is a decimal string", key)
    minor = _to_minor(Decimal(value), currency, None)
    if minor <= 0:
        raise _Refuse(400, "invalid_argument", f"{key} is positive", key)
    return minor


def _to_minor(value: Decimal, currency: str, rounding: str | None) -> int:
    scaled = value.scaleb(EXPONENT[currency])
    if rounding is None:
        try:
            exact = scaled.quantize(Decimal(1))
        except InvalidOperation:
            exact = None
        if exact is None or exact != scaled:
            raise _Refuse(400, "invalid_argument", f"too many decimal places for {currency}")
        return int(exact)
    return int(scaled.quantize(Decimal(1), rounding=rounding))


def _value(minor: int, currency: str) -> Decimal:
    return Decimal(minor).scaleb(-EXPONENT[currency])


def _string(minor: int, currency: str) -> str:
    return to_decimal(Money(minor=minor, currency=currency))


def _number(minor: int, currency: str) -> Decimal:
    """A response amount: the provider answers with JSON numbers."""
    return _value(minor, currency)

"""The live client's requests in the shapes the Airwallex sandbox accepts.

A contract run on the real sandbox (`checks/airwallex_live.py --require-key`, api_version
2024-06-30) refused three requests and misread one answer:
- the FX quote: 400 `field_required` [validity] — a quote names how long it is valid;
- the payout: 400 `field_required` [currency] — before 2024-09-27, `/api/v1/transfers/create` is
  the connected-account transfer; payouts there need that version, with `reason` and `reference`;
- the lookup by `request_id`: 400 `incorrect_version` — the transfers list needs it too, and
  conversions live under `/api/v1/fx/conversions`;
- the connected-accounts probe: http 200 with an account carrying no status chose Mode A.

Each shape is pinned on the live transport through an in-process `httpx.MockTransport` that
answers the way the sandbox did: nothing leaves the process.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.connectors.airwallex.client import (
    CONNECTED_PROBE_PATH,
    QUOTE_VALIDITY,
    TRANSFER_REASON,
    AirwallexClient,
)
from app.connectors.airwallex.errors import ConfigError, ProviderError
from app.connectors.airwallex.fake import FakeClock, FakeTransport
from app.connectors.airwallex.fake import _iso as fake_iso
from app.connectors.airwallex.live import LiveTransport
from app.connectors.airwallex.transport import (
    DEFAULT_API_VERSION,
    MIN_API_VERSION,
    SANDBOX_BASE_URL,
    Credentials,
    api_version_from,
)
from app.finance.schemas import Money

TRANSFERS_SINCE = "2024-09-27"
VALIDITIES = {"MIN_1", "MIN_15", "MIN_30", "HR_1", "HR_4", "HR_8", "HR_24"}


class Sandbox:
    """Answers as the sandbox did on the requests the contract run sent."""

    def __init__(self, accounts: list[dict] | dict | None = None) -> None:
        self.sent: list[httpx.Request] = []
        self.accounts = [{"id": "acct-1", "status": "ACTIVE"}] if accounts is None else accounts

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        path, version = request.url.path, request.headers.get("x-api-version", "")
        body = json.loads(request.content) if request.content else {}
        if path == "/api/v1/authentication/login":
            return httpx.Response(201, json={"token": "t", "expires_at": "2026-10-27T00:30:00Z"})
        if path == "/api/v1/fx/quotes/create":
            if body.get("validity") not in VALIDITIES:
                return refuse("field_required", "validity")
            return httpx.Response(201, json={"quote_id": "q-1", "client_rate": 1.11})
        if path.startswith("/api/v1/transfers") and version < TRANSFERS_SINCE:
            if path.endswith("/create"):  # the connected-account transfer of the old version
                return refuse("field_required", "currency")
            return refuse("incorrect_version", None)
        if path == "/api/v1/transfers/create":
            for key in ("request_id", "transfer_currency", "reason", "reference"):
                if not body.get(key):
                    return refuse("field_required", key)
            return httpx.Response(201, json={"id": "tr-1", "request_id": body["request_id"],
                                             "status": "SCHEDULED", "transfer_currency": "USD",
                                             "transfer_amount": 100})
        if path == "/api/v1/fx/conversions/create":
            return httpx.Response(201, json={"id": "cv-1", "request_id": body["request_id"],
                                             "status": "SCHEDULED", "sell_currency": "USD"})
        if path in ("/api/v1/transfers", "/api/v1/fx/conversions"):
            return httpx.Response(200, json={"items": []})
        if path == CONNECTED_PROBE_PATH:
            listed = self.accounts if isinstance(self.accounts, dict) else {"items": self.accounts}
            return httpx.Response(200, json=listed)
        return httpx.Response(404, json={"code": "resource_not_found", "message": path})

    def bodies(self, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.sent if r.url.path == path]


def refuse(code: str, source: str | None) -> httpx.Response:
    envelope = {"code": code, "message": "refused"}
    if source:
        envelope["source"] = source
    return httpx.Response(400, json=envelope)


def live(sandbox: Sandbox, api_version: str = DEFAULT_API_VERSION) -> AirwallexClient:
    transport = LiveTransport(SANDBOX_BASE_URL, Credentials("client", "key"),
                              http_transport=httpx.MockTransport(sandbox))
    return AirwallexClient(transport, api_version=api_version, sleep=lambda _: None)


def test_the_pinned_version_serves_payouts_on_the_transfers_api():
    assert DEFAULT_API_VERSION >= TRANSFERS_SINCE and MIN_API_VERSION >= TRANSFERS_SINCE
    with pytest.raises(ConfigError):
        api_version_from({"AIRWALLEX_API_VERSION": "2024-06-30"})


def test_a_quote_names_its_validity():
    sandbox = Sandbox()
    quote = live(sandbox).quote(sell_currency="USD", buy_currency="EUR",
                                amount=Money(minor=1_000_000, currency="EUR"))
    assert quote["quote_id"] == "q-1"
    (body,) = sandbox.bodies("/api/v1/fx/quotes/create")
    assert body == {"sell_currency": "USD", "buy_currency": "EUR", "buy_amount": "10000.00",
                    "validity": QUOTE_VALIDITY}
    assert QUOTE_VALIDITY in VALIDITIES


def test_a_payout_carries_reason_and_reference_on_the_transfers_version():
    sandbox = Sandbox()
    transfer = live(sandbox).create_transfer(
        "canon-pay-1", beneficiary_id="ben-1", amount=Money(minor=10_000, currency="USD"))
    assert transfer.status == "SCHEDULED"
    (body,) = sandbox.bodies("/api/v1/transfers/create")
    assert body == {"request_id": "canon-pay-1", "beneficiary_id": "ben-1",
                    "source_currency": "USD", "transfer_currency": "USD",
                    "transfer_amount": "100.00", "transfer_method": "LOCAL",
                    "reason": TRANSFER_REASON, "reference": "canon-pay-1"}
    assert {r.headers["x-api-version"] for r in sandbox.sent} == {DEFAULT_API_VERSION}


def test_the_lookups_by_request_id_reach_the_documented_lists():
    sandbox = Sandbox()
    client = live(sandbox)
    assert client.find_transfer("canon-pay-1") == []
    assert client.find_conversion("canon-fx-1") == []
    lists = [(r.url.path, dict(r.url.params)) for r in sandbox.sent if r.method == "GET"]
    assert lists == [("/api/v1/transfers", {"request_id": "canon-pay-1"}),
                     ("/api/v1/fx/conversions", {"request_id": "canon-fx-1"})]


def test_a_conversion_is_created_and_read_under_fx():
    sandbox = Sandbox()
    client = live(sandbox)
    client.create_conversion("canon-fx-1", sell_currency="USD", buy_currency="EUR",
                             amount=Money(minor=1_000, currency="USD"), quote_id="q-1")
    assert len(sandbox.bodies("/api/v1/fx/conversions/create")) == 1


@pytest.mark.parametrize(("accounts", "mode"), [
    ([{"id": "acct-1", "status": "ACTIVE"}], "A"),
    ([{"id": "acct-1"}], "B"),
    ([{"id": "acct-1", "status": "SUBMITTED"}], "B"),
    ([], "B"),
])
def test_only_an_active_connected_account_selects_mode_a(accounts, mode):
    assert live(Sandbox(accounts)).probe_connected("auto") == mode


def test_forcing_mode_a_without_an_active_account_fails_at_start():
    with pytest.raises(ConfigError, match="no active connected account"):
        live(Sandbox([{"id": "acct-1"}])).probe_connected("on")


def test_an_empty_reference_falls_back_to_the_request_id():
    sandbox = Sandbox()
    live(sandbox).create_transfer("canon-pay-2", beneficiary_id="ben-1", reference="",
                                  amount=Money(minor=10_000, currency="USD"))
    (body,) = sandbox.bodies("/api/v1/transfers/create")
    assert body["reference"] == "canon-pay-2"


def test_an_accounts_answer_with_no_items_is_unclear_not_empty():
    with pytest.raises(ConfigError) as refused:
        live(Sandbox({"note": "no list"})).probe_connected("on")
    assert "no active connected account" not in str(refused.value)


# ------------------------------------------------------------------------ the fake agrees


def fake_client(api_version: str = DEFAULT_API_VERSION) -> tuple[FakeTransport, AirwallexClient]:
    clock = FakeClock()
    transport = FakeTransport(clock=clock)
    return transport, AirwallexClient(transport, clock, api_version=api_version,
                                      sleep=lambda _: None)


def test_the_fake_refuses_payouts_and_their_lists_before_the_transfers_version():
    _, client = fake_client("2024-06-30")
    with pytest.raises(ProviderError) as refused:
        client.create_transfer("leg-old-1", beneficiary_id="ben-payroll-1",
                               amount=Money(minor=100, currency="USD"))
    assert (refused.value.code, refused.value.source) == ("field_required", "currency")
    with pytest.raises(ProviderError) as refused:
        client.find_transfer("leg-old-1")
    assert refused.value.code == "incorrect_version"
    assert client.balances()  # the rest of the API answers on the older version


def test_the_fake_quote_lasts_as_long_as_its_validity():
    transport, client = fake_client()
    quote = client.quote(sell_currency="USD", buy_currency="EUR",
                         amount=Money(minor=100, currency="EUR"))
    assert quote["validity"] == QUOTE_VALIDITY
    assert quote["valid_to"] == fake_iso(transport.clock() + 15 * 60)

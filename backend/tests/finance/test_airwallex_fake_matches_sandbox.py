"""The fake Airwallex answers the way the sandbox did on the second contract run.

The run (api_version 2024-09-27) showed the fake differing from the sandbox:
- a quote answers 200 (fake 201) and names its end `valid_to_at` (fake `valid_to`);
- a conversion settles at once (`SETTLED`) and its answer carries `conversion_id`, no `id`;
- a replayed transfer is `400 request_id_duplicate` (fake `duplicate_request_id`) with no
  `trace_id`;
- a payout answers `SCHEDULED` and reads back `PROCESSING` straight after (fake `SCHEDULED`);
- a Global Account carries no `currency` key; its currencies are in its features.

Each pin is on the fake's own wire answers, then through the client the callers use.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.connectors.airwallex.client import AirwallexClient, global_accounts_by_currency
from app.connectors.airwallex.errors import DuplicateRequest
from app.connectors.airwallex.fake import FakeClock, FakeTransport
from app.connectors.airwallex.fake import _iso as fake_iso
from app.connectors.airwallex.transport import DEFAULT_API_VERSION
from app.finance.schemas import Money

EUR_100 = Money(minor=10000, currency="EUR")
USD_1 = Money(minor=100, currency="USD")


class Wire:
    """The fake's raw answers (status and body), logged in as the client would be."""

    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        login = transport.send("POST", "/api/v1/authentication/login", {},
                               {"x-client-id": "fake-client", "x-api-key": "fake-key"})
        self.headers = {"authorization": f"Bearer {login.json['token']}",
                        "x-api-version": DEFAULT_API_VERSION}

    def __call__(self, method: str, path: str, body: Any = None) -> Any:
        return self.transport.send(method, path, body, self.headers)


def fake() -> tuple[FakeTransport, Wire, AirwallexClient]:
    clock = FakeClock()
    transport = FakeTransport(clock=clock)
    client = AirwallexClient(transport, clock, api_version=DEFAULT_API_VERSION,
                             sleep=lambda _: None)
    return transport, Wire(transport), client


def payout_body(request_id: str) -> dict:
    return {"request_id": request_id, "beneficiary_id": "ben-payroll-1", "source_currency": "USD",
            "transfer_currency": "USD", "transfer_amount": "1.00", "transfer_method": "LOCAL",
            "reason": "wages_salary", "reference": request_id}


def test_a_quote_answers_200_and_names_valid_to_at():
    transport, wire, _ = fake()
    answer = wire("POST", "/api/v1/fx/quotes/create",
                  {"sell_currency": "USD", "buy_currency": "EUR", "buy_amount": "100.00",
                   "validity": "MIN_15"})
    assert answer.status == 200
    assert "valid_to" not in answer.json
    assert answer.json["valid_to_at"] == fake_iso(transport.clock() + 15 * 60)


def test_a_conversion_settles_at_once_and_has_no_id_key():
    transport, wire, client = fake()
    answer = wire("POST", "/api/v1/fx/conversions/create",
                  {"request_id": "fx-1", "sell_currency": "USD", "buy_currency": "EUR",
                   "buy_amount": "100.00"})
    assert answer.json["status"] == "SETTLED"
    assert "id" not in answer.json and answer.json["conversion_id"]
    assert transport.available("EUR") == 10000  # the buy side is in the wallet already
    read = wire("GET", f"/api/v1/fx/conversions/{answer.json['conversion_id']}")
    assert read.json["status"] == "SETTLED" and "id" not in read.json

    conversion = client.create_conversion("fx-2", sell_currency="USD", buy_currency="EUR",
                                          amount=EUR_100)
    assert (conversion.status, conversion.provider_id) == ("SETTLED", conversion.raw["conversion_id"])
    assert [c.provider_id for c in client.find_conversion("fx-2")] == [conversion.provider_id]


def test_a_replayed_transfer_is_request_id_duplicate_with_no_trace_id():
    _, wire, client = fake()
    assert wire("POST", "/api/v1/transfers/create", payout_body("pay-1")).status == 201
    replay = wire("POST", "/api/v1/transfers/create", payout_body("pay-1"))
    assert replay.status == 400
    assert replay.json["code"] == "request_id_duplicate"
    assert "trace_id" not in replay.json

    client.create_transfer("pay-2", beneficiary_id="ben-payroll-1", amount=USD_1)
    with pytest.raises(DuplicateRequest):
        client.create_transfer("pay-2", beneficiary_id="ben-payroll-1", amount=USD_1)


def test_a_fresh_payout_answers_scheduled_and_reads_processing():
    _, _, client = fake()
    created = client.create_transfer("pay-3", beneficiary_id="ben-payroll-1", amount=USD_1)
    assert created.status == "SCHEDULED"
    assert client.get_transfer(created.provider_id).status == "PROCESSING"
    assert [t.status for t in client.find_transfer("pay-3")] == ["PROCESSING"]
    # the walk to PAID starts where the fake moved it, as it does on the sandbox
    for step in ("PROCESSING", "SENT", "PAID"):
        assert client.simulate_transition(created.provider_id, step).status == step


def test_a_global_account_carries_no_currency_key():
    transport, wire, client = fake()
    accounts = wire("GET", "/api/v1/global_accounts").json["items"]
    assert accounts and all("currency" not in account for account in accounts)
    usd = global_accounts_by_currency(client.global_accounts())["USD"]
    deposit = client.simulate_deposit(amount=USD_1, global_account_id=usd)
    assert deposit.currency == "USD"
    assert transport.available("USD") == 10000000 + 100

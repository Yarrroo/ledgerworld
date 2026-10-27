"""The second sandbox contract run (api_version 2024-09-27): the three checks it failed.

`checks/airwallex_live.py --require-key` passed 10 of 14 on the real sandbox. It failed:
- global-accounts: "no USD global account among 1". On this version a Global Account carries no
  `currency` key; its currencies are in `required_features` / `supported_features`;
- fx-conversion-replay: the conversions endpoint refuses a replay as `400 invalid_argument`
  "request_id '…' has been used in the past", not as a duplicate code, and that was read as a
  plain refusal;
- payout-to-paid: "outcome unknown for request_id None: http 500". The sandbox had already moved
  the payout to `PROCESSING` by itself, and the transition to `PROCESSING` answered 500.

Each answer is replayed on the live transport through an in-process `httpx.MockTransport` shaped
like the sandbox's: nothing leaves the process.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
import pytest
from app.connectors.airwallex.client import (
    MAX_ATTEMPTS,
    AirwallexClient,
    account_currencies,
)
from app.connectors.airwallex.errors import DuplicateRequest, OutcomeUnknown, ProviderError
from app.connectors.airwallex.live import LiveTransport
from app.connectors.airwallex.transport import SANDBOX_BASE_URL, Credentials
from app.finance.schemas import Money

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "checks"))

import airwallex_live as check

# The keys the sandbox's Global Account carried on the run (values are made up).
GLOBAL_ACCOUNT = {
    "id": "ga-1", "account_name": "n", "account_number": "1", "account_type": "Checking",
    "country_code": "US", "institution": {}, "nick_name": "n", "request_id": "r",
    "status": "ACTIVE", "swift_code": "s",
    "required_features": [{"currency": "USD", "transfer_method": "LOCAL"}],
    "supported_features": [{"currency": "USD", "transfer_method": "LOCAL", "type": "DEPOSIT"},
                           {"currency": "USD", "transfer_method": "SWIFT", "type": "DEPOSIT"}],
}
TRANSITION = re.compile(r"/api/v1/simulation/transfers/([^/]+)/transition")
NEXT = {"SCHEDULED": "PROCESSING", "PROCESSING": "SENT", "SENT": "PAID"}


class Sandbox:
    """Answers the way the sandbox did on run 2; `stuck` makes every transition a 500 that
    moves nothing."""

    def __init__(self, *, stuck: bool = False) -> None:
        self.stuck = stuck
        self.usd = 1_000_000_00
        self.transfers: dict[str, dict] = {}
        self.conversions: set[str] = set()
        self.transitions: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/api/v1/authentication/login":
            return httpx.Response(201, json={"token": "t", "expires_at": "2026-10-27T00:30:00Z"})
        if path == "/api/v1/balances/current":
            return httpx.Response(200, json=[{"currency": "USD", "available_amount":
                                              self.usd / 100, "pending_amount": 0}])
        if path == "/api/v1/global_accounts":
            return httpx.Response(200, json={"items": [GLOBAL_ACCOUNT], "has_more": False})
        if path == "/api/v1/fx/quotes/create":
            return httpx.Response(200, json={"quote_id": "q-1", "client_rate": 1.08})
        if path == "/api/v1/fx/conversions/create":
            rid = body["request_id"]
            if rid in self.conversions:
                return httpx.Response(400, json={
                    "code": "invalid_argument",
                    "message": f"request_id '{rid}' has been used in the past. Please use a "
                               "different request_id for this request"})
            self.conversions.add(rid)
            return httpx.Response(201, json={"id": "cv-1", "request_id": rid,
                                             "status": "SETTLED", "sell_currency": "USD"})
        if path == "/api/v1/transfers/create":
            self.usd -= int(body["transfer_amount"].replace(".", ""))
            transfer = {"id": "tr-1", "request_id": body["request_id"], "status": "SCHEDULED",
                        "transfer_currency": "USD", "transfer_amount": body["transfer_amount"]}
            self.transfers["tr-1"] = transfer
            answer = httpx.Response(201, json=dict(transfer))
            transfer["status"] = "PROCESSING"  # the sandbox moves it on by itself
            return answer
        if path.startswith("/api/v1/transfers/"):
            return httpx.Response(200, json=self.transfers[path.rsplit("/", 1)[1]])
        if match := TRANSITION.fullmatch(path):
            transfer, target = self.transfers[match.group(1)], body["next_status"]
            self.transitions.append(target)
            if self.stuck or NEXT.get(transfer["status"]) != target:
                return httpx.Response(500, json={"code": "internal_error"})
            transfer["status"] = target
            return httpx.Response(200, json=transfer)
        return httpx.Response(404, json={"code": "resource_not_found", "message": path})


def live(sandbox: Sandbox) -> AirwallexClient:
    transport = LiveTransport(SANDBOX_BASE_URL, Credentials("client", "key"),
                              http_transport=httpx.MockTransport(sandbox))
    return AirwallexClient(transport, sleep=lambda _: None)


def contract(sandbox: Sandbox) -> check.ContractPass:
    return check.ContractPass(live(sandbox), "run2", "ben-1")


# ------------------------------------------------------------------------- global accounts


def test_a_global_account_currency_is_read_from_its_features():
    assert account_currencies(GLOBAL_ACCOUNT) == ["USD"]
    assert account_currencies({"id": "ga", "currency": "EUR"}) == ["EUR"]
    assert account_currencies({"id": "ga", "supported_features": "junk"}) == []
    client = live(Sandbox())
    assert client.global_account_in("USD") == "ga-1"
    assert client.global_account_in("EUR") is None


def test_the_check_finds_the_usd_global_account():
    ok, provider_id, detail = contract(Sandbox()).global_accounts()
    assert (ok, provider_id, detail) == (True, "ga-1", "1 listed")


# --------------------------------------------------------------------- conversion replay


def test_a_replayed_conversion_is_a_duplicate():
    client = live(Sandbox())
    usd = Money(minor=100_00, currency="USD")
    client.create_conversion("canon-fx-1", sell_currency="USD", buy_currency="EUR", amount=usd)
    with pytest.raises(DuplicateRequest) as replay:
        client.create_conversion("canon-fx-1", sell_currency="USD", buy_currency="EUR",
                                 amount=usd)
    assert (replay.value.request_id, replay.value.in_flight, replay.value.code) == (
        "canon-fx-1", False, "invalid_argument")


def test_another_invalid_argument_is_still_a_refusal():
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(201, json={"token": "t"})
        return httpx.Response(400, json={"code": "invalid_argument",
                                         "message": "request_id must be at most 64 characters"})

    transport = LiveTransport(SANDBOX_BASE_URL, Credentials("client", "key"),
                              http_transport=httpx.MockTransport(answer))
    with pytest.raises(ProviderError) as refused:
        AirwallexClient(transport).create_conversion(
            "x", sell_currency="USD", buy_currency="EUR", amount=Money(minor=1, currency="USD"))
    assert not isinstance(refused.value, DuplicateRequest)


def test_the_check_passes_the_conversion_replay():
    run = contract(Sandbox())
    run.fx_quote()
    assert run.fx_conversion()[0]
    ok, _, detail = run.fx_conversion_replay()
    assert ok, detail
    assert "code invalid_argument, already used" in detail


# ------------------------------------------------------------------------- PAID transition


def test_the_payout_reaches_paid_from_where_the_sandbox_moved_it():
    sandbox = Sandbox()
    run = contract(sandbox)
    assert run.payout()[0]
    ok, provider_id, detail = run.payout_to_paid()
    assert (ok, provider_id) == (True, "tr-1"), detail
    assert detail == "status PAID, USD moved -10000 minor"
    assert sandbox.transitions == ["SENT", "PAID"]


def test_a_transition_to_the_status_already_held_is_that_transfer():
    sandbox = Sandbox()
    client = live(sandbox)
    client.create_transfer("canon-pay-1", beneficiary_id="ben-1",
                           amount=Money(minor=100_00, currency="USD"))
    moved = client.simulate_transition("tr-1", "PROCESSING")  # answered 500, already there
    assert (moved.provider_id, moved.status) == ("tr-1", "PROCESSING")
    assert sandbox.transitions == ["PROCESSING"]


def test_a_transition_that_never_answers_names_the_transfer():
    sandbox = Sandbox(stuck=True)
    run = contract(sandbox)
    assert run.payout()[0]
    with pytest.raises(OutcomeUnknown) as unknown:
        run.client.simulate_transition("tr-1", "SENT")
    assert unknown.value.provider_id == "tr-1"
    assert "None" not in str(unknown.value) and "tr-1" in str(unknown.value)
    assert "transfer at PROCESSING" in str(unknown.value)
    assert sandbox.transitions == ["SENT"] * MAX_ATTEMPTS

    sandbox.transitions.clear()
    ok, provider_id, detail = run.payout_to_paid()
    assert (ok, provider_id) == (False, "tr-1")
    assert detail.startswith("from PROCESSING, to SENT: OutcomeUnknown") and "None" not in detail

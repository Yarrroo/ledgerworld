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
    global_accounts_by_currency,
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
    """Answers the way the sandbox did on run 2. A transition it cannot make answers `refuse`
    (500); `stuck` makes every transition fail and move nothing. The sandbox moves a transfer on
    by itself: `drift` lists where each failed transition leaves it (None: where it was), `then`
    maps a made transition's status to the one it moves on to.
    `reads_fail` answers every transfer read with a 404; `flaky` fails that many transitions
    the sandbox could make, moving nothing."""

    def __init__(self, *, stuck: bool = False, refuse: int = 500, drift: list | None = None,
                 then: dict | None = None, reads_fail: bool = False,
                 accounts: list[dict] | None = None, flaky: int = 0) -> None:
        self.flaky = flaky
        self.stuck, self.refuse, self.reads_fail = stuck, refuse, reads_fail
        self.drift, self.then = list(drift or []), then or {}
        self.accounts = [GLOBAL_ACCOUNT] if accounts is None else accounts
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
            return httpx.Response(200, json={"items": self.accounts, "has_more": False})
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
            if self.reads_fail:
                return httpx.Response(404, json={"code": "resource_not_found"})
            return httpx.Response(200, json=self.transfers[path.rsplit("/", 1)[1]])
        if match := TRANSITION.fullmatch(path):
            transfer, target = self.transfers[match.group(1)], body["next_status"]
            self.transitions.append(target)
            if self.flaky:
                self.flaky -= 1
                return httpx.Response(500, json={"code": "internal_error"})
            if self.stuck or NEXT.get(transfer["status"]) != target:
                if self.drift and (moved := self.drift.pop(0)):
                    transfer["status"] = moved
                code = "internal_error" if self.refuse >= 500 else "invalid_argument"
                return httpx.Response(self.refuse, json={"code": code})
            transfer["status"] = target
            answer = httpx.Response(200, json=dict(transfer))
            transfer["status"] = self.then.get(target, target)
            return answer
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
    assert sandbox.transitions == ["PROCESSING", "SENT", "PAID"]


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
    assert detail.startswith("to SENT: OutcomeUnknown") and "None" not in detail


def paid_from(sandbox: Sandbox) -> AirwallexClient:
    client = live(sandbox)
    client.create_transfer("canon-pay-1", beneficiary_id="ben-1",
                           amount=Money(minor=100_00, currency="USD"))
    return client


@pytest.mark.parametrize("refuse", [500, 400])
def test_a_transition_the_sandbox_already_went_past_is_that_transfer(refuse):
    sandbox = Sandbox(refuse=refuse)
    client = paid_from(sandbox)
    sandbox.transfers["tr-1"]["status"] = "PAID"
    moved = client.simulate_transition("tr-1", "SENT")
    assert (moved.provider_id, moved.status) == ("tr-1", "PAID")
    assert sandbox.transitions == ["SENT"]


def test_a_transfer_the_sandbox_moved_on_to_the_step_before_is_asked_again():
    sandbox = Sandbox(drift=["SENT"])  # PAID from PROCESSING: 500, and on to SENT itself
    client = paid_from(sandbox)
    moved = client.simulate_transition("tr-1", "PAID")
    assert moved.status == "PAID"
    assert sandbox.transitions == ["PAID", "PAID"]


def test_a_transition_left_unknown_is_sent_again():
    sandbox = Sandbox(flaky=2)
    client = paid_from(sandbox)  # at PROCESSING: SENT fails twice, then is made
    assert client.simulate_transition("tr-1", "SENT").status == "SENT"
    assert sandbox.transitions == ["SENT"] * 3


def test_a_step_skipped_is_not_sent_again():
    sandbox = Sandbox()
    client = paid_from(sandbox)  # at PROCESSING: PAID skips SENT
    with pytest.raises(OutcomeUnknown) as unknown:
        client.simulate_transition("tr-1", "PAID")
    assert "transfer at PROCESSING" in str(unknown.value)
    assert sandbox.transitions == ["PAID"]


def test_the_check_takes_the_account_the_gateway_takes():
    run = contract(Sandbox(accounts=[EUR_WITH_USD, USD_ONLY]))
    assert run.global_accounts()[:2] == (True, "ga-usd")
    pinned = check.ContractPass(live(Sandbox(accounts=[EUR_WITH_USD, USD_ONLY])), "run2",
                                "ben-1", global_account_id="ga-eur")
    assert pinned.global_accounts()[:2] == (True, "ga-eur")


def test_the_check_passes_when_the_sandbox_pays_out_by_itself():
    sandbox = Sandbox(then={"SENT": "PAID"})  # SENT made, then PAID on its own
    run = contract(sandbox)
    assert run.payout()[0]
    ok, provider_id, detail = run.payout_to_paid()
    assert (ok, provider_id) == (True, "tr-1"), detail


def test_a_failure_transition_is_sent_once():
    sandbox = Sandbox(stuck=True)
    client = paid_from(sandbox)
    with pytest.raises(OutcomeUnknown) as unknown:
        client.simulate_transition("tr-1", "FAILED", failure_type="REJECTED")
    assert unknown.value.provider_id == "tr-1"
    assert sandbox.transitions == ["FAILED"]


def test_a_refusal_stands_when_the_read_back_fails():
    sandbox = Sandbox(refuse=400, reads_fail=True)
    client = paid_from(sandbox)
    with pytest.raises(ProviderError) as refused:
        client.simulate_transition("tr-1", "PAID")
    assert (refused.value.code, refused.value.http) == ("invalid_argument", 400)


EUR_WITH_USD = {"id": "ga-eur", "required_features": [{"currency": "EUR"}],
                "supported_features": [{"currency": "EUR"}, {"currency": "USD"}]}
USD_ONLY = {"id": "ga-usd", "required_features": [{"currency": "USD"}]}


def test_an_account_of_the_currency_wins_over_one_that_also_takes_it():
    client = live(Sandbox(accounts=[EUR_WITH_USD, USD_ONLY]))
    assert client.global_account_in("USD") == "ga-usd"
    assert client.global_account_in("EUR") == "ga-eur"
    assert global_accounts_by_currency([EUR_WITH_USD, USD_ONLY]) == {
        "EUR": "ga-eur", "USD": "ga-usd"}
    assert global_accounts_by_currency([EUR_WITH_USD]) == {"EUR": "ga-eur", "USD": "ga-eur"}

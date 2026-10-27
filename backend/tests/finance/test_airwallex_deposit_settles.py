"""Mode B deposits are observed asynchronously, never inferred from a create answer."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from app.connectors.airwallex.client import AirwallexClient, to_money
from app.connectors.airwallex.errors import DuplicateRequest, OutcomeUnknown, ProviderError
from app.connectors.airwallex.fake import PLATFORM, FakeClock, FakeTransport
from app.finance.schemas import Money

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "checks"))
sys.path.insert(0, str(ROOT / "tests" / "execution"))

import airwallex_live as check
from test_gateway import BASE, World, bind_terms

AMOUNT = Money(minor=100, currency="USD")
DEPOSITS = "/api/v1/deposits"


class AsyncDeposits(FakeTransport):
    """Require both page params; the third list observes settlement (or never does)."""

    def __init__(self, *, settles=True):
        super().__init__()
        self.settles = settles
        self.reads = 0

    def _deposit(self, body):
        # Keep the regression reproducible against the pre-fix, instantly settled fake.
        result = super()._deposit(body)
        deposit = self.objects["deposits"][result["id"]]
        if deposit["status"] == "SETTLED":
            self._credit(PLATFORM, deposit["currency"], -to_money(deposit["amount"], deposit["currency"]).minor)
        deposit["status"] = "PENDING"
        return self._public(deposit)

    def _handle(self, method, path, route, body, headers):
        if method == "GET" and route == DEPOSITS:
            self._authenticate(headers)
            query = parse_qs(urlsplit(path).query)
            assert query["page_num"] == ["0"]
            assert int(query["page_size"][0]) > 0
            self.reads += 1
            if self.settles and self.reads >= 3:
                for deposit in self.objects["deposits"].values():
                    if deposit["status"] == "PENDING":
                        deposit["status"] = "SETTLED"
                        self._credit(PLATFORM, deposit["currency"], to_money(deposit["amount"], deposit["currency"]).minor)
            return 200, {"items": [self._public(d) for d in self.objects["deposits"].values()],
                         "has_more": False}
        return super()._handle(method, path, route, body, headers)


def client_for(fake):
    return AirwallexClient(fake, fake.clock, api_version="2024-09-27", sleep=lambda _: None)


def world_for(fake):
    world = World(leg_mode="B")
    world.fake = world.wire.fake = fake
    world.gateway = world.boot()
    return world


def test_contract_check_waits_for_the_observed_deposit():
    fake = AsyncDeposits()
    contract = check.ContractPass(client_for(fake), "async", "ben-payroll-1")
    contract.mode = "B"
    contract.state["global_account"] = "ga-usd-1"
    ok, provider_id, detail = contract.advance()
    assert ok, detail
    assert provider_id and fake.reads == 3
    assert len(fake.objects["deposits"]) == 1


@pytest.mark.parametrize("settles", [True, False])
def test_gateway_reads_the_deposit_and_blocks_dependents_until_settled(settles):
    fake = AsyncDeposits(settles=settles)
    world = world_for(fake)
    done = world.execute(bind_terms(BASE))
    advance, payout = done.legs
    if settles:
        assert advance.state == "settled" and advance.reconciled
        assert advance.journal_id == "j-adv-a-disburse"
        assert payout.provider_id is not None
    else:
        assert advance.state != "settled" and not advance.reconciled
        assert payout.state == "pending" and payout.provider_id is None
        assert not world.journals(advance.leg_id)
    assert fake.reads >= 3
    assert len(world.posts(advance.request_id)) == 1


def test_wait_is_bounded_and_an_unsettled_deposit_is_not_success():
    fake = AsyncDeposits(settles=False)
    client = client_for(fake)
    deposit = client.simulate_deposit(amount=AMOUNT, global_account_id="ga-usd-1")
    with pytest.raises(OutcomeUnknown) as unknown:
        client.wait_for_deposit(deposit.provider_id)
    assert unknown.value.provider_id == deposit.provider_id
    assert 1 <= fake.reads <= 10
    assert len(fake.objects["deposits"]) == 1


def test_fake_deposit_is_pending_then_settled_and_credits_once():
    clock = FakeClock()
    fake = FakeTransport(clock=clock)
    client = AirwallexClient(fake, clock, sleep=clock.advance)
    before = fake.available("USD")
    deposit = client.simulate_deposit(amount=AMOUNT, global_account_id="ga-usd-1")
    assert deposit.status == "PENDING"
    assert fake.available("USD") == before
    observed = client.wait_for_deposit(deposit.provider_id)
    assert observed.status == "SETTLED"
    assert client.get_deposit(deposit.provider_id).status == "SETTLED"
    assert fake.available("USD") == before + AMOUNT.minor


def test_fake_requires_both_deposit_page_params():
    client = client_for(FakeTransport())
    for path in (DEPOSITS, DEPOSITS + "?page_num=0", DEPOSITS + "?page_size=100"):
        with pytest.raises(ProviderError):
            client._request("GET", path)


def test_fake_conversion_replay_uses_the_sandbox_code():
    client = client_for(FakeTransport())
    terms = {"sell_currency": "USD", "buy_currency": "EUR", "amount": AMOUNT}
    client.create_conversion("repeat-conversion", **terms)
    with pytest.raises(DuplicateRequest) as duplicate:
        client.create_conversion("repeat-conversion", **terms)
    assert duplicate.value.code == "invalid_argument"


def test_lookup_follows_pages_and_matches_the_exact_id_and_reference():
    fake = FakeTransport()
    client = client_for(fake)
    deposits = [client.simulate_deposit(amount=AMOUNT, global_account_id="ga-usd-1",
                                        reference=f"advance-{i}") for i in range(101)]
    last = client.get_deposit(deposits[-1].provider_id)
    assert last.provider_id == deposits[-1].provider_id and last.status == "SETTLED"
    assert [obj.provider_id for obj in client.find_deposit("advance-100")] == [last.provider_id]
    pages = [parse_qs(urlsplit(r.path).query)["page_num"][0] for r in fake.requests
             if urlsplit(r.path).path == DEPOSITS]
    assert pages == ["0", "1", "0", "1"]


@pytest.mark.parametrize("answer", [
    {"items": [], "has_more": False},
    {"items": [], "has_more": True},
    {"items": []},
    {"items": {}, "has_more": False},
])
def test_missing_malformed_or_unbounded_lists_never_confirm_a_deposit(answer):
    class BrokenList(FakeTransport):
        def _handle(self, method, path, route, body, headers):
            if method == "GET" and route == DEPOSITS:
                return 200, answer
            return super()._handle(method, path, route, body, headers)

    fake = BrokenList()
    with pytest.raises(OutcomeUnknown):
        client_for(fake).wait_for_deposit("unconfirmed")
    reads = [r for r in fake.requests if urlsplit(r.path).path == DEPOSITS]
    assert 1 <= len(reads) <= 200
    assert not fake.objects["deposits"]


def test_a_pending_deposit_is_read_again_after_a_gateway_restart():
    fake = AsyncDeposits(settles=False)
    world = world_for(fake)
    world.execute(bind_terms(BASE))
    advance, payout = world.legs()
    assert advance.state == "submitted" and payout.provider_id is None
    fake.settles = True
    world.restart()
    world.gateway.run(BASE["approval_id"])
    advance, payout = world.legs()
    assert advance.state == "settled" and advance.reconciled
    assert payout.provider_id is not None
    assert len(world.posts(advance.request_id)) == 1


def test_a_deposit_read_failure_never_replays_the_create():
    class Unavailable(AsyncDeposits):
        def _handle(self, method, path, route, body, headers):
            if method == "GET" and route == DEPOSITS:
                return 503, {"code": "unavailable"}
            return super()._handle(method, path, route, body, headers)

    fake = Unavailable()
    world = world_for(fake)
    world.execute(bind_terms(BASE))
    advance, payout = world.legs()
    assert advance.state == "submitted" and not advance.reconciled
    assert payout.state == "pending" and payout.provider_id is None
    assert len(world.posts(advance.request_id)) == 1


def test_wallet_setup_waits_for_settlement_and_refuses_failed_funding():
    from app.demo.run import DemoFailed, fund_wallet

    class FailedFunding(AsyncDeposits):
        def _handle(self, method, path, route, body, headers):
            if method == "GET" and route == DEPOSITS:
                for deposit in self.objects["deposits"].values():
                    deposit["status"] = "FAILED"
            return super()._handle(method, path, route, body, headers)

    fake = AsyncDeposits()
    plan = {"legs": [{"kind": "payout", "amount": {"minor": 101, "currency": "USD"}}]}
    fake.balances[PLATFORM]["USD"] = 0
    assert len(fund_wallet(client_for(fake), plan)) == 1
    assert fake.reads == 3 and fake.available("USD") == 101
    failed = FailedFunding()
    failed.balances[PLATFORM]["USD"] = 0
    with pytest.raises(DemoFailed, match="FAILED"):
        fund_wallet(client_for(failed), plan)


def test_a_deposit_not_yet_visible_in_the_list_can_still_settle():
    class NotVisibleYet(AsyncDeposits):
        def _handle(self, method, path, route, body, headers):
            status, answer = super()._handle(method, path, route, body, headers)
            if method == "GET" and route == DEPOSITS and self.reads < 3:
                answer = {"items": [], "has_more": False}
            return status, answer

    fake = NotVisibleYet()
    client = client_for(fake)
    deposit = client.simulate_deposit(amount=AMOUNT, global_account_id="ga-usd-1")
    assert client.wait_for_deposit(deposit.provider_id).status == "SETTLED"
    assert fake.reads == 3


@pytest.mark.parametrize("field,value", [("reference", "some-other-leg"), ("amount", 999)])
def test_a_settled_deposit_with_other_terms_does_not_book_an_advance(field, value):
    class WrongTerms(AsyncDeposits):
        def _handle(self, method, path, route, body, headers):
            status, answer = super()._handle(method, path, route, body, headers)
            if method == "GET" and route == DEPOSITS:
                for deposit in answer["items"]:
                    deposit[field] = value
            return status, answer

    fake = WrongTerms()
    world = world_for(fake)
    world.execute(bind_terms(BASE))
    advance, payout = world.legs()
    assert advance.state != "settled" and not advance.reconciled
    assert not world.journals(advance.leg_id)
    assert payout.provider_id is None
    assert len(world.posts(advance.request_id)) == 1


def test_a_reversed_deposit_unflags_an_already_reconciled_advance():
    from app.execution.reconcile import reconcile_leg

    world = World(leg_mode="B")
    world.execute(bind_terms(BASE))
    advance = world.legs()[0]
    assert advance.reconciled
    world.fake.objects["deposits"][advance.provider_id]["status"] = "REVERSED"
    reconcile_leg(world.gateway, advance.leg_id)
    assert not world.legs()[0].reconciled
    assert world.gateway.incidents(open_only=True)[0]["kind"] == "paid_then_failed"
    assert len(world.journals(advance.leg_id)) == 1


@pytest.mark.parametrize("problem", ["long_history", "unreadable_neighbor"])
def test_addressed_lookup_does_not_require_parsing_the_whole_history(problem):
    class History(FakeTransport):
        def _handle(self, method, path, route, body, headers):
            status, answer = super()._handle(method, path, route, body, headers)
            if method == "GET" and route == DEPOSITS:
                if problem == "long_history":
                    answer["has_more"] = True
                else:
                    answer["items"].append({"id": "unrelated", "amount": "not-a-number",
                                            "currency": "USD", "status": "SETTLED"})
            return status, answer

    fake = History()
    client = client_for(fake)
    deposit = client.simulate_deposit(amount=AMOUNT, global_account_id="ga-usd-1",
                                      reference="our-advance")
    assert client.get_deposit(deposit.provider_id).status == "SETTLED"
    if problem == "unreadable_neighbor":
        assert len(client.find_deposit("our-advance")) == 1


def test_contract_shape_is_the_create_not_unrelated_deposit_history():
    fake = AsyncDeposits()
    client = client_for(fake)
    client.simulate_deposit(amount=AMOUNT, global_account_id="ga-usd-1", reference="old")
    old = next(iter(fake.objects["deposits"].values()))
    old["status"] = "FAILED"
    contract = check.ContractPass(client, "shape", "ben-payroll-1")
    contract.mode = "B"
    contract.state["global_account"] = "ga-usd-1"
    assert contract.advance()[0]
    assert contract._shape.status == "PENDING"


def test_a_funding_wait_failure_keeps_every_accepted_setup_deposit(monkeypatch):
    from app.decisions import candidates
    from app.demo import run

    fake = FakeTransport()
    fake.balances[PLATFORM] = {"USD": 0, "EUR": 0}
    fake.global_accounts.append({"id": "ga-eur", "currency": "EUR"})
    client = client_for(fake)
    wait = client.wait_for_deposit
    calls = []

    def fail_second(provider_id):
        calls.append(provider_id)
        if len(calls) == 2:
            raise OutcomeUnknown(None, "still pending", provider_id=provider_id)
        return wait(provider_id)

    monkeypatch.setattr(client, "wait_for_deposit", fail_second)
    monkeypatch.setattr(candidates, "plan_for_now", lambda *a, **k: {"legs": [
        {"kind": "payout", "amount": {"minor": 100, "currency": c}}
        for c in ("USD", "EUR")]})
    into = {}
    with pytest.raises(OutcomeUnknown):
        run.execute("integrated", "sandbox", client=client, leg_mode="B", run_id="funding",
                    beneficiary="ben-payroll-1", connected_account=None, into=into)
    assert [entry["provider_id"] for entry in into["setup"]] == calls
    assert len(calls) == 2

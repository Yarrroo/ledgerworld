"""The money-safety hunts (T29): bad actions the system must reject, edge cases of LF-1 / LF-2.

Each case of design/modules/ledger/fixtures/money-safety.json, loaded unchanged, is attacked in
the module that owns it and asserted against its `expect` block; each would pass on the naive
implementation the fixture names only if that module were wrong. The worlds are the ones the
owning modules' own tests build: LF-1 in the ledger (`tests/finance/test_fixtures.py`), LF-1 and
LF-2 behind the gateway on the fake provider (`tests/execution/test_gateway.py`), and the coupled
world of the decisions tests (`tests/decisions/test_policies.py`).

The hunts found five real bugs at the execution gateway, each pinned by a test named for it:
- an arrival past its promise that has not landed was spendable at execution, and settling an
  advance or a repayment landed it as cash (the observed side of
  `delayed-receivable-credited-early`);
- two legs funded by one held reservation passed preflight and the queue then raised instead of
  refusing; one offered advance could be sent twice; and a pool's draws were checked against
  K_p one leg at a time (the same units spent twice, as in `double-pledge`).
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from app.connectors.airwallex.transport import TransportTimeout
from app.decisions.objective import rank
from app.execution.approval import Refusal, bind
from app.finance.ledger import check_outflow, from_snapshot, pay, settle_due
from app.finance.lending import capacity
from app.finance.models import LedgerRefusal
from app.finance.spendability import projected_cash, spendability
from app.finance.store import LedgerStore

from tests.decisions.test_policies import COMPARISON, compare, scenario_events, world_snapshot
from tests.execution.test_gateway import BASE as APPROVAL
from tests.execution.test_gateway import (
    NOW,
    OBSERVED,
    World,
    bind_terms,
    fund,
    plan_of,
    snapshot,
)
from tests.finance.test_fixtures import ACCOUNT, h, horizon, lf1
from tests.finance.test_fixtures import world as lf1_world

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "prp/2026-10-20-ledgerworld/design/modules/ledger/fixtures"
                      / "money-safety.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}
PAYEE = APPROVAL["legs"][1]["counterparty"]  # the allowlisted payroll beneficiary


def expect(case_id: str) -> dict:
    return CASES[case_id]["expect"]


def test_every_hunt_is_carried():
    assert set(CASES) == {
        "spend-beyond-cash", "double-pledge", "obligation-removed-by-inaction",
        "withdrawal-after-deadline-counted", "delayed-receivable-credited-early",
        "stale-balance-executed", "floor-relaxed-when-infeasible", "timeout-retried-blindly"}


# ----------------------------------------------------------------------------- the gateway

def approve(world: World, approval_id: str, legs: list[dict], *, at=None):
    """A validly bound approval of `legs` on the observed snapshot, recorded at `at`."""
    terms = copy.deepcopy(APPROVAL) | {"approval_id": approval_id, "legs": legs}
    approval = bind(plan_of(terms), terms["snapshot_id"], terms["approver"], terms["mode"],
                    now=at or world.now, approval_id=approval_id)
    world.gateway.record(approval)
    return approval


def payout(index: int, amount: int, funded_by: str = "spendable") -> dict:
    return {"index": index, "kind": "payout", "amount": amount, "currency": "USD",
            "source": ACCOUNT, "counterparty": PAYEE, "funded_by": funded_by}


def assert_refused_untouched(world: World, approval, code: str) -> Refusal:
    """Refused with `code`; no ledger row, no outbox row and no provider call written."""
    before = world.store.dump()
    verdict = world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == code, verdict
    assert world.store.dump() == before
    assert world.gateway.conn.execute("SELECT count(*) FROM execution_legs").fetchone() == (0,)
    assert world.posts() == []
    return verdict


def refresh(world: World) -> None:
    """Every known account observed at the gateway's now: fresh, nothing landed meanwhile."""
    for row in world.store.rows("account_observations"):
        if row["observability"] == "known":
            world.store.observe(row["account_id"], "known", world.now)


# --------------------------------------------------------------------------------- hunts

def test_spend_beyond_cash():
    case = CASES["spend-beyond-cash"]
    amount = case["action"]["amount"]
    store = lf1_world()
    view = store.view(ACCOUNT)
    assert view.settled_minor < amount  # settled 70,000 is not the test; S(0) = 20,000 is
    refusal = check_outflow(view, amount, h(0), horizon())
    assert refusal is not None and refusal.code == case["expect"]["rejected"]
    assert refusal.detail["S_now"] == spendability(view, h(0), h(0)).value
    to = store.external_account("USD")
    before = store.dump()
    with pytest.raises(LedgerRefusal) as caught:
        pay(store, ACCOUNT, amount, to_account=to, now=h(0), journal_id="hunt-pay-80k")
    assert caught.value.code == case["expect"]["rejected"]
    assert store.dump() == before and store.view(ACCOUNT).settled_minor >= 0
    # Within settled, beyond S: the reserved payroll is not spendable either.
    assert check_outflow(view, view.settled_minor, h(0), horizon()).code == \
        case["expect"]["rejected"]
    # The same payment as an execution leg is refused at preflight, before any provider call.
    world = World()
    assert_refused_untouched(world, approve(world, "apr-hunt-80k", [payout(1, amount)]),
                             case["expect"]["rejected"])


def test_double_pledge():
    case = CASES["double-pledge"]
    first, second = case["action"]
    store = lf1_world()
    store.pledge(ACCOUNT, first["amount"], first["collateral_ref"])
    before = store.dump()
    with pytest.raises(LedgerRefusal) as caught:
        store.pledge(ACCOUNT, second["amount"], second["collateral_ref"])
    assert caught.value.code == case["expect"]["second_rejected"]
    assert store.dump() == before
    assert store.view(ACCOUNT).pledged_minor == first["amount"]
    # The same units are refused whatever amount or account the second pledge names.
    for account_id, amount in ((ACCOUNT, 1), (store.external_account("USD"), second["amount"])):
        with pytest.raises(LedgerRefusal) as caught:
            store.pledge(account_id, amount, first["collateral_ref"])
        assert caught.value.code == case["expect"]["second_rejected"]
    # Pledged units are spoken for: they cannot be pledged under another ref, nor paid out.
    free = store.view(ACCOUNT).free_minor
    with pytest.raises(LedgerRefusal) as caught:
        store.pledge(ACCOUNT, free + 1, "lot-2")
    assert caught.value.code == "pledge_exceeds_free"
    assert check_outflow(store.view(ACCOUNT), free + 1, h(0), horizon()).code == \
        "insufficient_spendable"


def test_one_reservation_never_funds_two_legs():
    """The reservation side of a double pledge: the payroll hold spent by two payout legs.

    Bug found: both legs passed preflight, and queueing the second raised
    `LedgerRefusal(reservation_not_held)` out of `execute` instead of a refusal."""
    world = World()
    funded = f"reservation:{APPROVAL['legs'][1]['funded_by'].removeprefix('reservation:')}"
    legs = [payout(1, 5_000_000, funded), payout(2, 5_000_000, funded)]
    verdict = assert_refused_untouched(world, approve(world, "apr-hunt-twice", legs),
                                       "reservation_mismatch")
    assert "leg 2" in verdict.detail
    assert world.gateway.conn.execute("SELECT used_at FROM approvals").fetchone() == (None,)


def lost(world: World):
    """A create the provider accepts, then a dead wire and three failed lookups: unknown."""
    def hook():
        for _ in range(3):
            world.fake.respond_next(500, {"code": "internal_error", "message": "down"})
        raise TransportTimeout(after_send=True)
    return hook


def test_one_advance_is_never_sent_twice():
    """The pool's money disbursed twice. Bug found: the facility stays offered until its leg
    settles, so a second leg on it, in the same approval or in another while the first is in
    flight or unknown, passed preflight and created a second transfer."""
    advance = APPROVAL["legs"][0]
    world = World()
    twice = approve(world, "apr-hunt-adv-twice", [advance, advance | {"index": 2}])
    assert_refused_untouched(world, twice, "reservation_mismatch")
    first = approve(world, "apr-hunt-adv-1", [advance])
    world.wire.after_create = lost(world)
    world.gateway.execute(first, current_snapshot_id=OBSERVED)
    (leg,) = world.legs(first.approval_id)
    assert leg.state == "unknown"
    again = approve(world, "apr-hunt-adv-2", [advance, payout(2, 1)])  # another plan hash
    verdict = world.gateway.execute(again, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "reservation_mismatch", verdict
    assert world.legs(again.approval_id) == [] and len(world.posts()) == 1


def test_a_pools_draws_in_one_approval_share_its_capacity():
    """Two advances of one pool, each within K_p, together beyond it. Bug found: K_p was
    checked leg by leg, both transfers went out, and neither journal could ever post."""
    snap = snapshot()
    snap["contracts"].append({
        "contract_id": "adv-a2", "lender": "lender", "borrower": "borrower-a", "state": "offered",
        "kind": "revenue_advance", "principal": {"minor": 4_000_000, "currency": "USD"},
        "fee_bps": 800, "repay_share_bps": 1500})
    store = LedgerStore("sqlite://")
    from_snapshot(store, snap)
    fund(store, "lender/operating", 2_000_000)  # S on the pool's account is not what binds
    store.observe("lender/venue", "unknown", NOW)
    world = World(store=store)
    k_p = capacity(store, "lender", NOW).K_p
    legs = [APPROVAL["legs"][0], APPROVAL["legs"][0] | {"index": 2, "amount": 4_000_000,
                                                        "facility_id": "adv-a2"}]
    assert all(leg["amount"] <= k_p for leg in legs) and sum(
        leg["amount"] for leg in legs) > k_p
    assert sum(leg["amount"] for leg in legs) <= spendability(
        store.view("lender/operating"), NOW, NOW).value
    verdict = assert_refused_untouched(world, approve(world, "apr-hunt-kp", legs),
                                       "insufficient_spendable")  # the gateway's code for it
    assert verdict.detail.startswith("K_p of lender: beyond_capacity")


def test_a_settled_advance_lands_no_overdue_arrival():
    """Settling a leg is not an observation of the source's other arrivals. Bug found: the
    disbursal landed every arrival due by now on the lender's account, booking cash that had
    not arrived (the repayment's settle did the same on the borrower's)."""
    world = World()
    world.store.expect("lender/operating", "in", 500_000, NOW - timedelta(hours=1),
                       kind="receivable", flow_id="late-in")
    before = world.store.view("lender/operating").settled_minor
    approval = approve(world, "apr-hunt-land", [APPROVAL["legs"][0]])
    world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    (leg,) = world.legs(approval.approval_id)
    assert leg.state == "settled"
    (late,) = [f for f in world.store.rows("expected_flows") if f["flow_id"] == "late-in"]
    assert late["state"] == "pending"
    assert world.store.view("lender/operating").settled_minor == before - leg.amount_minor


def test_obligation_removed_by_inaction():
    case = expect("obligation-removed-by-inaction")
    (payroll,) = lf1()["snapshot"]["obligations"]
    due_h = 40
    assert case["payroll-1"] == f"settled at t={due_h} from its reservation"
    store = lf1_world()
    count = len(store.rows("obligations"))
    for hour in range(lf1()["horizon_h"] + 1):  # every round no_action: only step 8 runs
        settle_due(store, h(hour))
        states = {o["obligation_id"]: o["state"] for o in store.rows("obligations")}
        assert states[payroll["obligation_id"]] == ("open" if hour < due_h else "met"), hour
    assert len(store.rows("obligations")) - count == -case["obligations_dropped"]
    assert sum(o["state"] in ("open", "missed") for o in store.rows("obligations")) == \
        case["obligations_open_after_40"]
    assert store.reservation(payroll["reservation_id"]).state == "settled"
    (paid,) = [j for j in store.rows("journals") if j["journal_id"] == "settle:payroll-1"]
    assert paid["sim_time"].replace(tzinfo=None) == h(due_h).replace(tzinfo=None)
    # A world that skips straight past the due time still pays it: rounds missed are no excuse.
    jumped = lf1_world()
    settle_due(jumped, h(lf1()["horizon_h"]))
    assert {o["obligation_id"]: o["state"] for o in jumped.rows("obligations")} == {
        payroll["obligation_id"]: "met"}
    assert jumped.view(ACCOUNT).settled_minor == store.view(ACCOUNT).settled_minor


def test_withdrawal_after_deadline_counted():
    case = expect("withdrawal-after-deadline-counted")
    view = lf1_world().view(ACCOUNT)
    assert projected_cash(view, h(40)) == case["value"] != case["not"]
    (wd,) = [f for f in view.pending_in if f.at > h(40)]  # it lands at t=48, after payroll
    assert projected_cash(view, h(48)) == case["value"] + wd.amount_minor
    assert spendability(view, h(40), h(0)).value == spendability(view, h(47), h(0)).value


def test_delayed_receivable_credited_early():
    case = expect("delayed-receivable-credited-early")
    store = lf1_world(shock=True)  # the delay event rewrites the expected time (reschedule)
    view = store.view(ACCOUNT)
    assert projected_cash(view, h(40)) == case["value"] != case["not"]
    assert spendability(view, h(40), h(0)).value == spendability(view, h(0), h(0)).value
    settle_due(store, h(12))  # its old time passes: nothing lands
    assert store.view(ACCOUNT).settled_minor == lf1()["snapshot"]["accounts"][0]["buckets"][
        "settled"]["minor"]
    assert projected_cash(store.view(ACCOUNT), h(40)) == case["value"]


def test_an_overdue_receivable_is_never_spent_by_an_execution():
    """The observed side of the delay: at t=12 the receivable is promised and has not landed.

    Nothing on the observed ledger says when it will, so it adds nothing to S or P (as in the
    decisions projection). Bug found: the gateway counted it, S(12) read 40,000.00 and P(40)
    40,000.00, and a 10,000.00 discretionary payout went to the provider; without it P(40) is
    20,000.00, below the 30,000.00 floor."""
    world = World()
    world.now = NOW + timedelta(hours=12)
    refresh(world)
    (rcv,) = [f for f in world.store.view(ACCOUNT).pending_in if f.at <= world.now]
    approval = approve(world, "apr-hunt-overdue", [payout(1, 1_000_000)])
    verdict = assert_refused_untouched(world, approval, "breaks_floor")
    assert rcv.flow_id == "rcv-1"
    # Once it is observed to land, the same payout clears.
    world.store.settle_flow(rcv.flow_id, counterparty=world.store.external_account("USD"),
                            at=world.now)
    executed = world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    assert not isinstance(executed, Refusal), (executed, verdict)
    assert len(world.posts()) == 1


def test_stale_balance_executed():
    case = CASES["stale-balance-executed"]
    world = World()
    stale_h = 7
    assert case["world"] == f"LF-1 with as_of {stale_h} h old"
    for row in world.store.rows("account_observations"):
        if row["observability"] == "known":
            world.store.observe(row["account_id"], "known", NOW - timedelta(hours=stale_h))
    view = world.store.view(ACCOUNT)
    read = spendability(view, NOW, NOW)
    assert (read.state, read.authority) == ("stale", case["expect"]["authority"])
    assert read.value is not None  # the last value is kept, and still not enough to execute
    assert check_outflow(view, 1, NOW, horizon()).code == case["expect"]["rejected"]
    approval = bind_terms(APPROVAL)  # the integrated plan: the advance and the payroll payout
    world.gateway.record(approval)
    assert_refused_untouched(world, approval, case["expect"]["rejected"])
    # Six hours is still fresh; one second more is not.
    refresh_at = NOW - timedelta(hours=6)
    for row in world.store.rows("account_observations"):
        if row["observability"] == "known":
            world.store.observe(row["account_id"], "known", refresh_at)
    assert spendability(world.store.view(ACCOUNT), NOW, NOW).authority == "full"
    world.now = NOW + timedelta(seconds=1)
    assert_refused_untouched(world, approval, case["expect"]["rejected"])


def test_timeout_retried_blindly():
    """The payroll transfer is created, then the wire dies and the provider stays down."""
    case = expect("timeout-retried-blindly")
    world = World()

    def accepted_then_lost():  # the create landed; every lookup until restart gets a 500
        for _ in range(3):
            world.fake.respond_next(500, {"code": "internal_error", "message": "down"})
        raise TransportTimeout(after_send=True)

    world.wire.after_create = accepted_then_lost
    approval = approve(world, "apr-hunt-timeout", [payout(1, 5_000_000,
                                                          APPROVAL["legs"][1]["funded_by"])])
    world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    (leg,) = world.legs(approval.approval_id)
    assert leg.state == case["leg_state"]
    (incident,) = world.gateway.incidents(open_only=True)
    assert (incident["kind"], incident["leg_id"]) == ("outcome_unknown", leg.leg_id)
    assert case["incident"] == "opened"
    sent = [i for i, r in enumerate(world.fake.requests)
            if r.method == "POST" and r.path == "/api/v1/transfers/create"]
    assert len(sent) == 1
    after = [r for r in world.fake.requests[sent[0] + 1:] if "authentication" not in r.path]
    assert after and after[0].method == "GET" and \
        after[0].path.endswith(f"?request_id={leg.request_id}")  # the stored id, queried
    assert {r.method for r in after} == {"GET"}  # nothing created while the outcome is unknown
    # The provider answers again: the transfer is found by its id and adopted, never re-created.
    world.gateway.run(approval.approval_id)
    (leg,) = world.legs(approval.approval_id)
    assert leg.state == "submitted" and leg.provider_id
    assert world.fake.count("transfers", leg.request_id) == case["transfers_created"]
    assert len(world.posts()) == case["transfers_created"]


@pytest.fixture(scope="module")
def no_advance(tmp_path_factory):
    """LF-1 shocked (s1: rcv-1 delayed 240 h) beside a pool with K_p = 0: a redemption due in
    the horizon takes the whole capacity, so the eligible advance cannot be drawn."""
    snap = world_snapshot(redemption=4_200_000)
    s1 = next(s for s in COMPARISON["scenarios"] if s["id"] == "s1")
    cp, evaluations = asyncio.run(compare(tmp_path_factory.mktemp("no-advance"), snap,
                                          {"s1": scenario_events(s1)}))
    escalate_to = next(e.escalation for e in cp.snapshot.entities if e.entity_id == "treasury")
    return snap, evaluations, rank(evaluations, order=COMPARISON["policies_in_order"],
                                   escalate_to=escalate_to)


def test_floor_relaxed_when_infeasible(no_advance):
    case = expect("floor-relaxed-when-infeasible")
    snap, evaluations, result = no_advance
    store = LedgerStore("sqlite://")
    from_snapshot(store, snap)
    assert capacity(store, "lender", datetime.fromisoformat(snap["as_of"]),
                    timedelta(hours=COMPARISON["world"]["horizon_h"])).K_p == 0
    # `infeasible`: no policy is feasible, which the decisions result calls all_infeasible.
    assert case["result"] == "infeasible"
    assert [p["feasible"] for p in result.policies] == [False] * len(result.policies)
    assert result.status == "all_infeasible" and result.selected is None
    assert result.plan_for_now is None and result.floor_relaxed is False
    with pytest.raises(ValueError):
        result.with_plan({"legs": []})
    earliest = result.escalation["earliest_unmet"]
    assert (earliest["kind"], earliest["at_h"], earliest["short_minor"]) == (
        "reserve_floor", 40, 1_000_000)
    assert case["earliest_unmet"] == "reserve floor at t=40, short 10,000.00"
    assert result.escalation["binding"].startswith(f"{case['binding']}.00 <")
    assert result.escalation["escalate_to"] == "treasury operator"  # C5's named role
    (account,) = [a for a in snap["accounts"] if a.get("floor")]
    assert account["floor"]["minor"] == case["floor_minor"]
    for e in evaluations:  # every branch is judged on the unrelaxed floor
        f = e.feasibility.floor
        assert f.min_cash + f.short_minor == case["floor_minor"] and f.breach_h is not None
        assert not e.feasibility.feasible

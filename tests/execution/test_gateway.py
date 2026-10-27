"""The execution gateway on the fake provider: bound approval, preflight, legs that move money once.

The store is the observed ledger: LF-1's treasury and LF-2's lender pool in one C5 snapshot, its
times moved so that the fixtures' t = 0 is the approval fixture's `now`. The provider is the
connector's `FakeTransport` behind the real `AirwallexClient`; a test reaches past the client
only to make the wire die or lie at a named moment. Fixtures from
design/modules/execution/fixtures are loaded unchanged:

- `approval-binding.json`: every case but `no-token` (the token belongs to the approvals route)
  runs through `Gateway.execute`; a refused approval writes no leg, no ledger row and no POST.
- `crash-and-retry.json`: every case on leg 1 (the advance, Mode A so it carries a
  `request_id`), with restarts from the store; at most one provider object per id, one journal
  per leg.
- `leg-state-machine.json`: the dependency rule (a failed advance fails the payout unsent).
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from app.connectors.airwallex.client import AirwallexClient
from app.connectors.airwallex.fake import CONNECTED_ACCOUNT, MONEY_CREATES, FakeClock, FakeTransport
from app.connectors.airwallex.transport import TransportTimeout
from app.execution import outbox as ob
from app.execution import reconcile, state
from app.execution.approval import Refusal, bind
from app.execution.gateway import Execution, Gateway
from app.finance.ledger import from_snapshot
from app.finance.models import Journal, Posting
from app.finance.store import LedgerStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = state.DESIGN / "fixtures"
BINDING = json.loads((FIXTURES / "approval-binding.json").read_text(encoding="utf-8"))
CRASH = json.loads((FIXTURES / "crash-and-retry.json").read_text(encoding="utf-8"))
MACHINE = json.loads((FIXTURES / "leg-state-machine.json").read_text(encoding="utf-8"))
BASE = BINDING["base"]
CASES = {case["id"]: case for case in BINDING["cases"]}
NOW = datetime.fromisoformat(BINDING["now"])
OBSERVED = BINDING["current_observed_snapshot_id"]
LF_T0 = datetime.fromisoformat("2026-01-05T00:00:00Z")
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
LEG_TERM = re.compile(r"^legs\[(\d+)\]\.(\w+)$")
LEDGER = {"unowned-source", "beneficiary-not-allowlisted", "stale-balance", "breaks-floor",
          "reservation-mismatch"}
ROUTE = {"no-token"}  # POST /api/v1/approvals checks the token, not the gateway


class Crash(Exception):
    """The process dies here."""


# ------------------------------------------------------------------------------- the world


def _shift(value, delta: timedelta):
    if isinstance(value, dict):
        return {k: _shift(v, delta) for k, v in value.items()}
    if isinstance(value, list):
        return [_shift(v, delta) for v in value]
    if isinstance(value, str) and ISO.match(value):
        return (datetime.fromisoformat(value) + delta).isoformat().replace("+00:00", "Z")
    return value


def snapshot() -> dict:
    """LF-1's treasury and LF-2's pool as one observed snapshot, t = 0 at the fixture's now."""
    lf1 = json.loads((ROOT / "fixtures/lf1_treasury.json").read_text(encoding="utf-8"))["snapshot"]
    snap = copy.deepcopy(json.loads((ROOT / "fixtures/lf2_lender.json").read_text(
        encoding="utf-8"))["snapshot"])
    snap["accounts"] += lf1["accounts"]
    snap["obligations"] += lf1["obligations"]
    snap = _shift(snap, NOW - LF_T0)
    snap["snapshot_id"] = OBSERVED
    return snap


def ledger() -> LedgerStore:
    store = LedgerStore("sqlite://")
    from_snapshot(store, snapshot())
    return store


def fund(store: LedgerStore, account_id: str, minor: int) -> None:
    """Extra settled cash on an account, from its opening account."""
    store.apply(Journal(f"fund:{account_id}:{minor}", (Posting(account_id, minor),
                                                       Posting(f"{account_id}:opening", -minor))))


def c3_leg(leg: dict) -> dict:
    shaped = {k: v for k, v in leg.items() if k not in ("amount", "currency")}
    return shaped | {"amount": {"minor": leg["amount"], "currency": leg["currency"]}}


def plan_of(terms: dict) -> dict:
    return {"entity": terms["entity"], "account": terms["account"],
            "legs": [c3_leg(leg) for leg in terms["legs"]]}


def bind_terms(terms: dict, mode: str | None = None):
    return bind(plan_of(terms), terms["snapshot_id"], terms["approver"], mode or terms["mode"],
                now=NOW, approval_id=terms["approval_id"])


class Wire:
    """The fake behind a wire that can die or lie once, right after the fake took a create."""

    def __init__(self, fake: FakeTransport) -> None:
        self.fake = fake
        self.after_create = None

    def __getattr__(self, name: str):
        return getattr(self.fake, name)

    def send(self, method, path, json=None, headers=None):
        answer = self.fake.send(method, path, json, headers)
        if self.after_create and method == "POST" and path in MONEY_CREATES and \
                answer.status == 201:
            hook, self.after_create = self.after_create, None
            hook()
        return answer


class World:
    """One store, one fake provider, and the gateway of the current process."""

    def __init__(self, *, leg_mode: str = "A", mode: str = "fake", now: datetime = NOW,
                 store: LedgerStore | None = None, armed: set | None = None) -> None:
        self.store = store or ledger()
        self.clock = FakeClock()
        self.fake = FakeTransport(clock=self.clock, connected=leg_mode == "A")
        if leg_mode == "A":
            self.fake.balances[CONNECTED_ACCOUNT]["USD"] = 10_000_000
        self.wire = Wire(self.fake)
        self.leg_mode, self.mode, self.now = leg_mode, mode, now
        self.armed = set(armed or ())
        self.race = None
        self.gateway = self.boot()

    def boot(self, hooks: bool = True) -> Gateway:
        """A gateway process on the store; `hooks` wires this world's faults into it."""
        client = AirwallexClient(self.wire, self.clock, api_version="2024-09-27",
                                 sleep=lambda _: None)
        return Gateway(self.store, client, mode=self.mode, leg_mode=self.leg_mode,
                       beneficiaries=BINDING["beneficiary_allowlist"], clock=lambda: self.now,
                       connected_account=CONNECTED_ACCOUNT, global_account_id="ga-usd-1",
                       on_point=self.hit if hooks else None)

    def hit(self, point: str, leg: ob.Leg) -> None:
        if (point, leg.index) in self.armed:
            self.armed.discard((point, leg.index))
            raise Crash(point)
        if self.race and point == "after_outbox_write_before_submitted":
            race, self.race = self.race, None
            race()

    def restart(self) -> None:
        self.gateway = self.boot()
        self.seen = self.gateway.legs(BASE["approval_id"])[0]
        self.gateway.outbox.recover()

    def execute(self, approval, presented=None, current: str = OBSERVED, restarts: int = 8):
        """Execute, restarting from the store after each crash until the legs stop."""
        if self.gateway.stored(approval.approval_id) is None:
            self.gateway.record(approval)
        try:
            return self.gateway.execute(presented or approval.model_dump(mode="json"),
                                        current_snapshot_id=current)
        except Crash:
            pass
        for _ in range(restarts):
            self.restart()
            try:
                return Execution(approval.approval_id, self.gateway.run(approval.approval_id))
            except Crash:
                continue
        raise AssertionError("the legs did not finish")

    def pay(self, leg: ob.Leg, path=("PROCESSING", "SENT", "PAID")) -> None:
        """Move a payout along the provider's statuses (the sandbox's transition endpoint)."""
        for status in path:
            self.gateway.provider.client.simulate_transition(leg.provider_id, status)

    def legs(self, approval_id: str = BASE["approval_id"]) -> list[ob.Leg]:
        return self.gateway.legs(approval_id)

    def posts(self, request_id: str | None = None) -> list:
        creates = (*MONEY_CREATES, "/api/v1/simulation/deposit/create")
        return [r for r in self.fake.requests if r.method == "POST" and r.path in creates
                and (request_id is None or (r.body or {}).get("request_id") == request_id
                     or request_id in str((r.body or {}).get("reference")))]

    def objects(self, request_id: str) -> int:
        return sum(self.fake.count(c, request_id) for c in self.fake.objects if c != "deposits")

    def journals(self, leg_id: str) -> list[dict]:
        """The leg's journals: those naming it, and those posted under its id."""
        return [j for j in self.store.rows("journals")
                if j["source_leg_id"] == leg_id or j["journal_id"] == f"j-{leg_id}"]


def assert_moved_once(world: World) -> None:
    """The crash fixture's property: one provider object per id, one journal per leg."""
    for leg in world.legs():
        assert world.objects(leg.request_id) <= 1, leg.request_id
        assert len(world.journals(leg.leg_id)) <= 1, leg.leg_id
        if leg.state == "settled":
            assert [j["journal_id"] for j in world.journals(leg.leg_id)] == [leg.journal_id]
        sent = {(r.body or {}).get("request_id") for r in world.posts(leg.request_id)}
        assert sent <= {leg.request_id}, "a retry used a new id"


def finish(world: World) -> list[ob.Leg]:
    """The payout after the advance: driven to PAID, swept, both legs closed."""
    payout = world.legs()[1]
    assert payout.state == "submitted" and payout.provider_status == "SCHEDULED"
    world.pay(payout)
    reconcile.sweep(world.gateway)
    return world.legs()


# --------------------------------------------------------------------- approval binding


def setup(case_id: str, world: World | None = None):
    """The stored approval, what is presented, and the gateway the case runs on."""
    change = CASES[case_id]["change"] or {}
    terms = copy.deepcopy(BASE)
    env = {"now": BINDING["now"], "current_observed_snapshot_id": OBSERVED,
           "gateway_mode": BASE["mode"]}
    for key, value in change.items():
        if match := LEG_TERM.match(key):
            terms["legs"][int(match[1])][match[2]] = value
        elif key == "legs[+]":
            terms["legs"].append(value)
        elif key in ("snapshot_id",):
            terms[key] = value
        elif key in env:
            env[key] = value
    # A ledger-backed refusal is about a validly bound plan: those cases bind the changed terms.
    rehash = change.get("rehash") or case_id in LEDGER
    stored = bind_terms(terms if rehash else BASE)
    presented = stored.model_dump(mode="json") | {"legs": plan_of(terms)["legs"],
                                                  "snapshot_id": terms["snapshot_id"]}
    world = world or World(mode=env["gateway_mode"])
    world.gateway.record(stored)  # bound at the fixture's now; the case's clock runs after
    world.now = datetime.fromisoformat(env["now"])
    if "observation_age_h" in change:
        for account in world.store.rows("account_observations"):
            world.store.observe(account["account_id"], "known",
                                NOW - timedelta(hours=change["observation_age_h"]))
    return world, stored, presented, env["current_observed_snapshot_id"]


def test_every_fixture_case_is_carried():
    refused = {c for c in CASES if CASES[c]["expect"].get("refused")}
    assert refused | {"ok", "replayed-approval"} | ROUTE == set(CASES)
    assert LEDGER <= refused


@pytest.mark.parametrize("case_id", [c for c in CASES if CASES[c]["expect"].get("refused")])
def test_a_refused_approval_moves_nothing_and_writes_nothing(case_id):
    world, _, presented, current = setup(case_id)
    before = world.store.dump()
    verdict = world.gateway.execute(presented, current_snapshot_id=current)
    assert isinstance(verdict, Refusal), verdict
    assert verdict.code == CASES[case_id]["expect"]["refused"], verdict
    assert world.store.dump() == before
    assert world.gateway.conn.execute("SELECT count(*) FROM execution_legs").fetchone() == (0,)
    assert world.gateway.conn.execute("SELECT used_at FROM approvals").fetchone() == (None,)
    assert world.posts() == []


def test_altered_approval_refused():
    for case_id in ("amount-altered", "counterparty-altered", "leg-added"):
        world, _, presented, current = setup(case_id)
        verdict = world.gateway.execute(presented, current_snapshot_id=current)
        assert isinstance(verdict, Refusal) and verdict.code == "approval_altered", case_id
        assert world.posts() == []


def test_no_movement_from_unowned_funds():
    world, _, presented, current = setup("unowned-source")
    verdict = world.gateway.execute(presented, current_snapshot_id=current)
    assert isinstance(verdict, Refusal) and verdict.code == "unowned_funds"
    # The advance's money is the pool's: a leg naming another borrower's facility is refused too.
    terms = copy.deepcopy(BASE) | {"approval_id": "apr-other"}
    terms["legs"] = [terms["legs"][0] | {"counterparty": "lender/venue"}]
    other = bind_terms(terms)
    world.gateway.record(other)
    verdict = world.gateway.execute(other, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "unowned_funds"
    assert world.posts() == []


def test_ok_queues_both_legs_under_their_fixed_request_ids():
    expect = CASES["ok"]["expect"]
    world, stored, presented, current = setup("ok")
    done = world.execute(stored, presented, current)
    assert isinstance(done, Execution) and done.execution_id == stored.approval_id
    ids = [rid.replace("<plan_hash[:12]>", stored.plan_hash[:12]) for rid in expect["request_ids"]]
    assert [leg.request_id for leg in done.legs] == ids
    assert len(done.legs) == expect["legs_queued"]
    advance, payout = done.legs
    assert (advance.state, advance.reconciled, advance.journal_id) == (
        "settled", True, "j-adv-a-disburse")
    assert payout.state == "submitted"  # the payout started only once the advance settled
    assert payout.after == (1,)
    # Queued: the payroll reservation is committed, its units pending out under the leg id.
    res = world.store.reservation("res-payroll-1")
    assert res.state == "committed"
    flows = {f["flow_id"]: f for f in world.store.rows("expected_flows")}
    assert flows[payout.leg_id]["state"] == "pending"
    assert flows[payout.leg_id]["amount_minor"] == 5_000_000
    advance, payout = finish(world)
    assert payout.state == "settled" and payout.reconciled
    assert_moved_once(world)


def test_replayed_approval_refused_and_its_ids_never_change():
    world, stored, presented, current = setup("replayed-approval")
    first = world.execute(stored, presented, current)
    assert isinstance(first, Execution)
    posts = len(world.posts())
    second = world.gateway.execute(presented, current_snapshot_id=current)
    assert isinstance(second, Refusal)
    assert second.code == CASES["replayed-approval"]["expect"]["second"]["refused"]
    assert [leg.request_id for leg in world.legs()] == [leg.request_id for leg in first.legs]
    assert len(world.posts()) == posts


def test_sandbox_preflight_reads_the_provider_wallet_before_anything_is_queued():
    world = World(mode="sandbox")
    approval = bind_terms(BASE, mode="sandbox")
    world.fake.balances[CONNECTED_ACCOUNT]["USD"] = 4_999_999  # one cent short of payroll
    world.gateway.record(approval)
    verdict = world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "insufficient_spendable"
    assert "wallet" in verdict.detail
    assert world.legs() == [] and world.posts() == []
    world.fake.balances[CONNECTED_ACCOUNT]["USD"] = 5_000_000
    assert isinstance(world.gateway.execute(approval, current_snapshot_id=OBSERVED), Execution)


def test_two_discretionary_legs_cannot_spend_the_same_cash():
    world = World()
    terms = copy.deepcopy(BASE) | {"approval_id": "apr-split"}
    leg = {"kind": "payout", "amount": 1_000_000, "currency": "USD",
           "source": "borrower-a/operating", "counterparty": "ben-payroll-1",
           "funded_by": "spendable"}
    terms["legs"] = [leg | {"index": 1}, leg | {"index": 2}]  # 10k each fits; 20k breaks the floor
    approval = bind_terms(terms)
    world.gateway.record(approval)
    verdict = world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "breaks_floor"


# ----------------------------------------------------------------------- crash and retry


def arm(world: World, case: dict) -> None:
    if point := re.match(r"crash at (\w+)", case["fault"]):
        if point[1] == "after_send_before_response":
            world.wire.after_create = lambda: (_ for _ in ()).throw(Crash(point[1]))
        else:
            world.armed.add((point[1], 1))
        return
    match case["id"]:
        case "timeout-after-accept":
            world.fake.arm("timeout_after_accept")
        case "timeout-before-send":
            world.fake.arm("timeout_before_send")
        case "duplicate-on-resubmit":  # the create landed, the wire said it never left,
            def landed_unseen():       # and the first lookup misses it
                world.fake.respond_next(200, {"items": [], "has_more": False})
                raise TransportTimeout(after_send=False)
            world.wire.after_create = landed_unseen
        case "lookup-errors":
            def lost_then_500s():
                for _ in range(3):
                    world.fake.respond_next(500, {"code": "internal_error", "message": "down"})
                raise TransportTimeout(after_send=True)
            world.wire.after_create = lost_then_500s
        case "two-workers":
            second = world.boot(hooks=False)
            world.race = lambda: second.run(BASE["approval_id"])
        case unknown:
            raise AssertionError(f"no fault wired for {unknown}")


@pytest.mark.parametrize("case", CRASH["cases"], ids=[c["id"] for c in CRASH["cases"]])
def test_crash_and_retry(case):
    world = World()
    arm(world, case)
    approval = bind_terms(BASE)
    world.execute(approval)
    advance, payout = world.legs()
    expect = case["expect"]
    if case["id"] == "lookup-errors":
        assert (advance.state, payout.state) == (expect["state"], expect["leg2"])
        assert world.gateway.incidents(open_only=True)[0]["kind"] == "outcome_unknown"
        world.gateway.run(approval.approval_id)  # the provider answers again: adopted
        advance, payout = world.legs()
    assert world.objects(advance.request_id) == 1
    assert len(world.journals(advance.leg_id)) == 1
    assert advance.state == "settled" and advance.journal_id == "j-adv-a-disburse"
    if "posts_to_provider" in expect:
        assert len(world.posts(advance.request_id)) == expect["posts_to_provider"]
    if "request_ids_used" in expect:
        assert {r.body["request_id"] for r in world.posts(advance.request_id)} == {
            advance.request_id}
    if incident := expect.get("incident"):
        (found,) = [i for i in world.gateway.incidents() if i["leg_id"] == advance.leg_id]
        assert found["kind"] == incident["kind"]
        if "closed_by" in incident:
            assert found["closed_by"] == incident["closed_by"]
    if "restart_sees" in case:
        sees = case["restart_sees"].split(",")[0].split(" (")[0]
        assert world.seen.state == sees.split()[0]
    advance, payout = finish(world)
    assert advance.reconciled and payout.state == "settled" and payout.reconciled
    assert_moved_once(world)


def test_no_duplicate_movement():
    """Every crash point on the advance, each followed by restarts: one object, one journal."""
    for point in CRASH["points"]:
        world = World()
        if point == "after_send_before_response":
            world.wire.after_create = lambda: (_ for _ in ()).throw(Crash("send"))
        else:
            world.armed.add((point, 1))
        world.execute(bind_terms(BASE))
        finish(world)
        assert [leg.state for leg in world.legs()] == ["settled", "settled"], point
        assert_moved_once(world)


def test_timeout_resolved_by_query():
    world = World()
    world.fake.arm("timeout_after_accept")
    world.execute(bind_terms(BASE))
    advance = world.legs()[0]
    assert advance.state == "settled" and len(world.posts(advance.request_id)) == 1
    lookups = [r for r in world.fake.requests if r.method == "GET"
               and r.path.endswith(f"?request_id={advance.request_id}")]
    assert lookups, "the unknown outcome was resolved by a lookup, not a resend"
    (incident,) = world.gateway.incidents()
    assert (incident["kind"], incident["closed_by"]) == ("outcome_unknown", "lookup")


def test_a_409_in_flight_is_adopted_never_resent_under_a_new_id():
    world = World()
    approval = bind_terms(BASE)
    advance_id = f"{approval.plan_hash[:12]}-1-advance"

    def in_flight():  # the create landed and is still open; the wire said it never left
        world.fake.hold(advance_id)
        world.fake.respond_next(200, {"items": [], "has_more": False})
        raise TransportTimeout(after_send=False)

    world.wire.after_create = in_flight
    world.execute(approval)
    causes = [c for (c,) in world.gateway.conn.execute(
        "SELECT cause FROM leg_events WHERE leg_id = ? ORDER BY event_seq", (advance_id,))]
    assert "duplicate_request" in causes and "adopted_by_lookup" in causes
    advance = world.legs()[0]
    assert advance.state == "settled" and world.objects(advance_id) == 1
    assert {r.body["request_id"] for r in world.posts(advance_id)} == {advance_id}


def test_a_failed_advance_fails_the_payout_without_a_call_and_frees_its_reservation():
    world = World()
    world.fake.arm("insufficient_funds")
    world.execute(bind_terms(BASE))
    advance, payout = world.legs()
    assert (advance.state, payout.state) == ("failed", "failed")
    assert world.posts(payout.request_id) == []
    events = world.gateway.conn.execute(
        "SELECT cause FROM leg_events WHERE leg_id = ? ORDER BY event_seq",
        (payout.leg_id,)).fetchall()
    assert events[-1] == ("dependency_failed",)
    assert world.store.reservation("res-payroll-1").state == "held"
    flows = {f["flow_id"]: f["state"] for f in world.store.rows("expected_flows")}
    assert flows[payout.leg_id] == flows[advance.leg_id] == "cancelled"
    assert MACHINE["dependencies"]["demo"].endswith("payout failed without a call")


def test_mode_b_advance_is_a_labelled_deposit_and_a_lost_answer_is_looked_up():
    world = World(leg_mode="B")
    done = world.execute(bind_terms(BASE))
    advance, payout = done.legs
    assert advance.receipt_label == "advance inflow (sandbox simulation)"
    assert advance.state == "settled" and advance.journal_id == "j-adv-a-disburse"
    (deposit,) = world.posts(advance.request_id)
    assert deposit.body["reference"].endswith(advance.request_id)
    assert payout.receipt_label == "payout from the operator account"
    other = World(leg_mode="B")
    other.fake.arm("timeout_after_accept")
    other.execute(bind_terms(BASE))
    advance, payout = other.legs()
    assert advance.state == "settled" and advance.reconciled
    assert payout.state == "submitted"
    assert not other.gateway.incidents(open_only=True)
    assert len(other.posts(advance.request_id)) == 1


def test_an_unreadable_create_answer_is_an_unknown_outcome_never_an_error():
    world = World()
    approval = bind_terms(BASE)
    advance_id = f"{approval.plan_hash[:12]}-1-advance"
    # The create is answered 201 with no amount: the request may have moved money.
    world.fake.respond_next(201, {"id": "cat-x", "request_id": advance_id, "status": "SETTLED"})
    done = world.execute(approval)
    assert isinstance(done, Execution)
    advance, payout = done.legs
    assert (advance.state, payout.state) == ("unknown", "pending")
    assert world.gateway.incidents(open_only=True)[0]["kind"] == "outcome_unknown"


# ------------------------------------------------------------- vet round 2 regressions


def repayable(world: World) -> None:
    """adv-a disbursed and its first week's revenue observed: 3,600.00 owed."""
    from app.finance.lending import disburse, observe_revenue

    disburse(world.store, "adv-a", now=NOW, journal_id="j-adv-a-disburse")
    week_end = NOW - timedelta(hours=1)
    observe_revenue(world.store, "adv-a", week_end, 2_400_000, observed_at=week_end,
                    source="sales ledger")


def legs_of(approval_id: str, *legs: dict):
    terms = copy.deepcopy(BASE) | {"approval_id": approval_id}
    terms["legs"] = [{"index": i, "currency": "USD"} | leg for i, leg in enumerate(legs, 1)]
    return bind_terms(terms)


REPAY = {"kind": "repayment", "amount": 360_000, "source": "borrower-a/operating",
         "counterparty": "lender/operating", "facility_id": "adv-a"}


def test_a_journal_the_ledger_refuses_is_an_incident_not_a_crash():
    world = World()
    # The provider settles the advance, but by then the pool's balance has gone stale.
    world.wire.after_create = lambda: world.store.observe("lender/operating", "known",
                                                          NOW - timedelta(hours=7))
    done = world.execute(bind_terms(BASE))
    advance = done.legs[0]
    assert advance.state == "submitted" and advance.journal_id is None
    (incident,) = world.gateway.incidents(open_only=True)
    # A stale pool adds nothing to K_p, so the disbursal is refused beyond capacity.
    assert incident["kind"] == "ledger_refused" and "beyond_capacity" in incident["detail"]
    reconcile.sweep(world.gateway)  # the sweep goes on past it
    world.store.observe("lender/operating", "known", NOW)
    world.gateway.run(BASE["approval_id"])
    advance = world.legs()[0]
    assert advance.state == "settled" and advance.journal_id == "j-adv-a-disburse"
    assert world.gateway.incidents(open_only=True) == []


def test_a_queued_advance_speaks_for_the_pools_cash():
    from app.finance.ledger import check_outflow

    world = World()

    def lost():
        for _ in range(3):
            world.fake.respond_next(500, {"code": "internal_error", "message": "down"})
        raise TransportTimeout(after_send=True)

    world.wire.after_create = lost
    world.execute(bind_terms(BASE))
    assert world.legs()[0].state == "unknown"  # sent, not yet settled
    # 35,000.00 spendable before; the 10,000.00 in flight is no longer free to spend.
    refusal = check_outflow(world.store.view("lender/operating"), 3_000_000, NOW)
    assert refusal is not None and refusal.code == "insufficient_spendable"


def test_a_reservation_funded_repayment_settles_its_reservation():
    world = World()
    repayable(world)
    world.store.hold("borrower-a/operating", 360_000, now=NOW, reservation_id="res-repay")
    approval = legs_of("apr-res-repay", REPAY | {"funded_by": "reservation:res-repay"})
    (leg,) = world.execute(approval).legs
    assert leg.state == "settled" and leg.reconciled
    assert world.store.reservation("res-repay").state == "settled"
    flows = {f["flow_id"]: f["state"] for f in world.store.rows("expected_flows")}
    assert flows[leg.leg_id] == "settled"


def test_a_reservation_funded_advance_still_needs_an_offered_facility():
    world = World()
    repayable(world)  # adv-a is active now
    approval = legs_of("apr-again", {"kind": "advance", "amount": 1_000_000,
                                     "source": "lender/operating",
                                     "counterparty": "borrower-a/operating",
                                     "facility_id": "adv-a",
                                     "funded_by": "reservation:res-line-b"})
    world.gateway.record(approval)
    verdict = world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "reservation_mismatch"
    assert world.posts() == []


def test_an_fx_leg_recorded_by_another_process_runs():
    world = World()
    world.store.open_account("borrower-a/eur", "borrower-a", "EUR", as_of=NOW)
    fund(world.store, "borrower-a/operating", 5_000_000)
    worker = world.boot(hooks=False)  # started before the approval was recorded
    approval = legs_of("apr-fx-2", {"kind": "fx", "amount": 1_110_000,
                                    "source": "borrower-a/operating",
                                    "counterparty": "borrower-a/eur", "to_currency": "EUR"})
    world.gateway.record(approval)
    done = worker.execute(approval, current_snapshot_id=OBSERVED)
    assert isinstance(done, Execution)
    # the provider settles a conversion at create, so the leg is settled by the same run
    assert done.legs[0].state == "settled" and done.legs[0].provider_id is not None


def test_a_repayment_shares_spendable_cash_with_the_other_legs():
    world = World()
    repayable(world)
    world.store.hold("borrower-a/operating", 1_000_000, now=NOW)  # S(now) 20,000.00
    approval = legs_of("apr-both", REPAY, {"kind": "payout", "amount": 1_700_000,
                                           "source": "borrower-a/operating",
                                           "counterparty": "ben-payroll-1",
                                           "funded_by": "spendable"})
    world.gateway.record(approval)
    verdict = world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "insufficient_spendable"


def test_a_repayment_pays_exactly_what_the_observed_period_owes():
    world = World()
    repayable(world)
    approval = legs_of("apr-short", REPAY | {"amount": 350_000})
    world.gateway.record(approval)
    verdict = world.gateway.execute(approval, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "reservation_mismatch"
    assert world.posts() == []


def test_a_period_with_no_revenue_does_not_block_the_next():
    from app.finance.lending import disburse, observe_revenue

    world = World()
    disburse(world.store, "adv-a", now=NOW, journal_id="j-adv-a-disburse")
    for weeks_ago, revenue in ((2, 0), (1, 2_400_000)):
        end = NOW - timedelta(days=7 * weeks_ago - 6)
        observe_revenue(world.store, "adv-a", end, revenue, observed_at=end, source="sales")
    (leg,) = world.execute(legs_of("apr-week-2", REPAY)).legs
    assert leg.state == "settled" and leg.journal_id.startswith("repay:adv-a:")


def test_one_period_is_never_repaid_by_two_legs():
    world = World()
    repayable(world)
    twice = legs_of("apr-twice", REPAY, REPAY)
    world.gateway.record(twice)
    verdict = world.gateway.execute(twice, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "reservation_mismatch"
    # Nor by two approvals, while the first repayment is still on its way.
    world.fake.arm("timeout_after_accept", times=None)
    first = legs_of("apr-first", REPAY)
    assert isinstance(world.execute(first), Execution)
    assert world.legs("apr-first")[0].state == "unknown"
    # (the same plan twice on one snapshot is refused by the store itself: another plan here)
    second = legs_of("apr-second", REPAY, {"kind": "payout", "amount": 100,
                                           "source": "borrower-a/operating",
                                           "counterparty": "ben-payroll-1"})
    world.gateway.record(second)
    verdict = world.gateway.execute(second, current_snapshot_id=OBSERVED)
    assert isinstance(verdict, Refusal) and verdict.code == "reservation_mismatch"


def test_a_fault_in_posting_a_journal_is_raised_not_filed_as_a_refusal():
    world = World()

    def broken(_conn, _leg):
        raise RuntimeError("a bug, not a ledger refusal")

    world.gateway.outbox.post_journal = broken
    with pytest.raises(RuntimeError):
        world.execute(bind_terms(BASE))
    assert world.gateway.incidents() == []

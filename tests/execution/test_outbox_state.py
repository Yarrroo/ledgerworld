"""The outbox and the leg state machine: money moves once under retries, timeouts and crashes.

Every case of the execution design's `crash-and-retry.json` runs the base approval of
`approval-binding.json` (an advance, then the payroll payout after it) through the outbox on a
SQLite store, against an in-file provider double that rejects a duplicate `request_id` the way the
provider does. A crash kills the outbox object; the next one is built from the same store, as a
restarted process would be. `leg-state-machine.json` is the transition table under test.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from dataclasses import replace
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest
from app.execution import outbox as ob
from app.execution import state
from app.finance.schemas import EXPONENT, BoundApproval, ProviderOp
from hypothesis import given, settings
from hypothesis import strategies as st

FIXTURES = state.DESIGN / "fixtures"
MACHINE = json.loads((FIXTURES / "leg-state-machine.json").read_text())
CRASH = json.loads((FIXTURES / "crash-and-retry.json").read_text())
BASE = json.loads((FIXTURES / "approval-binding.json").read_text())["base"]
RECONCILIATION = {c["id"]: c for c in json.loads((FIXTURES / "reconciliation.json").read_text())[
    "cases"]}


def plan_hash(base: dict) -> str:
    terms = {k: base[k] for k in ("entity", "account", "legs", "snapshot_id", "mode")}
    return hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def approval(base: dict) -> BoundApproval:
    legs = [
        {k: v for k, v in leg.items() if k != "currency"}
        | {"amount": {"minor": leg["amount"], "currency": leg["currency"]}}
        for leg in base["legs"]
    ]
    return BoundApproval.model_validate(
        {k: base[k] for k in ("approval_id", "entity", "account", "snapshot_id", "expires_at",
                              "mode", "approver")}
        | {"legs": legs, "plan_hash": plan_hash(base)}
    )


APPROVAL = approval(BASE)
PLAN = {1: ob.LegPlan("advance inflow", "connected_account_transfer"),
        2: ob.LegPlan("payroll payout", "transfer")}


class Crash(Exception):
    """The process dies here."""


class Faults:
    """Crash points armed per leg index; each fires once."""

    def __init__(self, armed=()) -> None:
        self.armed = set(armed)

    def hit(self, point: str, leg: ob.Leg) -> None:
        if (point, leg.index) in self.armed:
            self.armed.discard((point, leg.index))
            raise Crash(point)


class FakeProvider:
    """The provider double: one object per accepted request id, a duplicate id is rejected (it is
    never returned), lookups by request id can error or miss an object that exists, and a `GET`
    shows the object settled."""

    def __init__(self, faults: Faults) -> None:
        self.faults = faults
        self.objects: dict[str, list[ob.ProviderObject]] = defaultdict(list)
        self.posts: Counter[str] = Counter()
        self.ids_used: dict[int, set[str]] = defaultdict(set)
        # leg index → "before_send" | "after_accept" | "landed_unseen" (the transport reports
        # a timeout before send, but the request landed), once
        self.timeouts: dict[int, str] = {}
        self.overrides: dict[int, dict] = {}  # leg index → fields a `GET` reports instead
        self.foreign: list[ob.ProviderObject] = []  # objects a lookup returns that are not ours
        self.rejects: set[int] = set()
        self.find_errors = 0
        self.stale_finds = 0

    def send(self, leg: ob.Leg) -> ob.ProviderObject:
        self.ids_used[leg.index].add(leg.request_id)
        timeout = self.timeouts.pop(leg.index, None)
        if timeout == "before_send":
            raise ob.OutcomeUnknown(may_have_sent=False)
        self.posts[leg.request_id] += 1
        if leg.index in self.rejects:
            raise ob.Rejected("validation_error")
        if self.objects[leg.request_id]:
            raise ob.DuplicateRequest("duplicate_request_id")
        obj = ob.ProviderObject(f"p-{sum(map(len, self.objects.values())) + 1}", leg.request_id,
                                "PROCESSING", leg.amount_minor, leg.currency, ("id", "status"))
        self.objects[leg.request_id].append(obj)
        self.faults.hit("after_send_before_response", leg)
        if timeout == "after_accept":
            raise ob.OutcomeUnknown(may_have_sent=True)
        if timeout == "landed_unseen":
            raise ob.OutcomeUnknown(may_have_sent=False)
        return obj

    def find(self, leg: ob.Leg) -> list[ob.ProviderObject]:
        if self.find_errors:
            self.find_errors -= 1
            raise ob.LookupFailed("500")
        if self.stale_finds:
            self.stale_finds -= 1
            return []
        return [*self.objects[leg.request_id], *self.foreign]

    def get(self, leg: ob.Leg) -> ob.ProviderObject:
        (obj,) = [o for o in self.objects[leg.request_id] if o.provider_id == leg.provider_id]
        settled = {"status": "PAID" if leg.kind == "payout" else "SETTLED"}
        return replace(obj, **settled | self.overrides.get(leg.index, {}))


def post_journal(conn: sqlite3.Connection, leg: ob.Leg) -> str:
    """The ledger double: journals are counted, never deduplicated, so a second post shows."""
    n = conn.execute("SELECT count(*) FROM journals WHERE leg_id = ?", (leg.leg_id,)).fetchone()[0]
    conn.execute("INSERT INTO journals VALUES (?, ?)", (f"j-{leg.leg_id}-{n + 1}", leg.leg_id))
    return f"j-{leg.leg_id}-{n + 1}"


class World:
    """One store, one provider, and the outbox of the current process."""

    def __init__(self, path: Path, approval_: BoundApproval = APPROVAL, plan=PLAN, faults=None):
        self.path, self.approval = path, approval_
        self.faults = faults or Faults()
        self.provider = FakeProvider(self.faults)
        self.seen: list[ob.Leg] = []  # leg 1 as each restart finds it
        conn = sqlite3.connect(path)
        ob.install(conn)
        conn.execute("CREATE TABLE journals (journal_id TEXT NOT NULL, leg_id TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO approvals (approval_id, entity_id, account_id, snapshot_id, plan_hash,"
            " mode, approver, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (approval_.approval_id, approval_.entity, approval_.account, approval_.snapshot_id,
             approval_.plan_hash, approval_.mode, approval_.approver, "2026-11-05T10:00:00Z",
             approval_.expires_at.isoformat()))
        conn.commit()
        conn.close()
        self.outbox = self.boot(recover=False)
        self.queued = self.outbox.queue(approval_, plan)

    def boot(self, recover: bool = True) -> ob.Outbox:
        outbox = ob.Outbox(sqlite3.connect(self.path), post_journal, on_point=self.faults.hit)
        if recover:
            outbox.recover()
        return outbox

    def run(self, restarts: int = 12) -> list[ob.Leg]:
        for _ in range(restarts):
            try:
                return self.outbox.drive(self.approval.approval_id, self.provider)
            except Crash:
                self.outbox.conn.close()
                self.outbox = self.boot(recover=False)
                self.seen.append(self.outbox.legs(self.approval.approval_id)[0])
                self.outbox.recover()
        raise AssertionError("the legs did not finish")

    def legs(self) -> list[ob.Leg]:
        return self.outbox.legs(self.approval.approval_id)

    def rows(self, sql: str, *args) -> list[tuple]:
        return self.outbox.conn.execute(sql, args).fetchall()

    def journals(self, leg: ob.Leg) -> int:
        return self.rows("SELECT count(*) FROM journals WHERE leg_id = ?", leg.leg_id)[0][0]


def assert_money_moved_once(world: World) -> None:
    """The fixture's property, and the outbox's bookkeeping around it."""
    for rid, objects in world.provider.objects.items():
        assert len(objects) <= 1, f"{rid}: {len(objects)} provider objects"
    queued = {leg.leg_id: leg.request_id for leg in world.queued}
    for leg in world.legs():
        assert world.journals(leg) <= 1, f"{leg.leg_id}: {world.journals(leg)} journals"
        assert leg.leg_id == leg.request_id == queued[leg.leg_id]
        assert leg.request_id == ob.request_id(world.approval.plan_hash, leg.index, leg.kind)
        assert world.provider.ids_used[leg.index] <= {leg.request_id}, "a retry used a new id"
        if leg.state == "settled":
            assert world.journals(leg) == 1 and leg.journal_id is not None
        # One leg_events row per transition: an unbroken chain from queued to the current state.
        events = world.rows("SELECT from_state, to_state FROM leg_events WHERE leg_id = ?"
                            " ORDER BY event_seq", leg.leg_id)
        assert events[0] == (None, "pending")
        for (_, before), (frm, to) in pairwise(events):
            assert frm == before
            state.check(frm, to, ledger_only=leg.ledger_only)
        assert events[-1][1] == leg.state


# ---------------------------------------------------------------------------- crash-and-retry

def arm(world: World, case: dict) -> int:
    """Inject the case's fault; returns how many drive calls the case makes."""
    if point := re.match(r"crash at (\w+)", case["fault"]):
        world.faults.armed.add((point[1], 1))
        return 1
    match case["id"]:
        case "timeout-after-accept":
            world.provider.timeouts[1] = "after_accept"
        case "timeout-before-send":
            world.provider.timeouts[1] = "before_send"
        case "duplicate-on-resubmit":  # the first send landed unseen, the first lookup misses it
            world.provider.timeouts[1] = "landed_unseen"
            world.provider.stale_finds = 1
        case "lookup-errors":
            world.provider.timeouts[1] = "after_accept"
            world.provider.find_errors = 3
            return 3
        case "two-workers":
            other, fired = world.boot(recover=False), []
            other.on_point = None

            def race(point: str, leg: ob.Leg) -> None:
                if point == "after_outbox_write_before_submitted" and not fired:
                    fired.append(point)
                    other.drive(world.approval.approval_id, world.provider)

            world.outbox.on_point = race
        case unknown:
            raise AssertionError(f"no fault wired for case {unknown}")
    return 1


def restart_saw(leg: ob.Leg) -> str:
    if leg.state == "submitted":
        return "submitted, provider_id null" if leg.provider_id is None else (
            "submitted with provider_id")
    if leg.state == "settled":
        return f"settled, reconciled {str(leg.reconciled).lower()}"
    return leg.state


@pytest.mark.parametrize("case", CRASH["cases"], ids=[c["id"] for c in CRASH["cases"]])
def test_crash_and_retry(case: dict, tmp_path: Path) -> None:
    world = World(tmp_path / "store.db")
    for _ in range(arm(world, case)):
        world.run()
    if "restart_sees" in case:
        assert [restart_saw(leg) for leg in world.seen] == [case["restart_sees"].split(" (")[0]]

    advance, payout = world.legs()
    incidents = world.rows("SELECT kind, closed_at, closed_by FROM incidents WHERE leg_id = ?",
                           advance.leg_id)
    for key, want in case["expect"].items():
        match key:
            case "provider_objects":
                assert len(world.provider.objects[advance.request_id]) == want
            case "journals":
                assert world.journals(advance) == want
            case "state":
                assert advance.state == want
            case "posts_to_provider":
                assert world.provider.posts[advance.request_id] == want
            case "request_ids_used":
                assert len(world.provider.ids_used[1]) == want
            case "reconciled":
                assert advance.reconciled is want
            case "leg2":
                assert payout.state == want
                assert world.provider.posts[payout.request_id] == 0
            case "incident":
                (found,) = [i for i in incidents if i[0] == want["kind"]]
                if "closed_by" in want:
                    assert found[2] == want["closed_by"]
                if "open" in want:
                    assert (found[1] is None) is want["open"]
            case other:
                raise AssertionError(f"expect key {other} is not checked")
    assert_money_moved_once(world)


def test_a_live_worker_leaves_a_claimed_leg_alone(tmp_path: Path) -> None:
    """A second worker that runs between the claim and the send neither sends nor looks the
    leg up: `submitted` without a provider id is somebody's call in flight."""
    world = World(tmp_path / "store.db")
    other, fired = world.boot(recover=False), []

    def race(point: str, leg: ob.Leg) -> None:
        if point == "after_submitted_before_send" and leg.index == 1 and not fired:
            fired.append(other.drive(world.approval.approval_id, world.provider))

    world.outbox.on_point = race
    advance, payout = world.run()
    assert [leg.state for leg in fired[0]] == ["submitted", "pending"]
    assert (advance.state, payout.state) == ("settled", "settled")
    assert world.provider.posts[advance.request_id] == 1
    assert_money_moved_once(world)


def test_lookup_errors_then_recovers(tmp_path: Path) -> None:
    """After the errors stop, the same unknown leg is adopted and the payout runs once."""
    world = World(tmp_path / "store.db")
    world.provider.timeouts[1] = "after_accept"
    world.provider.find_errors = 3
    for _ in range(4):
        world.run()
    assert [leg.state for leg in world.legs()] == ["settled", "settled"]
    assert sum(world.provider.posts.values()) == 2
    assert_money_moved_once(world)


@settings(max_examples=60, deadline=None)
@given(
    crashes=st.sets(st.tuples(st.sampled_from(CRASH["points"]), st.sampled_from([1, 2])),
                    max_size=5),
    timeouts=st.dictionaries(st.sampled_from([1, 2]), st.sampled_from(["before_send",
                                                                       "after_accept"])),
)
def test_any_crash_any_restarts_moves_money_once(crashes, timeouts) -> None:
    """crash-and-retry.json's property: any crash points on any legs, any restarts."""
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp) / "store.db", faults=Faults(crashes))
        world.provider.timeouts.update(timeouts)
        legs = world.run()
        assert [(leg.state, leg.reconciled) for leg in legs] == [("settled", True)] * 2
        assert all(len(objects) == 1 for objects in world.provider.objects.values())
        assert_money_moved_once(world)
        world.outbox.conn.close()


# ----------------------------------------------------------------------------- state machine

def test_allowed_transitions_pass_and_forbidden_ones_raise() -> None:
    assert set(state.STATES) == {"pending", "submitted", "settled", "failed", "unknown"}
    assert len(MACHINE["allowed"]) == 9 and len(MACHINE["forbidden"]) == 5
    for rule in MACHINE["allowed"]:
        state.check(rule["from"], rule["to"])
    for rule in MACHINE["forbidden"]:
        if rule["from"] != "*" and "when" not in rule:
            with pytest.raises(state.IllegalTransition):
                state.check(rule["from"], rule["to"])
    for frm in state.STATES:
        for to in state.STATES:
            if (frm, to) not in state.ALLOWED:
                with pytest.raises(state.IllegalTransition):
                    state.check(frm, to)
    state.check("pending", "settled", ledger_only=True)


def test_ledger_only_leg_settles_without_a_provider(tmp_path: Path) -> None:
    base = BASE | {"approval_id": "apr-repay", "legs": [
        {"index": 1, "kind": "repayment", "amount": 1080000, "currency": "USD",
         "source": "borrower-a/operating", "counterparty": "lender/operating"}]}
    plan = {1: ob.LegPlan(state.LEDGER_ONLY_LABEL, ledger_only=True)}
    world = World(tmp_path / "store.db", approval(base), plan)
    (leg,) = world.run()
    assert (leg.state, leg.provider_id, leg.receipt_label, leg.reconciled) == (
        "settled", None, MACHINE["ledger_only"]["receipt_label"],
        RECONCILIATION["repayment-mode-b"]["expect"]["reconciled"])
    assert not world.provider.posts and world.journals(leg) == 1
    assert world.rows("SELECT from_state, to_state, cause FROM leg_events WHERE leg_id = ?"
                      " ORDER BY event_seq", leg.leg_id) == [
        (None, "pending", "queued"), ("pending", "settled", "ledger_only")]


def test_failed_dependency_fails_the_payout_without_a_call(tmp_path: Path) -> None:
    """leg-state-machine.json's demo: advance failed → payout failed without a call."""
    world = World(tmp_path / "store.db")
    world.provider.rejects.add(1)
    advance, payout = world.run()
    assert (advance.state, payout.state) == ("failed", "failed")
    assert world.provider.posts[payout.request_id] == 0
    assert world.rows("SELECT cause FROM leg_events WHERE leg_id = ? AND to_state = 'failed'",
                      payout.leg_id) == [("dependency_failed",)]
    # A failed leg is never retried.
    world.run()
    assert world.provider.posts[advance.request_id] == 1
    assert_money_moved_once(world)


def test_a_timeout_that_may_have_sent_is_never_resent_blind(tmp_path: Path) -> None:
    """Lookup finds nothing after a timeout that may have left: the leg stays unknown."""
    world = World(tmp_path / "store.db")
    world.provider.timeouts[1] = "after_accept"
    world.provider.stale_finds = 5
    advance, payout = world.run()
    assert (advance.state, payout.state) == ("unknown", "pending")
    assert world.provider.posts[advance.request_id] == 1
    assert world.rows("SELECT closed_at FROM incidents WHERE leg_id = ? AND kind ="
                      " 'outcome_unknown'", advance.leg_id) == [(None,)]


def test_queue_is_idempotent_and_ids_never_change(tmp_path: Path) -> None:
    world = World(tmp_path / "store.db")
    again = world.outbox.queue(APPROVAL, PLAN)
    assert again == world.queued
    assert [leg.request_id for leg in again] == [
        f"{APPROVAL.plan_hash[:12]}-1-advance", f"{APPROVAL.plan_hash[:12]}-2-payout"]
    for leg in again:  # the ids are C4's: the contract's pattern and leg id = request id
        ProviderOp(leg_id=leg.leg_id, request_id=leg.request_id, kind=leg.kind, state=leg.state,
                   receipt=None, reconciled=leg.reconciled)
    with pytest.raises(sqlite3.IntegrityError):  # the store refuses a second leg with the id
        world.outbox.conn.execute(
            "INSERT INTO execution_legs SELECT 'x', approval_id, 9, kind, request_id,"
            " source_account, counterparty, currency, amount_minor, funded_by, after_legs,"
            " provider_op, ledger_only, state, provider_id, provider_status, receipt_label,"
            " journal_id, reconciled, attempts, updated_at FROM execution_legs WHERE leg_index = 1")


# ------------------------------------------------------------------- review regressions

def test_a_restart_after_the_send_never_resends_on_a_lookup_miss(tmp_path: Path) -> None:
    """The request left, the process died, and the first lookup lags: the leg waits as unknown
    rather than sending again; the next lookup adopts it."""
    world = World(tmp_path / "store.db")
    world.faults.armed.add(("after_send_before_response", 1))
    world.provider.stale_finds = 1
    advance, payout = world.run()
    assert (advance.state, payout.state) == ("unknown", "pending")
    assert world.provider.posts[advance.request_id] == 1
    advance, payout = world.run()
    assert (advance.state, payout.state) == ("settled", "settled")
    assert world.provider.posts[advance.request_id] == 1
    assert_money_moved_once(world)


@pytest.mark.parametrize("case_id", ["amount-mismatch", "currency-mismatch"])
def test_a_mismatched_settlement_posts_no_journal(case_id: str, tmp_path: Path) -> None:
    """reconciliation.json: the provider settled other terms than the leg's → incident, no
    journal, not reconciled; the payout after it does not start."""
    case = RECONCILIATION[case_id]
    index = {"advance": 1, "payout": 2}[case["leg"]["kind"]]
    reported = case["provider"]
    world = World(tmp_path / "store.db")
    world.provider.overrides[index] = (
        {"amount_minor": int(Decimal(reported["amount"]).scaleb(EXPONENT["USD"]))}
        if "amount" in reported
        else {"currency": reported["currency"]})
    leg = world.run()[index - 1]
    world.run()
    assert (leg.state, leg.reconciled, world.journals(leg)) == ("submitted", False, 0)
    assert case["expect"]["journal"] == "none"
    assert world.rows("SELECT kind FROM incidents WHERE leg_id = ? AND closed_at IS NULL",
                      leg.leg_id) == [(case["expect"]["incident"]["kind"],)]
    assert all(leg.state != "settled" for leg in world.legs()[index - 1:])


def test_paid_then_failed_opens_an_incident_and_never_unposts(tmp_path: Path) -> None:
    """reconciliation.json paid-then-failed: the settled payout's GET later shows FAILED."""
    expect = RECONCILIATION["paid-then-failed"]["expect"]
    world = World(tmp_path / "store.db")
    world.faults.armed.add(("after_journal_before_reconciled_flag", 2))
    with pytest.raises(Crash):
        world.outbox.drive(APPROVAL.approval_id, world.provider)
    world.provider.overrides[2] = {"status": "FAILED"}
    world.outbox = world.boot()
    for _ in range(2):  # a second pass opens nothing new
        _, payout = world.outbox.drive(APPROVAL.approval_id, world.provider)
    assert (payout.state, payout.reconciled) == ("settled", expect["reconciled"])
    assert world.journals(payout) == 1  # journals_added 0: the posting is never undone here
    assert world.rows("SELECT kind, closed_at FROM incidents WHERE leg_id = ?",
                      payout.leg_id) == [("paid_then_failed", None)]
    assert world.rows("SELECT count(*) FROM leg_events WHERE leg_id = ? AND cause ="
                      " 'paid_then_failed'", payout.leg_id) == [(1,)]
    assert_money_moved_once(world)


def test_a_lookup_never_adopts_another_request_ids_object(tmp_path: Path) -> None:
    world = World(tmp_path / "store.db")
    world.provider.timeouts[1] = "after_accept"
    world.provider.foreign = [ob.ProviderObject("p-x", "not-ours-1", "PAID", 1000000, "USD")]
    advance, payout = world.run()
    assert (advance.state, payout.state) == ("settled", "settled")
    assert advance.provider_id != "p-x"
    assert_money_moved_once(world)


def test_a_busy_commit_rolls_back_and_the_connection_recovers(tmp_path: Path) -> None:
    """A reader holds the store when the claim commits: the commit fails busy, the claim is
    rolled back, and the next drive runs on the same connection."""
    world = World(tmp_path / "store.db")
    world.outbox = ob.Outbox(sqlite3.connect(world.path, timeout=0), post_journal)
    reader = sqlite3.connect(world.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM execution_legs").fetchone()
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        world.outbox.drive(APPROVAL.approval_id, world.provider)
    assert not world.outbox.conn.in_transaction
    reader.execute("COMMIT")
    assert [leg.state for leg in world.legs()] == ["pending", "pending"]
    assert [leg.state for leg in world.run()] == ["settled", "settled"]
    assert_money_moved_once(world)


def test_an_earlier_unsent_claim_does_not_make_a_later_send_resendable(tmp_path: Path) -> None:
    """Claim 1 dies before its send, claim 2 sends and dies before the answer, the lookup lags:
    the leg waits as unknown rather than sending a third time."""
    world = World(tmp_path / "store.db")
    world.faults.armed |= {("after_submitted_before_send", 1), ("after_send_before_response", 1)}
    world.provider.stale_finds = 2
    advance, _ = world.run()
    assert advance.state == "unknown"
    assert world.provider.posts[advance.request_id] == 1
    assert [leg.state for leg in world.run()] == ["settled", "settled"]
    assert_money_moved_once(world)


def test_a_reconciled_payout_that_later_fails_is_caught_by_the_sweep(tmp_path: Path) -> None:
    """The normal path reconciles at once; the sweep's `reconcile` still sees the later FAILED,
    and an operator's close of the incident sticks."""
    world = World(tmp_path / "store.db")
    _, payout = world.run()
    assert payout.reconciled
    world.provider.overrides[2] = {"status": "FAILED"}
    assert world.outbox.reconcile(payout.leg_id, world.provider)
    world.rows("UPDATE incidents SET closed_at = 'now', closed_by = 'operator'")
    for _ in range(2):
        world.outbox.reconcile(payout.leg_id, world.provider)
        world.run()
    payout = world.legs()[1]
    assert (payout.state, payout.reconciled, world.journals(payout)) == ("settled", False, 1)
    assert world.rows("SELECT kind, closed_by FROM incidents WHERE leg_id = ?",
                      payout.leg_id) == [("paid_then_failed", "operator")]
    assert_money_moved_once(world)

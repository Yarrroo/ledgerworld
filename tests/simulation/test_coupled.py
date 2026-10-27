"""The coupled round: social and financial events on one clock, in one transactional round.

Every world here runs on a real OASIS platform (one SQLite file per branch) with
``ScriptedModel``s, through ``Coordinator.run_round``. Fixtures are read unchanged from the
agent-world design and their ``expect`` blocks asserted: clearing-order.json, coupled-chain.json
and round-rollback.json. The rollback cases inject exceptions and cancellation through the
coordinator's hooks and test models, with explicit barriers rather than sleeps; they prove
exception rollback, not process-crash recovery.
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
from pathlib import Path

import pytest
from app.finance.lending import capacity
from app.finance.schemas import ActionIntent
from app.simulation.clock import HORIZON_ROUNDS, ROUND_HOURS, Clock, ClockDrift
from app.simulation.coordinator import Coordinator, clear_intents, deliver, validate_intents
from app.simulation.world import World, WorldUnusable, import_oasis
from app.testing.scripted_model import ScriptedModel, ScriptedPlan
from oasis_finance.actions import FinancialActionType, IntentQueue, NoActionArgs, submit
from oasis_finance.observation import DEFAULT_EPOCH, iso_utc

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"
CLEARING = json.loads((FIXTURES / "clearing-order.json").read_text())
COUPLED = json.loads((FIXTURES / "coupled-chain.json").read_text())
ROLLBACK = json.loads((FIXTURES / "round-rollback.json").read_text())
ACTOR_SPECS = {a["actor_id"]: a for a in
               json.loads((FIXTURES / "actors.json").read_text())["actors"]}
MODEL_ACTORS = ["treasury", "lender", "borrower-b", "borrower-c", "feed"]
T0 = iso_utc(0)
HASH = "0" * 64
iso = iso_utc


def usd(minor: int) -> dict:
    return {"minor": minor, "currency": "USD"}


def account(account_id: str, settled: int, *, reserved: int = 0, floor: int | None = None,
            pending_in: list | None = None, venue: str | None = None) -> dict:
    acc = {"id": account_id, "entity": account_id.split("/")[0], "currency": "USD",
           "observability": "known", "as_of": T0,
           "buckets": {"settled": usd(settled), "reserved": usd(reserved), "pledged": usd(0),
                       "pending_in": pending_in or [], "pending_out": []}}
    if floor is not None:
        acc["floor"] = usd(floor)
    if venue is not None:
        acc["venue"] = venue
    return acc


def lender_and_borrowers() -> dict:
    """coupled-chain.json's lender_before, with borrowers b and c."""
    before = COUPLED["lender_before"]
    (line,) = before["committed_undrawn"]
    return {
        "entities": [{"entity_id": "lender", "name": "Lender pool (synthetic)",
                      "kind": "lender pool"},
                     {"entity_id": "borrower-b", "name": "Borrower B (synthetic)",
                      "kind": "borrower"},
                     {"entity_id": "borrower-c", "name": "Borrower C (synthetic)",
                      "kind": "borrower"}],
        "accounts": [account("lender/operating",
                             before["accounts"]["lender/operating"]["settled"],
                             reserved=line["amount"]),
                     account("lender/venue", before["accounts"]["lender/venue"]["settled"],
                             venue="exchange-venue"),
                     account("borrower-b/operating", 900_000),
                     account("borrower-c/operating", 400_000)],
        "contracts": [{"contract_id": "line-b", "lender": "lender", "borrower": line["to"],
                       "state": "active", "kind": "committed_line", "limit": usd(line["amount"]),
                       "drawn": usd(0), "reservation_id": "line-b:undrawn",
                       "reserved_on": "lender/operating"}],
        "pools": [{"entity": "lender", "floor": usd(before["pool_floor"])}],
    }


def snapshot(*, treasury: bool) -> dict:
    """The coupled lender world, plus LF-1's treasury (system brief §6) when asked."""
    parts = lender_and_borrowers()
    obligations = []
    if treasury:
        parts["entities"].append({"entity_id": "treasury", "name": "Borrower A treasury "
                                  "(synthetic)", "kind": "treasury"})
        parts["accounts"].append(account(
            "treasury/operating", 7_000_000, reserved=5_000_000, floor=3_000_000, pending_in=[
                {"flow_id": "receivable-1", "amount": usd(2_000_000), "expected_at": iso(12),
                 "kind": "receivable"},
                {"flow_id": "withdrawal-1", "amount": usd(1_500_000), "expected_at": iso(48),
                 "kind": "exchange_withdrawal"}]))
        obligations.append({"obligation_id": "payroll-1", "entity": "treasury",
                            "account": "treasury/operating", "amount": usd(5_000_000),
                            "due_at": iso(40), "kind": "payroll", "reservation_id": "payroll-hold"})
    return {"snapshot_id": "snap-coupled", "as_of": T0, "obligations": obligations,
            "exposures": [], **parts}


def plan_model(plan: ScriptedPlan):
    return lambda actor_id, world: plan.model(actor_id, lambda: world.clock.round)


def make_world(tmp_path, branch, *, plan, scenario=(), treasury=False, model=None, hooks=None,
               quiesce_timeout_s=5.0, name=None) -> World:
    workdir = tmp_path / (name or branch)
    workdir.mkdir()
    return World("coupled", branch, snapshot(treasury=treasury),
                 [ACTOR_SPECS[a] for a in MODEL_ACTORS + ["payroll", "market-maker"]],
                 model=model or plan_model(plan), workdir=workdir, scenario=scenario,
                 coordinator=Coordinator(hooks, quiesce_timeout_s=quiesce_timeout_s))


def k_p(world: World) -> int:
    return capacity(world.store, "lender", world.clock.now).K_p


def settled(world: World, account_id: str) -> int:
    return world.store.view(account_id).settled_minor


def run(coro):
    return asyncio.run(coro)


IDLE = [{"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}]


# --------------------------------------------------------------------------------- the clock


def test_one_clock_four_hour_rounds_and_a_drift_fails():
    clock = Clock()
    assert (ROUND_HOURS, HORIZON_ROUNDS) == (4, 18)
    assert (clock.round, clock.now) == (0, DEFAULT_EPOCH)
    clock.advance()
    assert (clock.round, clock.t_hours, clock.sim_minute) == (1, 4, 240)
    clock.check(1)
    with pytest.raises(ClockDrift):
        clock.check(0)


# ---------------------------------------------------------------- clearing-order.json (step 7)


def clearing_world(tmp_path, n) -> World:
    before = CLEARING["ledger_before"]
    tre = before["treasury/operating"]
    flows = [{"flow_id": f"in-{i}", "amount": usd(f["amount"]), "expected_at": iso(f["expected_h"]),
              "kind": "receivable"} for i, f in enumerate(tre["pending_in"], 1)]
    snap = {"snapshot_id": "snap-clearing", "as_of": T0, "obligations": [], "contracts": [],
            "exposures": [], "pools": [],
            "entities": [{"entity_id": e, "name": f"{e} (synthetic)", "kind": k} for e, k in
                         [("treasury", "treasury"), ("borrower-b", "borrower"),
                          ("borrower-c", "borrower")]],
            "accounts": [account("treasury/operating", tre["settled"], reserved=tre["reserved"],
                                 pending_in=flows),
                         account("borrower-b/operating",
                                 before["borrower-b/operating"]["settled"]),
                         account("borrower-c/operating",
                                 before["borrower-c/operating"]["settled"])]}
    workdir = tmp_path / f"clearing-{n}"
    workdir.mkdir()
    rule_actors = [{**ACTOR_SPECS[a], "llm": False} for a in ("treasury", "borrower-b",
                                                               "borrower-c")]
    return World("clearing", "shock", snap, rule_actors, model=plan_model(ScriptedPlan(IDLE)),
                 workdir=workdir)


def fixture_intents() -> dict[str, ActionIntent]:
    return {i["intent_id"]: ActionIntent(branch_id="shock", round=0, evidence_ids=[],
                                         obs_hash=HASH, **i) for i in CLEARING["intents"]}


def clear_in_arrival_order(world: World, order) -> list:
    intents = fixture_intents()
    queue = IntentQueue("shock")
    for intent_id in order:  # env.step's agents answer in any order
        queue.put(intents[intent_id])
    with world.store.engine.begin() as conn:
        return clear_intents(world, conn, queue.drain())


def test_clearing_order_does_not_depend_on_arrival(tmp_path):
    expect = CLEARING["expect"]
    orders = [*CLEARING["arrival_orders"]]
    shuffled = list(CLEARING["arrival_orders"][0])
    rng = random.Random(7)
    for _ in range(3):
        rng.shuffle(shuffled)
        orders.append(list(shuffled))
    dumps = []
    for n, order in enumerate(orders):
        world = clearing_world(tmp_path, n)
        assert world.store.view("treasury/operating").free_minor == \
            CLEARING["spendable_now"]["treasury/operating"]
        cleared = clear_in_arrival_order(world, order)
        assert [c.intent_id for c in cleared] == expect["cleared_order"]
        seqs = [c.journal.seq for c in cleared if c.journal is not None]
        assert seqs == sorted(seqs)
        for c in cleared:
            want = expect["results"][c.intent_id]
            assert c.c2.status == want["status"]
            if want["status"] == "accepted":
                journals = [x.intent_id for x in cleared if x.journal is not None]
                assert journals.index(c.intent_id) + 1 == want["journal_seq"]
                assert c.journal.source_intent_id == c.intent_id
            else:
                assert c.c2.reason == want["reason"]
                assert c.detail["S_now"] == want["spendable_minor"]
        for account_id, buckets in expect["ledger_after"].items():
            view = world.store.view(account_id)
            assert view.settled_minor == buckets["settled"]
            assert view.reserved_minor == buckets.get("reserved", 0)
        dumps.append(world.store.dump())
    assert expect["same_for_every_arrival_order"] is True
    assert all(d == dumps[0] for d in dumps)


def test_the_coordinator_sorts_whatever_order_it_is_handed(tmp_path):
    world = clearing_world(tmp_path, "unsorted")
    intents = fixture_intents()
    with world.store.engine.begin() as conn:
        cleared = clear_intents(world, conn, [intents[i] for i in
                                              CLEARING["arrival_orders"][0]])
    assert [c.intent_id for c in cleared] == CLEARING["expect"]["cleared_order"]


# ------------------------------------------------------------------- coupled-chain.json (T08)


async def coupled_run(tmp_path, branch, rounds=6, **kw):
    plan = ScriptedPlan.load(FIXTURES / "coupled-chain.json")
    world = make_world(tmp_path, branch, plan=plan, scenario=COUPLED["scheduled_events"], **kw)
    async with world:
        assert k_p(world) == COUPLED["lender_before"]["K_p"]
        results = await world.run(rounds)
    return world, results


def by_intent(result) -> dict:
    return {c.intent_id: c for c in result.records}


def test_public_shock_traceable_response(tmp_path):
    expect = COUPLED["expect"]
    shock, results = run(coupled_run(tmp_path, "shock"))
    r4, r5 = results[3], results[4]
    assert (r4.round, r5.round) == (4, 5)

    # Round 4: borrower-c read the rumour and asked for an advance; nothing moved yet.
    req = by_intent(r4)[expect["shock"]["round_4"]["intent"]]
    assert req.type == expect["shock"]["round_4"]["type"]
    assert set(expect["shock"]["round_4"]["evidence_ids"]) <= set(req.evidence_ids)
    assert req.c2.status == expect["shock"]["round_4"]["c2_status"]
    assert req.c2.journal_id is expect["shock"]["round_4"]["journal"]
    assert req.obs_hash == r4.transcript_entry["observations"]["borrower-c"]

    # Round 5: the lender, shown the request, accepted and disbursed: one journal.
    lender = [by_intent(r5)[i] for i in expect["shock"]["round_5"]["intents"]]
    assert [c.type for c in lender] == ["accept", "disburse"]
    assert all(c.c2.status == expect["shock"]["round_5"]["c2_status"] for c in lender)
    assert all(set(expect["shock"]["round_5"]["evidence_ids"]) <= set(c.evidence_ids)
               for c in lender)
    assert len(r5.journals) == expect["shock"]["round_5"]["journals"]
    (journal,) = r5.journals
    assert journal.source_intent_id == expect["shock"]["round_5"]["intents"][1]

    # The cash moved, and the lender's capacity with it.
    for account_id, buckets in expect["shock"]["lender_after"].items():
        assert settled(shock, account_id) == buckets["settled"]
    assert settled(shock, "borrower-c/operating") - 400_000 == \
        expect["shock"]["borrower_c_after"]["borrower-c/operating"]["settled_increase"]
    assert k_p(shock) == expect["shock"]["K_p_after"]

    # The chain of cause, from the journal back to the post.
    want = [journal.journal_id if link == f"journal of {journal.source_intent_id}" else link
            for link in expect["shock"]["trace"]]
    assert shock.trace(journal.journal_id) == want

    # The control branch never saw the rumour: nobody moved and capacity stayed.
    control, cresults = run(coupled_run(tmp_path, "control"))
    c4 = {c.actor_id: c.type for c in cresults[3].records}
    c5 = {c.actor_id: c.type for c in cresults[4].records}
    assert c4["borrower-c"] == expect["control"]["round_4"]["borrower-c"]
    assert c5["lender"] == expect["control"]["round_5"]["lender"]
    assert k_p(control) == expect["control"]["K_p_after"]
    assert "p-r3-1" not in {i["id"] for i in control.state.items}
    # The trap: a committed-line draw could not have shown the capacity move.
    assert COUPLED["lender_before"]["committed_undrawn"][0]["to"] == "borrower-b"


def test_the_advance_lands_at_the_next_round_boundary(tmp_path):
    shock, results = run(coupled_run(tmp_path, "shock"))
    r5, r6 = results[4], results[5]
    assert [j.kind for j in r6.journals] == ["settle_advance"]
    assert r6.journals[0].journal_id == "settle:arrive:adv:req:borrower-c:r4"
    assert shock.state.flow_status["arrive:adv:req:borrower-c:r4"] == "arrived"
    # In round 5 borrower-c's cash was still in flight, promised for t=24.
    (r5_entry,) = [r for r in shock.state.rounds if r["round"] == 5]
    assert r5_entry["journal_ids"] == [r5.journals[0].journal_id]


def test_the_oasis_clock_and_the_round_clock_agree(tmp_path):
    steps = []

    def stepped(world, ctx):
        steps.append((ctx.round, world.clock.round, world.platform.sandbox_clock.time_step))

    shock, _ = run(coupled_run(tmp_path, "shock", rounds=3, hooks={"stepped": stepped}))
    assert steps == [(1, 1, 1), (2, 2, 2), (3, 3, 3)]
    assert {c.round for c in shock.transcript.calls()} == {1, 2, 3}
    # The rumour went on the platform in round 3, before that round's step.
    (post,) = [i for i in shock.state.items if i["id"] == "p-r3-1"]
    assert post["visible_from_h"] == 3 * ROUND_HOURS


def test_a_round_that_fails_mid_way_leaves_the_ledger_untouched(tmp_path):
    async def go():
        plan = ScriptedPlan.load(FIXTURES / "coupled-chain.json")
        world = make_world(tmp_path, "shock", plan=plan, scenario=COUPLED["scheduled_events"])
        async with world:
            await world.run(4)
            before = world.fingerprint()
            world.coordinator.hooks["cleared"] = fail_after_clearing
            with pytest.raises(InjectedFault):
                await world.coordinator.run_round(world)
            assert world.fingerprint() == before
            assert world.unusable is None
            del world.coordinator.hooks["cleared"]
            result = await world.coordinator.run_round(world)
            return world, result

    def fail_after_clearing(world, ctx):
        assert ctx.journals, "the lender's disbursal was written before the fault"
        raise InjectedFault("after step 7")

    world, result = run(go())
    assert result.round == 5 and len(result.journals) == 1
    assert k_p(world) == COUPLED["expect"]["shock"]["K_p_after"]


# ------------------------------------------------- overdue, offered facilities, release (§7.2)


def test_a_late_receipt_is_overdue_before_observations(tmp_path):
    delay = [{"round": 3, "kind": "delay_receipt", "flow_id": "receivable-1", "delay_h": 240,
              "id": "shock-delay"}]

    async def go(branch, scenario):
        world = make_world(tmp_path, branch, plan=ScriptedPlan(IDLE), treasury=True,
                           scenario=scenario)
        async with world:
            seen = {}
            for _ in range(3):
                await world.coordinator.run_round(world)
                body = world.agents["treasury"].observation.body
                (acct,) = [i for i in body["items"] if i["id"] == "acct:treasury/operating"]
                seen[world.clock.round] = ({f["flow_id"]: f["status"] for f in acct["pending_in"]},
                                           acct["settled_minor"])
            return seen

    shock = run(go("shock", delay))
    assert shock[2][0] == {"receivable-1": "expected", "withdrawal-1": "expected"}
    assert shock[3][0] == {"receivable-1": "overdue", "withdrawal-1": "expected"}
    assert shock[3][1] == 7_000_000
    calm = run(go("calm", []))
    # On time it lands in step 2 and leaves pending_in: the account shows the cash instead.
    assert calm[3][0] == {"withdrawal-1": "expected"}
    assert calm[3][1] == 9_000_000


def test_an_offered_facility_clears_through_disburse_and_release_withdraws_an_offer(tmp_path):
    plan = ScriptedPlan([
        {"actor_id": "lender", "round": 1, "tool_calls": [
            {"name": "offer", "args": {"amount_minor": 1_000_000, "currency": "USD",
                                       "to": "borrower-c", "fee_bps": 800}},
            {"name": "offer", "args": {"amount_minor": 500_000, "currency": "USD",
                                       "to": "borrower-b", "fee_bps": 800}}]},
        {"actor_id": "borrower-c", "round": 2, "tool_calls": [
            {"name": "request_advance", "args": {"amount_minor": 1_000_000, "currency": "USD",
                                                 "from": "lender",
                                                 "facility_id": "adv:i-r1-lender-1"}}]},
        {"actor_id": "lender", "round": 2, "tool_calls": [
            {"name": "release", "args": {"target": "offer:adv:i-r1-lender-2"}}]},
        {"actor_id": "borrower-b", "round": 3, "tool_calls": [
            {"name": "request_advance", "args": {"amount_minor": 500_000, "currency": "USD",
                                                 "from": "lender",
                                                 "facility_id": "adv:i-r1-lender-2"}}]},
        *IDLE,
    ])

    async def go():
        world = make_world(tmp_path, "offers", plan=plan)
        async with world:
            return world, await world.run(3)

    world, (r1, r2, r3) = run(go())
    assert [(c.type, c.c2.status) for c in r1.records if c.actor_id == "lender"] == [
        ("offer", "accepted"), ("offer", "accepted")]
    request = by_intent(r2)["i-r2-borrower-c-1"]
    assert request.c2.status == "accepted" and request.journal.kind == "advance_disbursal"
    assert request.c2.journal_id == "j:i-r2-borrower-c-1"
    assert by_intent(r2)["i-r2-lender-1"].c2.status == "accepted"
    # Disbursed in round 2, in flight until the round-3 boundary, then settled.
    assert [j.kind for j in r3.journals][:1] == ["settle_advance"]
    assert settled(world, "borrower-c/operating") == 400_000 + 1_000_000
    assert settled(world, "lender/operating") == 4_500_000 - 1_000_000
    refused = by_intent(r3)["i-r3-borrower-b-1"]
    assert (refused.c2.status, refused.c2.reason) == ("rejected", "no_offered_facility")
    assert settled(world, "borrower-b/operating") == 900_000
    # The actor reads its rejection the next round.
    (c2,) = [c for c in world.state.pending_c2 if c["intent_id"] == "i-r3-borrower-b-1"]
    assert (c2["actor_id"], c2["status"], c2["reason"]) == (
        "borrower-b", "rejected", "no_offered_facility")


# ---------------------------------------------------------------- round-rollback.json (T08)


class InjectedFault(RuntimeError):
    pass


ROLLBACK_ROUND = 10
ROLLBACK_SCENARIO = [
    {"round": 3, "kind": "delay_receipt", "flow_id": "receivable-1", "delay_h": 240,
     "id": "shock-delay"},
    {"round": ROLLBACK_ROUND, "kind": "public_post", "post_id": "p-r10-1", "author": "feed",
     "text": "Payroll day: borrower-a is said to be short of cash."},
    {"round": ROLLBACK_ROUND, "kind": "message", "id": "msg-r10-1", "to": "treasury",
     "text": "Payroll of 50,000.00 is due today."},
]


class Barriers:
    """The actor interleaving of round-rollback.json, with explicit events and records."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.records: list[str] = []
        self.armed = True
        self.stubborn = False
        self.cleanup_gate: asyncio.Event | None = None  # set: a cancelled writer cleans up slowly
        self.in_cleanup = asyncio.Event()
        self.writer: asyncio.Task | None = None


class SiblingModel(ScriptedModel):
    """borrower-b at the rollback round: writes a provisional post, memory entry and intent,
    starts a child task, then waits on a barrier; cancelled, it tries one last write."""

    barriers: Barriers
    world: World

    async def _arun(self, messages, response_format=None, tools=None):
        b = self.barriers
        if not (b.armed and self.round_source() == ROLLBACK_ROUND):
            return self._answer(messages, tools)
        agent = self.world.agents["borrower-b"]
        await agent.env.action.create_post(content="provisional post by borrower-b")
        agent.memory.write_records([memory_record(agent, "provisional memory")])
        submit(self.world.queue, agent.finance_actor,
               [(FinancialActionType.NO_ACTION, NoActionArgs(reason="provisional"))])
        b.records.append("provisional writes")
        b.writer = asyncio.current_task()
        child = asyncio.create_task(self._child(agent))
        b.reached.set()
        try:
            await b.release.wait()
        except asyncio.CancelledError:
            if b.cleanup_gate is not None:
                b.in_cleanup.set()
                await b.cleanup_gate.wait()
            self._cleanup(agent)
            if b.stubborn:  # a writer that will not stop
                b.records.append("stubborn: ignoring cancellation")
                await b.release.wait()
                return self._answer(messages, tools)
            raise
        await child
        return self._answer(messages, tools)

    async def _child(self, agent):
        try:
            await self.barriers.release.wait()
        except asyncio.CancelledError:
            self.barriers.records.append("child cancelled")
            self.world.lifecycle.append(("child_done", "borrower-b"))
            raise
        agent.memory.write_records([memory_record(agent, "late child write")])

    def _cleanup(self, agent):
        b = self.barriers
        agent.memory.write_records([memory_record(agent, "cleanup memory")])
        try:
            submit(self.world.queue, agent.finance_actor,
                   [(FinancialActionType.NO_ACTION, NoActionArgs(reason="cleanup"))])
            b.records.append("cleanup queued")
        except RuntimeError:
            b.records.append("cleanup queue refused")
        b.records.append("cleanup memory written")
        self.world.lifecycle.append(("sibling_cleanup_done", "borrower-b"))


class FailingModel(ScriptedModel):
    """borrower-c at the rollback round: raises once the sibling is at its barrier."""

    barriers: Barriers
    fail: bool = False

    async def _arun(self, messages, response_format=None, tools=None):
        if self.barriers.armed and self.round_source() == ROLLBACK_ROUND and self.fail:
            await self.barriers.reached.wait()
            raise InjectedFault("an actor raised in step 5")
        return self._answer(messages, tools)


def memory_record(agent, text):
    from camel.memories import MemoryRecord
    from camel.messages import BaseMessage
    from camel.types import OpenAIBackendRole

    return MemoryRecord(message=BaseMessage.make_user_message("User", text),
                        role_at_backend=OpenAIBackendRole.USER, agent_id=agent.agent_id)


def rollback_world(tmp_path, name, barriers=None, fail=False, quiesce_timeout_s=5.0) -> World:
    plan = ScriptedPlan(IDLE)

    def model(actor_id, world):
        cls = {"borrower-b": SiblingModel, "borrower-c": FailingModel}.get(actor_id)
        if cls is None or barriers is None:
            return plan.model(actor_id, lambda: world.clock.round)
        m = cls(plan, actor_id, lambda: world.clock.round)
        m.barriers, m.world, m.fail = barriers, world, fail
        return m

    return make_world(tmp_path, "shock", plan=plan, treasury=True, scenario=ROLLBACK_SCENARIO,
                      model=model, name=name, quiesce_timeout_s=quiesce_timeout_s)


def outcome(world: World, result) -> dict:
    """What a retry must share with the clean control (retry_equals_control)."""
    entry = result.transcript_entry
    fp = world.fingerprint()
    return {
        "observation hashes": entry["observations"],
        "intent ids": entry["intents"],
        "C2 deliveries": [entry["c2"], entry["c2_delivered"], world.state.pending_c2],
        "journals": [(j.journal_id, j.kind, j.postings) for j in result.journals],
        "final ledger hash": fp["ledger"],
        "committed transcript": [world.transcript.to_jsonl(), world.state.rounds],
        "posts": fp["OASIS SQLite"],
        "memory": world.memory_entries(),
        "deliveries": world.state.deliveries,
    }


async def to_round_start(world: World):
    await world.start()
    await world.run(ROLLBACK_ROUND - 1)
    return world.capture()


def portable(world: World, capture) -> dict:
    """A capture as another world built the same way can reproduce it: camel stamps each
    memory record with a random id and a wall time, so memory compares by role and content."""
    return {**{k: v for k, v in capture.fingerprint.items() if k != "actor memory records"},
            "memory": world.memory_entries()}


@pytest.fixture(scope="module")
def control(tmp_path_factory):
    async def go():
        world = rollback_world(tmp_path_factory.mktemp("control"), "control")
        capture = await to_round_start(world)
        try:
            start = portable(world, capture)
            result = await world.coordinator.run_round(world)
            return start, outcome(world, result), world.store.rows("journals")
        finally:
            await world.close()

    return run(go())


def assert_restored(world: World, capture, status: str) -> None:
    assert set(ROLLBACK["round_start_capture"]) <= set(capture.fingerprint)
    assert world.fingerprint() == capture.fingerprint  # all_captured_state_equals_round_start
    assert world.state.rounds[-1]["round"] == ROLLBACK_ROUND - 1  # transcript ends at round 9
    assert max(c.round for c in world.transcript.calls()) == ROLLBACK_ROUND - 1
    assert world.failures[-1]["round"] == ROLLBACK_ROUND
    assert world.failures[-1]["status"] == status
    assert world.committed_round == ROLLBACK_ROUND - 1
    assert world.unusable is None


async def retry_equals_control(world: World, control) -> None:
    _, want, control_journals = control
    result = await world.coordinator.run_round(world)
    got = outcome(world, result)
    assert got == want  # retry_equals_clean_control, duplicate_deliveries_or_postings: 0
    assert world.store.rows("journals") == control_journals
    assert [j["journal_id"] for j in control_journals].count("settle:payroll-1") == 1
    posts = world.platform.db.execute(
        "SELECT count(*) FROM post WHERE content LIKE 'Payroll day%'").fetchone()[0]
    assert posts == 1
    assert world.state.deliveries.count("p-r10-1") == 1


HOOK_CASES = {
    "fault-in-events": "before_observations",
    "fault-in-settlement": "settled",
    "fault-in-commit": "before_transcript",
}


@pytest.mark.parametrize("case_id", list(HOOK_CASES))
def test_a_failed_round_rolls_back_and_its_retry_equals_the_control(tmp_path, control, case_id):
    case = next(c for c in ROLLBACK["cases"] if c["id"] == case_id)
    assert ROLLBACK["expect"][case_id]["retry_equals_clean_control"] is True
    seen = {}

    def fault(world, ctx):
        if case["inject"]["step"] == 2:
            seen["cursor"] = world.state.event_cursor
            seen["post"] = world.platform.db.execute("SELECT count(*) FROM post WHERE content "
                                                     "LIKE 'Payroll day%'").fetchone()[0]
        if case["inject"]["step"] == 8:
            seen["settled"] = [j.journal_id for j in ctx.journals if j.kind.startswith("settle")]
        if case["inject"]["step"] == 10:
            seen["journals"] = [j.journal_id for j in ctx.journals]
        raise InjectedFault(case_id)

    async def go():
        world = rollback_world(tmp_path, case_id)
        try:
            capture = await to_round_start(world)
            assert portable(world, capture) == control[0]  # the same capture as the control's
            world.coordinator.hooks[HOOK_CASES[case_id]] = fault
            with pytest.raises(InjectedFault):
                await world.coordinator.run_round(world)
            assert_restored(world, capture, "failed")
            del world.coordinator.hooks[HOOK_CASES[case_id]]
            await retry_equals_control(world, control)
        finally:
            await world.close()

    run(go())
    if case_id == "fault-in-events":  # the event changed state and moved the cursor first
        assert seen["cursor"] == len(ROLLBACK_SCENARIO) and seen["post"] == 1
    if case_id == "fault-in-settlement":
        assert "settle:payroll-1" in seen["settled"]
    if case_id == "fault-in-commit":
        assert "settle:payroll-1" in seen["journals"]


@pytest.mark.parametrize("case_id", ["fault-in-agent-step", "cancel-in-agent-step"])
def test_an_aborted_agent_step_stops_every_writer_before_restoring(tmp_path, control, case_id):
    expect = ROLLBACK["expect"][case_id]
    interleaving = ROLLBACK["actor_interleaving"]
    assert case_id in interleaving["applies_to"]

    async def go():
        barriers = Barriers()
        world = rollback_world(tmp_path, case_id, barriers,
                               fail=case_id == "fault-in-agent-step")
        try:
            capture = await to_round_start(world)
            assert portable(world, capture) == control[0]
            posts_before = world.sqlite_dump().count("provisional post")
            memory_before = len(world.memory_records()["borrower-b"])
            task = asyncio.create_task(world.coordinator.run_round(world))
            await barriers.reached.wait()
            # The sibling's provisional writes are in: a post, a memory entry, an intent.
            assert len(world.queue) >= 1
            assert world.sqlite_dump().count("provisional post") > posts_before
            assert len(world.memory_records()["borrower-b"]) > memory_before
            if case_id == "cancel-in-agent-step":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(InjectedFault):
                    await task
            lifecycle = [event for event, _ in world.lifecycle]
            restore_at = lifecycle.index("restore_begin")
            # Admission closed, then the sibling's cleanup and the child ended, then restoration.
            assert lifecycle.index("admission_closed") < lifecycle.index("sibling_cleanup_done")
            assert lifecycle.index("sibling_cleanup_done") < restore_at
            assert lifecycle.index("child_done") < restore_at
            assert lifecycle.index("platform_fenced") < restore_at
            assert dict(world.lifecycle)["restore_begin"] == str(
                expect["round_owned_tasks_at_restore"])
            assert "cleanup memory written" in barriers.records
            assert_restored(world, capture, "cancelled" if case_id.startswith("cancel")
                            else "failed")
            # cleanup_writes_removed, writes_after_restore: release every barrier and look again.
            barriers.release.set()
            for _ in range(20):
                await asyncio.sleep(0)
            assert world.fingerprint() == capture.fingerprint
            assert expect["writes_after_restore"] == 0 and expect["cleanup_writes_removed"]
            barriers.armed = False
            await retry_equals_control(world, control)
        finally:
            await world.close()

    run(go())


def test_a_world_whose_writer_will_not_stop_refuses_a_retry(tmp_path):
    async def go():
        barriers = Barriers()
        barriers.stubborn = True
        world = rollback_world(tmp_path, "stubborn", barriers, fail=True,
                               quiesce_timeout_s=0.2)
        try:
            await to_round_start(world)
            with pytest.raises(InjectedFault):
                await world.coordinator.run_round(world)
            assert world.unusable is not None and "outlived" in world.unusable
            assert "restore_begin" not in [e for e, _ in world.lifecycle]
            with pytest.raises(WorldUnusable):
                await world.coordinator.run_round(world)
            assert "stubborn: ignoring cancellation" in barriers.records
        finally:
            barriers.release.set()
            for _ in range(20):
                await asyncio.sleep(0)
            await world.close()

    run(go())


@pytest.mark.parametrize("cause", ["fault", "cancel"])
def test_a_cancellation_during_abort_cleanup_waits_for_it_to_finish(tmp_path, control, cause):
    """The coordinator is cancelled while the round's abort is still stopping a writer: the
    cleanup still runs to the end (writers joined, ledger rolled back, connection closed, world
    restored) before the cancellation propagates."""
    seen = {}

    def advanced(world, ctx):
        seen["conn"] = ctx.conn

    async def go():
        barriers = Barriers()
        barriers.cleanup_gate = asyncio.Event()
        world = rollback_world(tmp_path, f"cancel-in-cleanup-{cause}", barriers,
                               fail=cause == "fault")
        try:
            capture = await to_round_start(world)
            world.coordinator.hooks["advanced"] = advanced
            task = asyncio.create_task(world.coordinator.run_round(world))
            await barriers.reached.wait()
            if cause == "cancel":
                task.cancel()
            await barriers.in_cleanup.wait()  # the abort is waiting on the writer's cleanup
            task.cancel()
            for _ in range(20):
                await asyncio.sleep(0)
            assert not task.done()  # the cancellation waits for the cleanup
            barriers.cleanup_gate.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert barriers.writer.done()
            assert "cleanup memory written" in barriers.records
            conn = seen["conn"]
            assert conn.closed and not conn.in_transaction()
            assert_restored(world, capture, "cancelled" if cause == "cancel" else "failed")
            barriers.release.set()
            for _ in range(20):
                await asyncio.sleep(0)
            assert world.fingerprint() == capture.fingerprint
            del world.coordinator.hooks["advanced"]
            barriers.armed = False
            await retry_equals_control(world, control)
        finally:
            barriers.cleanup_gate.set()
            barriers.release.set()
            for _ in range(20):
                await asyncio.sleep(0)
            await world.close()

    run(go())


def test_a_rejected_intent_is_not_a_failed_round(tmp_path, control):
    case = next(c for c in ROLLBACK["cases"] if c["id"] == "invalid-intent")
    expect = ROLLBACK["expect"]["invalid-intent"]

    def inject(world, ctx, intents):
        raw = {"intent_id": f"i-r{ctx.round}-treasury-99", "branch_id": world.branch_id,
               "round": ctx.round, "evidence_ids": [], "obs_hash": HASH,
               **copy.deepcopy(case["inject"]["intent"])}
        raw["params"] = {**raw["params"], "to": "supplier-1"}
        return [*intents, raw]

    async def go():
        world = rollback_world(tmp_path, "invalid")
        try:
            await to_round_start(world)
            world.coordinator.hooks["intents"] = inject
            return world, await world.coordinator.run_round(world)
        finally:
            await world.close()

    world, result = run(go())
    assert world.committed_round == ROLLBACK_ROUND  # round_status: committed
    rejected = by_intent(result)[f"i-r{ROLLBACK_ROUND}-treasury-99"]
    assert rejected.c2.status == expect["c2"]["status"]
    assert rejected.c2.reason == expect["c2"]["reason"]
    assert ("settle:payroll-1" in [j.journal_id for j in result.journals]) is \
        expect["payroll_settled"]
    obligation = next(o for o in world.store.rows("obligations")
                      if o["obligation_id"] == "payroll-1")
    assert obligation["state"] == "met"
    assert not world.failures


def test_capture_covers_every_component_the_fixture_names():
    names = set(ROLLBACK["round_start_capture"])
    assert names == {"ledger", "OASIS SQLite", "actor memory records",
                     "world and OASIS clocks", "RNG state", "scheduled-event cursor",
                     "pending C2 deliveries", "intent queue", "transcript cursor"}
    assert ROLLBACK["abort_order"][0].startswith("close admission")


# ------------------------------------------------------------------- vet round 1 regressions


def test_a_model_chosen_reference_the_ledger_refuses_is_a_rejection_not_a_failed_round(tmp_path):
    plan = ScriptedPlan([
        {"actor_id": "lender", "round": 1, "tool_calls": [
            {"name": "offer", "args": {"amount_minor": 100_000, "currency": "USD",
                                       "to": "feed"}}]},
        {"actor_id": "borrower-c", "round": 1, "tool_calls": [
            {"name": "request_advance", "args": {"amount_minor": 100_000, "currency": "USD",
                                                 "from": "lender"}}]},
        {"actor_id": "lender", "round": 2, "tool_calls": [
            {"name": "accept", "args": {"request": "req:borrower-c:r1"}},
            {"name": "disburse", "args": {"request": "req:borrower-c:r1",
                                          "amount_minor": 100_000, "currency": "USD",
                                          "from_account": "lender/nowhere"}}]},
        *IDLE,
    ])

    async def go():
        world = make_world(tmp_path, "refs", plan=plan)
        async with world:
            return world, await world.run(2)

    world, (r1, r2) = run(go())
    assert world.committed_round == 2 and not world.failures
    offer = by_intent(r1)["i-r1-lender-1"]
    assert (offer.c2.status, offer.c2.reason) == ("rejected", "unknown_counterparty")
    assert by_intent(r2)["i-r2-lender-1"].c2.status == "accepted"
    disburse = by_intent(r2)["i-r2-lender-2"]
    assert (disburse.c2.status, disburse.c2.reason) == ("rejected", "not_own_account")
    assert settled(world, "lender/operating") == 4_500_000


def ledger_world(tmp_path, name, snap=None, scenario=(), epoch=DEFAULT_EPOCH,
                 tools=None) -> World:
    """A world with no platform, for the clearing and delivery rules alone."""
    workdir = tmp_path / name
    workdir.mkdir()
    actors = [{**ACTOR_SPECS[a], "llm": False,
               "tools": ACTOR_SPECS[a]["tools"] + (tools or {}).get(a, [])}
              for a in MODEL_ACTORS]
    return World("rules", "shock", snap or snapshot(treasury=True), actors,
                 model=plan_model(ScriptedPlan(IDLE)), workdir=workdir, scenario=scenario,
                 epoch=epoch)


def clear(world: World, round_: int, *intents: tuple) -> dict:
    """Clear (actor, type, params[, intent_id]) intents at ``round_``; verdicts by intent id."""
    world.clock.round = round_
    built = []
    for n, (actor, type_, params, *given) in enumerate(intents, 1):
        built.append(ActionIntent(
            intent_id=given[0] if given else f"i-r{round_}-{actor}-{n}", branch_id="shock",
            round=round_, actor_id=actor, type=type_, params=params, evidence_ids=[],
            obs_hash=HASH, priority_class=ACTOR_SPECS[actor]["priority_class"],
            sim_minute=world.clock.sim_minute))
    with world.store.engine.begin() as conn:
        deliver(world, conn)  # what is observable is refreshed every round
        valid, rejected = validate_intents(world, built)
        return {c.intent_id: c for c in clear_intents(world, conn, valid) + rejected}


def verdict(cleared) -> tuple:
    return cleared.c2.status, cleared.c2.reason


def test_an_advance_is_never_offered_into_an_account_of_another_currency(tmp_path):
    snap = snapshot(treasury=False)
    for acc in snap["accounts"]:
        if acc["entity"] == "lender":
            acc["currency"] = "EUR"
            for bucket in ("settled", "reserved", "pledged"):
                acc["buckets"][bucket]["currency"] = "EUR"
    snap["contracts"] = []
    for acc in snap["accounts"]:
        acc["buckets"]["reserved"]["minor"] = 0
    snap["pools"][0]["floor"]["currency"] = "EUR"
    world = ledger_world(tmp_path, "fx", snap)
    out = clear(world, 1, ("lender", "offer", {"amount": {"minor": 100_000, "currency": "EUR"},
                                               "to": "borrower-c"}))
    assert verdict(out["i-r1-lender-1"]) == ("rejected", "currency_mismatch")


def test_a_payment_naming_an_obligation_is_refused_so_it_is_never_paid_twice(tmp_path):
    world = ledger_world(tmp_path, "ob")
    out = clear(world, 1, ("treasury", "pay", {"amount": usd(100_000), "to": "payroll",
                                               "obligation_id": "payroll-1"}))
    assert verdict(out["i-r1-treasury-1"]) == ("rejected", "obligation_settles_when_due")


def test_a_payment_reaches_only_a_cash_account_or_the_outside_world(tmp_path):
    world = ledger_world(tmp_path, "payee")
    out = clear(world, 1,
                ("borrower-b", "pay", {"amount": usd(1_000), "to": "lender/loan:line-b"}),
                ("borrower-c", "pay", {"amount": usd(1_000), "to": "borrower-b/operating"}))
    assert verdict(out["i-r1-borrower-b-1"]) == ("rejected", "payee_not_cash")
    assert verdict(out["i-r1-borrower-c-2"]) == ("accepted", None)
    assert settled(world, "borrower-b/operating") == 900_000 + 1_000


def test_a_pledge_in_another_currency_is_refused(tmp_path):
    world = ledger_world(tmp_path, "pledge", tools={"borrower-c": ["pledge"]})
    out = clear(world, 1, ("borrower-c", "pledge", {"amount": {"minor": 50_000,
                                                               "currency": "JPY"},
                                                    "to": "lender"}))
    assert verdict(out["i-r1-borrower-c-1"]) == ("rejected", "currency_mismatch")


def test_ids_fit_the_ledger_columns(tmp_path):
    world = ledger_world(tmp_path, "ids")
    long_id = "i-r1-borrower-c-" + "7" * 64  # 80 characters: a journal id would not fit
    too_long = "i-r1-borrower-c-" + "7" * 90  # beyond the journal's source intent column
    out = clear(world, 1,
                ("borrower-c", "pay", {"amount": usd(1_000), "to": "supplier-2"}, long_id),
                ("borrower-c", "pay", {"amount": usd(1_000), "to": "supplier-2"}, too_long))
    accepted = out[long_id]
    assert accepted.c2.status == "accepted"
    assert len(accepted.journal.journal_id) <= 64
    assert accepted.journal.source_intent_id == long_id
    assert verdict(out[too_long]) == ("rejected", "intent_id_too_long")


def test_a_borrower_drawing_an_accepted_request_closes_the_request(tmp_path):
    world = ledger_world(tmp_path, "draw")
    advance = {"amount": usd(100_000), "from": "lender"}
    clear(world, 1, ("borrower-c", "request_advance", advance))
    assert verdict(clear(world, 2, ("lender", "accept", {"request": "req:borrower-c:r1"}))[
        "i-r2-lender-1"]) == ("accepted", None)
    drawn = clear(world, 3, ("borrower-c", "request_advance",
                             {**advance, "facility_id": "adv:req:borrower-c:r1"}))
    assert drawn["i-r3-borrower-c-1"].journal.kind == "advance_disbursal"
    assert world.state.requests["req:borrower-c:r1"]["status"] == "disbursed"
    again = clear(world, 4, ("lender", "disburse", {"request": "req:borrower-c:r1",
                                                    "amount": usd(100_000)}))
    assert verdict(again["i-r4-lender-1"]) == ("rejected", "request_not_open")


def deliver_round(world: World) -> None:
    with world.store.engine.begin() as conn:
        world.clock.advance()
        deliver(world, conn)


def test_a_receipt_promised_within_the_hour_is_not_overdue_before_it_is_due(tmp_path):
    snap = snapshot(treasury=True)
    tre = next(a for a in snap["accounts"] if a["id"] == "treasury/operating")
    tre["buckets"]["pending_in"][0]["expected_at"] = "2026-01-01T04:30:00Z"
    world = ledger_world(tmp_path, "half", snap)
    deliver_round(world)  # t = 4 h: promised for 04:30, not yet due
    assert world.state.flow_status["receivable-1"] == "expected"
    deliver_round(world)  # t = 8 h: landed
    assert world.state.flow_status["receivable-1"] == "arrived"


def test_a_delay_keeps_the_receipt_in_utc_whatever_the_epochs_zone(tmp_path):
    from datetime import timedelta, timezone

    epoch = DEFAULT_EPOCH.astimezone(timezone(timedelta(hours=4)))
    delay = [{"round": 1, "kind": "delay_receipt", "flow_id": "receivable-1", "delay_h": 24}]
    world = ledger_world(tmp_path, "zone", scenario=delay, epoch=epoch)
    deliver_round(world)
    (flow,) = [f for f in world.store.rows("expected_flows") if f["flow_id"] == "receivable-1"]
    assert flow["expected_at"] == (DEFAULT_EPOCH + timedelta(hours=12 + 24)).replace(tzinfo=None)


def test_an_intent_is_held_to_its_tools_schema_whoever_queued_it(tmp_path):
    world = ledger_world(tmp_path, "schema")
    out = clear(world, 1,
                ("lender", "offer", {"amount": usd(100_000), "to": "borrower-c",
                                     "fee_bps": 20_000}),
                ("borrower-c", "pay", {"amount": usd(1_000)}))
    assert verdict(out["i-r1-lender-1"]) == ("rejected", "malformed_intent")
    assert verdict(out["i-r1-borrower-c-2"]) == ("rejected", "malformed_intent")
    assert world.committed_round == 0 and settled(world, "borrower-c/operating") == 400_000


# ------------------------------------------------------------------- vet round 2 regressions


def test_a_long_intent_id_still_offers_a_facility_whose_ids_fit(tmp_path):
    from app.finance.contracts import repay_journal_id
    from app.finance.models import EPOCH

    world = ledger_world(tmp_path, "fid")
    long_id = "i-r1-lender-" + "4" * 30  # 42 characters
    out = clear(world, 1, ("lender", "offer", {"amount": usd(100_000), "to": "borrower-c"},
                           long_id))
    assert out[long_id].c2.status == "accepted"
    (fac,) = [f for f in world.store.rows("facilities") if f["facility_id"] != "line-b"]
    assert len(repay_journal_id(fac["facility_id"], EPOCH)) <= 64


def test_a_repeated_intent_id_is_a_rejection(tmp_path):
    world = ledger_world(tmp_path, "dup")
    pay = {"amount": usd(1_000), "to": "supplier-2"}
    out = clear(world, 1, ("borrower-c", "pay", pay, "i-r1-borrower-c-1"),
                ("borrower-b", "pay", pay, "i-r1-borrower-c-1"))
    (second,) = out.values()  # one id: the rejection of the second answers for it
    assert (second.actor_id, *verdict(second)) == ("borrower-b", "rejected", "duplicate_intent")
    assert settled(world, "borrower-c/operating") == 400_000 - 1_000
    assert settled(world, "borrower-b/operating") == 900_000
    world.state.intents["i-r1-borrower-c-1"] = {}  # as a committed round records it
    again = clear(world, 2, ("borrower-c", "pay", pay, "i-r1-borrower-c-1"))
    assert verdict(again["i-r1-borrower-c-1"]) == ("rejected", "duplicate_intent")


def test_the_in_transit_account_is_observed_from_the_disbursal(tmp_path):
    world = ledger_world(tmp_path, "transit")
    clear(world, 1, ("lender", "offer", {"amount": usd(100_000), "to": "borrower-c"}))
    clear(world, 2, ("borrower-c", "request_advance",
                     {"amount": usd(100_000), "from": "lender",
                      "facility_id": "adv:i-r1-lender-1"}))
    (obs,) = [o for o in world.store.rows("account_observations")
              if o["account_id"] == "borrower-c/in-transit"]
    assert obs["as_of"] == world.clock.now.replace(tzinfo=None)


def test_the_outside_world_is_payable_by_its_id_and_a_mistyped_account_is_not(tmp_path):
    world = ledger_world(tmp_path, "outside")
    with world.store.engine.begin() as conn:
        world.store.external_account("USD", conn=conn)
    out = clear(world, 1,
                ("borrower-c", "pay", {"amount": usd(1_000), "to": "external/USD"}),
                ("borrower-b", "pay", {"amount": usd(1_000), "to": "borrower-c/operatin"}))
    assert verdict(out["i-r1-borrower-c-1"]) == ("accepted", None)
    assert verdict(out["i-r1-borrower-b-2"]) == ("rejected", "unknown_payee")

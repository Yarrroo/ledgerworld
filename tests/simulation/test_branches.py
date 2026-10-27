"""Branches: checkpoint, fork, sibling isolation and exact replay (branch-isolation.json).

One run, shared by the module, plays the fixture on real OASIS platforms with ``ScriptedModel``s
and ``FakeGraphMemory``: ``main`` runs the coupled chain to round 3 (the rumour), is
checkpointed, and forks ``no-action`` and ``integrated`` run to round 6. Each test asserts one
line of the fixture's ``expect`` block, which is read unchanged.

Beyond the fixture, ``main``'s round 3 carries a rejected ``defer`` (so a C2 is pending at the
checkpoint) and round 4 a scheduled message (so an event is due after it): the continuation
check then has something to deliver exactly once.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import hashlib
import json
import random
import re
import sqlite3
from pathlib import Path

import pytest
import test_coupled as coupled
from app.simulation.branches import (
    BranchMismatch,
    checkpoint,
    fork,
    ledger_hash,
    replay,
)
from app.simulation.memory import BranchMemory, NamespaceViolation, namespace_for
from app.simulation.transcripts import ReplayMiss, Transcript
from app.testing.fake_graph_memory import FakeGraphMemory, GraphMemoryStore
from app.testing.scripted_model import ScriptedPlan
from oasis_finance.agent import FinanceAgent

FIXTURE = json.loads((coupled.FIXTURES / "branch-isolation.json").read_text())
EXPECT = FIXTURE["expect"]
WORLD_ID = FIXTURE["world_id"]
PARENT = FIXTURE["parent"]
CP_ROUND = FIXTURE["checkpoint"]["after_round"]
LAST_ROUND = 6

# The rumour as main's own event (the coupled fixture scopes it to its "shock" branch).
RUMOUR = {k: v for k, v in coupled.COUPLED["scheduled_events"][0].items() if k != "branch"}
NOTICE = {"round": CP_ROUND + 1, "kind": "message", "id": "m-r4-notice", "to": "borrower-b",
          "text": "Your statement for the week is ready."}
DEFER = {"actor_id": "borrower-b", "round": CP_ROUND,
         "tool_calls": [{"name": "defer", "args": {"obligation_id": "payroll-1"}}]}
PARENT_MEMORY = [("borrower-c", "rumour", "the venue may pause withdrawals", CP_ROUND)]
LATE_MEMORY = ("borrower-c", "note", "written after the checkpoint", CP_ROUND + 1)


def chain_plan() -> ScriptedPlan:
    """coupled-chain.json's plan as written."""
    return ScriptedPlan(copy.deepcopy(coupled.COUPLED["plan"]))


def plans() -> dict[str, ScriptedPlan]:
    fork_plans = {f["branch_id"]: f["plan"] for f in FIXTURE["forks"]}
    assert "no_action from round 4" in fork_plans["no-action"]
    assert fork_plans["integrated"] == "coupled-chain.json as written"
    return {"no-action": ScriptedPlan(copy.deepcopy(coupled.IDLE)),
            "integrated": chain_plan()}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recs(records) -> list[tuple]:
    return [(r.actor_id, r.key, r.value, r.round) for r in records]


def parent_world(tmp: Path, plan: ScriptedPlan, *, model=None, posters=(), **kw):
    """main on the coupled lender world, its model actors driven by ``plan`` (or ``model``);
    each of ``posters`` may also post."""
    (tmp / PARENT).mkdir()
    specs = [coupled.ACTOR_SPECS[a] for a in coupled.MODEL_ACTORS + ["payroll", "market-maker"]]
    return coupled.World(
        WORLD_ID, PARENT, coupled.snapshot(treasury=False),
        [{**s, "tools": [*s["tools"], "create_post"]} if s["actor_id"] in posters else s
         for s in specs],
        model=model or coupled.plan_model(plan), workdir=tmp / PARENT, **kw)


def journal_bytes(world) -> bytes:
    rows = {t: world.store.rows(t) for t in ("journals", "postings")}
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()


async def play(tmp: Path) -> dict:
    """The whole fixture, once; returns what each test asserts."""
    out: dict = {}
    graph = GraphMemoryStore()

    def client(branch_id: str) -> FakeGraphMemory:
        return FakeGraphMemory(namespace_for(WORLD_ID, branch_id), graph)

    parent_plan = ScriptedPlan(copy.deepcopy(coupled.COUPLED["plan"][:-1]) + [DEFER]
                               + copy.deepcopy(coupled.COUPLED["plan"][-1:]))
    parent = parent_world(tmp, parent_plan, scenario=[RUMOUR, NOTICE])
    parent_memory = BranchMemory(client(PARENT), WORLD_ID, PARENT)
    async with parent:
        await parent.run(CP_ROUND)
        for record in PARENT_MEMORY:
            parent_memory.write_record(*record)
        cp = checkpoint(parent, parent_memory)
        out["cp"] = cp
        def parent_state() -> dict:
            return {"ledger": ledger_hash(parent.store), "sqlite_file": file_hash(parent.db_path),
                    "fingerprint": parent.fingerprint(),
                    "memory": parent_memory.snapshot().digest()}

        out["parent_before"] = parent_state()
        with pytest.raises(BranchMismatch):
            await fork(cp, PARENT, model=coupled.plan_model(chain_plan()), workdir=tmp)

        branches = {}
        for branch_id, plan in plans().items():
            (tmp / branch_id).mkdir()
            branches[branch_id] = await fork(cp, branch_id, model=coupled.plan_model(plan),
                                             workdir=tmp / branch_id,
                                             memory_client=client(branch_id))
        out["forked"] = {b: {"fingerprint": br.world.fingerprint(),
                             "ledger": ledger_hash(br.world.store),
                             "agents": {a: (type(agent), sorted(agent.tool_dict),
                                            agent.intent_queue)
                                        for a, agent in br.world.agents.items()},
                             "queue": br.world.queue}
                         for b, br in branches.items()}
        for w in FIXTURE["memory_writes"]:
            branches[w["branch_id"]].memory.write_record(w["actor_id"], w["key"], w["value"],
                                                         w["round"])
        out["k_p_r5"], out["round_4"] = {}, {}
        for branch_id, branch in branches.items():
            await branch.world.run(1)
            out["round_4"][branch_id] = branch.world.state.rounds[-1]
            await branch.world.run(1)
            out["k_p_r5"][branch_id] = coupled.k_p(branch.world)
            await branch.world.run(LAST_ROUND - CP_ROUND - 2)
        out["branches"] = branches

        out["parent_after"] = parent_state()

        # The parent goes on: its round 4 is the clean continuation of the same capture, and
        # it remembers past the checkpoint.
        await parent.run(1)
        out["continuation_round_4"] = parent.state.rounds[-1]
        out["continuation_deliveries"] = list(parent.state.deliveries)
        parent_memory.write_record(*LATE_MEMORY)
        (tmp / "late").mkdir()
        late = await fork(cp, "late", model=coupled.plan_model(chain_plan()),
                          workdir=tmp / "late", memory_client=client("late"))
        out["late"] = {"records": late.memory.retrieve(),
                       "camel": late.world.memory_records(),
                       "fingerprint": late.world.fingerprint()}
        await late.world.close()

        # Replay: the stored transcript of 'integrated', read back from its file.
        integrated = branches["integrated"].world
        stored = tmp / "integrated.jsonl"
        Transcript(WORLD_ID, "integrated", path=stored, calls=integrated.transcript.calls())
        loaded = Transcript.load(stored, WORLD_ID, "integrated")
        (tmp / "replay").mkdir()
        replayed = await replay(cp, loaded, workdir=tmp / "replay")
        out["replay"] = {"journals": journal_bytes(replayed.world),
                         "ledger": ledger_hash(replayed.world.store),
                         "transcript": replayed.world.transcript.to_jsonl(),
                         "label": replayed.label(),
                         "lineage": replayed.world.store.rows("branch_meta"),
                         "round": replayed.world.clock.round}
        out["integrated"] = {"journals": journal_bytes(integrated),
                             "ledger": ledger_hash(integrated.store),
                             "transcript": integrated.transcript.to_jsonl(),
                             "calls": integrated.transcript.calls(),
                             "label": branches["integrated"].label(),
                             "lineage": integrated.store.rows("branch_meta")}
        await replayed.world.close()
        for branch in branches.values():
            await branch.world.close()
    return out


@pytest.fixture(scope="module")
def played(tmp_path_factory) -> dict:
    return asyncio.run(play(tmp_path_factory.mktemp("branches")))


def test_the_checkpoint_pins_every_component_the_fixture_names(played):
    cp = played["cp"]
    assert FIXTURE["checkpoint"]["after_round"] == cp.round == CP_ROUND
    fingerprint = cp.fingerprint()
    for component in FIXTURE["checkpoint"]["contains"]:
        name = {"ledger state": "ledger",
                "world state (OASIS SQLite file copy)": "OASIS SQLite",
                "immutable actor memory records and namespace id": "actor memory records",
                "world and OASIS clocks": "world and OASIS clocks",
                "RNG state": "RNG state",
                "scheduled-event cursor": "scheduled-event cursor",
                "pending C2 deliveries": "pending C2 deliveries",
                "empty committed-boundary intent queue": "intent queue",
                "transcript cursor": "transcript cursor"}[component]
        assert fingerprint[name]
    assert fingerprint["intent queue"] == "0"
    assert fingerprint["world and OASIS clocks"] == f"{CP_ROUND}/{CP_ROUND}"
    assert cp.memory_ns == cp.memory.namespace == namespace_for(WORLD_ID, PARENT)
    assert recs(cp.memory.records) == PARENT_MEMORY
    assert [c["status"] for c in cp.pending_c2] == ["rejected"]
    assert cp.event_cursor == 1  # the rumour delivered, the round-4 notice not yet
    assert cp.transcript_cursor == CP_ROUND * len(coupled.MODEL_ACTORS)


def test_a_fork_rebuilds_every_agent_on_its_own_queue(played):
    queues = set()
    for branch_id, forked in played["forked"].items():
        assert forked["fingerprint"] | {"ledger": forked["ledger"]} == played["cp"].fingerprint()
        for actor_id, (kind, tools, queue) in forked["agents"].items():
            assert kind is FinanceAgent, actor_id  # never a plain ChatAgent from clone()
            assert tools == sorted(coupled.ACTOR_SPECS[actor_id]["tools"]), actor_id
            assert queue is forked["queue"] and queue.branch_id == branch_id
        queues.add(id(forked["queue"]))
    assert len(queues) == len(played["forked"])


def test_sibling_read_raises_namespace_violation(played):
    expect = EXPECT["sibling_read"]
    reader = played["branches"][expect["from"]].memory
    assert expect["result"] == "raises NamespaceViolation"
    with pytest.raises(NamespaceViolation):
        reader.retrieve(namespace=expect["namespace"])
    expect_own = EXPECT["own_read"]
    own = played["branches"][expect_own["branch_id"]].memory
    assert own.read("borrower-c", expect_own["key"]) == expect_own["value"]
    # Each branch starts from main's pinned records and sees only its own writes after them.
    for w in FIXTURE["memory_writes"]:
        records = played["branches"][w["branch_id"]].memory.retrieve()
        assert recs(records) == \
            PARENT_MEMORY + [(w["actor_id"], w["key"], w["value"], w["round"])]


def test_checkpoint_memory_is_immutable(played):
    assert "cannot read that later record" in EXPECT["checkpoint_memory_immutable"]
    late = played["late"]
    assert recs(late["records"]) == PARENT_MEMORY
    assert LATE_MEMORY[2] not in [r.value for r in late["records"]]
    # The parent's actor (chat) memory moved on in its round 4; the fork's is the checkpoint's.
    cp = played["cp"].fingerprint()
    assert late["fingerprint"]["actor memory records"] == cp["actor memory records"]
    assert played["continuation_round_4"]["round"] == CP_ROUND + 1


def test_checkpoint_continuation(played):
    assert "once" in EXPECT["checkpoint_continuation"]
    continuation = played["continuation_round_4"]
    assert continuation["c2_delivered"], "a C2 was pending at the checkpoint"
    for branch_id, entry in played["round_4"].items():
        assert entry["round"] == CP_ROUND + 1
        assert entry["observations"] == continuation["observations"], branch_id
        assert entry["c2_delivered"] == continuation["c2_delivered"], branch_id
    deliveries = played["continuation_deliveries"]
    assert deliveries == [RUMOUR["post_id"], NOTICE["id"]]
    for branch in played["branches"].values():
        assert branch.world.state.deliveries == deliveries
        delivered = [c for r in branch.world.state.rounds for c in r["c2_delivered"]]
        assert len(delivered) == len(set(delivered))


def test_parent_unchanged(played):
    assert "byte-identical to the checkpoint" in EXPECT["parent_unchanged"]
    before, after = played["parent_before"], played["parent_after"]
    assert after["fingerprint"] == before["fingerprint"]  # its RNG included: each world owns one
    for component in ("ledger", "sqlite_file", "memory"):
        assert after[component] == before[component], component
    assert after["ledger"] == played["cp"].ledger_digest
    assert after["memory"] == played["cp"].memory.digest()
    assert after["fingerprint"]["OASIS SQLite"] == played["cp"].fingerprint()["OASIS SQLite"]
    for branch in played["branches"].values():
        assert branch.world.clock.round == LAST_ROUND


def test_branch_ledgers_differ(played):
    line = EXPECT["branch_ledgers_differ"]  # "K_p at round 5: no-action 4,200,000 · ..."
    assert line.startswith(f"K_p at round {CP_ROUND + 2}:")
    expected = {m["branch"]: int(m["k_p"].replace(",", ""))
                for m in re.finditer(r"(?P<branch>[a-z-]+) (?P<k_p>[\d,]+)",
                                     line.split(":", 1)[1])}
    assert played["k_p_r5"] == expected == {"no-action": 4_200_000, "integrated": 3_000_000}


def test_replay_identity(played):
    assert "byte-identical journals" in EXPECT["replay_identity"]
    replayed, original = played["replay"], played["integrated"]
    assert replayed["round"] == LAST_ROUND
    assert replayed["journals"] == original["journals"]
    assert replayed["ledger"] == original["ledger"]
    assert replayed["transcript"] == original["transcript"]
    assert json.loads(original["journals"])["journals"], "the integrated branch moved money"


def test_replay_label(played):
    assert "replay=true" in EXPECT["replay_label"]
    assert played["replay"]["label"]["replay"] is True
    assert played["integrated"]["label"]["replay"] is False
    lineage = {r["branch_id"]: r for r in played["replay"]["lineage"]}
    assert lineage["integrated"]["replay"] is True
    assert lineage["integrated"]["parent_branch_id"] == PARENT
    assert lineage["integrated"]["checkpoint_round"] == CP_ROUND
    assert {r["branch_id"]: r["replay"] for r in played["integrated"]["lineage"]} == \
        {"integrated": False}


def test_a_replay_refuses_a_transcript_of_another_history(played):
    cp = played["cp"]
    other = Transcript(WORLD_ID, "integrated", calls=cp.transcript_calls[1:])
    with pytest.raises(BranchMismatch):
        asyncio.run(replay(cp, other, workdir=Path("/nonexistent")))


def test_a_replay_shown_another_observation_fails_instead_of_answering(played, tmp_path):
    cp, calls = played["cp"], list(played["integrated"]["calls"])
    n = next(i for i, c in enumerate(calls)
             if (c.round, c.actor_id) == (CP_ROUND + 1, "borrower-c"))
    calls[n] = dataclasses.replace(calls[n], obs_hash="f" * 64)
    with pytest.raises(ReplayMiss, match="borrower-c round 4"):
        asyncio.run(replay(cp, Transcript(WORLD_ID, "integrated", calls=calls),
                           workdir=tmp_path))


# ------------------------------------------------------------- vet round 1: each failed first


async def small_parent(tmp: Path, **kw):
    """main after one idle round, its graph memory holding one record; and its checkpoint."""
    world = parent_world(tmp, ScriptedPlan(copy.deepcopy(coupled.IDLE)), **kw)
    memory = BranchMemory(FakeGraphMemory(namespace_for(WORLD_ID, PARENT), GraphMemoryStore()),
                          WORLD_ID, PARENT)
    await world.start()
    await world.run(1)
    memory.write_record(*PARENT_MEMORY[0])
    return world, checkpoint(world, memory)


def idle_model():
    return coupled.plan_model(ScriptedPlan(copy.deepcopy(coupled.IDLE)))


def test_a_replay_keeps_the_lineage_its_branch_inherited(tmp_path):
    async def go():
        parent, cp = await small_parent(tmp_path)
        (tmp_path / "a").mkdir()
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a")
        await a.world.run(1)
        cp_a = checkpoint(a.world)
        await a.world.run(1)
        (tmp_path / "again").mkdir()
        replayed = await replay(cp_a, a.world.transcript, workdir=tmp_path / "again")
        rows = replayed.world.store.rows("branch_meta")
        label = replayed.label()
        for w in (parent, a.world, replayed.world):
            await w.close()
        return rows, label

    rows, label = asyncio.run(go())
    assert (label["parent"], label["checkpoint_round"], label["replay"]) == (PARENT, 1, True)
    assert [(r["branch_id"], r["parent_branch_id"], r["checkpoint_round"], r["replay"])
            for r in rows] == [("a", PARENT, 1, True)]


def test_a_fork_may_not_take_an_ancestors_id(tmp_path):
    async def go():
        parent, cp = await small_parent(tmp_path)
        (tmp_path / "a").mkdir()
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a")
        cp_a = checkpoint(a.world)
        try:
            with pytest.raises(BranchMismatch, match="ancestor"):
                await fork(cp_a, PARENT, model=idle_model(), workdir=tmp_path)
        finally:
            await a.world.close()
            await parent.close()

    asyncio.run(go())


def test_a_replay_runs_under_the_branchs_coordinator_and_memory(tmp_path):
    async def go():
        parent, cp = await small_parent(tmp_path)
        (tmp_path / "a").mkdir()
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a")
        await a.world.run(1)
        seen = []
        coordinator = coupled.Coordinator({"intents": lambda w, ctx, i: seen.append(ctx.round)
                                           or i})
        (tmp_path / "again").mkdir()
        replayed = await replay(cp, a.world.transcript, workdir=tmp_path / "again",
                                coordinator=coordinator,
                                memory_client=FakeGraphMemory(namespace_for(WORLD_ID, "a"),
                                                              GraphMemoryStore()))
        records = replayed.memory.retrieve()
        for w in (parent, a.world, replayed.world):
            await w.close()
        return seen, records, replayed.world.coordinator is coordinator

    seen, records, same = asyncio.run(go())
    assert same and seen == [2]
    assert recs(records) == PARENT_MEMORY


def test_a_fork_takes_its_own_scheduled_events_after_the_checkpoint(tmp_path):
    own = {"round": 2, "kind": "message", "id": "m-own", "to": "borrower-b", "text": "hello",
           "branch": "a"}
    other = {**own, "id": "m-other", "branch": "b"}

    async def go():
        parent, cp = await small_parent(tmp_path)
        with pytest.raises(ValueError, match="after the checkpoint"):
            await fork(cp, "a", model=idle_model(), workdir=tmp_path,
                       scenario=[{**own, "round": 1}])
        (tmp_path / "a").mkdir()
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a",
                       scenario=[own, other])
        await a.world.run(1)
        deliveries = list(a.world.state.deliveries)
        await a.world.close()
        await parent.close()
        return deliveries

    assert asyncio.run(go()) == ["m-own"]


def test_lineage_time_is_utc_whatever_the_epochs_zone(tmp_path):
    from datetime import UTC, timedelta, timezone

    from oasis_finance.observation import DEFAULT_EPOCH

    epoch = DEFAULT_EPOCH.astimezone(timezone(timedelta(hours=3)))

    async def go():
        parent, cp = await small_parent(tmp_path, epoch=epoch)
        (tmp_path / "a").mkdir()
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a")
        rows = a.world.store.rows("branch_meta")
        await a.world.close()
        await parent.close()
        return rows

    (row,) = asyncio.run(go())
    assert row["created_at"] == (DEFAULT_EPOCH + timedelta(hours=4)).astimezone(UTC) \
        .replace(tzinfo=None)


def test_a_failed_fork_leaves_nothing_behind_and_can_be_retried(tmp_path, monkeypatch):
    from app.simulation import branches

    real = branches._copy_ledger
    calls = []

    def flaky(rows, store):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("injected")
        real(rows, store)

    monkeypatch.setattr(branches, "_copy_ledger", flaky)

    async def go():
        parent, cp = await small_parent(tmp_path)
        (tmp_path / "a").mkdir()
        with pytest.raises(RuntimeError, match="injected"):
            await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a")
        left = sorted(p.name for p in (tmp_path / "a").iterdir())
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a")
        await a.world.close()
        await parent.close()
        return left

    assert asyncio.run(go()) == []


def test_a_checkpoint_is_usable_from_another_thread(tmp_path):
    import threading

    async def go():
        parent, cp = await small_parent(tmp_path)
        await parent.close()
        return cp

    cp = asyncio.run(go())
    out: dict = {}

    def other() -> None:
        try:
            out["fingerprint"] = cp.fingerprint()
        except sqlite3.ProgrammingError as exc:  # reported, not swallowed
            out["error"] = exc

    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    assert "error" not in out, out.get("error")
    assert out["fingerprint"]["OASIS SQLite"]


# ------------------------------------------------------------- vet round 2: each failed first


def test_a_replay_of_the_checkpoints_own_branch_carries_its_graph_memory(tmp_path):
    async def go():
        parent, cp = await small_parent(tmp_path)
        await parent.run(1)
        (tmp_path / "again").mkdir()
        replayed = await replay(
            cp, parent.transcript, workdir=tmp_path / "again",
            memory_client=FakeGraphMemory(namespace_for(WORLD_ID, PARENT), GraphMemoryStore()))
        records = replayed.memory.retrieve()
        await replayed.world.close()
        await parent.close()
        return records, replayed.label()

    records, label = asyncio.run(go())
    assert recs(records) == PARENT_MEMORY
    assert (label["parent"], label["replay"]) == (None, True)


def test_a_replay_may_not_make_an_ancestor_its_child(tmp_path):
    async def go():
        parent, cp = await small_parent(tmp_path)
        (tmp_path / "a").mkdir()
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a")
        cp_a = checkpoint(a.world)  # before a diverges: main's transcript still fits it
        await parent.run(1)
        try:
            with pytest.raises(BranchMismatch, match="ancestor"):
                await replay(cp_a, parent.transcript, workdir=tmp_path)
        finally:
            await a.world.close()
            await parent.close()

    asyncio.run(go())


def test_another_branchs_early_event_is_no_reason_to_refuse_a_fork(tmp_path):
    async def go():
        parent, cp = await small_parent(tmp_path)
        (tmp_path / "a").mkdir()
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a",
                       scenario=[{"round": 1, "kind": "message", "id": "m-b", "to": "borrower-b",
                                  "text": "hello", "branch": "b"}])
        await a.world.close()
        await parent.close()

    asyncio.run(go())


@pytest.mark.parametrize("fault", ["start", "close", "memory"])
def test_a_fork_that_fails_anywhere_can_be_retried(tmp_path, monkeypatch, fault):
    from app.simulation import branches

    graph = GraphMemoryStore()
    once = {"armed": True}

    def trip() -> None:
        if once.pop("armed", False):
            raise RuntimeError("injected")

    real_start, real_close = coupled.World.start, coupled.World.close
    real_write = BranchMemory.write_record

    async def start(self):
        result = await real_start(self)
        if self.branch_id == "a":
            trip()
        return result

    async def close(self):
        await real_close(self)
        if self.branch_id == "a" and once.get("armed") is None and fault == "close":
            once["armed"] = True
            trip()

    def write(self, *args):
        if self.branch_id == "a":
            trip()
        return real_write(self, *args)

    if fault == "start":
        monkeypatch.setattr(coupled.World, "start", start)
    elif fault == "close":
        monkeypatch.setattr(branches, "_copy_ledger", lambda rows, store: trip())
        monkeypatch.setattr(coupled.World, "close", close)
    else:
        monkeypatch.setattr(BranchMemory, "write_record", write)

    async def go():
        parent, cp = await small_parent(tmp_path)  # writes main's memory, never trips
        (tmp_path / "a").mkdir()
        client = FakeGraphMemory(namespace_for(WORLD_ID, "a"), graph)
        with pytest.raises(RuntimeError, match="injected"):
            await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a", memory_client=client)
        monkeypatch.undo()
        left = sorted(p.name for p in (tmp_path / "a").iterdir())
        a = await fork(cp, "a", model=idle_model(), workdir=tmp_path / "a", memory_client=client)
        records = a.memory.retrieve()
        await a.world.close()
        await parent.close()
        return left, records

    left, records = asyncio.run(go())
    assert left == []
    assert recs(records) == PARENT_MEMORY


def test_a_failed_replay_can_be_retried_in_the_same_workdir(played, tmp_path):
    cp, calls = played["cp"], list(played["integrated"]["calls"])
    n = next(i for i, c in enumerate(calls)
             if (c.round, c.actor_id) == (CP_ROUND + 1, "borrower-c"))
    bad = [*calls[:n], dataclasses.replace(calls[n], obs_hash="f" * 64), *calls[n + 1:]]

    async def go():
        with pytest.raises(ReplayMiss):
            await replay(cp, Transcript(WORLD_ID, "integrated", calls=bad), workdir=tmp_path)
        branch = await replay(cp, Transcript(WORLD_ID, "integrated", calls=calls),
                              workdir=tmp_path)
        await branch.world.close()
        return journal_bytes(branch.world)

    assert asyncio.run(go()) == played["integrated"]["journals"]


# ----------------------------------------------- correction: each world draws from its own RNG

# More posts than OASIS recommends to a user (2), so every round's recommendations are drawn.
FEED = [{"round": 1, "kind": "public_post", "post_id": f"p-r1-{n}", "author": "feed",
         "text": f"Market note {n}."} for n in range(1, 4)]


def drawn(world) -> tuple[list[tuple], str]:
    """What a world's random stream decided: its recommendations, and where the stream is."""
    rec = world.platform.db.execute("SELECT user_id, post_id FROM rec").fetchall()
    return rec, world.fingerprint()["RNG state"]


def test_a_late_fork_does_not_move_the_parents_random_stream(tmp_path):
    """A parent that went on past its checkpoint draws on from where it was: a fork of the
    earlier checkpoint leaves its stream alone, and its next round recommends what a parent
    that was never forked recommends."""
    async def go():
        (tmp_path / "control").mkdir()
        control, _ = await small_parent(tmp_path / "control", scenario=FEED)
        await control.run(2)
        unforked = drawn(control)
        await control.close()
        parent, cp = await small_parent(tmp_path, scenario=FEED)
        await parent.run(1)
        before = parent.fingerprint()
        (tmp_path / "late").mkdir()
        late = await fork(cp, "late", model=idle_model(), workdir=tmp_path / "late")
        after = parent.fingerprint()
        await parent.run(1)
        forked = drawn(parent)
        await late.world.close()
        await parent.close()
        return unforked, before, after, forked

    unforked, before, after, forked = asyncio.run(go())
    assert after == before
    assert unforked[0], "the round drew recommendations"
    assert forked == unforked


@pytest.mark.parametrize("order", ["aabb", "bbaa", "abba", "ab|ab"])
def test_siblings_draw_alike_whatever_order_they_run_in(tmp_path, order):
    """Two siblings with one plan, forked from one checkpoint, draw the same recommendations
    round by round however their rounds interleave, one after another or at once ("ab|ab":
    each round of both under one gather); the process-global RNG is not drawn."""
    async def go():
        parent, cp = await small_parent(tmp_path, scenario=FEED)
        siblings = {}
        for b in "ab":
            (tmp_path / b).mkdir()
            siblings[b] = await fork(cp, b, model=idle_model(), workdir=tmp_path / b)
        process = random.getstate()
        seen: dict[str, list] = {"a": [], "b": []}
        for step in order.split("|") if "|" in order else order:
            await asyncio.gather(*(siblings[b].world.run(1) for b in step))
            for b in step:
                seen[b].append(drawn(siblings[b].world))
        untouched = random.getstate() == process
        for sibling in siblings.values():
            await sibling.world.close()
        await parent.close()
        return seen, untouched

    seen, untouched = asyncio.run(go())
    assert all(rec for rec, _ in seen["a"]), "every round drew recommendations"
    assert seen["a"] == seen["b"]
    assert untouched


# --------------------------------------- correction: concurrent social writes replay identically

POSTERS = ("borrower-b", "borrower-c")


class GatedModel(coupled.ScriptedModel):
    """A scripted model whose round-1 answer for borrower-b waits until borrower-c has answered;
    every answer is logged as (round, actor) in the order given."""

    def __init__(self, plan, actor_id, world, answered: dict, log: list) -> None:
        super().__init__(plan, actor_id, lambda: world.clock.round)
        self.answered, self.log = answered, log

    async def _arun(self, messages, response_format=None, tools=None):
        rnd = self.round_source()
        if (self.actor_id, rnd) == ("borrower-b", 1):
            await self.answered["borrower-c"].wait()
        out = await super()._arun(messages, response_format, tools)
        self.log.append((rnd, self.actor_id))
        if self.actor_id in self.answered:
            self.answered[self.actor_id].set()
        return out


def test_concurrent_posts_replay_through_the_following_round(tmp_path):
    """Two actors post in round 1 and their models answer in the reverse of their order (a
    barrier holds borrower-b's answer until borrower-c has answered); a replay answers at once,
    in order. The posts still land in one order, so round 2's observations, which name each post
    by its platform id, are the recorded ones and the replay runs on past them."""
    plan = ScriptedPlan(copy.deepcopy(coupled.IDLE) + [
        {"actor_id": a, "round": 1, "tool_calls": [
            {"name": "create_post", "args": {"content": f"{a} posts"}}]} for a in POSTERS])
    answered, log = {a: asyncio.Event() for a in POSTERS}, []

    def model(actor_id, world):
        return GatedModel(plan, actor_id, world, answered, log)

    def posts(world) -> list[tuple]:
        return world.platform.db.execute(
            "SELECT post_id, user_id, content FROM post ORDER BY post_id").fetchall()

    async def go():
        world = parent_world(tmp_path, plan, model=model, posters=POSTERS)
        await world.start()
        cp = checkpoint(world)
        await world.run(2)
        (tmp_path / "again").mkdir()
        replayed = await replay(cp, world.transcript, workdir=tmp_path / "again")
        out = (posts(world), posts(replayed.world), world.transcript.calls(),
               replayed.world.transcript.calls(), journal_bytes(world),
               journal_bytes(replayed.world))
        await world.close()
        await replayed.world.close()
        return out

    original, again, calls, replay_calls, journals, replay_journals = asyncio.run(go())
    first = [a for r, a in log if r == 1 and a in POSTERS]
    assert first == ["borrower-c", "borrower-b"], "the barrier reversed the answers"
    assert [c for _, _, c in original] == [f"{a} posts" for a in POSTERS]
    assert again == original
    assert {c.round for c in replay_calls} == {1, 2}
    assert replay_calls == calls
    assert replay_journals == journals


def test_a_step_that_fails_before_any_turn_holds_no_later_turn(tmp_path):
    """A step that fails before its agents' turns start leaves no order behind: an agent asked
    to act afterwards, outside a step, is not held for agents that never ran."""
    def refuse(agent):
        raise coupled.InjectedFault("before any turn")

    async def go():
        async with parent_world(tmp_path, ScriptedPlan(copy.deepcopy(coupled.IDLE))) as world:
            world.env._perform_llm_action = refuse
            with pytest.raises(coupled.InjectedFault):
                await world.run(1)
            with world.store.reading() as conn:
                world.observe_all(conn)
            return await asyncio.wait_for(world.agents["borrower-c"].perform_action_by_llm(), 5)

    assert [i.type for i in asyncio.run(go()).intents] == ["no_action"]

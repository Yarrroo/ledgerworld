"""Branch memory namespaces and model transcripts on the offline doubles.

Memory: a sibling never reads another branch's namespace, a snapshot is immutable after the
parent writes on, and a child restored from a snapshot sees exactly the parent's pinned records,
checked against the branch reference model. Transcripts: a replay serves each recorded call
back once and raises on anything the transcript does not hold.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from app.simulation.memory import (
    BranchMemory,
    MemoryRecord,
    NamespaceViolation,
    graph_id_for,
    namespace_for,
)
from app.simulation.transcripts import ModelCall, ReplayMiss, ReplayModel, Transcript
from app.testing.fake_graph_memory import FakeGraphMemory, GraphMemoryStore
from app.testing.scripted_model import ToolCall, UnexpectedModelCall
from zep_cloud.errors import ConflictError

from refmodel import branch_ref

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures/branch-isolation.json"
TOOLS = [{"type": "function", "function": {"name": n, "parameters": {}}}
         for n in ("request_advance", "no_action")]
PARENT_RECORDS = [  # actor, key, value, round: what main remembers by the checkpoint
    ("borrower-c", "rumour", "lender may pull lines", 3),
    ("treasury", "plan", "hold 4,200,000 for payroll", 2),
]


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def branch(store: GraphMemoryStore, world_id: str, branch_id: str) -> BranchMemory:
    client = FakeGraphMemory(namespace_for(world_id, branch_id), store)
    return BranchMemory(client, world_id, branch_id)


def projection(records) -> list[tuple]:
    return [(r.actor_id, r.key, r.value, r.round) for r in records]


@pytest.fixture
def world():
    """main with its pre-checkpoint records, a snapshot, and both fixture forks restored."""

    spec = fixture()
    store = GraphMemoryStore()
    parent = branch(store, spec["world_id"], spec["parent"])
    for record in PARENT_RECORDS:
        parent.write_record(*record)
    snap = parent.snapshot()
    forks = {}
    for f in spec["forks"]:
        forks[f["branch_id"]] = child = branch(store, spec["world_id"], f["branch_id"])
        snap.restore_into(child)
    for w in spec["memory_writes"]:
        forks[w["branch_id"]].write_record(w["actor_id"], w["key"], w["value"], w["round"])
    return spec, store, parent, snap, forks


def test_namespace_is_world_branch():
    assert namespace_for("w1", "integrated") == "world/w1/branch/integrated"
    assert graph_id_for("world/w1/branch/a") != graph_id_for("world/w1/branch/b")
    with pytest.raises(ValueError):
        BranchMemory(FakeGraphMemory("world/w1/branch/x"), "w1", "a/b")


def test_sibling_read_raises_namespace_violation(world):
    spec, _, _, _, forks = world
    expect = spec["expect"]["sibling_read"]
    reader = forks[expect["from"]]
    with pytest.raises(NamespaceViolation):
        reader.retrieve(namespace=expect["namespace"])
    # The fake refuses the reach too: the sibling's graph is not the reader's to open.
    sibling = forks["no-action"]
    with pytest.raises(NamespaceViolation):
        reader.client.graph.get(sibling.graph_id)
    with pytest.raises(NamespaceViolation):
        reader.client.graph.episode.get(sibling._uuids[-1])
    # A client bound to another namespace cannot back this branch.
    with pytest.raises(NamespaceViolation):
        BranchMemory(sibling.client, spec["world_id"], "third")


def test_own_read_and_siblings_do_not_leak(world):
    spec, _, parent, _, forks = world
    own = spec["expect"]["own_read"]
    assert forks[own["branch_id"]].read("borrower-c", own["key"]) == own["value"]
    assert forks["no-action"].read("borrower-c", "note") == "waited"
    assert parent.read("borrower-c", "note") is None
    for b in forks.values():
        assert all(r.namespace == b.namespace for r in b.retrieve())


def test_snapshot_is_immutable_after_parent_writes(world):
    spec, store, parent, snap, _ = world
    digest = snap.digest()
    parent.write_record("borrower-c", "late", "written after the checkpoint", 4)
    assert snap.digest() == digest
    assert projection(snap.records) == PARENT_RECORDS
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.records[0].value = "rewritten"  # type: ignore[misc]
    late_fork = branch(store, spec["world_id"], "late-fork")
    snap.restore_into(late_fork)
    assert late_fork.read("borrower-c", "late") is None
    assert projection(late_fork.retrieve()) == PARENT_RECORDS


def test_child_restored_from_snapshot_sees_parent_records(world):
    _, _, parent, snap, forks = world
    child = forks["integrated"]
    restored = child.retrieve()[: len(snap.records)]
    assert projection(restored) == projection(snap.records)
    assert [r.seq for r in restored] == list(range(len(snap.records)))
    assert child.read("treasury", "plan") == "hold 4,200,000 for payroll"
    assert child.retrieve(actor_id="treasury") == (
        MemoryRecord(child.namespace, "treasury", "plan", "hold 4,200,000 for payroll", 2, 1),
    )
    # Child writes never reach the parent: it is byte-identical to its snapshot.
    assert parent.snapshot().digest() == snap.digest()


def test_restore_refuses_non_empty_self_and_other_world(world):
    spec, store, parent, snap, forks = world
    with pytest.raises(ValueError):
        snap.restore_into(forks["integrated"])
    with pytest.raises(ValueError):
        snap.restore_into(parent)
    with pytest.raises(ValueError):
        snap.restore_into(branch(store, "w2", "elsewhere"))
    with pytest.raises(ConflictError):  # one BranchMemory per namespace on a store
        branch(store, spec["world_id"], spec["parent"])


def test_memory_matches_branch_reference_model(world):
    """The same writes through the reference model give the same records per branch."""

    spec, _, parent, _, forks = world
    ref_store = branch_ref.MemoryStore()
    ref_parent = branch_ref.MemoryClient(ref_store, branch_ref.namespace(spec["world_id"], "main"))
    for record in PARENT_RECORDS:
        ref_parent.write(*record)
    pinned = ref_parent.records()
    ref_forks = {}
    for f in spec["forks"]:
        ns = branch_ref.namespace(spec["world_id"], f["branch_id"])
        ref_forks[f["branch_id"]] = client = branch_ref.MemoryClient(ref_store, ns)
        for rec in pinned:
            client.write(rec.actor_id, rec.key, rec.value, rec.round)
    for w in spec["memory_writes"]:
        ref_forks[w["branch_id"]].write(w["actor_id"], w["key"], w["value"], w["round"])

    assert projection(parent.retrieve()) == projection(ref_parent.records())
    for branch_id, ref in ref_forks.items():
        assert projection(forks[branch_id].retrieve()) == projection(ref.records())
        assert ref.ns == forks[branch_id].namespace
    with pytest.raises(branch_ref.NamespaceViolation):
        ref_forks["integrated"].records(branch_ref.namespace(spec["world_id"], "no-action"))


# ---------------------------------------------------------------- transcripts


def recorded() -> Transcript:
    t = Transcript("w1", "integrated")
    t.record(4, "borrower-c", "obs-c4", [{"name": "request_advance",
                                          "args": {"amount_minor": 1200000, "currency": "USD"}}])
    t.record(4, "lender", "obs-l4", [ToolCall("no_action", {})])
    t.record(5, "borrower-c", "obs-c5", content="waiting")
    return t


def ask(model, content="observe"):
    return model.run([{"role": "user", "content": content}], tools=TOOLS)


def test_replay_serves_recorded_calls_back():
    t = recorded()
    state = {"round": 4, "obs": "obs-c4"}
    model = t.replay_model("borrower-c", lambda: state["round"], lambda: state["obs"])
    assert isinstance(model, ReplayModel)
    reply = ask(model).choices[0].message
    call = reply.tool_calls[0]
    assert call.function.name == "request_advance"
    assert json.loads(call.function.arguments) == {"amount_minor": 1200000, "currency": "USD"}
    # The agent returns the tool result; the turn ends without a new answer.
    follow = model.run([{"role": "tool", "tool_call_id": call.id, "content": "queued"}])
    assert follow.choices[0].message.tool_calls is None
    state.update(round=5, obs="obs-c5")
    assert ask(model).choices[0].message.content == "waiting"


def test_replay_raises_on_any_call_not_in_transcript():
    t = recorded()
    state = {"round": 4, "obs": "obs-c4"}
    model = t.replay_model("borrower-c", lambda: state["round"], lambda: state["obs"])
    ask(model)
    with pytest.raises(ReplayMiss):  # a second call in the same round
        ask(model, "again")
    state.update(round=6, obs="obs-c6")
    with pytest.raises(ReplayMiss):  # a round the transcript never recorded
        ask(model)
    state.update(round=5, obs="something else")
    with pytest.raises(ReplayMiss):  # what the actor sees differs from the recording
        ask(model)
    stranger = t.replay_model("venue", lambda: 4, lambda: "obs-v4")
    with pytest.raises(ReplayMiss):  # an actor with no recorded call
        ask(stranger)
    assert issubclass(ReplayMiss, UnexpectedModelCall)


def test_replay_from_cursor_serves_only_later_calls():
    t = recorded()
    model = t.replay_model("borrower-c", lambda: 4, lambda: "obs-c4", start=2)
    with pytest.raises(ReplayMiss):
        ask(model)


def test_transcript_is_append_only_and_round_trips(tmp_path):
    path = tmp_path / "integrated.jsonl"
    t = Transcript("w1", "integrated", path=path)
    t.record(4, "borrower-c", "obs-c4", [{"name": "no_action", "args": {}}])
    t.record(4, "lender", "obs-l4", [{"name": "no_action", "args": {}}])
    with pytest.raises(ValueError):  # one answer per actor per round
        t.record(4, "lender", "obs-l4", [{"name": "no_action", "args": {}}])
    with pytest.raises(ValueError):  # rounds only move forward
        t.record(3, "venue", "obs-v3", [{"name": "no_action", "args": {}}])
    with pytest.raises(ValueError):  # an answer is tool calls or text
        t.record(5, "venue", "obs-v5")
    assert path.read_bytes() == t.to_jsonl()
    back = Transcript.load(path, "w1", "integrated")
    assert back.calls() == t.calls() and back.to_jsonl() == t.to_jsonl()
    assert back.calls()[0] == ModelCall(4, "borrower-c", "obs-c4", (ToolCall("no_action", {}),))


def test_fork_starts_from_the_parent_prefix(tmp_path):
    parent = recorded()
    cursor = 2
    child = parent.fork("no-action", cursor, path=tmp_path / "no-action.jsonl")
    assert child.calls() == parent.calls()[:cursor]
    assert child.namespace == "world/w1/branch/no-action"
    child.record(5, "borrower-c", "obs-c5-quiet", [{"name": "no_action", "args": {}}])
    assert parent.cursor == 3 and parent.calls()[2].content == "waiting"
    assert (tmp_path / "no-action.jsonl").read_bytes() == child.to_jsonl()
    with pytest.raises(ValueError):
        parent.fork("bad", 9)


def test_fork_never_overwrites_an_existing_transcript_file(tmp_path):
    path = tmp_path / "main.jsonl"
    parent = recorded().fork("main", 3, path=path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        parent.fork("child", 1, path=path)
    assert path.read_bytes() == before


def test_a_new_transcript_never_appends_to_an_existing_file(tmp_path):
    path = tmp_path / "b.jsonl"
    path.write_bytes(recorded().to_jsonl())
    with pytest.raises(FileExistsError):
        Transcript("w1", "integrated", path=path)


@pytest.mark.parametrize("line", [
    {"round": 4, "actor_id": "a", "obs_hash": "h", "tool_calls": [], "content": None},
    {"round": 4, "actor_id": "a", "obs_hash": "", "tool_calls": [], "content": "x"},
    {"round": "4", "actor_id": "a", "obs_hash": "h", "tool_calls": [], "content": "x"},
])
def test_load_checks_every_line_as_record_does(tmp_path, line):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Transcript.load(path, "w1", "integrated")


def test_replay_model_builds_its_own_plan_from_its_start():
    t = recorded()
    with pytest.raises(TypeError):  # no caller plan that could cover other calls than start
        t.replay_model("borrower-c", lambda: 4, lambda: "obs-c4", start=2,
                       plan=t.replay_plan(0))


def test_replay_reads_the_round_once_per_call():
    rounds = iter([4, 5])  # the round moves on between two reads of one call
    model = recorded().replay_model("borrower-c", lambda: next(rounds), lambda: "obs-c4")
    reply = ask(model).choices[0].message
    assert reply.tool_calls[0].function.name == "request_advance"

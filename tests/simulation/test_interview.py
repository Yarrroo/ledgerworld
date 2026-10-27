"""The read-only actor interview, on a real coupled world with ``ScriptedModel`` and
``FakeGraphMemory``.

Two scripted rounds run first, so the transcript holds real answers; graph memory is written
beside them. An interview is then shown only its own actor's records and answers up to the
committed round, never another actor's, never a later one and never a scheduled event; it offers
no tool, refuses an answer that tries to act, and leaves every world digest as it found it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.simulation import interview
from app.simulation.interview import Interview, ReadOnlyViolation
from app.simulation.memory import BranchMemory, NamespaceViolation, namespace_for
from app.simulation.transcripts import Transcript
from app.simulation.world import World, import_oasis
from app.testing.fake_graph_memory import FakeGraphMemory, GraphMemoryStore
from app.testing.scripted_model import ScriptedPlan, UnexpectedModelCall
from oasis_finance.observation import iso_utc

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"
ACTOR_SPECS = {a["actor_id"]: a for a in
               json.loads((FIXTURES / "actors.json").read_text())["actors"]}
WORLD, BRANCH = "interview", "main"
FUTURE = "venue halts withdrawals at round 9"
SECRETS = {  # borrower-c's private history: never in treasury's interview
    "c-memory": "cannot repay line-c next week",
    "c-answer": "hide the shortfall from the lender",
}
PLAN = [
    {"actor_id": "treasury", "round": 1,
     "tool_calls": [{"name": "no_action", "args": {"reason": "wait for receivable-1"}}]},
    {"actor_id": "treasury", "round": 2,
     "tool_calls": [{"name": "no_action", "args": {"reason": "round-two plan"}}]},
    {"actor_id": "borrower-c", "round": 1,
     "tool_calls": [{"name": "no_action", "args": {"reason": SECRETS["c-answer"]}}]},
    {"default": True, "tool_calls": [{"name": "no_action", "args": {}}]},
]


def usd(minor: int) -> dict:
    return {"minor": minor, "currency": "USD"}


def account(account_id: str, settled: int) -> dict:
    return {"id": account_id, "entity": account_id.split("/")[0], "currency": "USD",
            "observability": "known", "as_of": iso_utc(0),
            "buckets": {"settled": usd(settled), "reserved": usd(0), "pledged": usd(0),
                        "pending_in": [], "pending_out": []}}


def snapshot() -> dict:
    return {"snapshot_id": "snap-interview", "as_of": iso_utc(0), "obligations": [],
            "contracts": [], "exposures": [], "pools": [],
            "entities": [{"entity_id": "treasury", "name": "Treasury (synthetic)",
                          "kind": "treasury"},
                         {"entity_id": "borrower-c", "name": "Borrower C (synthetic)",
                          "kind": "borrower"}],
            "accounts": [account("treasury/operating", 7_000_000),
                         account("borrower-c/operating", 400_000)]}


def memory_of(store: GraphMemoryStore, world_id: str, branch_id: str) -> BranchMemory:
    client = FakeGraphMemory(namespace_for(world_id, branch_id), store)
    return BranchMemory(client, world_id, branch_id)


def interview_model(entries: list[dict], actor_id: str, rnd: int):
    return ScriptedPlan(entries).model(actor_id, lambda: rnd)


def prompt(model) -> str:
    (call,) = model.calls
    return json.dumps(call.messages)


def run_interviewed(tmp_path, check):
    """Two committed rounds of treasury and borrower-c (payroll is a rule actor), their graph
    memory, then ``check``."""

    plan = ScriptedPlan(PLAN)
    scenario = [{"round": 9, "kind": "message", "id": "msg-future", "to": "treasury",
                 "text": FUTURE}]
    world = World(WORLD, BRANCH, snapshot(),
                  [ACTOR_SPECS["treasury"], ACTOR_SPECS["borrower-c"], ACTOR_SPECS["payroll"]],
                  model=lambda actor_id, w: plan.model(actor_id, lambda: w.clock.round),
                  workdir=tmp_path, scenario=scenario)
    store = GraphMemoryStore()
    memory = memory_of(store, WORLD, BRANCH)
    memory.write_record("treasury", "plan", "hold 5,000,000 for payroll", 1)
    memory.write_record("borrower-c", "position", SECRETS["c-memory"], 1)
    memory.write_record("treasury", "plan", FUTURE, 9)

    async def go():
        async with world:
            await world.run(2)
            return check(world, memory, store)

    return asyncio.run(go())


def state_of(world: World, memory: BranchMemory, store: GraphMemoryStore) -> tuple:
    return (world.fingerprint(), memory.snapshot().digest(), len(world.queue),
            {k: len(v) for k, v in vars(store).items() if isinstance(v, dict)})


def test_an_interview_sees_only_the_actors_own_history(tmp_path):
    def check(world, memory, _store):
        session = Interview.from_world(world, memory, "treasury")
        model = interview_model(
            [{"actor_id": "treasury", "round": 2, "content": "I held cash for payroll."}],
            "treasury", 2)
        answer = session.ask(model, "Why did you not draw on the line?")
        return world, session, model, answer

    world, session, model, answer = run_interviewed(tmp_path, check)
    assert answer.answer == "I held cash for payroll."
    assert (answer.actor_id, answer.namespace, answer.as_of_round) == \
        ("treasury", namespace_for(WORLD, BRANCH), 2)
    assert [r.actor_id for r in session.memory] == ["treasury"]
    assert [(c.actor_id, c.round) for c in session.calls] == [("treasury", 1), ("treasury", 2)]
    shown = prompt(model)
    assert "hold 5,000,000 for payroll" in shown and "round-two plan" in shown
    for secret in SECRETS.values():
        assert secret not in shown
    for call in world.transcript.calls():  # not even another actor's observation hash
        assert call.obs_hash not in shown


def test_an_interview_never_sees_a_future_event(tmp_path):
    def check(world, memory, _store):
        model = interview_model([{"actor_id": "treasury", "round": 1, "content": "waiting"}],
                                "treasury", 1)
        Interview.open(memory, world.transcript, "treasury", as_of_round=1).ask(
            model, "What happens next?")
        later = interview_model([{"actor_id": "treasury", "round": 2, "content": "waiting"}],
                                "treasury", 2)
        Interview.from_world(world, memory, "treasury").ask(later, "What happens next?")
        return model, later

    as_of_one, committed = run_interviewed(tmp_path, check)
    assert "round-two plan" not in prompt(as_of_one)
    for model in (as_of_one, committed):
        assert FUTURE not in prompt(model)  # neither the round-9 memory nor the scheduled event


def test_an_interview_offers_no_tool_and_submits_no_intent(tmp_path):
    acting = SimpleNamespace(run=lambda messages, tools: SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="request_advance"))]))]))

    def check(world, memory, _store):
        session = Interview.from_world(world, memory, "treasury")
        scripted = interview_model(
            [{"actor_id": "treasury", "round": 2,
              "tool_calls": [{"name": "request_advance", "args": {}}]}], "treasury", 2)
        with pytest.raises(UnexpectedModelCall, match=r"the agent offers \[\]"):
            session.ask(scripted, "Draw now?")
        with pytest.raises(ReadOnlyViolation, match="request_advance"):
            session.ask(acting, "Draw now?")
        return session, len(world.queue)

    session, queued = run_interviewed(tmp_path, check)
    assert queued == 0
    # The session holds plain frozen data only: no memory, transcript, world, ledger or queue.
    held = [getattr(session, f) for f in session.__dataclass_fields__]
    assert all(isinstance(v, (str, int, tuple)) for v in held)
    assert not any(isinstance(v, (BranchMemory, Transcript, World)) for v in held)


def test_an_interview_offers_no_tool_even_to_a_backend_configured_with_tools(tmp_path):
    def check(world, memory, _store):
        model = interview_model([{"actor_id": "treasury", "round": 2, "content": "no"}],
                                "treasury", 2)
        model.model_config_dict["tools"] = [  # a backend whose default request carries a tool
            {"type": "function", "function": {"name": "request_advance", "parameters": {}}}]
        Interview.from_world(world, memory, "treasury").ask(model, "Draw now?")
        return model

    (call,) = run_interviewed(tmp_path, check).calls
    assert call.tools == ()


def test_an_interview_cannot_be_asked_past_the_committed_round(tmp_path):
    def check(world, memory, _store):
        with pytest.raises(ValueError, match="round 3"):
            Interview.open(memory, world.transcript, "treasury", as_of_round=3)
        with pytest.raises(ValueError, match="round 3"):
            Interview.from_world(world, memory, "treasury", as_of_round=3)
        return Interview.from_world(world, memory, "treasury", as_of_round=1)

    assert run_interviewed(tmp_path, check).as_of_round == 1


def test_the_context_hash_covers_everything_the_model_was_shown(tmp_path, monkeypatch):
    def check(world, memory, _store):
        session = Interview.from_world(world, memory, "treasury")
        entry = [{"actor_id": "treasury", "round": 2, "content": "fine"}]
        first = session.ask(interview_model(entry, "treasury", 2), "How are you?")
        monkeypatch.setattr(interview, "SYSTEM_PROMPT", interview.SYSTEM_PROMPT + " Be brief.")
        second = session.ask(interview_model(entry, "treasury", 2), "How are you?")
        return first, second

    first, second = run_interviewed(tmp_path, check)
    assert first.context_hash != second.context_hash


def test_an_interview_leaves_the_world_state_hash_unchanged(tmp_path):
    def check(world, memory, store):
        before = state_of(world, memory, store)
        model = interview_model([{"actor_id": "treasury", "round": 2, "content": "fine"}],
                                "treasury", 2)
        Interview.from_world(world, memory, "treasury").ask(model, "How are you?")
        return before, state_of(world, memory, store)

    before, after = run_interviewed(tmp_path, check)
    assert before == after


def test_an_interview_reads_only_its_own_branch(tmp_path):
    def check(world, _memory, store):
        sibling = memory_of(store, WORLD, "fork")
        with pytest.raises(NamespaceViolation):
            Interview.from_world(world, sibling, "treasury")
        with pytest.raises(LookupError):
            Interview.from_world(world, _memory, "lender")
        with pytest.raises(LookupError, match="no model"):  # a rule actor has no answers
            Interview.from_world(world, _memory, "payroll")
        return True

    assert run_interviewed(tmp_path, check)

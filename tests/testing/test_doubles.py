"""The offline doubles: a scripted plan replays exactly, an unexpected call fails loudly,
and graph-memory namespaces isolate."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.testing.fake_graph_memory import FakeGraphMemory, NamespaceViolation, namespace_for
from app.testing.scripted_model import (
    PLANS_DIR,
    PlanError,
    ScriptedPlan,
    UnexpectedModelCall,
)
from zep_cloud import NotFoundError
from zep_cloud.errors import BadRequestError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures/coupled-chain.json"
ACTORS = ["borrower-b", "borrower-c", "feed", "lender", "treasury", "venue"]
ROUNDS = range(1, 7)
FINANCE_TOOLS = ["request_advance", "accept", "disburse", "no_action"]

try:  # camel's agent stack needs mcp<2; the workspace lock currently resolves mcp 2.x.
    from camel.agents import ChatAgent
    from camel.toolkits import FunctionTool

    AGENT_STACK_ERROR = None
except ImportError as error:
    AGENT_STACK_ERROR = f"camel.agents does not import in this environment: {error}"


def tool_schemas(names=FINANCE_TOOLS):
    return [{"type": "function", "function": {"name": n, "parameters": {}}} for n in names]


def coupled_chain() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def observation(branch: str, actor: str, rnd: int) -> str:
    """What each actor is shown: the rumour from round 4, the request from round 5."""

    seen = []
    if branch == "shock" and rnd >= 4 and actor == "borrower-c":
        seen.append("p-r3-1")
    if branch == "shock" and rnd == 5 and actor == "lender":
        seen.append("req:borrower-c:r4")
    return json.dumps({"actor": actor, "round": rnd, "evidence_ids": seen})


def run_branch(branch: str, seed: int):
    """Drive every actor for rounds 1-6, all at once and in a seeded shuffled order."""

    plan = ScriptedPlan.from_url("scripted://coupled-chain")
    clock = {"round": 0}
    models = {a: plan.model(a, lambda: clock["round"]) for a in ACTORS}
    rng = random.Random(seed)
    answers = {}

    async def ask(actor: str):
        await asyncio.sleep(rng.random() / 1000)
        messages = [
            {"role": "system", "content": f"You are {actor}."},
            {"role": "user", "content": observation(branch, actor, clock["round"])},
        ]
        return actor, await models[actor].arun(messages, tools=tool_schemas())

    async def main():
        for rnd in ROUNDS:
            clock["round"] = rnd
            order = ACTORS[:]
            rng.shuffle(order)
            for actor, completion in await asyncio.gather(*(ask(a) for a in order)):
                answers[(rnd, actor)] = completion

    asyncio.run(main())
    return plan, models, answers


def intent_id(call_id: str) -> str:
    """The intent a tool call becomes: i-r<round>-<actor_id>-<n> (agent-world HANDOFF, Data)."""

    assert call_id.startswith("call-"), call_id
    return "i-" + call_id[len("call-"):]


def calls_of(completion) -> list[tuple[str, str, dict]]:
    return [
        (c.id, c.function.name, json.loads(c.function.arguments))
        for c in completion.choices[0].message.tool_calls or []
    ]


# ScriptedModel


def test_plan_file_is_the_fixture_plan_and_selected_by_url():
    plan_file = json.loads((PLANS_DIR / "coupled-chain.json").read_text(encoding="utf-8"))
    assert plan_file["plan"] == coupled_chain()["plan"]

    plan = ScriptedPlan.from_env({"LLM_BASE_URL": "scripted://coupled-chain"})
    assert plan is not None and len(plan.entries) == 2 and plan.default is not None
    assert ScriptedPlan.from_env({"LLM_BASE_URL": "https://api.openai.com/v1"}) is None
    assert ScriptedPlan.from_url(f"scripted://{FIXTURE}").entries == plan.entries
    for bad in ("scripted://", "scripted://../x", "https://example.invalid"):
        with pytest.raises(PlanError):
            ScriptedPlan.from_url(bad)


def test_coupled_chain_plan_replays_exactly():
    expect = coupled_chain()["expect"]
    plan_entries = coupled_chain()["plan"]
    _, models, shock = run_branch("shock", seed=1)

    r4 = calls_of(shock[(4, "borrower-c")])
    assert [name for _, name, _ in r4] == [expect["shock"]["round_4"]["type"]]
    assert r4[0][2] == plan_entries[0]["tool_calls"][0]["args"]
    assert [intent_id(cid) for cid, _, _ in r4] == [expect["shock"]["round_4"]["intent"]]
    r5 = calls_of(shock[(5, "lender")])
    assert [(name, args) for _, name, args in r5] == [
        (c["name"], c["args"]) for c in plan_entries[1]["tool_calls"]
    ]
    assert [intent_id(cid) for cid, _, _ in r5] == expect["shock"]["round_5"]["intents"]

    # The model saw exactly the evidence the fixture traces each response to.
    by_round = {c.round: c for c in models["borrower-c"].calls}
    assert sorted(by_round[4].seen) == expect["shock"]["round_4"]["evidence_ids"]
    lender_r5 = next(c for c in models["lender"].calls if c.round == 5)
    assert sorted(lender_r5.seen) == expect["shock"]["round_5"]["evidence_ids"]

    # Everything the plan does not name falls to the default.
    for (rnd, actor), completion in shock.items():
        if (rnd, actor) not in {(4, "borrower-c"), (5, "lender")}:
            assert [name for _, name, _ in calls_of(completion)] == ["no_action"]

    # The control branch, without the rumour, never leaves the default.
    _, _, control = run_branch("control", seed=2)
    assert expect["control"]["round_4"]["borrower-c"] == "no_action"
    assert expect["control"]["round_5"]["lender"] == "no_action"
    assert all(
        [name for _, name, _ in calls_of(c)] == ["no_action"] for c in control.values()
    )

    # Another arrival order gives byte-identical completions.
    _, _, again = run_branch("shock", seed=99)
    assert {k: v.model_dump_json() for k, v in again.items()} == {
        k: v.model_dump_json() for k, v in shock.items()
    }


@pytest.mark.skipif(AGENT_STACK_ERROR is not None, reason=str(AGENT_STACK_ERROR))
def test_scripted_agent_drives_the_same_tools_a_live_one_does():
    executed = []

    def request_advance(amount_minor: int, currency: str, reason: str, **kw) -> str:
        """Ask the lender for an advance.

        Args:
            amount_minor (int): amount in minor units.
            currency (str): ISO currency.
            reason (str): why.
        """
        executed.append(("request_advance", amount_minor, currency))
        return "queued i-r4-borrower-c-1"

    def no_action() -> str:
        """Do nothing this round."""
        executed.append(("no_action",))
        return "queued"

    plan = ScriptedPlan.load(FIXTURE)
    clock = {"round": 4}
    model = plan.model("borrower-c", lambda: clock["round"])
    agent = ChatAgent(
        system_message="You are borrower-c.",
        model=model,
        tools=[FunctionTool(request_advance), FunctionTool(no_action)],
    )
    response = agent.step("Public post p-r3-1: the venue may pause withdrawals.")
    assert executed == [("request_advance", 1200000, "USD")]
    assert response.msgs[0].content == "done"
    assert [c.answer for c in model.calls] == ["entry:0", "follow-up"]
    assert [c.tool_calls[0].name for c in model.calls[:1]] == ["request_advance"]
    assert {"request_advance", "no_action"} <= set(model.calls[0].tools)

    clock["round"] = 5
    agent.step("Nothing new.")
    assert executed[-1] == ("no_action",)


def test_unexpected_calls_fail_loudly():
    plan = ScriptedPlan(
        [{"actor_id": "lender", "round": 1, "tool_calls": [{"name": "accept", "args": {}}]}]
    )
    model = plan.model("lender", lambda: 2)
    with pytest.raises(UnexpectedModelCall, match="no plan entry"):
        model.run([{"role": "user", "content": "hi"}], tools=tool_schemas())

    other = plan.model("borrower-b", lambda: 1)
    with pytest.raises(UnexpectedModelCall, match="no plan entry"):
        other.run([{"role": "user", "content": "hi"}], tools=tool_schemas())

    untooled = plan.model("lender", lambda: 1)
    with pytest.raises(UnexpectedModelCall, match="offers"):
        untooled.run([{"role": "user", "content": "hi"}], tools=tool_schemas(["no_action"]))

    once = plan.model("lender", lambda: 1)
    once.run([{"role": "user", "content": "hi"}], tools=tool_schemas())
    with pytest.raises(UnexpectedModelCall, match="already answered"):
        once.run([{"role": "user", "content": "again"}], tools=tool_schemas())

    ambiguous = ScriptedPlan([
        {"actor_id": "lender", "round": 1, "when_seen": ["p-1"], "content": "x"},
        {"actor_id": "lender", "round": 1, "when_seen": ["p-2"], "content": "y"},
    ])
    with pytest.raises(UnexpectedModelCall, match="all match"):
        ambiguous.model("lender", lambda: 1).run(
            [{"role": "user", "content": "saw p-1 and p-2"}], tools=tool_schemas()
        )

    # Whole-token matching: p-r3-10 is not p-r3-1, so the scripted entry does not fire.
    chain = ScriptedPlan.load(FIXTURE)
    c = chain.model("borrower-c", lambda: 4).run(
        [{"role": "user", "content": "saw p-r3-10"}], tools=tool_schemas()
    )
    assert calls_of(c)[0][1] == "no_action"

    for bad in (
        [{"default": True, "content": "a"}, {"default": True, "content": "b"}],
        [{"actor_id": "a", "round": "1", "content": "x"}],
        [{"actor_id": "a", "round": 1}],
        [{"actor_id": "a", "round": 1, "tool_calls": [{"args": {}}]}],
        [{"actor_id": "a", "round": 1, "content": "x"}, {"actor_id": "a", "round": 1, "content": "y"}],
    ):
        with pytest.raises(PlanError):
            ScriptedPlan(bad)


def test_every_prompt_is_recorded():
    plan = ScriptedPlan([{"default": True, "content": '{"ok": true}'}])
    model = plan.model("report", lambda: 0)
    messages = [{"role": "user", "content": "first"}]
    model.run(messages)
    messages[0]["content"] = "changed after the call"
    model.run([{"role": "user", "content": "second"}])
    assert [c.messages[-1]["content"] for c in model.calls] == ["first", "second"]
    assert [c.messages[-1]["content"] for c in plan.calls] == ["first", "second"]


def test_upstream_llm_client_reads_the_scripted_model():
    from app.utils.llm_client import LLMClient

    plan = ScriptedPlan([{"default": True, "content": '{"grounded": true, "figures": [3000000]}'}])
    model = plan.model("report", lambda: 0)
    llm = LLMClient(api_key="unused", base_url="http://127.0.0.1:9", model="scripted")
    llm.client = model.openai_client()
    assert llm.chat_json([{"role": "user", "content": "Summarise run r-1."}]) == {
        "grounded": True,
        "figures": [3000000],
    }
    assert model.calls[0].messages[-1]["content"] == "Summarise run r-1."


# FakeGraphMemory


def seeded(namespace: str, client: FakeGraphMemory | None = None):
    mem = client.for_namespace(namespace) if client else FakeGraphMemory(namespace)
    graph_id = namespace.replace("/", "_")
    mem.graph.create(graph_id=graph_id, name="world")
    lender = mem.add_node(graph_id, "lender", labels=["Entity", "Lender"], summary="pool")
    venue = mem.add_node(graph_id, "venue", labels=["Entity", "Venue"], summary="exchange")
    mem.add_edge(graph_id, lender, venue, "HOLDS_CASH_AT", "The lender holds cash at the venue")
    episode = mem.graph.add(graph_id=graph_id, type="text", data="rumour about the venue")
    return mem, graph_id, lender, episode.uuid_


def test_graph_memory_namespaces_isolate():
    a, graph_a, node_a, episode_a = seeded(namespace_for("w1", "shock"))
    b, graph_b, _, _ = seeded(namespace_for("w1", "control"), a)
    batch_a = a.batch.create(metadata={"graph_id": graph_a}).batch_id

    reaches = [
        lambda: b.graph.get(graph_a),
        lambda: b.graph.delete(graph_id=graph_a),
        lambda: b.graph.create(graph_id=graph_a),
        lambda: b.graph.add(graph_id=graph_a, type="text", data="leak"),
        lambda: b.graph.search(graph_id=graph_a, query="venue", scope="edges"),
        lambda: b.graph.set_ontology(graph_ids=[graph_a], entities={}),
        lambda: b.graph.node.get(uuid_=node_a),
        lambda: b.graph.node.get_edges(node_uuid=node_a),
        lambda: b.graph.node.with_raw_response.get_by_graph_id(graph_a, limit=10),
        lambda: b.graph.edge.get_by_graph_id(graph_a),
        lambda: b.graph.episode.get(uuid_=episode_a),
        lambda: b.batch.get(batch_id=batch_a),
        lambda: b.batch.list_items(batch_id=batch_a),
        lambda: b.add_node(graph_a, "intruder"),
    ]
    for reach in reaches:
        with pytest.raises(NamespaceViolation):
            reach()

    # The owner's world is unchanged and each namespace sees only its own.
    assert [n.name for n in a.graph.node.get_by_graph_id(graph_a)] == ["lender", "venue"]
    assert len(a.graph.search(graph_id=graph_a, query="venue", scope="episodes").episodes) == 1
    assert [x.batch_id for x in b.batch.list().batches] == []
    assert [x.batch_id for x in a.batch.list().batches] == [batch_a]
    assert b.graph.get(graph_b).graph_id == graph_b

    with pytest.raises(NotFoundError):
        a.graph.get("no-such-graph")
    with pytest.raises(NotFoundError):
        a.graph.node.get(uuid_="node-999999")
    with pytest.raises(ValueError):
        FakeGraphMemory("branch-1")


def test_graph_memory_is_deterministic():
    def ids():
        mem, graph_id, node, episode = seeded(namespace_for("w", "b"))
        hits = mem.graph.search(graph_id=graph_id, query="cash venue", limit=5)
        return node, episode, [(e.uuid_, e.score) for e in hits.edges]

    assert ids() == ids() == ("node-000001", "episode-000001", [("edge-000001", 2.0)])


def test_upstream_services_read_the_fake(monkeypatch):
    from app.services.graph_builder import GraphBuilderService
    from app.services.zep_entity_reader import ZepEntityReader
    from app.services.zep_tools import ZepToolsService
    from app.utils.zep_paging import fetch_all_nodes

    mem = FakeGraphMemory(namespace_for("w1", "base")).install(monkeypatch)
    builder = GraphBuilderService(api_key="unused")
    assert builder.client is mem

    graph_id = builder.create_graph(name="LedgerWorld", graph_id="lw-base")
    submission = builder.add_text_batches(graph_id, ["chunk one", "chunk two"], batch_size=1)
    episodes = builder._wait_for_batch(submission)
    assert submission.item_count == len(episodes) == 2
    assert [mem.graph.episode.get(uuid_=e).content for e in episodes] == ["chunk one", "chunk two"]

    lender = mem.add_node(graph_id, "lender", labels=["Entity", "Lender"], summary="the pool")
    for n in range(4):
        borrower = mem.add_node(graph_id, f"borrower-{n}", labels=["Entity", "Borrower"])
        mem.add_edge(graph_id, lender, borrower, "LENDS_TO", f"The lender lends to borrower-{n}")
    assert len(fetch_all_nodes(mem, graph_id, page_size=2)) == 5
    data = builder.get_graph_data(graph_id)
    assert (data["node_count"], data["edge_count"]) == (5, 4)

    tools = ZepToolsService(api_key="unused")
    result = tools.search_graph(graph_id, "lends borrower-2", limit=2)
    assert result.facts[0] == "The lender lends to borrower-2"
    assert tools.get_node_detail(lender).name == "lender"

    reader = ZepEntityReader(api_key="unused")
    assert len(reader.get_node_edges(lender)) == 4

    sibling = mem.for_namespace(namespace_for("w1", "other"))
    with pytest.raises(NamespaceViolation):
        sibling.graph.search(graph_id=graph_id, query="lender")


# Regressions from review


def test_the_most_specific_matching_entry_answers():
    plan = ScriptedPlan([
        {"actor_id": "lender", "round": 1, "tool_calls": [{"name": "accept", "args": {}}]},
        {"actor_id": "lender", "round": 1, "when_seen": ["p-1"],
         "tool_calls": [{"name": "no_action", "args": {}}]},
    ])
    saw = plan.model("lender", lambda: 1).run(
        [{"role": "user", "content": "saw p-1"}], tools=tool_schemas()
    )
    assert [name for _, name, _ in calls_of(saw)] == ["no_action"]
    unseen = plan.model("lender", lambda: 1).run(
        [{"role": "user", "content": "quiet"}], tools=tool_schemas()
    )
    assert [name for _, name, _ in calls_of(unseen)] == ["accept"]


def test_a_tool_result_the_model_never_asked_for_fails_loudly():
    plan = ScriptedPlan([{"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}])
    model = plan.model("lender", lambda: 1)
    stray = {"role": "tool", "tool_call_id": "call-r0-lender-1", "content": "queued"}
    with pytest.raises(UnexpectedModelCall, match="tool result"):
        model.run([{"role": "user", "content": "hi"}, stray], tools=tool_schemas())

    first = model.run([{"role": "user", "content": "hi"}], tools=tool_schemas())
    (call_id, _, _), = calls_of(first)
    result = {"role": "tool", "tool_call_id": call_id, "content": "queued"}
    history = [{"role": "user", "content": "hi"}, first.choices[0].message.model_dump(), result]
    done = model.run(history, tools=tool_schemas())
    assert done.choices[0].message.content == "done" and not calls_of(done)
    assert [c.answer for c in model.calls] == ["default", "follow-up"]
    with pytest.raises(UnexpectedModelCall, match="tool result"):
        model.run(history, tools=tool_schemas())


def test_batch_process_is_all_or_nothing():
    mem = FakeGraphMemory(namespace_for("w", "b"))
    for graph_id in ("g1", "g2"):
        mem.graph.create(graph_id=graph_id)
    batch_id = mem.batch.create().batch_id
    items = [SimpleNamespace(type="graph_episode", graph_id=g, data=g, content=None,
                             created_at=None, source_description=None, metadata=None)
             for g in ("g1", "g2")]
    mem.batch.add(batch_id, items=items)
    mem.graph.delete(graph_id="g2")
    with pytest.raises(NotFoundError):
        mem.batch.process(batch_id)
    assert mem.graph.search(graph_id="g1", query="g1", scope="episodes").episodes == []
    assert mem.batch.get(batch_id).status == "draft"


def test_graph_paging_takes_the_sdk_arguments_and_rejects_a_zero_limit():
    mem, graph_id, _, _ = seeded(namespace_for("w", "b"))
    first = mem.graph.node.with_raw_response.get_by_graph_id(graph_id, limit=1)
    cursor = first.headers["zep-next-cursor"]
    rest = mem.graph.node.with_raw_response.get_by_graph_id(graph_id, limit=1, uuid_cursor=cursor)
    assert [n.name for n in first.data + rest.data] == ["lender", "venue"]
    for call in (
        lambda: mem.graph.search(graph_id=graph_id, query="venue", limit=0),
        lambda: mem.batch.list(limit=0),
        lambda: mem.graph.node.get_by_graph_id(graph_id, limit=0),
    ):
        with pytest.raises(BadRequestError):
            call()


def test_cursor_paging_survives_ids_past_six_digits():
    mem = FakeGraphMemory(namespace_for("w", "b"))
    mem.graph.create(graph_id="g")
    mem.store._counters["node"] = 999_998
    names = [mem.add_node("g", name) for name in ("old", "new")]
    assert names == ["node-999999", "node-1000000"]
    seen, cursor = [], None
    while True:
        page = mem.graph.node.with_raw_response.get_by_graph_id("g", limit=1, cursor=cursor)
        seen += [n.name for n in page.data]
        cursor = page.headers.get("zep-next-cursor")
        if cursor is None:
            break
    assert sorted(seen) == ["new", "old"]

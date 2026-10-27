"""Financial actions in the agent platform: actors move money through their finance tools only.

Each actor is a ``FinanceAgent`` (an OASIS ``SocialAgent``) driven by ``OasisEnv.step`` on a
real OASIS platform in a temporary SQLite file, with a ``ScriptedModel`` for its model. A tool
call queues a C1 intent and nothing else; the ledger moves only when the queued intents are
cleared, which here a stand-in for the coordinator's step 7 does with ``ledger.pay``.

Fixtures are read unchanged from the agent-world design: observation-scope.json,
malformed-output.json and actors.json.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from app.finance import ledger
from app.finance.models import Journal, Posting
from app.finance.store import LedgerStore
from app.simulation.actions import IntentQueue, build_finance_agent
from app.simulation.observations import build_observation
from app.testing.scripted_model import PlanEntry, ScriptedModel, ScriptedPlan, ToolCall
from oasis_finance.guardrail import RawCall, parse_social_call
from oasis_finance.observation import DEFAULT_EPOCH, sha256_of

# Importing oasis writes ./log in the working directory (oasis-seam.md S13): do it elsewhere.
_cwd = os.getcwd()
os.chdir(tempfile.mkdtemp(prefix="oasis-log-"))
try:
    from oasis import ActionType, AgentGraph, LLMAction, ManualAction, Platform
    from oasis.environment.env import OasisEnv
    from oasis_finance.agent import FinanceAgent, SealedToolset
finally:
    os.chdir(_cwd)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"
ACTORS = {a["actor_id"]: a for a in json.loads((FIXTURES / "actors.json").read_text())["actors"]}
SCOPE = json.loads((FIXTURES / "observation-scope.json").read_text())
MALFORMED = json.loads((FIXTURES / "malformed-output.json").read_text())
ROUND_HOURS = 4
FINANCIAL_BLOCK = "Your financial observation"
KINDS = {"treasury": "treasury", "lender": "lender pool", "borrower-c": "borrower"}
SOCIAL_BLOCK = "Here is your social media environment:"


def at(round_: int):
    return DEFAULT_EPOCH + timedelta(hours=round_ * ROUND_HOURS)


def opened(accounts: dict[str, int], as_of) -> LedgerStore:
    """A ledger whose ``<actor>/operating`` accounts hold the given settled USD cents."""
    store = LedgerStore("sqlite://")
    store.add_entity("x", "Outside (synthetic)", "external")
    for account_id, settled in accounts.items():
        owner = account_id.split("/")[0]
        store.add_entity(owner, f"{owner} (synthetic)", KINDS[owner])
        store.open_account(account_id, owner, "USD", as_of=as_of)
        store.open_account(f"{account_id}:opening", "x", "USD", kind="external", as_of=as_of)
        store.apply(Journal(f"open:{account_id}", (
            Posting(account_id, settled), Posting(f"{account_id}:opening", -settled)),
            kind="opening", sim_time=as_of))
    return store


def settled(store: LedgerStore, account_id: str) -> int:
    return store.view(account_id).settled_minor


def clear_payments(store: LedgerStore, intents, now) -> list[Journal]:
    """Stand-in for the coordinator's step 7: post each ``pay`` intent, in drain order."""
    return [ledger.pay(store, f"{i.actor_id}/operating", i.params.amount.minor,
                       to_account=f"{i.params.to}/operating", now=now,
                       journal_id=f"j:{i.intent_id}", round=i.round, source_intent_id=i.intent_id)
            for i in intents if i.type == "pay"]


def account_item(owner: str, settled_minor: int) -> dict:
    return {"id": f"acct:{owner}/operating", "kind": "own_account", "owner": owner,
            "visible_from_h": 0, "settled_minor": settled_minor}


def idle_plan() -> ScriptedPlan:
    return ScriptedPlan([{"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}])


def user_prompt(call) -> str:
    return next(m["content"] for m in call.messages if m["role"] == "user")


class ListModel(ScriptedModel):
    """A model that answers each call with the next response of a list, whatever it was asked.

    ``ScriptedModel`` refuses to answer with a tool the agent does not offer; the malformed cases
    need exactly that, so this double hands its responses over unchecked.
    """

    def __init__(self, actor_id: str, round_: int, responses: list[list[dict]]) -> None:
        super().__init__(ScriptedPlan([]), actor_id, lambda: round_)
        self.responses = [list(r) for r in responses]

    def _answer(self, messages, tools):
        response = self.responses.pop(0)
        entry = PlanEntry(0, self.actor_id, self.round_source(), frozenset(),
                          tuple(ToolCall(c["name"], c["args"]) for c in response), None)
        offered = tuple(t["function"]["name"] for t in tools or [])
        return self._finish(self.round_source(), len(self.calls) + 1, copy.deepcopy(messages),
                            offered, frozenset(), "list", entry)


async def on_platform(agents, actions, tmp_path, *, before_step=None):
    """Sign the agents up on a fresh OASIS platform and run one ``env.step``."""
    graph = AgentGraph()
    for agent in agents:
        graph.add_agent(agent)
    platform = Platform(db_path=str(tmp_path / "oasis.db"), recsys_type="random")
    env = OasisEnv(graph, platform, database_path=str(tmp_path / "oasis.db"))
    await env.reset()
    try:
        if before_step is not None:
            before_step()
        await env.step(actions)
    finally:
        await env.close()
    return platform


def rows(db: Path, sql: str) -> list[tuple]:
    import sqlite3

    with sqlite3.connect(db) as c:
        return c.execute(sql).fetchall()


# ------------------------------------------------- two actors move money through tools only


def test_two_scripted_actors_change_ledger_state_only_through_tools(tmp_path):
    round_ = 1
    now = at(round_)
    store = opened({"treasury/operating": 7_000_000, "borrower-c/operating": 500_000},
                   DEFAULT_EPOCH)
    items = [account_item("treasury", 7_000_000), account_item("borrower-c", 500_000)]
    plan = ScriptedPlan([
        {"actor_id": "treasury", "round": round_, "when_seen": ["acct:treasury/operating"],
         "tool_calls": [{"name": "pay", "args": {"amount_minor": 1_000_000, "currency": "USD",
                                                 "to": "borrower-c"}}]},
        {"actor_id": "borrower-c", "round": round_, "when_seen": ["acct:borrower-c/operating"],
         "tool_calls": [{"name": "pay", "args": {"amount_minor": 250_000, "currency": "USD",
                                                 "to": "treasury"}}]},
    ])
    queue = IntentQueue("shock")
    agents = [build_finance_agent(ACTORS[a], n, queue, model=plan.model(a, lambda: round_))
              for n, a in enumerate(["treasury", "borrower-c"])]
    observations = {a.finance_actor.actor_id: build_observation(
        ACTORS[a.finance_actor.actor_id], items, round_, round_ * ROUND_HOURS) for a in agents}

    def observe():
        for agent in agents:
            agent.observe(observations[agent.finance_actor.actor_id])

    before = store.dump()
    asyncio.run(on_platform(agents, {a: LLMAction() for a in agents}, tmp_path,
                            before_step=observe))

    # The platform's own dispatch reached each agent's finance turn, and nothing was posted.
    assert all(a.last_turn is not None and a.last_turn.alert is None for a in agents)
    assert store.dump() == before
    intents = queue.drain()
    assert [(i.actor_id, i.type, i.params.amount.minor) for i in intents] == [
        ("treasury", "pay", 1_000_000), ("borrower-c", "pay", 250_000)]
    for intent in intents:
        observation = observations[intent.actor_id]
        assert intent.obs_hash == observation.obs_hash == sha256_of(observation.body)
        assert tuple(intent.evidence_ids) == observation.evidence_ids

    journals = clear_payments(store, intents, now)
    assert settled(store, "treasury/operating") == 7_000_000 - 1_000_000 + 250_000
    assert settled(store, "borrower-c/operating") == 500_000 + 1_000_000 - 250_000
    assert sorted(j.source_intent_id for j in journals) == sorted(i.intent_id for i in intents)
    moved = [j for j in store.rows("journals") if j["kind"] != "opening"]
    assert {j["source_intent_id"] for j in moved} == {i.intent_id for i in intents}

    # Each prompt opened with the actor's own financial block, then the social feed.
    for agent in agents:
        (call,) = agent.model_backend.models[0].calls
        prompt = user_prompt(call)
        assert prompt.startswith(FINANCIAL_BLOCK)
        assert prompt.index(observations[call.actor_id].text) < prompt.index(SOCIAL_BLOCK)
        other = "borrower-c" if call.actor_id == "treasury" else "treasury"
        assert f"acct:{other}/operating" not in prompt


def test_a_post_runs_on_the_platform_and_queues_no_intent(tmp_path):
    plan = ScriptedPlan([{"actor_id": "feed", "round": 3, "tool_calls": [
        {"name": "create_post", "args": {"content": "Unconfirmed: the venue may pause."}},
        {"name": "no_action", "args": {}}]}])
    queue = IntentQueue("shock")
    feed = build_finance_agent(ACTORS["feed"], 0, queue, model=plan.model("feed", lambda: 3))
    asyncio.run(on_platform([feed], {feed: LLMAction()}, tmp_path, before_step=lambda: feed.observe(
        build_observation(ACTORS["feed"], [], 3, 12))))
    assert rows(tmp_path / "oasis.db", "select content from post") == [
        ("Unconfirmed: the venue may pause.",)]
    assert [i.type for i in queue.drain()] == ["no_action"]
    assert [c.name for c in feed.last_turn.social] == ["create_post"]
    assert feed.last_social_results == (("create_post", {"success": True, "post_id": 1}),)


# --------------------------------------------------------- malformed output: repair, fallback


def borrower_c(queue, model):
    return build_finance_agent(ACTORS["borrower-c"], 0, queue, model=model)


async def one_turn(agent, observation, feed="(no posts)"):
    async def no_feed(**_):
        return feed

    agent.env.to_text_prompt = no_feed  # the platform's feed, which these cases do not need
    agent.observe(observation)
    return await agent.perform_action_by_llm()


@pytest.mark.parametrize("case", MALFORMED["cases"], ids=lambda c: c["id"])
def test_malformed_output_gets_one_repair_then_no_action(case):
    round_ = 4
    now = at(round_)
    queue = IntentQueue("shock")
    model = ListModel("borrower-c", round_, [[case["first"]], [case["repair"]]])
    agent = borrower_c(queue, model)
    store = opened({"lender/operating": 4_500_000, "borrower-c/operating": 500_000,
                    "treasury/operating": 7_000_000}, now)
    store.hold("treasury/operating", 5_000_000, now=now, purpose="payroll")
    reservation = store.rows("reservations")[0]["reservation_id"]
    store.add_obligation("payroll", "treasury/operating", 5_000_000, now, kind="payroll",
                         reservation_id=reservation)
    observation = build_observation(ACTORS["borrower-c"], SCOPE["world_items"], round_,
                                    SCOPE["sim_time_h"])
    before = store.dump()

    result = asyncio.run(one_turn(agent, observation))

    expect = case["expect"]
    assert result.repair_attempts == expect["repair_attempts"] <= MALFORMED["expect_all"][
        "max_repair_attempts"]
    assert len(model.calls) == 1 + result.repair_attempts
    assert (result.alert is not None) is expect["alert"]
    if expect["alert"]:
        assert result.alert.reason == expect["alert_reason"]
        assert agent.last_turn.alert == result.alert
    (intent,) = queue.drain()
    assert intent.type == expect["intent_type"]
    assert store.dump() == before  # the turn itself never touches the ledger

    # The repair prompt names the schema error the first answer made.
    repair_prompt = model.calls[1].messages[-1]["content"]
    assert repair_prompt.startswith(f"repair:borrower-c:r{round_}")
    named = "wire_money" if case["first"]["name"] == "wire_money" else "amount_minor"
    assert named in repair_prompt

    if "posted_amount_minor" in expect:
        # Stand-in clearing of the advance: the lender's cash moves by the intent's integer.
        amount = intent.params.amount.minor
        assert type(amount) is int and amount == expect["posted_amount_minor"]
        ledger.pay(store, "lender/operating", amount, to_account="borrower-c/operating",
                   now=now, journal_id=f"j:{intent.intent_id}", round=round_,
                   source_intent_id=intent.intent_id)
        assert settled(store, "borrower-c/operating") == 500_000 + expect["posted_amount_minor"]

    # Mandatory settlements still run in the round, whatever the actor answered.
    (paid,) = ledger.settle_due(store, now, round=round_)
    assert paid.journal_id == "settle:payroll"
    assert settled(store, "treasury/operating") == 2_000_000


def test_a_malformed_social_call_is_repaired_with_the_response():
    queue = IntentQueue("shock")
    model = ListModel("feed", 3, [
        [{"name": "create_post", "args": {"text": "wrong key"}}, {"name": "no_action", "args": {}}],
        [{"name": "no_action", "args": {}}]])
    feed = build_finance_agent(ACTORS["feed"], 0, queue, model=model)
    result = asyncio.run(one_turn(feed, build_observation(ACTORS["feed"], [], 3, 12)))
    assert result.repair_attempts == 1 and result.alert is None and result.social == ()
    repair = model.calls[1].messages[-1]["content"]
    assert "'content' is a required property" in repair and "'text' was unexpected" in repair
    assert [i.type for i in queue.drain()] == ["no_action"]


# ------------------------------------------------------------------ what an actor is shown


def test_an_observation_never_holds_the_future_or_another_actors_cash():
    round_ = SCOPE["round"]
    plan = idle_plan()
    queue = IntentQueue("shock")
    agent = borrower_c(queue, plan.model("borrower-c", lambda: round_))
    observation = build_observation(ACTORS["borrower-c"], SCOPE["world_items"], round_,
                                    SCOPE["sim_time_h"])
    asyncio.run(one_turn(agent, observation, feed="post p-feed-1: markets calm"))

    prompt = user_prompt(agent.model_backend.models[0].calls[0])
    financial, social = prompt.split(SOCIAL_BLOCK)
    assert financial.startswith(FINANCIAL_BLOCK) and "p-feed-1" in social
    assert sorted(observation.evidence_ids) == sorted(SCOPE["expect"]["included"])
    for item_id in SCOPE["expect"]["included"]:
        assert item_id in financial
    for item_id in SCOPE["expect"]["excluded"]:
        assert item_id not in prompt
    (intent,) = queue.drain()
    assert intent.obs_hash == observation.obs_hash == agent.observation.obs_hash
    # The same world, or the same world plus every excluded item, gives the same hash.
    included = [i for i in SCOPE["world_items"] if i["id"] in SCOPE["expect"]["included"]]
    again = build_observation(ACTORS["borrower-c"], included, round_, SCOPE["sim_time_h"])
    assert again.obs_hash == observation.obs_hash


def test_a_turn_needs_its_own_observation_first():
    queue = IntentQueue("shock")
    plan = idle_plan()
    agent = borrower_c(queue, plan.model("borrower-c", lambda: 4))
    with pytest.raises(RuntimeError, match="before it was given its observation"):
        asyncio.run(agent.perform_action_by_llm())
    with pytest.raises(ValueError, match="given to borrower-c"):
        agent.observe(build_observation(ACTORS["treasury"], [], 4, 16))
    assert len(queue) == 0


# ------------------------------------------------------- every dispatch boundary is extended


@pytest.mark.parametrize("actor_id", sorted(a for a, s in ACTORS.items() if s["llm"]))
def test_each_agent_offers_exactly_its_mandate_and_the_set_is_sealed(actor_id):
    spec = ACTORS[actor_id]
    plan = idle_plan()
    agent = build_finance_agent(spec, 0, IntentQueue("b"), model=plan.model(actor_id, lambda: 1))
    assert isinstance(agent, FinanceAgent)
    assert sorted(agent.tool_dict) == sorted(spec["tools"])
    assert "purchase_product" not in agent.tool_dict
    asyncio.run(one_turn(agent, build_observation(spec, [], 1, 4)))
    assert sorted(plan.calls[0].tools) == sorted(spec["tools"])
    with pytest.raises(RuntimeError, match="before it was given its observation"):
        asyncio.run(agent.perform_action_by_llm())  # one observation, one turn

    with pytest.raises(SealedToolset):
        agent.add_tool(lambda: None)
    with pytest.raises(SealedToolset):
        agent.add_tools([lambda: None])
    with pytest.raises(SealedToolset):
        agent.add_external_tool({"type": "function", "function": {"name": "wire_money"}})
    with pytest.raises(SealedToolset):
        agent.remove_tool("no_action")
    with pytest.raises(SealedToolset):
        agent.remove_external_tool("no_action")
    with pytest.raises(NotImplementedError):
        agent.clone()
    assert sorted(agent.tool_dict) == sorted(spec["tools"])

    # What the model is offered is fixed at construction, not read from a mutable list.
    agent.action_tools.append(agent.tool_dict["no_action"])
    asyncio.run(one_turn(agent, build_observation(spec, [], 2, 8)))
    assert sorted(plan.calls[-1].tools) == sorted(spec["tools"])


def test_a_finance_agent_is_never_offered_a_purchase():
    spec = {**ACTORS["feed"], "tools": ["create_post", "purchase_product", "no_action"]}
    with pytest.raises(ValueError, match="purchase_product"):
        build_finance_agent(spec, 0, IntentQueue("b"), model=ListModel("feed", 1, []))


def test_an_agent_without_a_model_is_refused():
    with pytest.raises(ValueError, match="needs its model"):
        build_finance_agent(ACTORS["feed"], 0, IntentQueue("b"))


def test_acting_by_data_runs_only_the_social_subset(tmp_path):
    queue = IntentQueue("shock")
    feed = build_finance_agent(ACTORS["feed"], 0, queue, model=ListModel("feed", 1, []))
    for name in ("purchase_product", "pay", ActionType.LIKE_POST):
        with pytest.raises(ValueError, match="social tools"):
            asyncio.run(feed.perform_action_by_data(name, post_id=1))
    asyncio.run(on_platform([feed], {feed: ManualAction(
        action_type=ActionType.CREATE_POST, action_args={"content": "scheduled news"})},
        tmp_path))
    assert rows(tmp_path / "oasis.db", "select content from post") == [("scheduled news",)]
    assert len(queue) == 0
    with pytest.raises(NotImplementedError):
        asyncio.run(feed.perform_action_by_hci())


def test_a_social_schema_with_a_list_type_refuses_instead_of_raising():
    schema = {"function": {"name": "note", "parameters": {
        "properties": {"text": {"type": ["string", "null"]}}, "required": ["text"]}}}
    refused = parse_social_call(RawCall("note", {"text": 3}), schema)
    assert refused.code == "malformed_tool_args" and "note.text" in refused.detail
    assert parse_social_call(RawCall("note", {"text": None}), schema).arguments == {"text": None}


def test_a_response_of_social_calls_only_still_queues_no_action():
    queue = IntentQueue("shock")
    model = ListModel("feed", 3, [[{"name": "create_post", "args": {"content": "news"}}]])
    feed = build_finance_agent(ACTORS["feed"], 0, queue, model=model)
    observation = build_observation(ACTORS["feed"], [], 3, 12)
    posted = []  # no platform in this case: the post lands in a list

    async def create_post(content):
        posted.append(content)
        return {"success": True, "post_id": 7}

    feed._social_tools["create_post"].func = create_post
    result = asyncio.run(one_turn(feed, observation))
    (intent,) = queue.drain()
    assert (intent.type, intent.obs_hash) == ("no_action", observation.obs_hash)
    assert result.alert is None and posted == ["news"]


def test_a_tool_outside_the_offer_is_refused_naming_every_offered_tool():
    queue = IntentQueue("shock")
    model = ListModel("feed", 3, [[{"name": "like_post", "args": {"post_id": 1}}],
                                  [{"name": "no_action", "args": {}}]])
    feed = build_finance_agent(ACTORS["feed"], 0, queue, model=model)
    result = asyncio.run(one_turn(feed, build_observation(ACTORS["feed"], [], 3, 12)))
    repair = model.calls[1].messages[-1]["content"]
    assert "'like_post' is not one of your tools ['create_post', 'no_action']" in repair
    assert "amount_minor" not in repair  # no money hint when no money call was refused
    assert result.alert is None and [i.type for i in queue.drain()] == ["no_action"]


def test_an_integral_float_is_not_an_integer_argument():
    schema = {"function": {"name": "like_post", "parameters": {
        "properties": {"post_id": {"type": "integer"}}, "required": ["post_id"]}}}
    refused = parse_social_call(RawCall("like_post", {"post_id": 1.0}), schema)
    assert refused.code == "malformed_tool_args" and "like_post.post_id" in refused.detail
    assert parse_social_call(RawCall("like_post", '{"post_id": 1}'), schema).arguments == {
        "post_id": 1}


def test_a_turn_is_remembered_under_the_agents_id_and_recorded_before_its_posts_run():
    queue = IntentQueue("shock")
    model = ListModel("feed", 3, [[{"name": "create_post", "args": {"content": "news"}}]])
    feed = build_finance_agent(ACTORS["feed"], 0, queue, model=model)

    async def broken(content):
        raise ConnectionError("platform gone")

    feed._social_tools["create_post"].func = broken
    with pytest.raises(ConnectionError):
        asyncio.run(one_turn(feed, build_observation(ACTORS["feed"], [], 3, 12)))
    assert feed.last_turn is not None and feed.last_turn.social[0].name == "create_post"
    assert feed.last_social_results == ()

    feed2 = build_finance_agent(ACTORS["feed"], 1, IntentQueue("shock"), model=ListModel(
        "feed", 3, [[{"name": "no_action", "args": {}}]]))
    asyncio.run(one_turn(feed2, build_observation(ACTORS["feed"], [], 3, 12)))
    written = [r for r in feed2.memory.retrieve() if r.memory_record.message.content
               and "queued" in r.memory_record.message.content]
    assert written and all(r.memory_record.agent_id == feed2.agent_id for r in written)

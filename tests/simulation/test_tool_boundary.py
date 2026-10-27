"""The finance tool boundary: a tool only queues one C1 intent on its branch's queue, an actor
sees only its scope, and a malformed response gets one repair, then ``no_action`` and an alert.

Fixtures are read unchanged from the agent-world design: observation-scope.json,
malformed-output.json, actors.json and coupled-chain.json. Clearing the queued intents against
the ledger (C2) is the coordinator's and is tested there.
"""

from __future__ import annotations

import asyncio
import json
import threading
import types
from pathlib import Path
from typing import get_args

import pytest
from app.finance.schemas import ActionIntent, Amount, IntentParams, IntentType
from app.testing.scripted_model import PLANS_DIR, ScriptedPlan
from oasis_finance import (
    FinanceActor,
    FinancialActionType,
    IntentQueue,
    RawCall,
    ToolCallError,
    Turn,
    amodel_responder,
    arun_turn,
    build_observation,
    canonical_json,
    make_finance_tools,
    model_responder,
    parse_tool_call,
    repair_marker,
    run_turn,
    sha256_of,
    tool_schema,
)
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"
ACTORS = {a["actor_id"]: a for a in json.loads((FIXTURES / "actors.json").read_text())["actors"]}
SCOPE = json.loads((FIXTURES / "observation-scope.json").read_text())
MALFORMED = json.loads((FIXTURES / "malformed-output.json").read_text())
COUPLED = json.loads((FIXTURES / "coupled-chain.json").read_text())
HASH = "0" * 64

# One valid call per finance tool.
VALID = {
    "request_advance": {"amount_minor": 1200000, "currency": "USD", "from": "lender"},
    "offer": {"amount_minor": 1000000, "currency": "USD", "to": "borrower-a", "fee_bps": 800},
    "accept": {"request": "req:borrower-c:r4"},
    "disburse": {"request": "req:borrower-c:r4", "amount_minor": 1200000, "currency": "USD",
                 "from_account": "lender/operating"},
    "repay": {"amount_minor": 360000, "currency": "USD", "to": "lender", "facility_id": "adv-a"},
    "convert": {"amount_minor": 500000, "currency": "USD", "to_currency": "EUR"},
    "pay": {"amount_minor": 1000000, "currency": "USD", "to": "supplier-1"},
    "pledge": {"amount_minor": 500000, "currency": "USD", "to": "lender"},
    "release": {"target": "offer:lender:borrower-c"},
    "defer": {"obligation_id": "withdrawal-1"},
    "no_action": {},
}


def actor_with_all_tools(branch="shock", actor_id="tester", priority=1):
    actor = FinanceActor(actor_id, branch, tuple(FinancialActionType), priority)
    actor.begin_turn(Turn(round=4, sim_minute=960, obs_hash=HASH, evidence_ids=("p-r3-1",)))
    return actor


def scope_observation(items=None, actor_id="borrower-c"):
    return build_observation(actor_id, ACTORS[actor_id]["sees"], SCOPE["round"],
                             SCOPE["sim_time_h"], SCOPE["world_items"] if items is None else items)


# ------------------------------------------------------------------------- tools and handler


def test_action_type_is_the_c1_intent_type():
    assert [a.value for a in FinancialActionType] == list(get_args(IntentType))
    assert set(VALID) == {a.value for a in FinancialActionType}


def test_every_tool_call_queues_exactly_one_c1_intent():
    queue = IntentQueue("shock")
    actor = actor_with_all_tools()
    tools = make_finance_tools(queue, actor)
    assert set(tools) == set(VALID)
    for n, (name, args) in enumerate(VALID.items(), 1):
        assert tools[name](**args) == f"queued i-r4-tester-{n}"
        assert len(queue) == n
    intents = queue.drain()
    assert [i.type for i in sorted(intents, key=lambda i: int(i.intent_id.rsplit("-", 1)[1]))] \
        == list(VALID)
    for intent in intents:
        # Each is a valid C1 document, stamped with the turn it was proposed in.
        assert ActionIntent.model_validate(json.loads(intent.model_dump_json())) == intent
        assert (intent.branch_id, intent.round, intent.actor_id) == ("shock", 4, "tester")
        assert (intent.obs_hash, intent.evidence_ids) == (HASH, ["p-r3-1"])
        assert (intent.priority_class, intent.sim_minute) == (1, 960)
        if intent.params.amount is not None:
            assert type(intent.params.amount.minor) is int
    assert len(queue) == 0


@pytest.mark.parametrize("name,args", [
    ("pay", {"amount_minor": 1000000.0, "currency": "USD", "to": "supplier-1"}),
    ("pay", {"amount_minor": "1000000", "currency": "USD", "to": "supplier-1"}),
    ("pay", {"amount_minor": True, "currency": "USD", "to": "supplier-1"}),
    ("pay", {"amount_minor": 0, "currency": "USD", "to": "supplier-1"}),
    ("pay", {"amount_minor": 1000000, "currency": "XYZ", "to": "supplier-1"}),
    ("request_advance", {"amount": 12000, "currency": "USD", "from": "lender"}),
])
def test_a_refused_tool_call_queues_nothing(name, args):
    queue = IntentQueue("shock")
    reply = make_finance_tools(queue, actor_with_all_tools())[name](**args)
    assert reply.startswith("rejected malformed_tool_args")
    assert len(queue) == 0


def _reachable(root):
    """Every object reachable from a tool: its closure cells and what they hold, recursively."""
    seen, stack, found = set(), [root], []
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        found.append(obj)
        if isinstance(obj, types.FunctionType):
            stack += [c.cell_contents for c in obj.__closure__ or ()]
            stack += [obj.__defaults__ or (), obj.__kwdefaults__ or {}]
        elif isinstance(obj, dict):
            stack += list(obj.keys()) + list(obj.values())
        elif isinstance(obj, list | tuple | set | frozenset):
            stack += list(obj)
        elif isinstance(obj, IntentQueue | FinanceActor | Turn | BaseModel):
            stack.append(vars(obj))
            stack.append(getattr(obj, "__pydantic_extra__", None) or {})
    return found


def test_no_ledger_handle_exists_in_any_tool_closure():
    queue = IntentQueue("shock")
    actor = actor_with_all_tools()
    tools = make_finance_tools(queue, actor)
    tools["pay"](**VALID["pay"])  # a queued intent is reachable too, and holds no handle
    allowed = (IntentQueue, FinanceActor, Turn, ActionIntent, IntentParams, Amount,
               FinancialActionType,
               types.FunctionType, str, int, dict, list, tuple, set, frozenset, type(None),
               type(threading.Lock()))
    for name, tool in tools.items():
        reachable = _reachable(tool)
        stray = [type(o).__name__ for o in reachable if not isinstance(o, allowed)]
        assert stray == [], f"{name} reaches {stray}"
        assert not [o for o in reachable if isinstance(o, str) and "ledger" in o.lower()]
        cells = {type(c.cell_contents) for c in tool.__closure__}
        assert cells == {IntentQueue, FinanceActor, FinancialActionType}, name


def test_tools_are_bound_to_their_branch_queue():
    shock, control = IntentQueue("shock"), IntentQueue("control")
    in_shock, in_control = actor_with_all_tools("shock"), actor_with_all_tools("control")
    make_finance_tools(shock, in_shock)["pay"](**VALID["pay"])
    make_finance_tools(control, in_control)["no_action"]()
    assert [i.branch_id for i in shock.drain()] == ["shock"]
    assert [i.branch_id for i in control.drain()] == ["control"]
    with pytest.raises(ValueError, match="bound to the queue"):
        make_finance_tools(control, in_shock)
    with pytest.raises(ValueError, match="offered to the queue"):
        control.put(ActionIntent(intent_id="i-r4-x-1", branch_id="shock", round=4, actor_id="x",
                                 type="no_action", params={}, evidence_ids=[], obs_hash=HASH,
                                 priority_class=1, sim_minute=960))


def test_a_tool_outside_a_turn_is_refused():
    actor = FinanceActor("tester", "shock", (FinancialActionType.NO_ACTION,), 1)
    with pytest.raises(RuntimeError, match="outside a turn"):
        make_finance_tools(IntentQueue("shock"), actor)["no_action"]()


@pytest.mark.parametrize("actor_id", sorted(ACTORS))
def test_each_actor_is_offered_exactly_its_finance_mandate(actor_id):
    """Closes the tool-set bypasses (oasis-seam.md S3, S4, S8) at the finance boundary."""
    spec = ACTORS[actor_id]
    actor = FinanceActor.from_spec(spec, "shock")
    mandate = {t for t in spec["tools"] if t in {a.value for a in FinancialActionType}}
    tools = make_finance_tools(IntentQueue("shock"), actor)
    assert set(tools) == mandate
    assert {tool_schema(a)["function"]["name"] for a in actor.tools} == mandate
    assert "purchase_product" not in tools and "create_post" not in tools
    assert actor.priority_class == spec["priority_class"]
    outside = sorted({a.value for a in FinancialActionType} - mandate) + ["purchase_product"]
    for name in outside:
        refused = parse_tool_call(name, VALID.get(name, {}), actor.tools)
        assert isinstance(refused, ToolCallError) and refused.code == "tool_not_in_mandate"


def test_drain_order_does_not_depend_on_arrival_order():
    """clearing-order.json's arrival orders, through the queue; the clearing is the coordinator's."""
    fixture = json.loads((FIXTURES / "clearing-order.json").read_text())
    intents = {
        raw["intent_id"]: ActionIntent(branch_id="base", round=0, evidence_ids=[], obs_hash=HASH,
                                       **raw)
        for raw in fixture["intents"]
    }
    for arrival in fixture["arrival_orders"] + [list(reversed(fixture["arrival_orders"][0]))]:
        queue = IntentQueue("base")
        for intent_id in arrival:
            queue.put(intents[intent_id])
        assert [i.intent_id for i in queue.drain()] == fixture["expect"]["cleared_order"]


# -------------------------------------------------------------------------------- observation


def test_observation_scope_matches_the_fixture():
    observation = scope_observation()
    expect = SCOPE["expect"]
    assert sorted(observation.evidence_ids) == sorted(expect["included"])
    assert not set(observation.evidence_ids) & set(expect["excluded"])
    assert [i["id"] for i in observation.body["items"]] == list(observation.evidence_ids)
    assert (observation.body["actor_id"], observation.body["round"],
            observation.body["t_hours"]) == ("borrower-c", 4, 16)
    for item_id in expect["excluded"]:
        assert item_id not in canonical_json(observation.body)


def test_obs_hash_is_stable_and_excluded_items_change_nothing():
    observation = scope_observation()
    assert observation.obs_hash == scope_observation().obs_hash
    assert observation.obs_hash == sha256_of(observation.body)
    included = [i for i in SCOPE["world_items"] if i["id"] in SCOPE["expect"]["included"]]
    assert scope_observation(included).obs_hash == observation.obs_hash
    shuffled = list(reversed(SCOPE["world_items"]))
    assert scope_observation(shuffled).obs_hash == observation.obs_hash
    # Anything the actor may see does change the hash.
    extra = {"id": "p-r4-1", "kind": "public_post", "owner": "feed", "visible_from_h": 16}
    assert scope_observation(SCOPE["world_items"] + [extra]).obs_hash != observation.obs_hash


def test_ownership_is_read_from_the_item_not_its_label():
    spoof = [
        {"id": "acct:treasury/x", "kind": "own_account", "owner": "treasury", "visible_from_h": 0},
        {"id": "contract:x", "kind": "own_contract", "owner": "lender", "visible_from_h": 0},
        {"id": "mem:treasury-1", "kind": "memory", "owner": "treasury", "visible_from_h": 0},
        {"id": "weird", "kind": "rumour_mill", "visible_from_h": 0},
        {"id": "no-time", "kind": "public_post"},
        {"id": "contract:shared", "kind": "contract", "owner": "lender",
         "parties": ["lender", "borrower-c"], "visible_from_h": 0},
    ]
    assert scope_observation(spoof).evidence_ids == ("contract:shared",)
    # The feed's scope has no accounts at all, even its own.
    own = [{"id": "acct:feed", "kind": "account", "owner": "feed", "visible_from_h": 0}]
    assert scope_observation(own, actor_id="feed").evidence_ids == ()


def test_an_observation_refuses_a_float():
    price = {"id": "price:USDC-USD@16h", "kind": "public_price", "visible_from_h": 16,
             "price": 0.97}
    with pytest.raises(TypeError, match="float"):
        scope_observation([price])
    price["price"] = "0.97"
    assert scope_observation([price]).evidence_ids == ("price:USDC-USD@16h",)


# ---------------------------------------------------------------- one repair, then no_action


def _plan_for(case, actor_id, rnd):
    return ScriptedPlan([
        {"actor_id": actor_id, "round": rnd, "tool_calls": [case["first"]]},
        {"actor_id": actor_id, "round": rnd, "when_seen": [repair_marker(actor_id, rnd)],
         "tool_calls": [case["repair"]]},
    ], source=f"malformed-output.json#{case['id']}")


class _ListResponder:
    """For a tool the agent never offers: ScriptedModel itself refuses to answer with one."""

    def __init__(self, *responses):
        self.responses, self.prompts = list(responses), []

    def __call__(self, messages, tools):
        self.prompts.append(messages)
        call = self.responses.pop(0)
        return [RawCall(call["name"], json.dumps(call["args"]), f"c{len(self.prompts)}")]


@pytest.mark.parametrize("case", MALFORMED["cases"], ids=lambda c: c["id"])
def test_malformed_output_gets_one_repair_then_no_action(case):
    actor_id, rnd = "borrower-c", 4
    queue = IntentQueue("shock")
    actor = FinanceActor.from_spec(ACTORS[actor_id], "shock")
    observation = scope_observation()
    offered = {a.value for a in actor.tools}
    if case["first"]["name"] in offered:
        plan = _plan_for(case, actor_id, rnd)
        respond = model_responder(plan.model(actor_id, lambda: rnd))
        prompts = None
    else:
        respond = prompts = _ListResponder(case["first"], case["repair"])

    result = run_turn(respond, queue, actor, observation)  # never raises: the round goes on

    expect = case["expect"]
    calls = plan.calls if prompts is None else prompts.prompts
    assert len(calls) == 1 + MALFORMED["expect_all"]["max_repair_attempts"]
    assert result.repair_attempts == expect["repair_attempts"]
    queued = queue.drain()
    assert queued == list(result.intents) and len(queued) == 1
    intent = queued[0]
    assert intent.type == expect["intent_type"]
    assert intent.intent_id == f"i-r{rnd}-{actor_id}-1"
    assert intent.obs_hash == observation.obs_hash
    assert (result.alert is not None) == expect["alert"]
    if expect["alert"]:
        assert result.alert.reason == expect["alert_reason"]
        assert intent.params.amount is None
    if "posted_amount_minor" in expect:
        assert type(intent.params.amount.minor) is int
        assert intent.params.amount.minor == expect["posted_amount_minor"]
    # The repair prompt names the schema error of the first response.
    repair_prompt = (calls[1].messages if prompts is None else calls[1])[-1]["content"]
    first = parse_tool_call(case["first"]["name"], case["first"]["args"], actor.tools)
    assert repair_marker(actor_id, rnd) in repair_prompt
    assert first.detail in repair_prompt


def test_a_response_without_a_tool_call_is_repaired_too():
    actor = FinanceActor.from_spec(ACTORS["treasury"], "shock")
    queue = IntentQueue("shock")
    observation = build_observation("treasury", ACTORS["treasury"]["sees"], 4, 16, [])
    result = run_turn(lambda messages, tools: [], queue, actor, observation)
    assert result.repair_attempts == 1
    assert result.alert.reason == "no_tool_call"
    assert [i.type for i in queue.drain()] == ["no_action"]


def test_a_response_is_taken_whole_or_not_at_all():
    """One bad call in a response queues none of its calls; the repair answers for all."""
    actor = FinanceActor.from_spec(ACTORS["treasury"], "shock")
    queue = IntentQueue("shock")
    good = RawCall("pay", json.dumps(VALID["pay"]))
    bad = RawCall("pay", json.dumps({**VALID["pay"], "amount_minor": 10.5}))
    responses = iter([[good, bad], [good, good]])
    observation = build_observation("treasury", ACTORS["treasury"]["sees"], 4, 16, [])
    result = run_turn(lambda m, t: next(responses), queue, actor, observation)
    assert (result.repair_attempts, result.alert) == (1, None)
    assert [i.intent_id for i in queue.drain()] == ["i-r4-treasury-1", "i-r4-treasury-2"]


# ------------------------------------------------- the coupled chain through the boundary


def _chain_turns(branch):
    plan = ScriptedPlan.load(PLANS_DIR / "coupled-chain.json")
    queue = IntentQueue(branch)
    posts = [{"id": "p-r3-1", "kind": "public_post", "owner": "feed", "visible_from_h": 12,
              "text": COUPLED["scheduled_events"][0]["text"]}] if branch == "shock" else []
    results = {}
    for actor_id, rnd in [("borrower-c", 4), ("lender", 5)]:
        items = list(posts)
        if actor_id == "lender" and results["borrower-c"].intents[0].type == "request_advance":
            items.append({"id": "req:borrower-c:r4", "kind": "message", "to": "lender",
                          "visible_from_h": 16, "intent_id": "i-r4-borrower-c-1"})
        observation = build_observation(actor_id, ACTORS[actor_id]["sees"], rnd, rnd * 4, items)
        actor = FinanceActor.from_spec(ACTORS[actor_id], branch)
        model = plan.model(actor_id, lambda rnd=rnd: rnd)
        results[actor_id] = run_turn(model_responder(model), queue, actor, observation)
        assert results[actor_id].alert is None
    return results, queue


def test_the_coupled_chain_plan_crosses_the_boundary_as_intents():
    shock, _ = _chain_turns("shock")
    expect = COUPLED["expect"]["shock"]
    (request,) = shock["borrower-c"].intents
    assert (request.intent_id, request.type) == (expect["round_4"]["intent"],
                                                 expect["round_4"]["type"])
    assert request.evidence_ids == expect["round_4"]["evidence_ids"]
    assert request.params.amount.minor == 1200000
    lender = shock["lender"].intents
    assert [i.intent_id for i in lender] == expect["round_5"]["intents"]
    assert [i.type for i in lender] == ["accept", "disburse"]
    # Evidence is the whole scoped observation; the lender also sees the public rumour.
    assert all(set(expect["round_5"]["evidence_ids"]) <= set(i.evidence_ids) for i in lender)

    control, _ = _chain_turns("control")
    assert [i.type for i in control["borrower-c"].intents] == ["no_action"]
    assert [i.type for i in control["lender"].intents] == ["no_action"]


def test_concurrent_async_turns_drain_in_one_order():
    plan = ScriptedPlan([{"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}])
    actors = ["treasury", "lender", "borrower-b", "borrower-c", "venue", "feed"]

    async def round_of(order):
        queue = IntentQueue("shock")
        turns = []
        for actor_id in order:
            actor = FinanceActor.from_spec(ACTORS[actor_id], "shock")
            observation = build_observation(actor_id, ACTORS[actor_id]["sees"], 2, 8, [])
            respond = amodel_responder(plan.model(actor_id, lambda: 2))
            turns.append(arun_turn(respond, queue, actor, observation))
        await asyncio.gather(*turns)
        return [(i.priority_class, i.actor_id) for i in queue.drain()]

    first = asyncio.run(round_of(actors))
    assert first == asyncio.run(round_of(list(reversed(actors))))
    assert first == sorted((ACTORS[a]["priority_class"], a) for a in actors)

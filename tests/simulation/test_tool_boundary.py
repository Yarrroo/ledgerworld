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
    submit,
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


def actor_with_all_tools(branch="shock"):
    actor = FinanceActor("tester", branch, tuple(FinancialActionType), 1)
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
    assert {i.intent_id: i.type for i in intents} == {
        f"i-r4-tester-{n}": name for n, name in enumerate(VALID, 1)}
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
    assert (observation.body["actor_id"], observation.body["round"], observation.body["t"]) \
        == ("borrower-c", 4, "2026-01-01T16:00:00Z")
    assert (observation.round, observation.t_hours) == (4, 16)
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


def test_obs_hash_matches_the_reference_model():
    """The stdlib oracle (refmodel/tools_ref.py) pins this hash for the fixture."""
    pinned = "c8430aaeae01473fc5aacc9915b72fa40af720189ebcb8db5dd3236b4bcbb1f0"
    assert scope_observation().obs_hash == pinned
    assert scope_observation().body["items"][0]["visible_from"] == "2026-01-01T00:00:00Z"


def test_a_due_scheduled_event_is_seen_by_whom_it_concerns():
    events = [
        {"id": "sched:rumour@8h", "kind": "scheduled_event", "visible_from_h": 8},
        {"id": "sched:to-c@8h", "kind": "scheduled_event", "to": "borrower-c",
         "visible_from_h": 8},
        {"id": "sched:to-treasury@8h", "kind": "scheduled_event", "to": "treasury",
         "visible_from_h": 8},
        {"id": "post:to-treasury", "kind": "public_post", "to": "treasury", "visible_from_h": 8},
    ]
    assert scope_observation(events).evidence_ids == ("sched:rumour@8h", "sched:to-c@8h")
    treasury = build_observation("treasury", ACTORS["treasury"]["sees"], 4, 16, events)
    # An addressed post enters through no scope: a post is public or it is a message.
    assert treasury.evidence_ids == ("sched:rumour@8h", "sched:to-treasury@8h")


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


class _ListResponder:
    """For a tool the agent never offers: ScriptedModel itself refuses to answer with one."""

    def __init__(self, *responses):
        self.responses = list(responses)

    def __call__(self, messages, tools):
        call = self.responses.pop(0)
        return [RawCall(call["name"], json.dumps(call["args"]))]


@pytest.mark.parametrize("case", MALFORMED["cases"], ids=lambda c: c["id"])
def test_malformed_output_gets_one_repair_then_no_action(case):
    actor_id, rnd = "borrower-c", 4
    queue = IntentQueue("shock")
    actor = FinanceActor.from_spec(ACTORS[actor_id], "shock")
    observation = scope_observation()
    if case["first"]["name"] in {a.value for a in actor.tools}:
        plan = ScriptedPlan([
            {"actor_id": actor_id, "round": rnd, "tool_calls": [case["first"]]},
            {"actor_id": actor_id, "round": rnd, "when_seen": [repair_marker(actor_id, rnd)],
             "tool_calls": [case["repair"]]},
        ], source=f"malformed-output.json#{case['id']}")
        responder = model_responder(plan.model(actor_id, lambda: rnd))
    else:
        responder = _ListResponder(case["first"], case["repair"])
    prompts = []

    def respond(messages, tools):
        prompts.append(messages)
        return responder(messages, tools)

    result = run_turn(respond, queue, actor, observation)  # never raises: the round goes on

    expect = case["expect"]
    assert len(prompts) == 1 + MALFORMED["expect_all"]["max_repair_attempts"]
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
    repair_prompt = prompts[1][-1]["content"]
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
    return results


def test_the_coupled_chain_plan_crosses_the_boundary_as_intents():
    shock = _chain_turns("shock")
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

    control = _chain_turns("control")
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


# ------------------------------------------------------------------- vet round 1 regressions


def test_an_actors_tenth_intent_clears_after_its_second():
    queue = IntentQueue("shock")
    tools = make_finance_tools(queue, actor_with_all_tools())
    for _ in range(10):
        tools["no_action"]()
    assert [i.intent_id for i in queue.drain()] == [f"i-r4-tester-{n}" for n in range(1, 11)]


def test_a_finished_turn_refuses_late_tool_calls():
    actor = FinanceActor.from_spec(ACTORS["treasury"], "shock")
    queue = IntentQueue("shock")
    tools = make_finance_tools(queue, actor)
    observation = build_observation("treasury", ACTORS["treasury"]["sees"], 4, 16, [])
    run_turn(lambda m, t: [RawCall("no_action", "{}")], queue, actor, observation)
    with pytest.raises(RuntimeError, match="outside a turn"):
        tools["no_action"]()
    assert len(queue) == 1


def test_a_response_that_cannot_be_queued_queues_nothing():
    """The second of three intents collides in the queue: none of the response is queued."""
    actor = FinanceActor.from_spec(ACTORS["treasury"], "shock")
    queue = IntentQueue("shock")
    queue.put(ActionIntent(intent_id="i-r4-treasury-2", branch_id="shock", round=4,
                           actor_id="treasury", type="no_action", params={}, evidence_ids=[],
                           obs_hash=HASH, priority_class=1, sim_minute=960))
    observation = build_observation("treasury", ACTORS["treasury"]["sees"], 4, 16, [])
    with pytest.raises(ValueError, match=r"\['i-r4-treasury-2'\] are queued twice"):
        run_turn(lambda m, t: [RawCall("no_action", "{}")] * 3, queue, actor, observation)
    assert [i.intent_id for i in queue.drain()] == ["i-r4-treasury-2"]


def test_an_actor_id_leaves_room_for_the_intent_id():
    with pytest.raises(ValueError, match="actor id"):
        FinanceActor("a" * 101, "shock", (FinancialActionType.NO_ACTION,), 1)


def test_a_mandate_naming_a_tool_twice_is_refused():
    spec = {**ACTORS["treasury"], "tools": ["pay", "pay", "no_action"]}
    with pytest.raises(ValueError, match="twice"):
        FinanceActor.from_spec(spec, "shock")


def test_a_reason_is_a_string_not_bytes():
    refused = parse_tool_call("no_action", {"reason": b"abc"}, tuple(FinancialActionType))
    assert isinstance(refused, ToolCallError)


def test_an_id_of_another_shape_clears_after_the_standard_ones():
    queue = IntentQueue("shock")
    for intent_id in ["fb", "i-r4-x-10", "i-r4-x-2"]:
        queue.put(ActionIntent(intent_id=intent_id, branch_id="shock", round=4, actor_id="x",
                               type="no_action", params={}, evidence_ids=[], obs_hash=HASH,
                               priority_class=1, sim_minute=960))
    assert [i.intent_id for i in queue.drain()] == ["i-r4-x-2", "i-r4-x-10", "fb"]


def test_social_tools_are_the_pinned_oasis_action_types():
    """SOCIAL_TOOLS is a copy (oasis does not import here): read the enum from its source."""
    import ast
    import importlib.util

    from oasis_finance.actions import SOCIAL_TOOLS

    spec = importlib.util.find_spec("oasis")
    source = Path(spec.origin).parent / "social_platform" / "typing.py"
    enum = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.ClassDef) and n.name == "ActionType")
    values = {n.value.value for n in enum.body
              if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)}
    assert values == SOCIAL_TOOLS


@pytest.mark.parametrize("bad_id", ["", "x" * 129, 7], ids=["empty", "long", "int"])
def test_an_observation_refuses_an_id_no_intent_can_cite(bad_id):
    item = {"id": bad_id, "kind": "public_post", "visible_from_h": 0}
    with pytest.raises(ValueError, match="evidence id"):
        scope_observation([item])


def test_each_tool_carries_its_schema_for_camel():
    """camel's FunctionTool cannot read a schema off **kwargs; the tool hands it over."""
    tools = make_finance_tools(IntentQueue("shock"), actor_with_all_tools())
    for action in FinancialActionType:
        assert tools[action.value].openai_tool_schema == tool_schema(action)


class _SwitchTurnOnLock:
    """A lock that starts round 5 the first time it is taken: a begin_turn racing a tool."""

    def __init__(self, actor):
        self.actor, self.fired = actor, False

    def __enter__(self):
        if not self.fired:
            self.fired = True
            self.actor.turn, self.actor._n = Turn(5, 1200, "1" * 64, ("p-r5-1",)), 0
        return self

    def __exit__(self, *exc):
        return False


def test_an_intent_is_stamped_from_one_turn():
    actor = actor_with_all_tools()
    actor._lock = _SwitchTurnOnLock(actor)
    queue = IntentQueue("shock")
    make_finance_tools(queue, actor)["no_action"]()
    (intent,) = queue.drain()
    assert intent.intent_id == f"i-r{intent.round}-tester-1"
    assert (intent.round, intent.obs_hash) == (5, "1" * 64)


def test_parties_must_be_a_list_and_a_strange_kind_is_unseen():
    items = [
        {"id": "c:string-parties", "kind": "contract", "owner": "lender",
         "parties": "lender,borrower-cc", "visible_from_h": 0},
        {"id": "c:list-kind", "kind": ["account"], "owner": "borrower-c", "visible_from_h": 0},
    ]
    assert scope_observation(items).evidence_ids == ()


@pytest.mark.parametrize("arguments", [
    '{"amount_minor": ' + "1" * 5000 + ', "currency": "USD", "to": "supplier-1"}',
    "[" * 100000 + "]" * 100000,
], ids=["huge-int", "deep-nesting"])
def test_unparseable_arguments_fall_back_instead_of_raising(arguments):
    actor = FinanceActor.from_spec(ACTORS["treasury"], "shock")
    queue = IntentQueue("shock")
    observation = build_observation("treasury", ACTORS["treasury"]["sees"], 4, 16, [])
    result = run_turn(lambda m, t: [RawCall("pay", arguments)], queue, actor, observation)
    assert result.alert.reason == "malformed_tool_args"
    assert [i.type for i in queue.drain()] == ["no_action"]


def test_a_conversion_goes_into_another_currency():
    refused = parse_tool_call("convert", {"amount_minor": 500000, "currency": "USD",
                                          "to_currency": "USD"}, tuple(FinancialActionType))
    assert isinstance(refused, ToolCallError) and refused.code == "malformed_tool_args"


def test_submit_refuses_an_act_outside_the_mandate_whoever_calls_it():
    actor = FinanceActor.from_spec(ACTORS["borrower-c"], "shock")
    actor.begin_turn(Turn(4, 960, HASH, ()))
    queue = IntentQueue("shock")
    disburse = parse_tool_call("disburse", VALID["disburse"], tuple(FinancialActionType))
    with pytest.raises(ValueError, match="mandate"):
        submit(queue, actor, [(FinancialActionType.DISBURSE, disburse)])
    assert len(queue) == 0


def test_a_mandate_naming_an_unknown_tool_is_refused():
    spec = {**ACTORS["treasury"], "tools": ["pay", "reapy", "no_action"]}
    with pytest.raises(ValueError, match="reapy"):
        FinanceActor.from_spec(spec, "shock")

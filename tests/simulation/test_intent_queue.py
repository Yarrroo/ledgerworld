"""The intent queue drains in one order; an observation shows an actor only its scope (§7.1–7.2).

Both are reached the way the simulation reaches them, through `app.simulation`. Fixtures load
unchanged from design/modules/agent-world/fixtures: `clearing-order.json` (three arrival orders,
one cleared order), `observation-scope.json` (borrower-c at t=16 h) and `actors.json`.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from app.finance.schemas import ActionIntent
from app.simulation.actions import IntentQueue
from app.simulation.observations import Observation, build_observation
from oasis_finance import sha256_of

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


CLEARING = load("clearing-order")
SCOPE = load("observation-scope")
ACTOR = next(a for a in load("actors")["actors"] if a["actor_id"] == SCOPE["actor_id"])
# The value refmodel/test_tools_ref.py pins for the same fixture: the product matches the oracle.
PINNED_OBS_HASH = "c8430aaeae01473fc5aacc9915b72fa40af720189ebcb8db5dd3236b4bcbb1f0"
BRANCH = "main"


def c1(raw: dict, **extra) -> ActionIntent:
    """A fixture intent completed into a full C1 (the fields clearing does not read)."""
    return ActionIntent.model_validate(
        {"branch_id": BRANCH, "round": 0, "evidence_ids": [], "obs_hash": "0" * 64, **raw, **extra})


def intent(actor_id: str, n: int, *, priority_class: int = 2, sim_minute: int = 0) -> ActionIntent:
    return c1({"intent_id": f"i-r0-{actor_id}-{n}", "actor_id": actor_id, "type": "no_action",
               "params": {}, "priority_class": priority_class, "sim_minute": sim_minute})


def call_index(i: ActionIntent) -> int:
    return int(i.intent_id.rsplit("-", 1)[1])


# ------------------------------------------------------------------------------- intent queue


@pytest.mark.parametrize("arrival", CLEARING["arrival_orders"])
def test_three_arrival_orders_drain_to_one_order(arrival):
    by_id = {i["intent_id"]: i for i in CLEARING["intents"]}
    queue = IntentQueue(BRANCH)
    for intent_id in arrival:
        queue.put(c1(by_id[intent_id]))
    assert [i.intent_id for i in queue.drain()] == CLEARING["expect"]["cleared_order"]
    assert len(queue) == 0 and queue.drain() == []


def test_call_index_sorts_as_an_integer():
    queue = IntentQueue(BRANCH)
    queue.put(*(intent("borrower-b", n) for n in (10, 2, 1)))
    assert [i.intent_id for i in queue.drain()] == [
        "i-r0-borrower-b-1", "i-r0-borrower-b-2", "i-r0-borrower-b-10"]


def test_concurrent_thread_puts_lose_nothing():
    queue, threads, per = IntentQueue(BRANCH), 8, 250
    start = threading.Barrier(threads)

    def worker(t: int) -> None:
        start.wait()
        for n in range(per):
            queue.put(intent(f"actor-{t}", n, priority_class=t % 4, sim_minute=n % 3))

    pool = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for th in pool:
        th.start()
    for th in pool:
        th.join()
    drained = queue.drain()
    assert len({i.intent_id for i in drained}) == len(drained) == threads * per
    keys = [(i.priority_class, i.sim_minute, i.actor_id, call_index(i)) for i in drained]
    assert keys == sorted(keys)


def test_concurrent_task_puts_lose_nothing():
    queue = IntentQueue(BRANCH)

    async def actor(name: str) -> None:
        for n in range(50):
            queue.put(intent(name, n))
            await asyncio.sleep(0)

    async def step() -> None:
        await asyncio.gather(*(actor(f"actor-{k}") for k in range(6)))

    asyncio.run(step())
    assert len(queue) == 300
    assert len(queue.drain()) == 300


def test_put_refuses_an_unorderable_repeated_or_foreign_intent():
    queue = IntentQueue(BRANCH)
    with pytest.raises(ValueError, match="priority class"):
        queue.put(c1({"intent_id": "i-r0-x-1", "actor_id": "x", "type": "no_action", "params": {}}))
    queue.put(intent("x", 1))
    with pytest.raises(ValueError, match="twice"):
        queue.put(intent("x", 1))
    with pytest.raises(ValueError, match="branch"):
        queue.put(c1(intent("y", 1).model_dump(), branch_id="other"))
    assert len(queue) == 1


# ------------------------------------------------------------------------------- observation


def build(items: list[dict]) -> Observation:
    return build_observation(ACTOR, items, SCOPE["round"], SCOPE["sim_time_h"])


def test_observation_scope_included_and_excluded():
    evidence = build(SCOPE["world_items"]).evidence_ids
    expect = SCOPE["expect"]
    assert len(expect["included"]) == 5 and len(expect["excluded"]) == 6
    assert sorted(evidence) == sorted(expect["included"])
    for item_id in expect["excluded"]:
        assert item_id not in evidence, expect["excluded"][item_id]


def test_obs_hash_stable_and_blind_to_excluded_items():
    obs = build(SCOPE["world_items"])
    assert build(list(reversed(SCOPE["world_items"]))).obs_hash == obs.obs_hash
    only_included = [i for i in SCOPE["world_items"] if i["id"] not in SCOPE["expect"]["excluded"]]
    assert build(only_included) == obs
    assert obs.obs_hash == sha256_of(obs.body)
    assert obs.obs_hash == PINNED_OBS_HASH
    assert obs.body["t"] == "2026-01-01T16:00:00Z"


def test_float_in_observation_refused():
    item = {"id": "acct:borrower-c/operating", "kind": "account", "owner": "borrower-c",
            "visible_from_h": 0, "balance_minor": 1.5}
    with pytest.raises(TypeError, match="float"):
        build([item])

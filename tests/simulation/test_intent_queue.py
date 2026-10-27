"""The intent queue drains in one order; an observation shows an actor only its scope (§7.1–7.2).

Fixtures load unchanged from design/modules/agent-world/fixtures: `clearing-order.json` (three
arrival orders, one cleared order), `observation-scope.json` (borrower-c at t=16 h) and
`actors.json` (borrower-c's scope).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path

import pytest
from app.finance.schemas import ActionIntent
from app.simulation.actions import IntentQueue
from app.simulation.observations import build_observation, canonical_json

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


CLEARING = load("clearing-order")
SCOPE = load("observation-scope")
ACTOR = next(a for a in load("actors")["actors"] if a["actor_id"] == SCOPE["actor_id"])
# The value refmodel/test_tools_ref.py pins for the same fixture: the product matches the oracle.
PINNED_OBS_HASH = "c8430aaeae01473fc5aacc9915b72fa40af720189ebcb8db5dd3236b4bcbb1f0"


def c1(raw: dict, **extra) -> dict:
    """A fixture intent completed into a full C1 (the fields clearing does not read)."""
    return {"branch_id": "main", "round": 0, "evidence_ids": [], "obs_hash": "0" * 64, **raw, **extra}


def intent(actor_id: str, n: int, *, priority_class: int = 2, sim_minute: int = 0) -> dict:
    return c1({"intent_id": f"i-r0-{actor_id}-{n}", "actor_id": actor_id, "type": "no_action",
               "params": {}, "priority_class": priority_class, "sim_minute": sim_minute})


# ------------------------------------------------------------------------------- intent queue


@pytest.mark.parametrize("arrival", CLEARING["arrival_orders"])
def test_three_arrival_orders_drain_to_one_order(arrival):
    by_id = {i["intent_id"]: i for i in CLEARING["intents"]}
    queue = IntentQueue()
    for intent_id in arrival:
        queue.put(c1(by_id[intent_id]))
    drained = queue.drain()
    assert [i.intent_id for i in drained] == CLEARING["expect"]["cleared_order"]
    assert all(isinstance(i, ActionIntent) for i in drained)
    assert len(queue) == 0 and queue.drain() == []


def test_call_index_sorts_as_an_integer():
    queue = IntentQueue()
    for n in (10, 2, 1):
        queue.put(intent("borrower-b", n))
    assert [i.intent_id for i in queue.drain()] == [
        "i-r0-borrower-b-1", "i-r0-borrower-b-2", "i-r0-borrower-b-10"]


def test_concurrent_thread_puts_lose_nothing():
    queue, threads, per = IntentQueue(), 8, 250
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
    assert len(drained) == threads * per
    assert len({i.intent_id for i in drained}) == threads * per
    keys = [(i.priority_class, i.sim_minute, i.actor_id, int(i.intent_id.rsplit("-", 1)[1]))
            for i in drained]
    assert keys == sorted(keys)


def test_concurrent_task_puts_lose_nothing():
    queue = IntentQueue()

    async def actor(name: str) -> None:
        for n in range(50):
            queue.put(intent(name, n))
            await asyncio.sleep(0)

    async def step() -> None:
        await asyncio.gather(*(actor(f"actor-{k}") for k in range(6)))

    asyncio.run(step())
    assert len(queue) == 300
    assert len(queue.drain()) == 300


def test_put_refuses_an_unorderable_or_repeated_intent():
    queue = IntentQueue()
    with pytest.raises(ValueError, match="priority_class"):
        queue.put(c1({"intent_id": "i-r0-x-1", "actor_id": "x", "type": "no_action", "params": {}}))
    queue.put(intent("x", 1))
    with pytest.raises(ValueError, match="already queued"):
        queue.put(intent("x", 1))
    assert len(queue) == 1


def test_put_refuses_a_float_amount():
    queue = IntentQueue()
    raw = c1(CLEARING["intents"][0])
    raw["params"] = {**raw["params"], "amount": {"minor": 1500000.0, "currency": "USD"}}
    with pytest.raises(ValueError):
        queue.put(raw)
    assert len(queue) == 0


# ------------------------------------------------------------------------------- observation


def build(items: list[dict]):
    return build_observation(ACTOR, items, SCOPE["round"], SCOPE["sim_time_h"])


def test_observation_scope_included_and_excluded():
    _, _, evidence = build(SCOPE["world_items"])
    expect = SCOPE["expect"]
    assert len(expect["included"]) == 5 and len(expect["excluded"]) == 6
    assert sorted(evidence) == sorted(expect["included"])
    for item_id in expect["excluded"]:
        assert item_id not in evidence, expect["excluded"][item_id]


def test_obs_hash_stable_and_blind_to_excluded_items():
    obs, h, _ = build(SCOPE["world_items"])
    assert build(list(reversed(SCOPE["world_items"])))[1] == h
    only_included = [i for i in SCOPE["world_items"] if i["id"] not in SCOPE["expect"]["excluded"]]
    assert build(only_included)[:2] == (obs, h)
    assert h == hashlib.sha256(canonical_json(obs).encode()).hexdigest() == PINNED_OBS_HASH
    assert obs["t"] == "2026-01-01T16:00:00Z"
    assert all("visible_from_h" not in item for item in obs["items"])


def test_duplicate_world_item_ids_refused():
    item = {"id": "acct:borrower-c/operating", "kind": "account", "owner": "borrower-c"}
    with pytest.raises(ValueError, match="duplicate"):
        build([item, dict(item, balance_minor=2)])


def test_float_in_observation_refused():
    item = {"id": "acct:borrower-c/operating", "kind": "account", "owner": "borrower-c",
            "balance_minor": 1.5}
    with pytest.raises(ValueError, match="float"):
        build([item])


# ------------------------------------------------------------------------- vet round 1 guards


@pytest.mark.parametrize("intent_id", ["i-r0-x-repair", "i-r0-x-2\n", "i-r1-x-2", "i-r0-y-2", "uuid-1"])
def test_put_refuses_an_id_off_the_intent_id_scheme(intent_id):
    # the call index orders same-actor intents, so an id it cannot be read from is refused
    with pytest.raises(ValueError, match="i-r<round>-<actor_id>-<n>"):
        IntentQueue().put(intent("x", 1) | {"intent_id": intent_id})


def test_put_stores_a_copy_the_caller_cannot_reorder():
    queue = IntentQueue()
    first = ActionIntent.model_validate(intent("b", 1, priority_class=2))
    queue.put(first)
    queue.put(intent("a", 1, priority_class=1))
    first.priority_class = 0
    assert [i.actor_id for i in queue.drain()] == ["a", "b"]


@pytest.mark.parametrize("value", [12.5, None, True, "12"])
def test_non_integer_time_point_refused(value):
    item = {"id": "p-1", "kind": "public_post", "owner": "feed", "visible_from_h": value}
    with pytest.raises(ValueError, match="integer hour"):
        build([item])


def test_time_point_colliding_with_its_iso_name_refused():
    item = {"id": "c-1", "kind": "contract", "owner": "borrower-c", "due_h": 40, "due": "z"}
    with pytest.raises(ValueError, match="both due_h and due"):
        build([item])

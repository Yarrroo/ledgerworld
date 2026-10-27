"""The intent queue between the finance tools and the round coordinator (§7.2 steps 5–7).

A finance tool validates its call, builds a C1 `ActionIntent` and `put`s it on its branch's
queue; it never touches the ledger. The coordinator `drain`s the queue once per round and clears
the intents in the order `drain` returns. That order is a function of the intents alone —
`(priority_class, sim_minute, actor_id, n)` with `n` the call's position in the actor's response —
so the agents answering concurrently (`env.step` gathers them) cannot change what clears first.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from typing import Any

from app.finance.schemas import ActionIntent

ClearingKey = tuple[int, int, str, int]


def clearing_key(intent: ActionIntent) -> ClearingKey:
    """The deterministic clearing order of one intent.

    `n` is read from the id `i-r<round>-<actor_id>-<n>` and compared as an integer, so call 10
    sorts after call 2; an id off that scheme is refused, never given a default place.
    """
    match = re.fullmatch(rf"i-r{intent.round}-{re.escape(intent.actor_id)}-(\d+)", intent.intent_id)
    if match is None:
        raise ValueError(f"intent id {intent.intent_id!r} is not i-r<round>-<actor_id>-<n> "
                         f"for round {intent.round}, actor {intent.actor_id}")
    if intent.priority_class is None or intent.sim_minute is None:
        raise ValueError(f"intent {intent.intent_id} needs priority_class and sim_minute")
    return (intent.priority_class, intent.sim_minute, intent.actor_id, int(match.group(1)))


class IntentQueue:
    """Thread- and task-safe; `drain` empties the queue and returns its intents sorted.

    `put` keeps its own validated copy, keyed once: an intent that cannot be ordered is refused,
    as is a second intent with an id already queued this round (it would clear twice).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[ClearingKey, ActionIntent]] = {}

    def put(self, intent: ActionIntent | Mapping[str, Any]) -> ActionIntent:
        if isinstance(intent, ActionIntent):
            intent = intent.model_dump()
        intent = ActionIntent.model_validate(intent)
        key = clearing_key(intent)
        with self._lock:
            if intent.intent_id in self._items:
                raise ValueError(f"intent {intent.intent_id} is already queued")
            self._items[intent.intent_id] = (key, intent)
        return intent

    def drain(self) -> list[ActionIntent]:
        with self._lock:
            items, self._items = self._items, {}
        return [intent for _, intent in sorted(items.values(), key=lambda kv: kv[0])]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

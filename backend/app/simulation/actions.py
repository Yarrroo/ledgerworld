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

# `i-r<round>-<actor_id>-<n>`: n is compared as an integer, so call 10 sorts after call 2.
_CALL_INDEX = re.compile(r"-(\d+)$")


def clearing_key(intent: ActionIntent) -> tuple[int, int, str, int, str]:
    """The deterministic clearing order of one intent; the id string breaks any remaining tie."""
    match = _CALL_INDEX.search(intent.intent_id)
    n = int(match.group(1)) if match else 0
    return (intent.priority_class, intent.sim_minute, intent.actor_id, n, intent.intent_id)


class IntentQueue:
    """Thread- and task-safe; `drain` empties the queue and returns its intents sorted.

    An intent without a priority class or a simulated minute cannot be ordered and is refused at
    `put`, as is a second intent with an id already queued (one call queued twice would clear twice).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, ActionIntent] = {}

    def put(self, intent: ActionIntent | Mapping[str, Any]) -> ActionIntent:
        intent = ActionIntent.model_validate(intent)
        if intent.priority_class is None or intent.sim_minute is None:
            raise ValueError(f"intent {intent.intent_id} needs priority_class and sim_minute")
        with self._lock:
            if intent.intent_id in self._items:
                raise ValueError(f"intent {intent.intent_id} is already queued")
            self._items[intent.intent_id] = intent
        return intent

    def drain(self) -> list[ActionIntent]:
        with self._lock:
            items, self._items = self._items, {}
        return sorted(items.values(), key=clearing_key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

"""What one actor may see at one simulated time, and the hash its intents carry.

An actor sees its own accounts and contracts, messages addressed to it, public posts and public
prices, and its own memory, each only if its scope (``actors.json`` ``sees``) names that class
and the item is visible at or before the current time (system brief §7.1). A scheduled event is
never seen: the scenario delivers it as a post, a message or a balance when it happens. An item
of an unknown kind is never seen. Ownership is read from ``owner`` / ``parties`` / ``to``, never
from a kind label, so an item labelled ``own_account`` but owned by another actor stays hidden.

``obs_hash`` is the sha256 of the observation's canonical JSON: sorted keys, no whitespace,
money as integer minor units, times as ISO-8601 UTC. A float anywhere is refused: give money in
minor units and a price or rate as a decimal string.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# scope class -> the item kinds it admits, and whether the item must be the actor's own.
SCOPES: dict[str, tuple[frozenset[str], str | None]] = {
    "own_accounts": (frozenset({"account", "own_account"}), "owner"),
    "own_contracts": (frozenset({"contract", "own_contract"}), "party"),
    "messages_to_me": (frozenset({"message"}), "to"),
    "public_posts": (frozenset({"public_post"}), None),
    "public_prices": (frozenset({"public_price"}), None),
    "memory": (frozenset({"memory"}), "owner"),
}


def _canonical(value: Any, path: str = "$") -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, float):
        raise TypeError(f"a float at {path} in an observation: money is integer minor units, "
                         "a price or rate a decimal string")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"a naive time at {path} in an observation")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(k): _canonical(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_canonical(v, f"{path}[{i}]") for i, v in enumerate(value)]
    raise ValueError(f"{type(value).__name__} at {path} is not JSON")


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def visible(item: Mapping[str, Any], actor_id: str, sees: Iterable[str], t_hours: int) -> bool:
    """Whether ``actor_id`` with scope ``sees`` may see ``item`` at ``t_hours``."""
    shown_from = item.get("visible_from_h")
    if isinstance(shown_from, bool) or not isinstance(shown_from, int) or shown_from > t_hours:
        return False
    kind = item.get("kind")
    for scope in sees:
        kinds, mine = SCOPES.get(scope, (frozenset(), None))
        if kind not in kinds:
            continue
        if mine is None:
            return True
        if mine == "party":
            if item.get("owner") == actor_id or actor_id in item.get("parties", ()):
                return True
        elif item.get(mine) == actor_id:
            return True
    return False


@dataclass(frozen=True)
class Observation:
    body: dict[str, Any]
    obs_hash: str
    evidence_ids: tuple[str, ...]

    def to_prompt(self) -> str:
        """The financial block, placed before the social feed in the actor's prompt."""
        return ("Your financial observation (only what you may see now; money in integer "
                f"minor units):\n{canonical_json(self.body)}")


def build_observation(
    actor_id: str,
    sees: Iterable[str],
    round: int,
    t_hours: int,
    items: Iterable[Mapping[str, Any]],
) -> Observation:
    """The scope-filtered observation of ``actor_id`` at ``t_hours`` from the world's items.

    Every item carries an ``id``, a ``kind`` and ``visible_from_h``; the evidence ids are the
    included items' ids, sorted, so building twice gives one hash and an excluded item added to
    the world changes nothing.
    """
    sees = tuple(sees)
    shown = sorted((dict(i) for i in items if visible(i, actor_id, sees, t_hours)),
                   key=lambda i: str(i["id"]))
    ids = [str(i["id"]) for i in shown]
    if len(set(ids)) != len(ids):
        raise ValueError(f"item ids repeat in {actor_id}'s observation")
    body = {"actor_id": actor_id, "round": round, "t_hours": t_hours, "items": shown}
    return Observation(_canonical(body), sha256_of(body), tuple(ids))

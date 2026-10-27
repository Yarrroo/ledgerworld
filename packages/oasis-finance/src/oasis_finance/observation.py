"""What one actor may see at one simulated time, and the hash its intents carry.

An actor sees its own accounts and contracts, messages addressed to it, public posts and public
prices, and its own memory, each only if its scope (``actors.json`` ``sees``) names that class
and the item is visible at or before the current time (system brief §7.1). A due scheduled
event addressed to an actor (``to``) is private to it, like a message; an unaddressed one is
public, like a post; an addressed item never enters through a public scope. An item of an unknown
kind is never seen. Ownership is read from ``owner`` / ``parties`` / ``to``, never from a kind
label, so an item labelled ``own_account`` but owned by another actor stays hidden.

``obs_hash`` is the sha256 of the observation's canonical JSON: sorted keys, no whitespace,
UTF-8, money as integer minor units, and times as ISO-8601 UTC from the world's epoch: the
observation's ``t`` and each item's time points (``visible_from_h`` becomes ``visible_from``).
A float anywhere is refused: give money in minor units and a price or rate as a decimal string.
This is the encoding of the reference model (``refmodel/tools_ref.py``), whose pinned hash for
``observation-scope.json`` the tests reproduce.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# The simulated clock counts hours; the world's start time turns them into ISO-8601 times.
DEFAULT_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
TIME_POINTS = frozenset({"visible_from_h", "due_h", "expected_h", "to_h", "until_h"})

# scope class -> the item kinds it admits, and whether the item must be the actor's own.
SCOPES: dict[str, tuple[frozenset[str], str | None]] = {
    "own_accounts": (frozenset({"account", "own_account"}), "owner"),
    "own_contracts": (frozenset({"contract", "own_contract"}), "party"),
    "messages_to_me": (frozenset({"message", "scheduled_event"}), "to"),
    "public_posts": (frozenset({"public_post", "scheduled_event"}), None),
    "public_prices": (frozenset({"public_price"}), None),
    "memory": (frozenset({"memory"}), "owner"),
}


def _canonical(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, int | str):  # a bool is an int
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


def _dumps(canonical: Any) -> str:
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_json(value: Any) -> str:
    return _dumps(_canonical(value))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_of(value: Any) -> str:
    return _sha256(canonical_json(value))


def visible(item: Mapping[str, Any], actor_id: str, sees: Iterable[str], t_hours: int) -> bool:
    """Whether ``actor_id`` with scope ``sees`` may see ``item`` at ``t_hours``."""
    shown_from = item.get("visible_from_h")
    if isinstance(shown_from, bool) or not isinstance(shown_from, int) or shown_from > t_hours:
        return False
    kind = item.get("kind")
    if not isinstance(kind, str):
        return False
    for scope in sees:
        kinds, mine = SCOPES.get(scope, (frozenset(), None))
        if kind not in kinds:
            continue
        if mine is None:
            if "to" in item:  # addressed: only messages_to_me admits it
                continue
            return True
        if mine == "party":
            parties = item.get("parties", ())
            if item.get("owner") == actor_id or (
                    isinstance(parties, list | tuple) and actor_id in parties):
                return True
        elif item.get(mine) == actor_id:
            return True
    return False


@dataclass(frozen=True)
class Observation:
    body: dict[str, Any]
    text: str  # the canonical JSON that obs_hash hashes
    obs_hash: str
    evidence_ids: tuple[str, ...]
    round: int
    t_hours: int

    def to_prompt(self) -> str:
        """The financial block, placed before the social feed in the actor's prompt."""
        return ("Your financial observation (only what you may see now; money in integer "
                f"minor units):\n{self.text}")


def iso_utc(t_hours: int, epoch: datetime = DEFAULT_EPOCH) -> str:
    return _canonical(epoch + timedelta(hours=t_hours))


def _observed(item: Mapping[str, Any], epoch: datetime) -> dict[str, Any]:
    """The item as it enters the hash input: its time points become ISO-8601 UTC times."""
    return {(k[:-2] if k in TIME_POINTS else k): (iso_utc(v, epoch) if k in TIME_POINTS else v)
            for k, v in item.items()}


def build_observation(
    actor_id: str,
    sees: Iterable[str],
    round: int,
    t_hours: int,
    items: Iterable[Mapping[str, Any]],
    epoch: datetime = DEFAULT_EPOCH,
) -> Observation:
    """The scope-filtered observation of ``actor_id`` at ``t_hours`` from the world's items.

    Every item carries an ``id``, a ``kind`` and ``visible_from_h``; the evidence ids are the
    included items' ids, sorted, so building twice gives one hash and an excluded item added to
    the world changes nothing. A shown id must be one an intent can cite (C1: 1 to 128
    characters), or every intent of the actor would fail, its fallback included.
    """
    sees = tuple(sees)
    shown = [i for i in items if visible(i, actor_id, sees, t_hours)]
    for item in shown:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 128:
            raise ValueError(f"evidence id {item_id!r} in {actor_id}'s observation is not a "
                             "string of 1 to 128 characters")
    shown.sort(key=lambda i: i["id"])
    ids = [i["id"] for i in shown]
    if len(set(ids)) != len(ids):
        raise ValueError(f"item ids repeat in {actor_id}'s observation")
    body = _canonical({"actor_id": actor_id, "round": round, "t": iso_utc(t_hours, epoch),
                       "items": [_observed(i, epoch) for i in shown]})
    text = _dumps(body)
    return Observation(body, text, _sha256(text), tuple(ids), round, t_hours)

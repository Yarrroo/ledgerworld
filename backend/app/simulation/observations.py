"""What one actor may see at simulated time t, and the hash of it (§7.1, §7.2 step 4).

An actor sees its own accounts and contracts, messages addressed to it, public posts and prices,
and its memory — each only once `visible_from_h <= t`. The scope rules are the actor's `sees`
list (design fixture `actors.json`); an item of an unknown kind is not seen. `obs_hash` is the
sha256 of the observation's canonical JSON: sorted keys, no whitespace, integer minor units (a
float is refused) and every point in simulated time as ISO-8601 UTC.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from app.decisions.nonanticipativity import canonical

# The simulated clock has no calendar date in the brief; the epoch is an explicit input.
DEFAULT_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

# scope in `sees` -> (item kinds it admits, the field that must name the actor, or None if public)
SCOPE_RULES: dict[str, tuple[frozenset[str], str | None]] = {
    "own_accounts": (frozenset({"account", "own_account"}), "owner"),
    "own_contracts": (frozenset({"contract", "own_contract"}), "owner"),
    # A scheduled event addressed to one actor is private to it; an unaddressed one is public.
    "messages_to_me": (frozenset({"message", "scheduled_event"}), "to"),
    "public_posts": (frozenset({"public_post", "scheduled_event"}), None),
    "public_prices": (frozenset({"public_price"}), None),
    "memory": (frozenset({"memory"}), "owner"),
}

# Item fields that are points in simulated time (hours); in the hash input they are ISO-8601 UTC
# under the name without `_h`. Durations such as `delay_h` stay in hours.
TIME_POINT_FIELDS = frozenset({"visible_from_h", "due_h", "expected_h", "to_h", "until_h"})


def iso_utc(sim_time_h: int, epoch: datetime = DEFAULT_EPOCH) -> str:
    return (epoch + timedelta(hours=sim_time_h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refuse_floats(value: Any) -> None:
    if isinstance(value, float):
        raise ValueError(f"float in canonical payload: {value!r}")  # noqa: TRY004 — the oracle's error
    if isinstance(value, Mapping):
        for v in value.values():
            _refuse_floats(v)
    elif isinstance(value, list | tuple):
        for v in value:
            _refuse_floats(v)


def canonical_json(value: Any) -> str:
    """The decisions guard's canonical JSON, with a float anywhere refused (money is minor units)."""
    _refuse_floats(value)
    return canonical(value)


def check_item(item: Mapping[str, Any]) -> None:
    """A time point is an integer hour and does not collide with the ISO name it is hashed under."""
    for k in TIME_POINT_FIELDS & item.keys():
        v = item[k]
        if type(v) is not int:
            raise ValueError(f"item {item.get('id')!r}: {k} must be an integer hour, got {v!r}")
        if k[:-2] in item:
            raise ValueError(f"item {item.get('id')!r} has both {k} and {k[:-2]}")


def visible(item: Mapping[str, Any], actor: Mapping[str, Any], sim_time_h: int) -> bool:
    """True if `item` is inside `actor`'s scope at `sim_time_h`; anything unmatched is hidden."""
    if item.get("visible_from_h", 0) > sim_time_h:
        return False
    for scope in actor.get("sees", ()):
        kinds, bound = SCOPE_RULES.get(scope, (frozenset(), None))
        if item.get("kind") not in kinds:
            continue
        if bound is None and "to" in item:
            continue  # addressed to someone: only messages_to_me may admit it
        if bound is None or item.get(bound) == actor["actor_id"]:
            return True
    return False


def observed_item(item: Mapping[str, Any], epoch: datetime = DEFAULT_EPOCH) -> dict[str, Any]:
    """The item as it enters the hash input: time points become ISO-8601 UTC times."""
    out = {}
    for k, v in item.items():
        if k in TIME_POINT_FIELDS:
            k, v = k[:-2], iso_utc(v, epoch)
        out[k] = v
    return out


def build_observation(actor: Mapping[str, Any], world_items: Sequence[Mapping[str, Any]], round_: int,
                      sim_time_h: int, epoch: datetime = DEFAULT_EPOCH,
                      ) -> tuple[dict[str, Any], str, list[str]]:
    """-> (observation, obs_hash, evidence_ids). Items are ordered by id, so input order is irrelevant.

    Two world items sharing an id, or an item failing `check_item`, are an inconsistent world,
    refused rather than hashed.
    """
    dupes = sorted(i for i, n in Counter(item["id"] for item in world_items).items() if n > 1)
    if dupes:
        raise ValueError(f"duplicate world item ids: {dupes}")
    for item in world_items:
        check_item(item)
    items = sorted((observed_item(i, epoch) for i in world_items if visible(i, actor, sim_time_h)),
                   key=lambda i: i["id"])
    observation = {"actor_id": actor["actor_id"], "round": round_, "t": iso_utc(sim_time_h, epoch),
                   "items": items}
    obs_hash = hashlib.sha256(canonical_json(observation).encode("utf-8")).hexdigest()
    return observation, obs_hash, [i["id"] for i in items]

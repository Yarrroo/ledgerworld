"""What one actor may see at simulated time t, and the hash of it (§7.1, §7.2 step 4).

The scope rules and the hash live in `oasis_finance.observation`; this adapts the world to it:
an actor is its `actors.json` entry (`actor_id`, `sees`) and the world is its list of items.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from oasis_finance.observation import DEFAULT_EPOCH, Observation, canonical_json
from oasis_finance.observation import build_observation as _build

__all__ = ["Observation", "build_observation", "canonical_json"]


def build_observation(actor: Mapping[str, Any], world_items: Iterable[Mapping[str, Any]],
                      round_: int, t_hours: int, epoch: datetime = DEFAULT_EPOCH) -> Observation:
    """The scope-filtered observation of `actor` at `t_hours`, from the world's items."""
    return _build(actor["actor_id"], actor["sees"], round_, t_hours, world_items, epoch)

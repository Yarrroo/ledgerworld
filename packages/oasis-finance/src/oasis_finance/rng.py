"""Per-world randomness for OASIS.

OASIS's platform and its random recommender draw from the module ``random``, which is one stream
for the whole process. ``route_oasis_random()`` points the ``random`` of each of those modules at
``WORLD_RNG``, so a draw goes to the RNG the running code's context holds and worlds sharing a
process never share a stream. A context that holds none draws from ``random`` as before.

A task inherits the context it is created in: the platform's task holds the RNG that was set
when ``OasisEnv.reset`` created it, and a round's task the RNG its coordinator set.
"""

from __future__ import annotations

import contextvars
import random
from typing import Any

__all__ = ["WORLD_RNG", "route_oasis_random"]

WORLD_RNG: contextvars.ContextVar[random.Random | None] = contextvars.ContextVar(
    "oasis_world_rng", default=None)


class _WorldRandom:
    """``random`` as an OASIS module sees it: every name resolves on the context's RNG."""

    def __getattr__(self, name: str) -> Any:
        return getattr(WORLD_RNG.get() or random, name)


_ROUTED = _WorldRandom()


def route_oasis_random() -> None:
    """Route every OASIS module that draws from ``random`` through ``WORLD_RNG``; idempotent."""
    from oasis.social_platform import platform, recsys

    for module in (platform, recsys):
        module.random = _ROUTED

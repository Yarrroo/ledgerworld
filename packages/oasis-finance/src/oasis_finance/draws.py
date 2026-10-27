"""Per-world random draws.

OASIS's recommender (``oasis.social_platform.platform`` and ``recsys``) and camel's model choice
(``camel.models.model_manager.choice``) draw from the module-level ``random``. ``route_draws()``
points those names at the RNG in ``WORLD_RNG``, the one of the world running in the current
context, and at the process-global ``random`` only outside every world. A world sets
``WORLD_RNG`` around its own platform task and steps; asyncio copies it into their child tasks.
"""

from __future__ import annotations

import random
from contextvars import ContextVar
from typing import Any

__all__ = ["WORLD_RNG", "route_draws"]

WORLD_RNG: ContextVar[random.Random | None] = ContextVar("world_rng", default=None)


def _running_rng() -> Any:
    return WORLD_RNG.get() or random


class _RunningWorldRandom:
    """Stands in for the ``random`` module where OASIS draws: each draw is the running world's."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_running_rng(), name)


def route_draws() -> None:
    """Point every module-level draw a round makes at the running world's RNG; idempotent.

    Call it once ``oasis`` is imported (``app.simulation.world.import_oasis`` does): importing
    ``oasis`` writes ``./log`` in the working directory.
    """
    from camel.models import model_manager
    from oasis.social_platform import platform, recsys

    for module in (platform, recsys):
        if not isinstance(module.random, _RunningWorldRandom):
            module.random = _RunningWorldRandom()
    model_manager.choice = lambda seq: _running_rng().choice(seq)

"""Per-world randomness for OASIS.

OASIS's platform and its random recommender draw from the module ``random``, which is one stream
for the whole process. ``route_oasis_random()`` points the ``random`` of each of those modules at
``WORLD_RNG``, so a draw goes to the RNG the running code's context holds and worlds sharing a
process never share a stream. A context that holds none draws from ``random`` as before.

A task inherits the context it is created in: the platform's task holds the RNG that was set
(``using``) when ``OasisEnv.reset`` created it, and ``drawing_from`` gives a coroutine function,
such as ``OasisEnv.step``, the RNG for every call whoever makes it.
"""

from __future__ import annotations

import contextvars
import random
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

__all__ = ["WORLD_RNG", "drawing_from", "route_oasis_random", "using"]

WORLD_RNG: contextvars.ContextVar[random.Random | None] = contextvars.ContextVar(
    "oasis_world_rng", default=None)


class _WorldRandom:
    """``random`` as an OASIS module sees it: every name resolves on the context's RNG."""

    def __getattr__(self, name: str) -> Any:
        return getattr(WORLD_RNG.get() or random, name)


_ROUTED = _WorldRandom()


def route_oasis_random() -> None:
    """Route every OASIS module that draws from ``random`` through ``WORLD_RNG``; idempotent.

    Import ``oasis`` first: importing it writes ``./log`` in the working directory.
    """
    from oasis.social_platform import platform, recsys

    for module in (platform, recsys):
        module.random = _ROUTED


@contextmanager
def using(rng: random.Random) -> Iterator[None]:
    """``rng`` is the context's RNG inside the block."""
    token = WORLD_RNG.set(rng)
    try:
        yield
    finally:
        WORLD_RNG.reset(token)


def drawing_from(rng: random.Random,
                 call: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """``call``, run with ``rng`` as the context's RNG."""

    async def run(*args: Any, **kwargs: Any) -> Any:
        with using(rng):
            return await call(*args, **kwargs)

    return run

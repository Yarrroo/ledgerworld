"""A platform channel that hands each answer over the moment the platform sends it.

OASIS's ``Channel.read_from_send_queue`` polls its answer dict every 0.1 s, so every platform
round trip (an action, a fence) waits up to that long for an answer already there. This channel
keeps the same queue, dict and message shapes and wakes the one reader whose answer landed.

Importing this module imports OASIS: import it only after ``app.simulation.world.import_oasis``,
which imports OASIS from a temporary directory. The package's ``__init__`` does not import it.
"""

from __future__ import annotations

import asyncio

from oasis.social_platform.channel import Channel

__all__ = ["PromptChannel"]


class PromptChannel(Channel):
    def __init__(self) -> None:
        super().__init__()
        self._waiting: dict[str, asyncio.Future] = {}  # message id -> its reader's wakeup

    async def send_to(self, message):
        await super().send_to(message)
        waiter = self._waiting.get(message[0])
        if waiter is not None and not waiter.done():
            waiter.set_result(None)

    async def read_from_send_queue(self, message_id):
        # Registered before the look, so an answer landing between the two still wakes it.
        waiter = self._waiting[message_id] = asyncio.get_running_loop().create_future()
        try:
            if message_id not in await self.send_dict.keys():
                await waiter
        finally:
            del self._waiting[message_id]
        return await self.send_dict.pop(message_id)

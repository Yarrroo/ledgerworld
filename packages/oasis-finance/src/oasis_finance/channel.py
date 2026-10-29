"""A platform channel that hands each answer over the moment the platform sends it.

OASIS's ``Channel.read_from_send_queue`` polls its answer dict every 0.1 s, so every platform
round trip (an action, a fence) waits up to that long for an answer already there. This channel
keeps the same queue, dict and message shapes and wakes the waiting reader when the answer lands.

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
        self._sent = asyncio.Condition()

    async def send_to(self, message):
        await super().send_to(message)
        async with self._sent:
            self._sent.notify_all()

    async def read_from_send_queue(self, message_id):
        async with self._sent:
            await self._sent.wait_for(lambda: message_id in self.send_dict.dict)
        return await self.send_dict.pop(message_id)

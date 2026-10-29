"""The world's platform channel hands an answer over when it lands, not on OASIS's 0.1 s poll."""

from __future__ import annotations

import asyncio
import time

from app.simulation.world import import_oasis

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

from oasis_finance.channel import PromptChannel


def test_each_reader_gets_its_own_answer_as_soon_as_it_is_sent():
    async def scenario():
        channel = PromptChannel()
        first = await channel.write_to_receive_queue(("a",))
        second = await channel.write_to_receive_queue(("b",))
        readers = [asyncio.create_task(channel.read_from_send_queue(m)) for m in (first, second)]
        await asyncio.sleep(0)
        started = time.monotonic()
        for _ in range(2):  # the platform answers in order, as Platform.running does
            message_id, action = await channel.receive_from()
            await channel.send_to((message_id, None, action[0]))
        answers = await asyncio.gather(*readers)
        return answers, time.monotonic() - started, await channel.send_dict.keys()

    (a, b), elapsed, left = asyncio.run(scenario())
    assert a[2] == "a" and b[2] == "b"
    assert elapsed < 0.05  # the polling channel takes up to 0.1 s per answer
    assert left == []  # each answer is taken once


def test_a_reader_that_times_out_leaves_the_channel_usable():
    async def scenario():
        channel = PromptChannel()
        late = await channel.write_to_receive_queue(("late",))
        try:
            await asyncio.wait_for(channel.read_from_send_queue(late), 0.01)
        except TimeoutError:
            pass
        message_id, action = await channel.receive_from()
        await channel.send_to((message_id, None, action[0]))
        return await asyncio.wait_for(channel.read_from_send_queue(late), 1)

    assert asyncio.run(scenario())[2] == "late"


def test_the_world_platform_uses_the_prompt_channel():
    assert import_oasis().Channel is PromptChannel

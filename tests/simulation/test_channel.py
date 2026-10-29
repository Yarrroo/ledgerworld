"""The world's platform channel hands an answer over when it lands, not on OASIS's 0.1 s poll."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.simulation.world import World, import_oasis
from app.testing.scripted_model import ScriptedPlan

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

from oasis_finance.channel import PromptChannel
from oasis_finance.observation import iso_utc

ROOT = Path(__file__).resolve().parents[2]
ACTORS = json.loads(
    (ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures/actors.json").read_text()
)["actors"]


async def settle() -> None:
    """A few turns of the loop, no wall time: a woken reader finishes, a polling one cannot."""
    for _ in range(5):
        await asyncio.sleep(0)


def test_each_reader_gets_its_own_answer_as_soon_as_it_is_sent():
    async def scenario():
        channel = PromptChannel()
        first = await channel.write_to_receive_queue(("a",))
        second = await channel.write_to_receive_queue(("b",))
        readers = [asyncio.create_task(channel.read_from_send_queue(m)) for m in (first, second)]
        await settle()
        for _ in range(2):  # the platform answers in order, as Platform.running does
            message_id, action = await channel.receive_from()
            await channel.send_to((message_id, None, action[0]))
        await settle()
        done = [r.done() for r in readers]  # OASIS's Channel is still in its 0.1 s sleep here
        answers = await asyncio.gather(*readers)
        return done, answers, await channel.send_dict.keys(), channel._waiting

    done, (a, b), left, waiting = asyncio.run(scenario())
    assert done == [True, True]
    assert a[2] == "a" and b[2] == "b"
    assert left == [] and waiting == {}  # each answer is taken once, no reader left registered


def test_an_answer_sent_before_the_read_is_handed_over_at_once():
    async def scenario():
        channel = PromptChannel()
        message_id = await channel.write_to_receive_queue(("early",))
        await channel.send_to((message_id, None, "early"))
        return await asyncio.wait_for(channel.read_from_send_queue(message_id), 1)

    assert asyncio.run(scenario())[2] == "early"


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


def test_a_started_world_and_its_agents_talk_over_the_prompt_channel(tmp_path):
    def usd(minor: int) -> dict:
        return {"minor": minor, "currency": "USD"}

    snapshot = {"snapshot_id": "snap-channel", "as_of": iso_utc(0), "obligations": [],
                "contracts": [], "exposures": [], "pools": [],
                "entities": [{"entity_id": "treasury", "name": "Treasury (synthetic)",
                              "kind": "treasury"}],
                "accounts": [{"id": "treasury/operating", "entity": "treasury",
                              "currency": "USD", "observability": "known", "as_of": iso_utc(0),
                              "buckets": {"settled": usd(1_000_000), "reserved": usd(0),
                                          "pledged": usd(0), "pending_in": [],
                                          "pending_out": []}}]}
    plan = ScriptedPlan([{"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}])
    world = World("channel", "main", snapshot,
                  [a for a in ACTORS if a["actor_id"] == "treasury"],
                  model=lambda actor_id, w: plan.model(actor_id, lambda: w.clock.round),
                  workdir=tmp_path)

    async def go():
        async with world:
            await world.run(1)
            agents = [agent for _, agent in world.env.agent_graph.get_agents()]
            return world.env.channel, world.env.platform.channel, [a.channel for a in agents]

    env_channel, platform_channel, agent_channels = asyncio.run(go())
    assert type(env_channel) is PromptChannel and platform_channel is env_channel
    assert agent_channels and all(c is env_channel for c in agent_channels)

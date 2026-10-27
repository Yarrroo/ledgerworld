"""Financial actions in the agent world: the intent queue and the agent each actor runs as.

One implementation, in `oasis_finance`: the tools `put` C1 intents on their branch's queue and the
coordinator `drain`s it once per round, sorted by `(priority_class, sim_minute, actor_id, call
order)` so the agents answering concurrently cannot change what clears first (§7.2 steps 5–7).
`build_finance_agent` turns an `actors.json` entry into the `FinanceAgent` the OASIS env drives;
the world and a fork build every agent through it, never through `clone()`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from oasis_finance.actions import SOCIAL_TOOLS, FinanceActor, IntentQueue

if TYPE_CHECKING:
    from oasis_finance.agent import FinanceAgent

__all__ = ["IntentQueue", "build_finance_agent"]


def build_finance_agent(spec: Mapping[str, Any], agent_id: int, queue: IntentQueue, *,
                        model: Any = None, channel: Any = None) -> FinanceAgent:
    """The agent of one `actors.json` entry, bound to one branch's queue.

    Its finance tools are the entry's finance acts; its social tools are the entry's social acts
    (none when it names none). `oasis` is imported here, not at module import: it takes seconds
    and writes `./log` in the working directory.
    """
    from oasis.social_platform.config import UserInfo
    from oasis_finance.agent import FinanceAgent

    actor = FinanceActor.from_spec(spec, queue.branch_id)
    profile = f"{spec['role']}. Objective: {spec['objective']}."
    user = UserInfo(user_name=spec["actor_id"], name=spec["actor_id"], description=profile,
                    profile={"other_info": {"user_profile": profile}})
    return FinanceAgent(agent_id, user, actor=actor, queue=queue,
                        social_actions=[t for t in spec["tools"] if t in SOCIAL_TOOLS],
                        model=model, channel=channel)

"""The OASIS agent an actor runs as: a ``SocialAgent`` whose money acts are the finance tools.

``FinanceAgent`` extends camel-oasis 0.2.5 at every seam an action can enter by
(research/oasis-seam.md):

- S3/S4: the finance tools are extra ``tools``; the social subset is passed explicitly, never
  empty (upstream reads empty as "every social tool") and never with ``purchase_product``.
- S5: ``perform_action_by_llm`` shows the scoped financial observation first, then the social
  feed, and judges the whole response through the guardrail before any tool runs; finance calls
  only queue C1 intents, and the accepted response's social calls run on the platform, in the
  agent's turn of its ``SocialOrder``.
- S6: ``perform_action_by_data`` runs only the actor's social subset; a finance act by data has
  no observation to cite and is refused. ``perform_action_by_hci`` is refused.
- S8: the tool set is sealed once built (camel's registry refuses changes, and the social offer
  is fixed at construction rather than read from upstream's mutable ``action_tools``), and
  ``clone()`` (which returns a plain ``ChatAgent`` without the finance tools) is refused: a fork
  rebuilds the agent.

Importing this module imports ``oasis``, which writes ``./log`` in the working directory (S13).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from types import MappingProxyType
from typing import Any

from camel.memories import MemoryRecord
from camel.messages import BaseMessage
from camel.toolkits import FunctionTool
from camel.types import OpenAIBackendRole
from oasis.social_agent.agent import SocialAgent
from oasis.social_platform.typing import ActionType

from oasis_finance.actions import SOCIAL_TOOLS, FinanceActor, IntentQueue, make_finance_tools
from oasis_finance.guardrail import TurnResult, amodel_responder, arun_turn
from oasis_finance.observation import Observation

# A social act that moves money outside the ledger is never offered to an actor (S3).
REFUSED_SOCIAL = frozenset({ActionType.PURCHASE_PRODUCT.value})


class SealedToolset(PermissionError):
    """A tool added to or removed from a finance agent after it was built."""


def _name(action: str | ActionType) -> str:
    return action.value if isinstance(action, ActionType) else action


class SocialOrder:
    """The order one step's agents commit their social calls in: an agent with calls to make
    waits until every agent before it has finished its turn, posted or not, failed or not.

    The platform numbers posts as their writes arrive. Models answer in any order (a live one
    when it likes, a replayed one at once), so without this order a replay can hand the same
    posts other ids and show the next round another observation. Only the social calls wait: the
    feed is read and the model asked concurrently, as before. Upstream's step semaphore admits the
    agents in the step's order, so begun in that order an agent that waits never holds a slot an
    earlier one needs. Outside a step (before ``begin``, after ``end``) nothing waits.
    """

    def __init__(self) -> None:
        self._turns: dict[int, asyncio.Event] = {}

    def begin(self, agent_ids: Iterable[int]) -> None:
        """A new step, its agents in the order they commit."""
        self._turns = {agent_id: asyncio.Event() for agent_id in agent_ids}

    def end(self) -> None:
        """The step is over, however it ended: a turn that never started holds nobody up."""
        self._turns = {}

    async def wait(self, agent_id: int) -> None:
        """Until every agent before ``agent_id`` is done; at once for one outside the step."""
        turns = self._turns
        if agent_id not in turns:
            return
        for earlier, done in turns.items():
            if earlier == agent_id:
                return
            await done.wait()

    def done(self, agent_id: int) -> None:
        turn = self._turns.get(agent_id)
        if turn is not None:
            turn.set()


class FinanceAgent(SocialAgent):
    """One actor in one branch: its persona, its finance tools on the branch's queue, its feed."""

    _sealed = False

    def __init__(
        self,
        agent_id: int,
        user_info: Any,
        *,
        actor: FinanceActor,
        queue: IntentQueue,
        social_actions: Iterable[str | ActionType] = (),
        model: Any = None,
        channel: Any = None,
        user_info_template: Any = None,
        agent_graph: Any = None,
    ) -> None:
        social = tuple(_name(a) for a in social_actions)
        unknown = sorted(set(social) - SOCIAL_TOOLS)
        refused = sorted(set(social) & REFUSED_SOCIAL)
        if unknown or refused:
            raise ValueError(f"{actor.actor_id} may not be offered social tools "
                             f"{unknown + refused}")
        if model is None:  # upstream would fall back to a default live model
            raise ValueError(f"{actor.actor_id} needs its model: a scripted or a configured one")
        self.finance_actor = actor
        self.intent_queue = queue
        self.observation: Observation | None = None  # this round's, kept after the turn
        self._observed = False  # an observation given and not yet acted on
        self.last_turn: TurnResult | None = None
        self.last_social_results: tuple[tuple[str, Any], ...] = ()
        self.social_order = SocialOrder()  # never begun, until a world shares its own
        finance = [FunctionTool(tool, openai_tool_schema=tool.openai_tool_schema)
                   for tool in make_finance_tools(queue, actor).values()]
        super().__init__(
            agent_id, user_info, user_info_template, channel, model, agent_graph,
            available_actions=list(social) or [ActionType.DO_NOTHING.value],
            tools=finance, max_iteration=1,
        )
        if not social:
            super().remove_tool(ActionType.DO_NOTHING.value)
            self.action_tools = []
        self._social_tools = MappingProxyType(
            {t.get_function_name(): t for t in self.action_tools})
        self._social_schemas = MappingProxyType(
            {n: t.get_openai_tool_schema() for n, t in self._social_tools.items()})
        self._sealed = True

    # ------------------------------------------------------------------- the tool set (S8)

    def _refuse_change(self) -> None:
        if self._sealed:
            raise SealedToolset(f"{self.finance_actor.actor_id}'s tools are fixed by its mandate")

    def add_tool(self, tool: Any) -> None:
        self._refuse_change()
        super().add_tool(tool)

    def add_tools(self, tools: Any) -> None:
        self._refuse_change()
        super().add_tools(tools)

    def add_external_tool(self, tool: Any) -> None:
        self._refuse_change()
        super().add_external_tool(tool)

    def remove_tool(self, tool_name: str) -> bool:
        self._refuse_change()
        return super().remove_tool(tool_name)

    def remove_tools(self, tool_names: Any) -> None:
        self._refuse_change()
        super().remove_tools(tool_names)

    def remove_external_tool(self, tool_name: str) -> bool:
        self._refuse_change()
        return super().remove_external_tool(tool_name)

    def clone(self, with_memory: bool = False) -> Any:
        raise NotImplementedError("a finance agent is rebuilt from its persona, never cloned")

    # --------------------------------------------------------------------- one turn (S5)

    def observe(self, observation: Observation) -> None:
        """Give the agent this round's scoped observation (§7.2 step 4); one per turn."""
        if observation.body.get("actor_id") != self.finance_actor.actor_id:
            raise ValueError(f"{observation.body.get('actor_id')}'s observation given to "
                             f"{self.finance_actor.actor_id}")
        self.observation, self._observed = observation, True

    async def perform_action_by_llm(self) -> TurnResult:
        """One model response, judged whole: finance calls queue intents, social calls post.

        A malformed response is repaired once, then becomes ``no_action`` plus an alert
        (``last_turn.alert``). An error from the model or the platform is raised, not returned:
        the round fails and rolls back (system brief §7.2).
        """
        try:
            return await self._turn()
        finally:  # a turn that failed must not hold up the agents after it
            self.social_order.done(self.social_agent_id)

    async def _turn(self) -> TurnResult:
        if not self._observed:
            raise RuntimeError(f"{self.finance_actor.actor_id} was asked to act before it was "
                               "given its observation")
        observation, self._observed = self.observation, False
        # The follower and follow counts are not part of the prompt upstream renders.
        feed = await self.env.to_text_prompt(include_followers=False, include_follows=False)
        result = await arun_turn(
            amodel_responder(self.model_backend), self.intent_queue, self.finance_actor,
            observation, social_prompt=f"Here is your social media environment: {feed}",
            social=self._social_schemas,
            system=self.system_message.content if self.system_message else None,
        )
        # Recorded before the posts run: a platform error leaves this turn, not the last, on view.
        self.last_turn, self.last_social_results = result, ()
        if result.social:
            await self.social_order.wait(self.social_agent_id)
        outcomes = tuple([(call.name, await self._social_tools[call.name].async_call(
            **call.arguments)) for call in result.social])
        self.last_social_results = outcomes
        self._remember(observation, result, outcomes)
        return result

    def _remember(self, observation: Observation, result: TurnResult, outcomes: tuple) -> None:
        """What the actor saw (its financial block; the feed is the platform's) and did."""
        done = [f"queued {i.intent_id} ({i.type})" for i in result.intents]
        done += [f"{name} -> {json.dumps(out, sort_keys=True, default=str)}"
                 for name, out in outcomes]
        if result.alert is not None:
            done.append(f"refused after repair: {result.alert.reason}")
        # Written as records: update_memory re-counts the whole history's tokens each time.
        self.memory.write_records([
            MemoryRecord(message=BaseMessage.make_user_message("User", observation.to_prompt()),
                         role_at_backend=OpenAIBackendRole.USER, agent_id=self.agent_id),
            MemoryRecord(message=BaseMessage.make_assistant_message("Assistant", "; ".join(done)),
                         role_at_backend=OpenAIBackendRole.ASSISTANT, agent_id=self.agent_id),
        ])

    # ----------------------------------------------------------- other dispatch paths (S6)

    async def perform_action_by_data(self, func_name: Any, *args: Any, **kwargs: Any) -> Any:
        name = _name(func_name)
        if name not in self._social_tools:
            raise ValueError(f"{name!r} is not one of {self.finance_actor.actor_id}'s social "
                             "tools; a finance act is a tool call inside a turn")
        return await super().perform_action_by_data(func_name, *args, **kwargs)

    async def perform_action_by_hci(self) -> Any:
        raise NotImplementedError("a finance agent acts only through its model or its data")

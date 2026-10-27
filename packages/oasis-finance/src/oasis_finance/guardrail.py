"""One actor's finance turn: one model response, at most one repair, then ``no_action``.

The model is offered the actor's finance tools and its scoped observation. A response is taken
whole or not at all: if any tool call names a tool outside the mandate, carries arguments that do
not validate (a float amount, a missing field) or the response calls no tool, nothing is queued
and the model is asked once more with the errors named. If the repair is refused too, the actor
queues one ``no_action`` and the turn carries an alert. A malformed response never raises, so
the round goes on to its mandatory settlements; an error from the model call itself does raise
(that is a round failure, not malformed output). The turn ends when the driver returns or
raises, so a tool the actor still holds refuses any later call.

Upstream ``SocialAgent.perform_action_by_llm`` returns exceptions instead of raising
(oasis-seam.md S5), so the guardrail inspects every call before any tool runs rather than relying
on a tool to raise.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any

from app.finance.schemas import ActionIntent

from oasis_finance.actions import (
    FinanceActor,
    FinancialActionType,
    IntentQueue,
    NoActionArgs,
    ToolCallError,
    Turn,
    parse_tool_call,
    submit,
    tool_schema,
)
from oasis_finance.observation import Observation

MAX_REPAIRS = 1


@dataclass(frozen=True)
class RawCall:
    """One tool call as the model produced it; ``arguments`` is a JSON string or an object."""

    name: str
    arguments: Any
    call_id: str | None = None


@dataclass(frozen=True)
class Alert:
    actor_id: str
    branch_id: str
    round: int
    reason: str
    detail: str


@dataclass(frozen=True)
class TurnResult:
    intents: tuple[ActionIntent, ...]
    repair_attempts: int
    alert: Alert | None
    refused: tuple[ToolCallError, ...]
    calls: tuple[RawCall, ...]  # the response whose calls were queued, empty on fallback


Messages = list[dict[str, Any]]
Tools = list[dict[str, Any]]
Responder = Callable[[Messages, Tools], Sequence[RawCall]]
AsyncResponder = Callable[[Messages, Tools], Awaitable[Sequence[RawCall]]]


def _calls(completion: Any) -> list[RawCall]:
    message = completion.choices[0].message
    return [RawCall(c.function.name, c.function.arguments, c.id)
            for c in (message.tool_calls or [])]


def model_responder(model: Any) -> Responder:
    """A camel model backend (``ScriptedModel`` or a live one) as a responder."""
    return lambda messages, tools: _calls(model.run(messages, tools=tools))


def amodel_responder(model: Any) -> AsyncResponder:
    async def respond(messages: Messages, tools: Tools) -> list[RawCall]:
        return _calls(await model.arun(messages, tools=tools))

    return respond


def repair_marker(actor_id: str, round: int) -> str:
    """The token a repair prompt opens with; a scripted plan keys its repair entry on it."""
    return f"repair:{actor_id}:r{round}"


def _check(calls: Sequence[RawCall], actor: FinanceActor) -> tuple[list, list[ToolCallError]]:
    parsed, refused = [], []
    if not calls:
        refused.append(ToolCallError("", "no_tool_call",
                                     "the response called no tool; call no_action to wait"))
    for call in calls:
        result = parse_tool_call(call.name, call.arguments, actor.tools)
        (refused if isinstance(result, ToolCallError) else parsed).append(result)
    return parsed, refused


def _assistant(calls: Sequence[RawCall], round: int, actor_id: str) -> Messages:
    """The refused response and one tool result per call, as a chat API expects them."""
    if not calls:
        return []
    ids = [c.call_id or f"refused-r{round}-{actor_id}-{n}" for n, c in enumerate(calls, 1)]
    tool_calls = [
        {"id": i, "type": "function", "function": {
            "name": c.name,
            "arguments": c.arguments if isinstance(c.arguments, str)
            else json.dumps(c.arguments, sort_keys=True, default=str)}}
        for i, c in zip(ids, calls, strict=True)
    ]
    results = [{"role": "tool", "tool_call_id": i, "content": "refused; nothing was queued"}
               for i in ids]
    return [{"role": "assistant", "content": None, "tool_calls": tool_calls}, *results]


def _turn(
    queue: IntentQueue,
    actor: FinanceActor,
    observation: Observation,
    sim_minute: int | None,
    social_prompt: str | None,
) -> Generator[tuple[Messages, Tools], Sequence[RawCall], TurnResult]:
    round = int(observation.body["round"])
    minute = int(observation.body["t_hours"]) * 60 if sim_minute is None else sim_minute
    actor.begin_turn(Turn(round, minute, observation.obs_hash, observation.evidence_ids))
    tools = [tool_schema(a) for a in actor.tools]
    prompt = observation.to_prompt() + (f"\n\n{social_prompt}" if social_prompt else "")
    messages: Messages = [
        {"role": "system", "content": (
            f"You are {actor.actor_id}. You act on money only through your tools; each tool "
            "call proposes one action, which the ledger clears or rejects after the round.")},
        {"role": "user", "content": prompt},
    ]
    calls = yield messages, tools
    parsed, refused = _check(calls, actor)
    repairs = 0
    while refused and repairs < MAX_REPAIRS:
        repairs += 1
        errors = "\n".join(f"- {e.detail}" for e in refused)
        messages = messages + _assistant(calls, round, actor.actor_id) + [{
            "role": "user", "content": (
                f"{repair_marker(actor.actor_id, round)}\nYour tool calls were refused and "
                f"nothing was queued:\n{errors}\nAnswer once more with valid tool calls: "
                "amount_minor is an integer number of minor units. If you cannot, call "
                "no_action.")}]
        calls = yield messages, tools
        parsed, refused = _check(calls, actor)
    if refused:
        first = refused[0]
        alert = Alert(actor.actor_id, actor.branch_id, round, first.code,
                      "; ".join(e.detail for e in refused))
        fallback = submit(queue, actor, [(FinancialActionType.NO_ACTION, NoActionArgs(
            reason=f"fallback after repair: {first.code}"))])
        return TurnResult(fallback, repairs, alert, tuple(refused), ())
    intents = submit(queue, actor, [
        (FinancialActionType(call.name), args) for call, args in zip(calls, parsed, strict=True)])
    return TurnResult(intents, repairs, None, (), tuple(calls))


def run_turn(
    respond: Responder,
    queue: IntentQueue,
    actor: FinanceActor,
    observation: Observation,
    *,
    sim_minute: int | None = None,
    social_prompt: str | None = None,
) -> TurnResult:
    """Run one actor's turn and queue its intents; see the module docstring."""
    turn = _turn(queue, actor, observation, sim_minute, social_prompt)
    try:
        request = next(turn)
        while True:
            request = turn.send(respond(*request))
    except StopIteration as done:
        return done.value
    finally:
        actor.end_turn()


async def arun_turn(
    respond: AsyncResponder,
    queue: IntentQueue,
    actor: FinanceActor,
    observation: Observation,
    *,
    sim_minute: int | None = None,
    social_prompt: str | None = None,
) -> TurnResult:
    """``run_turn`` for a coordinator that runs every actor at once."""
    turn = _turn(queue, actor, observation, sim_minute, social_prompt)
    try:
        request = next(turn)
        while True:
            request = turn.send(await respond(*request))
    except StopIteration as done:
        return done.value
    finally:
        actor.end_turn()

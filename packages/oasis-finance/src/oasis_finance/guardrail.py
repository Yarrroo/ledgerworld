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

An agent may also be offered social tools (``social``: name to OpenAI schema). A social call is
checked against its JSON schema with the rest of the response and, once the response is accepted,
is returned in ``TurnResult.social`` for the agent to run on the platform; the guardrail never
runs it. An accepted response that makes no financial call queues ``no_action``, so every turn
leaves one intent carrying the hash of what the actor was shown.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.finance.schemas import ActionIntent
from jsonschema import Draft202012Validator, validators

from oasis_finance.actions import (
    FinanceActor,
    FinancialActionType,
    IntentQueue,
    NoActionArgs,
    ToolCallError,
    Turn,
    decode_args,
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
    calls: tuple[RawCall, ...]  # the accepted response as the model wrote it, empty on fallback
    social: tuple[RawCall, ...] = ()  # its social calls, arguments decoded, for the agent to run


Messages = list[dict[str, Any]]
Tools = list[dict[str, Any]]
Social = Mapping[str, dict[str, Any]]
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


# JSON Schema counts 1.0 as an integer; a model's float never reaches a platform action as an id.
_Validator = validators.extend(Draft202012Validator, type_checker=(
    Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _, v: isinstance(v, int) and not isinstance(v, bool))))


def parse_social_call(call: RawCall, schema: dict[str, Any]) -> RawCall | ToolCallError:
    """A social call with its arguments decoded and valid against the tool's JSON schema.

    An argument the schema does not name is refused, whatever the schema says, because the
    arguments become the keyword arguments of the platform action.
    """
    args = decode_args(call.name, call.arguments)
    if isinstance(args, ToolCallError):
        return args
    params = {**schema["function"].get("parameters", {}), "additionalProperties": False}
    errors = sorted(_Validator(params).iter_errors(dict(args)),
                    key=lambda e: [str(p) for p in e.path])
    if errors:
        return ToolCallError(call.name, "malformed_tool_args", "; ".join(
            f"{call.name}.{'.'.join(str(p) for p in e.path) or '(args)'}: {e.message}"
            for e in errors))
    return RawCall(call.name, dict(args), call.call_id)


def _check(
    calls: Sequence[RawCall], actor: FinanceActor, social: Social
) -> tuple[list, list[RawCall], list[ToolCallError]]:
    parsed, social_calls, refused = [], [], []
    if not calls:
        refused.append(ToolCallError("", "no_tool_call",
                                     "the response called no tool; call no_action to wait"))
    offered = sorted({a.value for a in actor.tools} | set(social))
    for call in calls:
        if call.name in social:
            result = parse_social_call(call, social[call.name])
            (refused if isinstance(result, ToolCallError) else social_calls).append(result)
        elif call.name not in offered:
            refused.append(ToolCallError(call.name, "tool_not_in_mandate",
                                         f"{call.name!r} is not one of your tools {offered}"))
        else:
            result = parse_tool_call(call.name, call.arguments, actor.tools)
            if isinstance(result, ToolCallError):
                refused.append(result)
            else:
                parsed.append((FinancialActionType(call.name), result))
    return parsed, social_calls, refused


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
    social: Social | None = None,
    system: str | None = None,
) -> Generator[tuple[Messages, Tools], Sequence[RawCall], TurnResult]:
    round = observation.round
    minute = observation.t_hours * 60 if sim_minute is None else sim_minute
    social = social or {}
    actor.begin_turn(Turn(round, minute, observation.obs_hash, observation.evidence_ids))
    tools = [tool_schema(a) for a in actor.tools] + list(social.values())
    prompt = observation.to_prompt() + (f"\n\n{social_prompt}" if social_prompt else "")
    rule = (f"You are {actor.actor_id}. You act on money only through your tools; each tool "
            "call proposes one action, which the ledger clears or rejects after the round.")
    messages: Messages = [
        {"role": "system", "content": f"{system}\n\n{rule}" if system else rule},
        {"role": "user", "content": prompt},
    ]
    calls = yield messages, tools
    parsed, social_calls, refused = _check(calls, actor, social)
    repairs = 0
    while refused and repairs < MAX_REPAIRS:
        repairs += 1
        errors = "\n".join(f"- {e.detail}" for e in refused)
        money = any(e.code == "malformed_tool_args" and e.name not in social for e in refused)
        hint = " amount_minor is an integer number of minor units." if money else ""
        messages = messages + _assistant(calls, round, actor.actor_id) + [{
            "role": "user", "content": (
                f"{repair_marker(actor.actor_id, round)}\nYour tool calls were refused and "
                f"nothing was queued:\n{errors}\nAnswer once more with valid tool calls."
                f"{hint} If you cannot, call no_action.")}]
        calls = yield messages, tools
        parsed, social_calls, refused = _check(calls, actor, social)
    if refused:
        first = refused[0]
        alert = Alert(actor.actor_id, actor.branch_id, round, first.code,
                      "; ".join(e.detail for e in refused))
        fallback = submit(queue, actor, [(FinancialActionType.NO_ACTION, NoActionArgs(
            reason=f"fallback after repair: {first.code}"))])
        return TurnResult(fallback, repairs, alert, tuple(refused), ())
    intents = submit(queue, actor, parsed or [(FinancialActionType.NO_ACTION, NoActionArgs())])
    return TurnResult(intents, repairs, None, (), tuple(calls), tuple(social_calls))


def run_turn(
    respond: Responder,
    queue: IntentQueue,
    actor: FinanceActor,
    observation: Observation,
    *,
    sim_minute: int | None = None,
    social_prompt: str | None = None,
    social: Social | None = None,
    system: str | None = None,
) -> TurnResult:
    """Run one actor's turn and queue its intents; see the module docstring."""
    turn = _turn(queue, actor, observation, sim_minute, social_prompt, social, system)
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
    social: Social | None = None,
    system: str | None = None,
) -> TurnResult:
    """``run_turn`` for a coordinator that runs every actor at once."""
    turn = _turn(queue, actor, observation, sim_minute, social_prompt, social, system)
    try:
        request = next(turn)
        while True:
            request = turn.send(await respond(*request))
    except StopIteration as done:
        return done.value
    finally:
        actor.end_turn()

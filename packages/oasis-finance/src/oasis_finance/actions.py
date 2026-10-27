"""Financial actions: the typed tools an actor calls and the C1 intents they queue.

OASIS's ``ActionType`` is a closed enum (oasis-seam.md S1), so the finance acts are a separate
``FinancialActionType`` and reach the model as extra tools, never through the platform channel
(S2). A tool call validates its arguments, builds one C1 ``ActionIntent`` and appends it to its
branch's ``IntentQueue``; it never reads or writes the ledger. ``make_finance_tools`` binds the
tools by closure over one branch's queue and one actor, and nothing else, so no ledger handle can
be reached from a tool. The coordinator drains the queue and clears the intents (C2).

Money arguments are ``amount_minor`` (a strict integer) and an ISO ``currency``; a float, a
string or a bool in ``amount_minor`` is a validation error, never rounded.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any

from app.finance.schemas import MINOR_MAX, ActionIntent, Amount, Bps, Currency
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)


class FinancialActionType(StrEnum):
    """The finance acts an actor may propose; separate from OASIS's closed ``ActionType``."""

    REQUEST_ADVANCE = "request_advance"
    OFFER = "offer"
    ACCEPT = "accept"
    DISBURSE = "disburse"
    REPAY = "repay"
    CONVERT = "convert"
    PAY = "pay"
    PLEDGE = "pledge"
    RELEASE = "release"
    DEFER = "defer"
    NO_ACTION = "no_action"


# camel-oasis 0.2.5 ``ActionType`` values: an actor's social tools, handed to ``SocialAgent``.
SOCIAL_TOOLS = frozenset({
    "exit", "refresh", "search_user", "search_posts", "create_post", "like_post", "unlike_post",
    "dislike_post", "undo_dislike_post", "report_post", "follow", "unfollow", "mute", "unmute",
    "trend", "sign_up", "repost", "quote_post", "update_rec_table", "create_comment",
    "like_comment", "unlike_comment", "dislike_comment", "undo_dislike_comment", "do_nothing",
    "purchase_product", "interview", "join_group", "leave_group", "send_to_group", "create_group",
    "listen_from_group",
})

# ---------------------------------------------------------------------------- tool arguments

Ref = Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    reason: Annotated[StrictStr, StringConstraints(max_length=1000)] | None = Field(
        None, description="why, in a sentence")


class _MoneyArgs(_Args):
    amount_minor: StrictInt = Field(
        gt=0, le=MINOR_MAX, description="integer minor units (cents for USD), never a decimal"
    )
    currency: Currency


class RequestAdvanceArgs(_MoneyArgs):
    from_: Ref = Field(alias="from", description="the lender asked")
    facility_id: Ref | None = None


class OfferArgs(_MoneyArgs):
    to: Ref
    request: Ref | None = None
    fee_bps: Bps | None = None


class AcceptArgs(_Args):
    request: Ref


class DisburseArgs(_MoneyArgs):
    request: Ref
    from_account: Ref | None = None


class RepayArgs(_MoneyArgs):
    to: Ref
    facility_id: Ref | None = None


class ConvertArgs(_MoneyArgs):
    to_currency: Currency

    @model_validator(mode="after")
    def _into_another_currency(self) -> ConvertArgs:
        if self.to_currency == self.currency:
            raise ValueError("a conversion goes into another currency")
        return self


class PayArgs(_MoneyArgs):
    to: Ref
    obligation_id: Ref | None = None


class PledgeArgs(_MoneyArgs):
    to: Ref


class ReleaseArgs(_Args):
    target: Ref = Field(description="the facility, offer or pledge released")


class DeferArgs(_Args):
    obligation_id: Ref


class NoActionArgs(_Args):
    pass


ARGS: dict[FinancialActionType, type[_Args]] = {
    FinancialActionType.REQUEST_ADVANCE: RequestAdvanceArgs,
    FinancialActionType.OFFER: OfferArgs,
    FinancialActionType.ACCEPT: AcceptArgs,
    FinancialActionType.DISBURSE: DisburseArgs,
    FinancialActionType.REPAY: RepayArgs,
    FinancialActionType.CONVERT: ConvertArgs,
    FinancialActionType.PAY: PayArgs,
    FinancialActionType.PLEDGE: PledgeArgs,
    FinancialActionType.RELEASE: ReleaseArgs,
    FinancialActionType.DEFER: DeferArgs,
    FinancialActionType.NO_ACTION: NoActionArgs,
}

DESCRIPTIONS: dict[FinancialActionType, str] = {
    FinancialActionType.REQUEST_ADVANCE: "Ask a lender for a revenue advance.",
    FinancialActionType.OFFER: "Offer an advance to a borrower.",
    FinancialActionType.ACCEPT: "Accept an advance request addressed to you.",
    FinancialActionType.DISBURSE: "Disburse an accepted advance.",
    FinancialActionType.REPAY: "Repay part of an advance.",
    FinancialActionType.CONVERT: "Convert an amount into another currency.",
    FinancialActionType.PAY: "Pay a counterparty or an obligation.",
    FinancialActionType.PLEDGE: "Pledge an amount as collateral.",
    FinancialActionType.RELEASE: "Release a facility, an offer or a pledge.",
    FinancialActionType.DEFER: "Defer an obligation the contract allows to defer.",
    FinancialActionType.NO_ACTION: "Take no financial action this round.",
}


def tool_schema(action: FinancialActionType) -> dict[str, Any]:
    """The OpenAI function schema the model is offered for one finance tool."""
    params = ARGS[action].model_json_schema(by_alias=True)
    params.pop("title", None)
    return {"type": "function", "function": {
        "name": action.value, "description": DESCRIPTIONS[action], "parameters": params}}


@dataclass(frozen=True)
class ToolCallError:
    """Why one tool call was refused: ``tool_not_in_mandate`` or ``malformed_tool_args``."""

    name: str
    code: str
    detail: str


def parse_tool_call(
    name: str, args: Any, mandate: Iterable[FinancialActionType]
) -> _Args | ToolCallError:
    """Validate one tool call against the actor's mandate and the tool's argument schema.

    ``args`` is an object or the JSON text a model wrote; anything that does not decode to an
    object (bad JSON, an integer too long to parse, nesting too deep) is malformed, never raised.
    """
    allowed = {a.value for a in mandate}
    if name not in allowed:
        return ToolCallError(name, "tool_not_in_mandate",
                             f"{name!r} is not one of your tools {sorted(allowed)}")
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except (ValueError, RecursionError) as error:  # JSONDecodeError is a ValueError
            return ToolCallError(name, "malformed_tool_args",
                                 f"{name}: arguments are not JSON ({str(error)[:200]})")
    if not isinstance(args, Mapping):
        return ToolCallError(name, "malformed_tool_args", f"{name}: arguments are not an object")
    try:
        return ARGS[FinancialActionType(name)].model_validate(dict(args))
    except ValidationError as error:
        detail = "; ".join(
            f"{name}.{'.'.join(str(p) for p in e['loc']) or '(args)'}: {e['msg']}"
            for e in error.errors(include_url=False)
        )
        return ToolCallError(name, "malformed_tool_args", detail)


def intent_params(args: _Args) -> dict[str, Any]:
    """C1 ``params``: the amount as Money, every other argument as given, nothing unset."""
    raw = args.model_dump(by_alias=True, exclude_none=True)
    if "amount_minor" in raw:
        amount = Amount(minor=raw.pop("amount_minor"), currency=raw.pop("currency"))
        raw["amount"] = amount.model_dump()
    return raw


# ---------------------------------------------------------------------------- the intent queue


def call_number(intent: ActionIntent) -> tuple[int, int, str]:
    """An intent's place among its actor's: (round, call) from ``i-r<round>-<actor>-<n>``.

    Read as numbers, so ``i-r4-x-2`` comes before ``i-r4-x-10``; an id of another shape sorts
    after every standard one, by its text.
    """
    found = re.fullmatch(rf"i-r(\d+)-{re.escape(intent.actor_id)}-(\d+)", intent.intent_id)
    return (int(found[1]), int(found[2]), "") if found else (MINOR_MAX, MINOR_MAX,
                                                             intent.intent_id)


def clearing_key(intent: ActionIntent) -> tuple:
    return (intent.priority_class, intent.sim_minute, intent.actor_id, call_number(intent))


class IntentQueue:
    """One branch's intents for the current round; thread- and task-safe.

    ``drain`` returns them sorted by (priority class, simulated minute, actor, call order), so the
    cleared order never depends on which agent answered first. An intent of another branch, or
    without a priority class and simulated minute, is refused.
    """

    def __init__(self, branch_id: str) -> None:
        self.branch_id = branch_id
        self._items: dict[str, ActionIntent] = {}
        self._lock = threading.Lock()

    def put(self, *intents: ActionIntent) -> None:
        """Queue every intent given, or none of them."""
        for intent in intents:
            if intent.branch_id != self.branch_id:
                raise ValueError(
                    f"intent {intent.intent_id} of branch {intent.branch_id!r} offered to the "
                    f"queue of branch {self.branch_id!r}"
                )
            if intent.priority_class is None or intent.sim_minute is None:
                raise ValueError(f"intent {intent.intent_id} has no priority class or minute")
        ids = [i.intent_id for i in intents]
        with self._lock:
            twice = sorted({i for i in ids if ids.count(i) > 1 or i in self._items})
            if twice:
                raise ValueError(f"intents {twice} are queued twice")
            self._items.update(zip(ids, intents, strict=True))

    def drain(self) -> list[ActionIntent]:
        with self._lock:
            items, self._items = self._items, {}
        return sorted(items.values(), key=clearing_key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# ------------------------------------------------------------------------------- the actor


@dataclass(frozen=True)
class Turn:
    """What one actor's intents this round are stamped with."""

    round: int
    sim_minute: int
    obs_hash: str
    evidence_ids: tuple[str, ...]


MAX_ACTOR_ID = 100


@dataclass
class FinanceActor:
    """An actor's mandate in one branch, and the turn its tool calls currently belong to."""

    actor_id: str
    branch_id: str
    tools: tuple[FinancialActionType, ...]
    priority_class: int
    turn: Turn | None = None
    _n: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        # Room for "i-r<round>-" and "-<n>" inside a C1 id of 128 characters.
        if not 1 <= len(self.actor_id) <= MAX_ACTOR_ID:
            raise ValueError(f"actor id {self.actor_id!r} is not 1 to {MAX_ACTOR_ID} characters")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError(f"{self.actor_id} names a tool twice: {list(self.tools)}")

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any], branch_id: str) -> FinanceActor:
        """From an ``actors.json`` entry; its social tools go to ``SocialAgent``, not here."""
        unknown = [t for t in spec["tools"]
                   if t not in SOCIAL_TOOLS and t not in FinancialActionType]
        if unknown:
            raise ValueError(f"{spec['actor_id']} names unknown tools {unknown}")
        tools = tuple(FinancialActionType(t) for t in spec["tools"] if t in FinancialActionType)
        return cls(spec["actor_id"], branch_id, tools, int(spec["priority_class"]))

    def begin_turn(self, turn: Turn) -> None:
        with self._lock:
            self.turn, self._n = turn, 0

    def end_turn(self) -> None:
        """Close the turn: a tool called after it (a late or failed-round writer) is refused."""
        with self._lock:
            self.turn = None

    def stamp(self, count: int = 1) -> tuple[Turn, list[str]]:
        """The current turn and the next ``count`` intent ids, read in one step."""
        with self._lock:
            if self.turn is None:
                raise RuntimeError(f"{self.actor_id} called a tool outside a turn")
            first, self._n = self._n + 1, self._n + count
            return self.turn, [f"i-r{self.turn.round}-{self.actor_id}-{n}"
                               for n in range(first, self._n + 1)]


def submit(
    queue: IntentQueue,
    actor: FinanceActor,
    calls: Iterable[tuple[FinancialActionType, _Args]],
) -> tuple[ActionIntent, ...]:
    """The handler: validated tool calls become C1 intents on the branch's queue, all or none.

    An act outside the actor's mandate is refused here, whoever the caller; ``no_action`` is
    always allowed, being the fallback.
    """
    calls = list(calls)
    for action, _ in calls:
        if action not in actor.tools and action is not FinancialActionType.NO_ACTION:
            raise ValueError(f"{action.value} is not in {actor.actor_id}'s mandate")
    turn, ids = actor.stamp(len(calls))
    intents = tuple(
        ActionIntent(
            intent_id=intent_id,
            branch_id=actor.branch_id,
            round=turn.round,
            actor_id=actor.actor_id,
            type=action.value,
            params=intent_params(args),
            evidence_ids=list(turn.evidence_ids),
            obs_hash=turn.obs_hash,
            priority_class=actor.priority_class,
            sim_minute=turn.sim_minute,
        )
        for intent_id, (action, args) in zip(ids, calls, strict=True)
    )
    queue.put(*intents)
    return intents


FinanceTool = Callable[..., str]


def make_finance_tools(queue: IntentQueue, actor: FinanceActor) -> dict[str, FinanceTool]:
    """The actor's mandate as callables bound to one branch's queue, keyed by tool name.

    A call returns ``"queued <intent_id>"`` or a structured refusal string (camel feeds a raised
    error back to the model as text anyway: oasis-seam.md S7); the guardrail validates a response
    with ``parse_tool_call`` before calling any tool, so its alert never depends on that string.
    A tool takes ``**kwargs`` (``from`` is a Python keyword), so camel cannot read its schema
    off the signature and ignores attributes: whoever hands a tool to camel wraps it as
    ``FunctionTool(tool, openai_tool_schema=tool.openai_tool_schema)``. The closures
    hold the queue, the actor and the action, and nothing else.
    """
    if queue.branch_id != actor.branch_id:
        raise ValueError(f"{actor.actor_id} of branch {actor.branch_id!r} bound to the queue "
                         f"of branch {queue.branch_id!r}")

    def bind(action: FinancialActionType) -> FinanceTool:
        def tool(**kwargs: Any) -> str:
            parsed = parse_tool_call(action.value, kwargs, actor.tools)
            if isinstance(parsed, ToolCallError):
                return f"rejected {parsed.code}: {parsed.detail}"
            (intent,) = submit(queue, actor, [(action, parsed)])
            return f"queued {intent.intent_id}"

        tool.__name__ = action.value
        tool.__doc__ = DESCRIPTIONS[action]
        tool.openai_tool_schema = tool_schema(action)
        return tool

    return {a.value: bind(a) for a in actor.tools}

"""A deterministic stand-in for the language model, driven by a tool-call plan.

A plan is a JSON list of entries ``{actor_id, round, when_seen?, tool_calls[] | content}``
plus at most one ``{default: true, ...}``. ``ScriptedModel`` is a camel model backend, so an
OASIS or camel agent built on it calls the same tools a live model would: each fresh call is
answered from the entry matching (actor, round, what the actor saw), never from call order, so
concurrent agents get the same answers in any order. Among matching entries the most specific
(the largest ``when_seen``) answers; a call no entry matches, with no default, raises
``UnexpectedModelCall``, as do a tie, an entry answered twice by one model, a tool the agent does
not offer and a tool result for a call this model never made. Every prompt is recorded on the
model and on its plan.

One plan may drive several branches, so an entry is consumed per model: a model is one actor in
one branch. What the actor saw is the ``seen_source`` it is given (the observation's evidence
ids), or else the ``when_seen`` ids written as whole tokens in its latest user message.

Selection: ``LLM_BASE_URL=scripted://<plan>`` (a name in ``plans/`` or an absolute path) through
``ScriptedPlan.from_env``, or by passing a ``ScriptedModel`` directly. ``openai_client()`` gives
the upstream ``LLMClient`` an injectable ``chat.completions.create``.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from camel.models import BaseModelBackend
from camel.models.stub_model import StubTokenCounter
from camel.types import (
    ChatCompletion,
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
    Choice,
    CompletionUsage,
    ModelType,
)
from camel.utils import BaseTokenCounter
from openai.types.chat.chat_completion_message_function_tool_call import Function

PLANS_DIR = Path(__file__).resolve().parent / "plans"
SCRIPTED_SCHEME = "scripted://"
# The text a scripted agent ends its turn with once its tool results come back.
FINISHED = "done"


class UnexpectedModelCall(AssertionError):
    """A model call the plan does not answer, or answers in a way the caller cannot take."""


class PlanError(ValueError):
    """A plan file that is malformed or ambiguous."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Mapping[str, Any]


@dataclass(frozen=True)
class PlanEntry:
    index: int
    actor_id: str | None
    round: int | None
    when_seen: frozenset[str]
    tool_calls: tuple[ToolCall, ...]
    content: str | None


@dataclass(frozen=True)
class ScriptedCall:
    """One recorded model call: who asked, when, what it saw and what it was told."""

    actor_id: str
    round: int
    messages: list[dict[str, Any]]
    tools: tuple[str, ...]
    seen: frozenset[str]
    answer: str  # "entry:<index>", "default" or "follow-up"
    tool_calls: tuple[ToolCall, ...] = field(default=())


def _parse_entry(index: int, raw: Any) -> PlanEntry:
    if not isinstance(raw, dict):
        raise PlanError(f"plan entry {index} is not an object")
    tool_calls = []
    for n, call in enumerate(raw.get("tool_calls", [])):
        if not isinstance(call, dict) or not isinstance(call.get("name"), str):
            raise PlanError(f"plan entry {index} tool call {n} has no name")
        args = call.get("args", {})
        if not isinstance(args, dict):
            raise PlanError(f"plan entry {index} tool call {n} args are not an object")
        tool_calls.append(ToolCall(call["name"], copy.deepcopy(args)))
    content = raw.get("content")
    if content is not None and not isinstance(content, str):
        raise PlanError(f"plan entry {index} content is not a string")
    if not tool_calls and content is None:
        raise PlanError(f"plan entry {index} has neither tool_calls nor content")
    if raw.get("default"):
        return PlanEntry(index, None, None, frozenset(), tuple(tool_calls), content)
    actor_id, rnd = raw.get("actor_id"), raw.get("round")
    if not isinstance(actor_id, str) or not isinstance(rnd, int) or isinstance(rnd, bool):
        raise PlanError(f"plan entry {index} needs a string actor_id and an integer round")
    seen = raw.get("when_seen", [])
    if not isinstance(seen, list) or not all(isinstance(s, str) for s in seen):
        raise PlanError(f"plan entry {index} when_seen is not a list of ids")
    return PlanEntry(index, actor_id, rnd, frozenset(seen), tuple(tool_calls), content)


def seen_in_prompt(messages: list[dict[str, Any]], ids: Iterable[str]) -> frozenset[str]:
    """The ids, among ``ids``, that appear as whole tokens in the latest user message."""

    text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, list):  # OpenAI content parts
                content = " ".join(
                    str(part.get("text", "")) for part in content if isinstance(part, dict)
                )
            text = content if isinstance(content, str) else json.dumps(content, sort_keys=True)
            break
    # Ids carry "-" and ":" (req:borrower-c:r4), so a token ends where neither continues it.
    return frozenset(
        i for i in ids
        if re.search(r"(?<![\w-])(?<!\w:)" + re.escape(i) + r"(?![\w-])(?!:\w)", text)
    )


class ScriptedPlan:
    """A loaded plan, shared by every actor's model; it records all calls across them."""

    def __init__(self, entries: list[Any], *, source: str = "<inline>") -> None:
        if not isinstance(entries, list):
            raise PlanError("a plan is a list of entries")
        self.source = source
        parsed = [_parse_entry(i, raw) for i, raw in enumerate(entries)]
        defaults = [e for e in parsed if e.actor_id is None]
        if len(defaults) > 1:
            raise PlanError("a plan has at most one default entry")
        self.default: PlanEntry | None = defaults[0] if defaults else None
        self.entries: tuple[PlanEntry, ...] = tuple(e for e in parsed if e.actor_id is not None)
        self._by_turn: dict[tuple[str, int], list[PlanEntry]] = {}
        for entry in self.entries:
            turn = self._by_turn.setdefault((entry.actor_id, entry.round), [])
            if any(other.when_seen == entry.when_seen for other in turn):
                raise PlanError("two plan entries share actor, round and when_seen")
            turn.append(entry)
        self._lock = threading.Lock()
        self.calls: list[ScriptedCall] = []

    @classmethod
    def load(cls, path: str | Path) -> ScriptedPlan:
        """Load a plan file: a bare list, or an object carrying the list under ``plan``."""

        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["plan"] if isinstance(data, dict) else data, source=str(path))

    @classmethod
    def from_url(cls, url: str) -> ScriptedPlan:
        if not url.startswith(SCRIPTED_SCHEME):
            raise PlanError(f"not a scripted model url: {url!r}")
        ref = url[len(SCRIPTED_SCHEME):]
        if not ref:
            raise PlanError("scripted:// needs a plan name or an absolute path")
        if ref.startswith("/"):
            return cls.load(ref)
        if "/" in ref or "\\" in ref or ref.startswith("."):
            raise PlanError(f"a plan name is a file in plans/, not a path: {ref!r}")
        name = ref if ref.endswith(".json") else f"{ref}.json"
        return cls.load(PLANS_DIR / name)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ScriptedPlan | None:
        """The plan ``LLM_BASE_URL`` selects, or None when it names a live endpoint."""

        url = (os.environ if environ is None else environ).get("LLM_BASE_URL", "")
        return cls.from_url(url) if url.startswith(SCRIPTED_SCHEME) else None

    def model(
        self,
        actor_id: str,
        round_source: Callable[[], int],
        *,
        seen_source: Callable[[list[dict[str, Any]]], Iterable[str]] | None = None,
    ) -> ScriptedModel:
        return ScriptedModel(self, actor_id, round_source, seen_source=seen_source)

    def candidates(self, actor_id: str, rnd: int) -> list[PlanEntry]:
        return self._by_turn.get((actor_id, rnd), [])

    def record(self, call: ScriptedCall) -> None:
        with self._lock:
            self.calls.append(call)


class _PromptTokenCounter(StubTokenCounter):
    """Camel's stub counter, but scaled to the prompt so context trimming behaves as live."""

    def count_tokens_from_messages(self, messages: list[dict[str, Any]]) -> int:
        return sum(len(str(m.get("content") or "")) // 4 + 1 for m in messages)


def _tool_names(tools: list[dict[str, Any]] | None) -> tuple[str, ...]:
    names = []
    for tool in tools or []:
        function = tool.get("function", tool) if isinstance(tool, dict) else {}
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return tuple(names)


class ScriptedModel(BaseModelBackend):
    """A camel model backend that answers one actor's calls from a ``ScriptedPlan``."""

    def __init__(
        self,
        plan: ScriptedPlan,
        actor_id: str,
        round_source: Callable[[], int],
        *,
        seen_source: Callable[[list[dict[str, Any]]], Iterable[str]] | None = None,
    ) -> None:
        super().__init__(ModelType.STUB, {}, None, None, _PromptTokenCounter())
        self.plan = plan
        self.actor_id = actor_id
        self.round_source = round_source
        self.seen_source = seen_source
        self.calls: list[ScriptedCall] = []
        self._used: set[int] = set()
        self._pending: set[str] = set()  # tool-call ids issued and not yet answered
        self._lock = threading.Lock()

    @property
    def token_counter(self) -> BaseTokenCounter:
        return self._token_counter

    def _run(self, messages, response_format=None, tools=None) -> ChatCompletion:
        return self._answer(messages, tools)

    async def _arun(self, messages, response_format=None, tools=None) -> ChatCompletion:
        return self._answer(messages, tools)

    def _seen(self, messages: list[dict[str, Any]], candidates: list[PlanEntry]) -> frozenset:
        if self.seen_source is not None:
            return frozenset(self.seen_source(messages))
        ids = set().union(*(e.when_seen for e in candidates))
        return seen_in_prompt(messages, ids) if ids else frozenset()

    def _answer(self, messages: list[dict[str, Any]], tools) -> ChatCompletion:
        rnd = int(self.round_source())
        offered = _tool_names(tools)
        snapshot = copy.deepcopy(list(messages))
        with self._lock:
            seq = len(self.calls) + 1
            # The agent sent back the results of the tool calls it was given: end the turn.
            if snapshot and snapshot[-1].get("role") == "tool":
                call_id = snapshot[-1].get("tool_call_id")
                if call_id not in self._pending:
                    raise UnexpectedModelCall(
                        f"{self.actor_id} round {rnd}: a tool result for {call_id!r}, which "
                        "this model has no open call for"
                    )
                self._pending.clear()
                return self._finish(rnd, seq, snapshot, offered, frozenset(), "follow-up", None)
            candidates = self.plan.candidates(self.actor_id, rnd)
            seen = self._seen(snapshot, candidates)
            matched = [e for e in candidates if e.when_seen <= seen]
            best = [e for e in matched if all(o.when_seen <= e.when_seen for o in matched)]
            if matched and len(best) != 1:
                raise UnexpectedModelCall(
                    f"{self.actor_id} round {rnd}: plan entries "
                    f"{[e.index for e in matched]} all match what it saw {sorted(seen)}"
                )
            if matched:
                entry, answer = best[0], f"entry:{best[0].index}"
                if entry.index in self._used:
                    raise UnexpectedModelCall(
                        f"{self.actor_id} round {rnd}: plan entry {entry.index} already answered"
                    )
                self._used.add(entry.index)
            elif self.plan.default is not None:
                entry, answer = self.plan.default, "default"
            else:
                raise UnexpectedModelCall(
                    f"{self.actor_id} round {rnd}: no plan entry matches what it saw "
                    f"{sorted(seen)} and the plan has no default ({self.plan.source})"
                )
            missing = [c.name for c in entry.tool_calls if c.name not in offered]
            if missing:
                raise UnexpectedModelCall(
                    f"{self.actor_id} round {rnd}: the plan calls {missing} but the agent "
                    f"offers {list(offered)}"
                )
            return self._finish(rnd, seq, snapshot, offered, seen, answer, entry)

    def _finish(self, rnd, seq, messages, offered, seen, answer, entry) -> ChatCompletion:
        tool_calls = entry.tool_calls if entry else ()
        call = ScriptedCall(self.actor_id, rnd, messages, offered, seen, answer, tool_calls)
        self.calls.append(call)
        self.plan.record(call)
        call_ids = [f"call-r{rnd}-{self.actor_id}-{n}" for n in range(1, len(tool_calls) + 1)]
        self._pending.update(call_ids)
        message = ChatCompletionMessage(
            role="assistant",
            content=FINISHED if entry is None else entry.content,
            tool_calls=[
                ChatCompletionMessageFunctionToolCall(
                    id=call_id,
                    type="function",
                    function=Function(
                        name=c.name,
                        arguments=json.dumps(c.args, sort_keys=True, separators=(",", ":")),
                    ),
                )
                for call_id, c in zip(call_ids, tool_calls, strict=True)
            ]
            or None,
        )
        prompt_tokens = self.count_tokens_from_messages(messages)
        return ChatCompletion(
            id=f"scripted-r{rnd}-{self.actor_id}-{seq}",
            object="chat.completion",
            created=0,
            model="scripted",
            choices=[
                Choice(
                    index=0,
                    message=message,
                    finish_reason="tool_calls" if tool_calls else "stop",
                    logprobs=None,
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=prompt_tokens, completion_tokens=1, total_tokens=prompt_tokens + 1
            ),
        )

    def openai_client(self) -> SimpleNamespace:
        """An object with ``chat.completions.create`` for the upstream ``LLMClient.client``."""

        def create(*, messages, tools=None, **_ignored) -> ChatCompletion:
            return self.run(list(messages), tools=tools)

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

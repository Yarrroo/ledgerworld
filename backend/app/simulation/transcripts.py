"""Per-branch model transcripts, and a model that replays one with no live model behind it.

A ``Transcript`` is append-only: one ``ModelCall`` per actor per round, holding the hash of what
the actor was shown (``obs_hash``) and what the model answered (its tool calls, or text). It
serialises as canonical JSONL, one call per line, and can mirror every append to a file.

``ReplayModel`` is a ``ScriptedModel`` whose plan is built from a transcript's calls: no default
answer, each call answerable once, keyed on (actor, round). Before answering it checks that the
actor is shown what it was shown when the call was recorded; a call the transcript does not hold,
a second call in one round, or a different ``obs_hash`` raises ``ReplayMiss``, an
``UnexpectedModelCall``. A replay therefore either re-serves exactly what was recorded or fails.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..testing.fake_graph_memory import namespace_for
from ..testing.scripted_model import ScriptedModel, ScriptedPlan, ToolCall, UnexpectedModelCall

__all__ = ["ModelCall", "ReplayMiss", "ReplayModel", "Transcript"]


class ReplayMiss(UnexpectedModelCall):
    """A replayed model call the transcript does not hold, or holds for another observation."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ModelCall:
    """One recorded model response: who, when, what it was shown, and what it answered."""

    round: int
    actor_id: str
    obs_hash: str
    tool_calls: tuple[ToolCall, ...]
    content: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "actor_id": self.actor_id,
            "obs_hash": self.obs_hash,
            "tool_calls": [{"name": c.name, "args": dict(c.args)} for c in self.tool_calls],
            "content": self.content,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> ModelCall:
        return cls(
            raw["round"], raw["actor_id"], raw["obs_hash"],
            tuple(ToolCall(c["name"], c["args"]) for c in raw["tool_calls"]), raw.get("content"),
        )


def _tool_call(call: ToolCall | Mapping[str, Any]) -> ToolCall:
    if isinstance(call, ToolCall):
        name, args = call.name, call.args
    else:
        name, args = call.get("name"), call.get("args", {})
    if not isinstance(name, str) or not isinstance(args, Mapping):
        raise TypeError(f"a tool call needs a string name and object args, got {call!r}")
    # A round trip through JSON: what is recorded is exactly what a replay serves.
    return ToolCall(name, json.loads(_canonical(dict(args))))


class Transcript:
    """The append-only record of every model call one branch made."""

    def __init__(
        self, world_id: str, branch_id: str, *, path: str | Path | None = None,
        calls: Iterable[ModelCall] = (),
    ) -> None:
        self.world_id = world_id
        self.branch_id = branch_id
        self.namespace = namespace_for(world_id, branch_id)
        self.path = Path(path) if path is not None else None
        self._calls: list[ModelCall] = []
        self._turns: set[tuple[str, int]] = set()
        self._lock = threading.Lock()
        for call in calls:
            self._append(call, persist=False)

    @classmethod
    def load(cls, path: str | Path, world_id: str, branch_id: str) -> Transcript:
        """A transcript read back from its JSONL file; later appends go to the same file."""

        path = Path(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        calls = [ModelCall.from_json(json.loads(line)) for line in lines if line]
        return cls(world_id, branch_id, path=path, calls=calls)

    def record(
        self, round_: int, actor_id: str, obs_hash: str,
        tool_calls: Iterable[ToolCall | Mapping[str, Any]] = (), content: str | None = None,
    ) -> ModelCall:
        """Append the model's answer to ``actor_id`` in ``round_`` (one per actor per round)."""

        if not isinstance(round_, int) or isinstance(round_, bool) or round_ < 0:
            raise ValueError(f"round must be a non-negative integer, got {round_!r}")
        if not isinstance(obs_hash, str) or not obs_hash:
            raise ValueError("a model call is recorded with the hash of what the actor saw")
        calls = tuple(_tool_call(c) for c in tool_calls)
        if not calls and content is None:
            raise ValueError("a model call answers with tool calls or content")
        return self._append(ModelCall(round_, actor_id, obs_hash, calls, content), persist=True)

    def _append(self, call: ModelCall, *, persist: bool) -> ModelCall:
        with self._lock:
            turn = (call.actor_id, call.round)
            if turn in self._turns:
                raise ValueError(f"{self.namespace}: {call.actor_id} already answered round "
                                 f"{call.round}")
            if self._calls and call.round < self._calls[-1].round:
                raise ValueError(f"{self.namespace}: round {call.round} recorded after round "
                                 f"{self._calls[-1].round}")
            if persist and self.path is not None:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(_canonical(call.to_json()) + "\n")
            self._turns.add(turn)
            self._calls.append(call)
            return call

    @property
    def cursor(self) -> int:
        """How many calls are recorded; a checkpoint pins it."""

        with self._lock:
            return len(self._calls)

    def calls(self, start: int = 0) -> tuple[ModelCall, ...]:
        with self._lock:
            return tuple(self._calls[start:])

    def to_jsonl(self) -> bytes:
        return "".join(_canonical(c.to_json()) + "\n" for c in self.calls()).encode()

    def fork(self, branch_id: str, cursor: int, *, path: str | Path | None = None) -> Transcript:
        """A child branch's transcript, starting from this one's first ``cursor`` calls."""

        if not 0 <= cursor <= self.cursor:
            raise ValueError(f"cursor {cursor} outside 0..{self.cursor}")
        child = Transcript(self.world_id, branch_id, path=path,
                           calls=self.calls()[:cursor])
        if child.path is not None:
            child.path.write_bytes(child.to_jsonl())
        return child

    def replay_plan(self, start: int = 0) -> ScriptedPlan:
        """A strict plan (no default) answering every call from ``start`` on, once each."""

        entries = []
        for call in self.calls(start):
            entry: dict[str, Any] = {
                "actor_id": call.actor_id, "round": call.round,
                "tool_calls": [{"name": c.name, "args": dict(c.args)} for c in call.tool_calls],
            }
            if call.content is not None:
                entry["content"] = call.content
            entries.append(entry)
        return ScriptedPlan(entries, source=f"transcript {self.namespace}")

    def replay_model(
        self, actor_id: str, round_source: Callable[[], int], obs_hash_source: Callable[[], str],
        *, start: int = 0, plan: ScriptedPlan | None = None,
    ) -> ReplayModel:
        """One actor's replay model; pass one ``plan`` to every actor of a replayed branch."""

        return ReplayModel(
            self, plan or self.replay_plan(start), actor_id, round_source, obs_hash_source,
            start=start,
        )


class ReplayModel(ScriptedModel):
    """Serves one actor's recorded answers back and raises on anything the transcript lacks."""

    def __init__(
        self, transcript: Transcript, plan: ScriptedPlan, actor_id: str,
        round_source: Callable[[], int], obs_hash_source: Callable[[], str], *, start: int = 0,
    ) -> None:
        super().__init__(plan, actor_id, round_source)
        self.obs_hash_source = obs_hash_source
        self.recorded = {
            c.round: c for c in transcript.calls(start) if c.actor_id == actor_id
        }

    def _answer(self, messages, tools):
        follow_up = bool(messages) and messages[-1].get("role") == "tool"
        if not follow_up:
            rnd = int(self.round_source())
            call = self.recorded.get(rnd)
            if call is None:
                raise ReplayMiss(f"{self.actor_id} round {rnd}: no call in the transcript")
            seen = self.obs_hash_source()
            if seen != call.obs_hash:
                raise ReplayMiss(
                    f"{self.actor_id} round {rnd}: shown {seen}, recorded {call.obs_hash}"
                )
        try:
            return super()._answer(messages, tools)
        except ReplayMiss:
            raise
        except UnexpectedModelCall as exc:
            raise ReplayMiss(str(exc)) from exc

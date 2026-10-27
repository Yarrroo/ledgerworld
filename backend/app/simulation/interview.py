"""A read-only interview of one actor, from its own memory and its own transcript (system brief §7.1).

``Interview.open`` copies, once, what one actor of one branch remembers (its records in the
branch's ``BranchMemory``) and what it answered (its calls in the branch's ``Transcript``), each up
to and including ``as_of_round``, into frozen tuples. The session keeps no reference to the
memory, the transcript, the world, the ledger or the intent queue, so it has nothing to write
through: asking a question changes no state anywhere. Another actor's records and calls and
anything after ``as_of_round`` are never copied, so the model cannot be shown them.

``ask`` puts the question to a model with no tool offered. An answer that carries a tool call is
refused with ``ReadOnlyViolation``; an interview never becomes an intent. ``Interview.from_world``
interviews a world's actor as of its last committed round, from the world's own transcript.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..decisions.nonanticipativity import canonical
from .memory import BranchMemory, MemoryRecord, NamespaceViolation
from .transcripts import ModelCall, Transcript

__all__ = ["Interview", "InterviewAnswer", "ReadOnlyViolation"]

SYSTEM_PROMPT = (
    "You are {actor_id}, interviewed about your own past decisions as of round {as_of_round}. "
    "Answer only from the history below: your own memory and your own recorded answers. "
    "You cannot act; no tool is available."
)


class ReadOnlyViolation(PermissionError):
    """An interview answer that tried to act."""


@dataclass(frozen=True)
class InterviewAnswer:
    """One answer, with the hash of exactly what the model was shown."""

    actor_id: str
    namespace: str
    as_of_round: int
    question: str
    answer: str
    context_hash: str


@dataclass(frozen=True)
class Interview:
    """One actor's own history in one branch, pinned at ``as_of_round``; read-only."""

    actor_id: str
    namespace: str
    as_of_round: int
    memory: tuple[MemoryRecord, ...]
    calls: tuple[ModelCall, ...]

    @classmethod
    def open(
        cls, memory: BranchMemory, transcript: Transcript, actor_id: str, *, as_of_round: int
    ) -> Interview:
        if memory.namespace != transcript.namespace:
            raise NamespaceViolation(
                f"memory {memory.namespace} and transcript {transcript.namespace} differ"
            )
        if not isinstance(actor_id, str) or not actor_id:
            raise ValueError(f"an interview names its actor, got {actor_id!r}")
        if not isinstance(as_of_round, int) or isinstance(as_of_round, bool) or as_of_round < 0:
            raise ValueError(f"as_of_round must be a non-negative integer, got {as_of_round!r}")
        return cls(
            actor_id,
            memory.namespace,
            as_of_round,
            tuple(r for r in memory.retrieve(actor_id=actor_id) if r.round <= as_of_round),
            tuple(c for c in transcript.calls()
                  if c.actor_id == actor_id and c.round <= as_of_round),
        )

    @classmethod
    def from_world(cls, world: Any, memory: BranchMemory, actor_id: str) -> Interview:
        """A world's actor, as of the world's last committed round."""

        if actor_id not in world.actors:
            raise LookupError(f"{world.world_id}/{world.branch_id} has no actor {actor_id}")
        return cls.open(memory, world.transcript, actor_id, as_of_round=world.committed_round)

    def context(self) -> dict[str, Any]:
        """Everything the model is shown besides the question."""

        return {
            "actor_id": self.actor_id,
            "as_of_round": self.as_of_round,
            "memory": [{"round": r.round, "key": r.key, "value": r.value} for r in self.memory],
            "answers": [
                {k: v for k, v in c.to_json().items() if k not in ("actor_id", "obs_hash")}
                for c in self.calls
            ],
        }

    def messages(self, question: str) -> list[dict[str, str]]:
        system = SYSTEM_PROMPT.format(actor_id=self.actor_id, as_of_round=self.as_of_round)
        user = canonical({"history": self.context(), "question": question})
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def ask(self, model: Any, question: str) -> InterviewAnswer:
        """Put ``question`` to ``model`` (a camel model backend) with no tool offered."""

        if not isinstance(question, str) or not question.strip():
            raise ValueError("an interview question is non-empty text")
        messages = self.messages(question)
        message = model.run(messages).choices[0].message
        if message.tool_calls:
            names = [c.function.name for c in message.tool_calls]
            raise ReadOnlyViolation(f"{self.actor_id} tried to call {names} in an interview")
        if not isinstance(message.content, str):
            raise TypeError(f"{self.actor_id} gave no text answer")
        return InterviewAnswer(
            self.actor_id, self.namespace, self.as_of_round, question, message.content,
            hashlib.sha256(messages[1]["content"].encode()).hexdigest(),
        )

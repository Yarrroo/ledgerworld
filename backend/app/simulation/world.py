"""The coupled world of one branch: actors, ledger, OASIS platform and one clock (system brief §7).

A ``World`` owns everything a round changes: the ledger store, the OASIS env (one SQLite file
per branch, a TWITTER-type platform so ``env.step`` advances its clock), one ``IntentQueue``, one
``FinanceAgent`` per model actor, the model ``Transcript`` and ``WorldState``, the plain data the
coordinator keeps between rounds (world items, advance requests, pending inflow statuses, the C2
results still to deliver, the scheduled-event cursor, the committed intents and round records).
``Coordinator.run_round`` drives the ten steps of §7.2 over it.

Conventions: an actor's ledger entity is its ``actor_id`` and it acts from ``<actor>/operating``;
a scheduled event is ``{round, kind, ...}`` with kind ``public_post`` (``post_id``, ``author``,
``text``), ``delay_receipt`` (``flow_id``, ``delay_h``), ``message`` (``id``, ``to``, ``text``) or
``observe`` (``account``, ``observability``); an event naming a ``branch`` is delivered only in
that branch. Graph memory is not in the round loop (HANDOFF); an actor's memory is its agent's.

``capture()`` pins every component a round can change, before step 1; ``restore()`` puts them
back and ``fingerprint()`` digests each, so a restoration is checked rather than trusted.
Each world draws from its own ``random.Random``, OASIS's draws included (``oasis_finance.rng``),
so a sibling world in the same process never moves its stream. Importing ``oasis`` writes
``./log`` in the working directory (oasis-seam.md S13), so it is imported on first use from a
temporary directory.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import random
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

from oasis_finance.actions import decode_args
from oasis_finance.observation import DEFAULT_EPOCH
from oasis_finance.rng import WORLD_RNG, route_oasis_random
from sqlalchemy import Connection, select

from ..finance import ledger
from ..finance.lending import capacity
from ..finance.models import journals
from ..finance.schemas import Snapshot
from ..finance.store import LedgerStore
from ..testing.scripted_model import ScriptedModel
from .actions import IntentQueue, build_finance_agent
from .clock import Clock
from .observations import Observation, build_observation
from .transcripts import ModelCall, Transcript

__all__ = ["Capture", "World", "WorldState", "WorldUnusable", "due_hour", "hours_of",
           "import_oasis"]

TRANSIT = "in-transit"  # a borrower's cash account an advance waits in until the next boundary
ModelFactory = Callable[[str, "World"], Any]


class WorldUnusable(RuntimeError):
    """A failed round could not be shown to have stopped every writer; this world is spent."""


def import_oasis() -> SimpleNamespace:
    """The OASIS names the world uses, imported from a temporary directory the first time."""
    if "oasis.environment.env" not in sys.modules:
        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp(prefix="oasis-log-"))
        try:
            import oasis  # noqa: F401
        finally:
            os.chdir(cwd)
    from oasis import AgentGraph, LLMAction, Platform
    from oasis.environment.env import OasisEnv
    from oasis.social_platform.typing import ActionType

    route_oasis_random()
    return SimpleNamespace(AgentGraph=AgentGraph, LLMAction=LLMAction, Platform=Platform,
                           OasisEnv=OasisEnv, ActionType=ActionType)


def hours_of(when: datetime, epoch: datetime) -> int:
    """Whole simulated hours from the epoch, rounded down."""
    return (when - epoch) // timedelta(hours=1)


def due_hour(when: datetime, epoch: datetime) -> int:
    """The first whole simulated hour at or after ``when``: a promise for 04:30 is not yet due
    at 04:00."""
    return -((epoch - when) // timedelta(hours=1))


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class WorldState:
    """What the coordinator keeps between rounds, as plain data; a capture deep-copies it."""

    items: list[dict] = field(default_factory=list)  # posts, messages, prices, requests
    requests: dict[str, dict] = field(default_factory=dict)  # advance requests by id
    expected_h: dict[str, int] = field(default_factory=dict)  # a pending_in's promised hour
    flow_status: dict[str, str] = field(default_factory=dict)  # expected | overdue | arrived
    arrivals: dict[str, dict] = field(default_factory=dict)  # advance inflows in transit
    pending_c2: list[dict] = field(default_factory=list)  # last round's C2, delivered next
    event_cursor: int = 0
    post_cursor: int = 0  # the last OASIS post id already a world item
    intents: dict[str, dict] = field(default_factory=dict)  # committed C1, for the trace
    rounds: list[dict] = field(default_factory=list)  # committed round records
    deliveries: list[str] = field(default_factory=list)  # scheduled event ids delivered


def _fingerprint(*, ledger: str, sqlite_dump: str, memory: Mapping[str, list[dict]],
                 round_: int, time_step: int | None, rng: tuple, state: WorldState,
                 queued: int, transcript: Transcript) -> dict[str, str]:
    """One digest per captured component (round-rollback.json ``round_start_capture``)."""
    return {
        "ledger": ledger,
        "OASIS SQLite": hashlib.sha256(sqlite_dump.encode()).hexdigest(),
        "actor memory records": _digest(memory),
        "world and OASIS clocks": f"{round_}/{'-' if time_step is None else time_step}",
        "RNG state": _digest(rng),
        "scheduled-event cursor": str(state.event_cursor),
        "pending C2 deliveries": _digest(state.pending_c2),
        "intent queue": str(queued),
        "transcript cursor": f"{transcript.cursor}/{len(state.rounds)}/"
                             + hashlib.sha256(transcript.to_jsonl()).hexdigest(),
        "world state": _digest(asdict(state)),
    }


@dataclass(frozen=True)
class Capture:
    """Every component of a world at a round boundary (round-rollback.json round_start_capture).

    The ledger is pinned by its digest (the round's transaction rolls it back); every other
    component by a copy, so the fingerprint is computed from the copies only when it is asked
    for, which is on an aborted round.
    """

    world_id: str
    branch_id: str
    round: int
    ledger: str
    sqlite: sqlite3.Connection | None
    memory: dict[str, list[dict]]
    agents: dict[str, tuple]
    models: dict[str, list[tuple[set, set]]]
    oasis_time_step: int | None
    rng: tuple
    state: WorldState
    transcript: tuple[ModelCall, ...]

    @cached_property
    def fingerprint(self) -> dict[str, str]:
        return _fingerprint(
            ledger=self.ledger,
            sqlite_dump="\n".join(self.sqlite.iterdump()) if self.sqlite is not None else "",
            memory=self.memory, round_=self.round, time_step=self.oasis_time_step,
            rng=self.rng, state=self.state, queued=0,
            transcript=Transcript(self.world_id, self.branch_id, calls=self.transcript))


class World:
    """One branch of the coupled world; ``async with`` it to start and stop its platform.

    ``model(actor_id, world)`` gives each model actor (``llm: true``) its model backend;
    ``store``, when given, is an empty ledger the snapshot is loaded into.
    """

    def __init__(
        self,
        world_id: str,
        branch_id: str,
        snapshot: Snapshot | Mapping[str, Any],
        actors: Iterable[Mapping[str, Any]],
        *,
        model: ModelFactory,
        workdir: str | Path,
        scenario: Sequence[Mapping[str, Any]] = (),
        store: LedgerStore | None = None,
        seed: int = 0,
        epoch: datetime = DEFAULT_EPOCH,
        coordinator: Any = None,
    ) -> None:
        from .coordinator import Coordinator

        self.world_id = world_id
        self.branch_id = branch_id
        self.snapshot = snapshot if isinstance(snapshot, Snapshot) \
            else Snapshot.model_validate(snapshot)
        self.actors = {a["actor_id"]: dict(a) for a in actors}
        self.events = sorted((dict(e) for e in scenario
                              if e.get("branch") in (None, branch_id)),
                             key=lambda e: e["round"])
        self.clock = Clock(epoch=epoch)
        # This world's own stream, OASIS's draws included. Its tasks hold this object, so it is
        # only ever reseeded or restored in place, never replaced.
        self.rng = random.Random(seed)
        self.store = store or LedgerStore("sqlite://")
        ledger.from_snapshot(self.store, self.snapshot)
        self.queue = IntentQueue(branch_id)
        self.transcript = Transcript(world_id, branch_id)
        self.state = WorldState()
        for account in self.snapshot.accounts:
            for flow in account.buckets.pending_in:
                self.state.expected_h[flow.flow_id] = due_hour(flow.expected_at, epoch)
                self.state.flow_status[flow.flow_id] = "expected"
        model_actors = [a for a in self.actors.values() if a.get("llm")]
        self.agents = {
            a["actor_id"]: build_finance_agent(a, n, self.queue, model=model(a["actor_id"], self))
            for n, a in enumerate(model_actors)
        }
        self.agent_actor = {agent.social_agent_id: actor_id
                            for actor_id, agent in self.agents.items()}
        self.db_path = Path(workdir) / f"{branch_id}.db"
        self.env: Any = None
        self.oasis: SimpleNamespace | None = None
        self.coordinator = coordinator or Coordinator()
        self.committed_round = 0
        self.unusable: str | None = None
        self.failures: list[dict] = []  # failed-round diagnostics, never committed history
        self.lifecycle: list[tuple[str, str]] = []

    # ------------------------------------------------------------------------- the platform

    async def start(self) -> Self:
        if self.db_path.exists():
            raise FileExistsError(f"{self.db_path}: a branch's platform starts from no file")
        self.oasis = import_oasis()
        graph = self.oasis.AgentGraph()
        for agent in self.agents.values():
            graph.add_agent(agent)
        platform = self.oasis.Platform(db_path=str(self.db_path), recsys_type="random")
        self.env = self.oasis.OasisEnv(graph, platform, database_path=str(self.db_path))
        # The platform's task, created here, draws from this world's RNG for its whole life
        # (oasis_finance.rng); a round's own draws are given it by the coordinator.
        token = WORLD_RNG.set(self.rng)
        try:
            await self.env.reset()
        finally:
            WORLD_RNG.reset(token)
        platform.sandbox_clock.time_step = self.clock.round
        return self

    async def close(self) -> None:
        if self.env is not None and not self.env.platform_task.done():
            await self.env.close()

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def platform(self) -> Any:
        return self.env.platform if self.env is not None else None

    async def run(self, rounds: int) -> list:
        """Run ``rounds`` rounds, each whole or not at all; returns their ``RoundResult``s."""
        return [await self.coordinator.run_round(self) for _ in range(rounds)]

    # ----------------------------------------------------------------------- ledger helpers

    def operating(self, actor_id: str) -> str:
        return f"{actor_id}/operating"

    def due_events(self) -> list[dict]:
        """The scheduled events of the current round, advancing the cursor past them."""
        due = []
        while (self.state.event_cursor < len(self.events)
               and self.events[self.state.event_cursor]["round"] <= self.clock.round):
            due.append(self.events[self.state.event_cursor])
            self.state.event_cursor += 1
        return due

    # ----------------------------------------------------------------------- observations

    def items_for(self, conn: Connection) -> list[dict]:
        """The world's items at the current round: ledger state of every actor, posts, messages
        and the C2 results of the last round (delivered once, this round)."""
        t = self.clock.t_hours
        now = self.clock.now
        epoch = self.clock.epoch
        items: list[dict] = []
        accounts = self.store.rows("accounts", conn=conn)
        for row in accounts:
            if row["kind"] != "cash" or row["entity_id"] not in self.actors \
                    or row["account_id"].endswith(f"/{TRANSIT}"):
                continue  # an advance in transit is shown once, as its pending_in
            view = self.store.view(row["account_id"], conn=conn)
            known = view.observability == "known"
            items.append({
                "id": f"acct:{view.account_id}", "kind": "account", "owner": view.entity_id,
                "visible_from_h": 0, "account": view.account_id, "currency": view.currency,
                "observability": view.observability,
                "settled_minor": view.settled_minor if known else None,
                "reserved_minor": view.reserved_minor, "pledged_minor": view.pledged_minor,
                "floor_minor": view.floor_minor,
                # Promised times err on the cautious side: an inflow is due at the next whole
                # hour, an outflow or obligation at the hour it falls in.
                "pending_in": [{"flow_id": f.flow_id, "amount_minor": f.amount_minor,
                                "expected_h": self.state.expected_h.get(
                                    f.flow_id, due_hour(f.at, epoch)),
                                "status": self.state.flow_status.get(f.flow_id, "expected")}
                               for f in view.pending_in],
                "pending_out": [{"flow_id": f.flow_id, "amount_minor": f.amount_minor,
                                 "due_h": hours_of(f.at, epoch)} for f in view.pending_out],
                "obligations": [{"obligation_id": d.obligation_id, "amount_minor": d.amount_minor,
                                 "due_h": hours_of(d.at, epoch)} for d in view.obligations],
            })
        for pool in self.store.rows("lending_pools", conn=conn):
            if pool["pool_entity_id"] in self.actors:
                cap = capacity(self.store, pool["pool_entity_id"], now, conn=conn)
                items.append({"id": f"capacity:{cap.pool}", "kind": "account", "owner": cap.pool,
                              "visible_from_h": 0, "currency": cap.currency, "K_p": cap.K_p,
                              "authority": cap.authority})
        for f in self.store.rows("facilities", conn=conn):
            items.append({"id": f"contract:{f['facility_id']}", "kind": "contract",
                          "parties": [f["pool_entity_id"], f["borrower_entity_id"]],
                          "visible_from_h": 0, "facility_id": f["facility_id"],
                          "facility_kind": f["kind"], "state": f["state"],
                          "limit_minor": f["limit_minor"], "currency": f["currency"]})
        items += self.state.items  # read, never written, by the observation builder
        # A verdict's id is its place among its actor's verdicts, not its intent id: an intent
        # id at the 128-character limit, or one repeated in the round, would make the id too
        # long or shared and fail the actor's observation. The intent id stays as data.
        n: dict[str, int] = {}
        for c in self.state.pending_c2:
            n[c["actor_id"]] = n.get(c["actor_id"], 0) + 1
            items.append({"id": f"c2:r{c['round']}-{n[c['actor_id']]}", "kind": "message",
                          "to": c["actor_id"], "visible_from_h": t,
                          **{k: v for k, v in c.items() if k != "actor_id"}})
        return items

    def observe_all(self, conn: Connection) -> dict[str, Observation]:
        """§7.2 step 4: each model actor's scoped observation, given to its agent."""
        items = self.items_for(conn)
        observations = {}
        for actor_id, agent in self.agents.items():
            obs = build_observation(self.actors[actor_id], items, self.clock.round,
                                    self.clock.t_hours, self.clock.epoch)
            agent.observe(obs)
            observations[actor_id] = obs
        return observations

    # ------------------------------------------------------------------------ social side

    async def publish(self, posts: Iterable[Mapping[str, Any]]) -> None:
        """§7.2 step 3: each scheduled post goes on the platform (as its author, when the
        author is an agent) and becomes a public world item."""
        for post in posts:
            author = post.get("author")
            agent = self.agents.get(author)
            if agent is not None:
                result = await agent.perform_action_by_data(
                    self.oasis.ActionType.CREATE_POST, content=post["text"])
                if not isinstance(result, dict) or not result.get("success"):
                    raise RuntimeError(f"post {post['post_id']} was refused: {result!r}")
                self.state.post_cursor = max(self.state.post_cursor, int(result["post_id"]))
            self.state.items.append({"id": post["post_id"], "kind": "public_post",
                                     "owner": author, "visible_from_h": self.clock.t_hours,
                                     "text": post["text"]})

    def ingest_posts(self) -> None:
        """The posts agents made in step 5, as public world items from the next observation."""
        rows = self.platform.db.execute(
            "SELECT post_id, user_id, content FROM post WHERE post_id > ? ORDER BY post_id",
            (self.state.post_cursor,)).fetchall()
        for post_id, user_id, content in rows:
            self.state.items.append({"id": f"post-{post_id}", "kind": "public_post",
                                     "owner": self.agent_actor.get(user_id, f"user-{user_id}"),
                                     "visible_from_h": self.clock.t_hours, "text": content})
            self.state.post_cursor = post_id

    def round_tool_calls(self) -> dict[str, list[dict]]:
        """What each agent's model answered this round, as the transcript records it.

        A turn that fell back to ``no_action`` is recorded as that fallback, so a replay queues
        the same intent.
        """
        calls = {}
        for actor_id, agent in self.agents.items():
            turn = agent.last_turn
            if turn is None:
                raise RuntimeError(f"{actor_id} did not act in round {self.clock.round}")
            if turn.calls:
                calls[actor_id] = [{"name": c.name, "args": dict(decode_args(c.name, c.arguments))}
                                   for c in turn.calls]
            else:
                calls[actor_id] = [{"name": i.type, "args": i.params.model_dump(
                    mode="json", exclude_none=True)} for i in turn.intents]
        return calls

    # ---------------------------------------------------------------- admission, quiescence

    def close_admission(self) -> None:
        """No tool call is accepted after this: every actor's turn ends."""
        for agent in self.agents.values():
            agent.finance_actor.end_turn()
        self.lifecycle.append(("admission_closed", f"round {self.clock.round}"))

    async def fence_platform(self, timeout_s: float) -> bool:
        """Wait until the platform has processed every action sent before now.

        The platform answers its channel in order, so one round trip of a read-only action
        proves every earlier write landed. A dead platform has no writer left, but cannot go on.
        """
        if self.env is None:
            return True
        if self.env.platform_task.done():
            return False
        channel = self.env.channel
        message_id = await channel.write_to_receive_queue(
            (None, None, self.oasis.ActionType.UPDATE_REC_TABLE))
        try:
            await asyncio.wait_for(channel.read_from_send_queue(message_id), timeout_s)
        except TimeoutError:
            return False
        self.lifecycle.append(("platform_fenced", f"round {self.clock.round}"))
        return True

    # ------------------------------------------------------------------- capture, restore

    def _memory(self, agent: Any) -> Any:
        return agent.memory._chat_history_block.storage

    @staticmethod
    def _scripted(agent: Any) -> list[ScriptedModel]:
        """A scripted model's answered entries are round state (each entry answers once); a
        live model holds none, and its charges are not reversed by a rollback."""
        return [m for m in getattr(agent.model_backend, "models", [])
                if isinstance(m, ScriptedModel)]

    def memory_records(self) -> dict[str, list[dict]]:
        return {a: self._memory(agent).load() for a, agent in self.agents.items()}

    def memory_entries(self) -> dict[str, list[tuple]]:
        """Each actor's memory as (role, content), without camel's random ids and wall times."""
        return {a: [(r.get("role_at_backend"), (r.get("message") or {}).get("content"))
                    for r in records] for a, records in self.memory_records().items()}

    def sqlite_dump(self) -> str:
        if self.platform is None:
            return ""
        return "\n".join(self.platform.db.iterdump())

    def _time_step(self) -> int | None:
        return self.platform.sandbox_clock.time_step if self.platform is not None else None

    def fingerprint(self) -> dict[str, str]:
        """The live world's digests, comparable with ``Capture.fingerprint``."""
        return _fingerprint(
            ledger=_digest(self.store.dump()), sqlite_dump=self.sqlite_dump(),
            memory=self.memory_records(), round_=self.clock.round, time_step=self._time_step(),
            rng=self.rng.getstate(), state=self.state, queued=len(self.queue),
            transcript=self.transcript)

    def capture(self) -> Capture:
        """Pin every component a round may change; taken before step 1."""
        if len(self.queue):
            raise RuntimeError("a round starts with an empty intent queue")
        sqlite_copy = None
        if self.platform is not None:
            self.platform.db.commit()
            sqlite_copy = sqlite3.connect(":memory:")
            self.platform.db.backup(sqlite_copy)
        return Capture(
            world_id=self.world_id,
            branch_id=self.branch_id,
            round=self.clock.round,
            ledger=_digest(self.store.dump()),
            sqlite=sqlite_copy,
            memory=self.memory_records(),
            agents={a: (agent.observation, agent._observed, agent.last_turn,
                        agent.last_social_results) for a, agent in self.agents.items()},
            models={a: [(set(m._used), set(m._pending)) for m in self._scripted(agent)]
                    for a, agent in self.agents.items()},
            oasis_time_step=self._time_step(),
            rng=self.rng.getstate(),
            state=copy.deepcopy(self.state),
            transcript=self.transcript.calls(),
        )

    def restore(self, capture: Capture) -> None:
        """Put every captured component back except the ledger, which the round's transaction
        rolls back; the caller has already stopped every writer."""
        if self.platform is not None and capture.sqlite is not None:
            self.platform.db.commit()
            capture.sqlite.backup(self.platform.db)
            self.platform.sandbox_clock.time_step = capture.oasis_time_step
        for actor_id, agent in self.agents.items():
            storage = self._memory(agent)
            storage.clear()
            storage.save(capture.memory[actor_id])
            agent.finance_actor.end_turn()
            (agent.observation, agent._observed, agent.last_turn,
             agent.last_social_results) = capture.agents[actor_id]
            for model, (used, pending) in zip(self._scripted(agent), capture.models[actor_id],
                                              strict=True):
                with model._lock:
                    model._used, model._pending = set(used), set(pending)
        self.clock.round = capture.round
        self.rng.setstate(capture.rng)
        self.state = copy.deepcopy(capture.state)
        self.queue.drain()
        self.transcript = Transcript(self.world_id, self.branch_id, calls=capture.transcript)

    # ---------------------------------------------------------------------------- the trace

    def trace(self, journal_id: str) -> list[str]:
        """The chain of cause behind a journal: the journal, its intent, the item that intent
        acted on, that item's own intent, and so on to the public posts the first one saw."""
        with self.store.reading() as c:
            journal = c.execute(select(journals.c.source_intent_id)
                                .where(journals.c.journal_id == journal_id)).first()
        if journal is None:
            raise LookupError(f"no journal {journal_id}")
        items = {i["id"]: i for i in self.state.items}
        chain, intent_id = [journal_id], journal.source_intent_id
        while intent_id is not None:
            chain.append(intent_id)
            intent = self.state.intents[intent_id]
            evidence = intent["evidence_ids"]
            params = intent["params"]
            ref = next((params[k] for k in ("request", "facility_id", "target", "obligation_id")
                        if params.get(k) in evidence), None)
            if ref is None:
                chain += [e for e in evidence if items.get(e, {}).get("kind") == "public_post"]
                break
            chain.append(ref)
            intent_id = items.get(ref, {}).get("intent_id")
        return chain

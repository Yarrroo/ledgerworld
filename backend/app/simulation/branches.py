"""Branches: checkpoint a world at a committed boundary, fork it, replay a branch exactly.

``checkpoint(world)`` pins everything a later round could change (agent-world HANDOFF,
"Checkpoint completeness"): the ledger's rows, a copy of the OASIS SQLite database, the actors'
memory records, both clocks, the RNG, the scheduled-event cursor, the pending C2 deliveries, the
(empty) intent queue and the transcript calls, plus the branch's graph-memory snapshot when it
has one. All of it is copied, so a parent that runs or remembers on cannot change a checkpoint.
The RNG is OASIS's module-global one: a fork sets it from the checkpoint, and a parent that goes
on after a fork has run draws from where the fork left it.

``fork(checkpoint, branch_id, model=...)`` builds a new ``World``: every ``FinanceAgent`` is
rebuilt from its persona (camel's ``ChatAgent.clone()`` would return a plain agent without the
finance tools), bound to the new branch's own queue, on its own SQLite file, ledger and memory
namespace. The checkpoint is restored into it and every component is checked against the
checkpoint's digests; the parent is never written. The child's lineage is a ``branch_meta`` row
in its own ledger, which ``ledger_hash`` leaves out: it is lineage, not money.

``replay(checkpoint, transcript)`` re-runs a branch from its recorded model calls with no live
model: each actor answers through the transcript's ``ReplayModel``, which refuses any call whose
observation differs from the recorded one. A replay keeps the branch's id, so its journals can
be compared byte for byte, and it is labelled ``replay=true`` in its ledger and its label.
"""

from __future__ import annotations

import copy
import dataclasses
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Self

from sqlalchemy import delete, func, insert, select, text, update

from ..finance.models import branch_meta, metadata, postings
from ..finance.schemas import Snapshot
from ..finance.store import LedgerStore, _naive
from .memory import BranchMemory, MemorySnapshot, namespace_for
from .transcripts import ModelCall, Transcript
from .world import Capture, ModelFactory, World, _digest

__all__ = ["Branch", "BranchMismatch", "Checkpoint", "checkpoint", "fork", "ledger_hash",
           "replay"]

LINEAGE_TABLES = frozenset({branch_meta.name})


class BranchMismatch(RuntimeError):
    """A checkpoint, fork or replay that cannot be made faithfully."""


def _hash_rows(rows: Mapping[str, list[dict]]) -> str:
    return _digest({name: table for name, table in rows.items() if name not in LINEAGE_TABLES})


def ledger_hash(store: LedgerStore) -> str:
    """sha256 of every money table's rows; ``branch_meta`` (lineage) is left out."""
    return _hash_rows(store.dump())


@dataclass(frozen=True)
class Checkpoint:
    """A world pinned at a committed round boundary; every field is a copy."""

    world_id: str
    branch_id: str
    round: int
    snapshot: Snapshot
    actors: tuple[Mapping[str, Any], ...]
    events: tuple[Mapping[str, Any], ...]
    seed: int
    epoch: datetime
    created_at: datetime
    capture: Capture
    ledger_state: Mapping[str, list[dict]]
    ledger_digest: str
    memory: MemorySnapshot | None

    @property
    def memory_ns(self) -> str:
        return namespace_for(self.world_id, self.branch_id)

    @property
    def transcript_cursor(self) -> int:
        return len(self.capture.transcript)

    @property
    def transcript_calls(self) -> tuple[ModelCall, ...]:
        return self.capture.transcript

    @property
    def lineage(self) -> frozenset[str]:
        """This branch and every branch it descends from, as its ledger records them."""
        rows = self.ledger_state.get(branch_meta.name, [])
        return frozenset({self.branch_id} | {r["branch_id"] for r in rows}
                         | {r["parent_branch_id"] for r in rows if r["parent_branch_id"]})

    @property
    def event_cursor(self) -> int:
        return self.capture.state.event_cursor

    @property
    def pending_c2(self) -> list[dict]:
        return copy.deepcopy(self.capture.state.pending_c2)

    def fingerprint(self) -> dict[str, str]:
        """One digest per pinned component, comparable with a world's (ledger by
        ``ledger_hash``)."""
        return {**self.capture.fingerprint, "ledger": self.ledger_digest}


def checkpoint(world: World, memory: BranchMemory | None = None) -> Checkpoint:
    """Pin ``world`` (and its graph memory) at the round it last committed."""
    if world.unusable is not None:
        raise BranchMismatch(f"{world.branch_id} is unusable: {world.unusable}")
    if world.env is None:
        raise BranchMismatch("start the world before checkpointing it")
    if world.committed_round != world.clock.round:
        raise BranchMismatch(f"{world.branch_id} is mid-round: committed "
                             f"{world.committed_round}, clock {world.clock.round}")
    if memory is not None and memory.namespace != namespace_for(world.world_id,
                                                                 world.branch_id):
        raise BranchMismatch(f"{memory.namespace} is not the memory of "
                             f"{namespace_for(world.world_id, world.branch_id)}")
    capture = world.capture()  # refuses a non-empty queue
    # The capture's SQLite copy is bound to this thread; a checkpoint is read from any.
    sqlite_copy = sqlite3.connect(":memory:", check_same_thread=False)
    capture.sqlite.backup(sqlite_copy)
    capture.sqlite.close()
    capture = dataclasses.replace(capture, sqlite=sqlite_copy,
                                  memory=copy.deepcopy(capture.memory),
                                  agents=copy.deepcopy(capture.agents))
    rows = world.store.dump()  # fresh dicts, shared with nothing
    return Checkpoint(
        world_id=world.world_id,
        branch_id=world.branch_id,
        round=world.clock.round,
        snapshot=world.snapshot.model_copy(deep=True),
        actors=tuple(copy.deepcopy(a) for a in world.actors.values()),
        # Already selected for the parent's lineage: a fork inherits them whatever its name.
        events=tuple({k: v for k, v in e.items() if k != "branch"}
                     for e in copy.deepcopy(world.events)),
        seed=world.seed,
        epoch=world.clock.epoch,
        created_at=world.clock.now,
        capture=capture,
        ledger_state=rows,
        ledger_digest=_hash_rows(rows),
        memory=memory.snapshot() if memory is not None else None,
    )


@dataclass
class Branch:
    """A forked world with its graph memory and lineage; ``async with`` closes the world."""

    world: World
    memory: BranchMemory | None
    parent: str | None
    checkpoint_round: int
    replay: bool = False

    @property
    def branch_id(self) -> str:
        return self.world.branch_id

    def label(self) -> dict[str, Any]:
        """What every response and screen about this branch carries."""
        return {"world_id": self.world.world_id, "branch_id": self.branch_id,
                "parent": self.parent, "checkpoint_round": self.checkpoint_round,
                "replay": self.replay}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.world.close()


def _copy_ledger(rows: Mapping[str, list[dict]], store: LedgerStore) -> None:
    """Make ``store`` hold exactly ``rows``, in one transaction."""
    with store.engine.begin() as conn:
        for table in reversed(metadata.sorted_tables):
            conn.execute(delete(table))
        for table in metadata.sorted_tables:
            if rows.get(table.name):
                conn.execute(insert(table), rows[table.name])
        if conn.dialect.name == "postgresql":  # explicit ids do not move the sequence
            top = conn.execute(select(func.max(postings.c.posting_id))).scalar()
            if top is not None:
                conn.execute(text("SELECT setval(pg_get_serial_sequence('postings', "
                                  "'posting_id'), :top)"), {"top": top})


def _write_lineage(store: LedgerStore, cp: Checkpoint, branch_id: str,
                   replay: bool) -> tuple[str | None, int]:
    """The child's ``branch_meta`` row, stamped in simulated time; returns its parent and
    checkpoint round.

    A replay of a branch whose row the checkpoint already holds keeps that row's parent and
    round and only marks it a replay; a replay of a root branch has no parent.
    """
    with store.engine.begin() as conn:
        mine = branch_meta.c.branch_id == branch_id
        row = conn.execute(select(branch_meta.c.parent_branch_id,
                                  branch_meta.c.checkpoint_round).where(mine)).first()
        if row is not None:
            conn.execute(update(branch_meta).where(mine).values(replay=replay))
            return row.parent_branch_id, row.checkpoint_round
        parent = None if branch_id == cp.branch_id else cp.branch_id
        conn.execute(insert(branch_meta).values(
            branch_id=branch_id, world_id=cp.world_id, parent_branch_id=parent,
            checkpoint_round=cp.round, replay=replay, created_at=_naive(cp.created_at)))
        return parent, cp.round


async def fork(
    cp: Checkpoint,
    branch_id: str,
    *,
    model: ModelFactory,
    workdir: str | Path,
    memory_client: Any = None,
    store: LedgerStore | None = None,
    coordinator: Any = None,
    scenario: Sequence[Mapping[str, Any]] = (),
) -> Branch:
    """A new, started branch restored from ``cp``; the parent is not touched.

    ``model(actor_id, world)`` gives each rebuilt agent its backend. With ``memory_client`` the
    branch gets its own ``BranchMemory`` holding the checkpoint's pinned records. ``scenario``
    adds events after the checkpoint (one naming a ``branch`` only in that branch) to the ones
    the checkpoint inherited. A fork that fails removes the platform file and the memory
    graph it created, so it can be retried.
    """
    return await _fork(cp, branch_id, model=model, workdir=workdir, memory_client=memory_client,
                       store=store, coordinator=coordinator, scenario=scenario, replay=False)


async def _fork(cp: Checkpoint, branch_id: str, *, model: ModelFactory, workdir: str | Path,
                memory_client: Any, store: LedgerStore | None, coordinator: Any,
                scenario: Sequence[Mapping[str, Any]], replay: bool) -> Branch:
    """``fork``, or with ``replay`` the same branch re-run under its own id."""
    if branch_id in (cp.lineage if not replay else cp.lineage - {cp.branch_id}):
        raise BranchMismatch(f"{branch_id!r} is the checkpoint's branch or an ancestor of it; "
                             "a fork needs its own id and only the checkpoint's branch replays")
    early = [e for e in scenario
             if e.get("branch") in (None, branch_id) and e["round"] <= cp.round]
    if early:
        raise ValueError(f"a fork's own events come after the checkpoint (round {cp.round}): "
                         f"{early}")
    world = World(cp.world_id, branch_id, cp.snapshot.model_copy(deep=True),
                  copy.deepcopy(list(cp.actors)), model=model, workdir=workdir,
                  scenario=copy.deepcopy([*cp.events, *scenario]), store=store, seed=cp.seed,
                  epoch=cp.epoch, coordinator=coordinator)
    created = not world.db_path.exists()  # else start refuses: the file is not this fork's
    memory = None
    try:
        await world.start()
        if set(world.agents) != set(cp.capture.agents):
            raise BranchMismatch(f"{branch_id}'s model actors differ from the checkpoint's")
        # The new branch's models answer a new plan: none of their entries is used yet.
        fresh = {a: [(set(), set()) for _ in world._scripted(agent)]
                 for a, agent in world.agents.items()}
        world.restore(dataclasses.replace(
            cp.capture, memory=copy.deepcopy(cp.capture.memory),
            agents=copy.deepcopy(cp.capture.agents), models=fresh))
        world.committed_round = cp.round
        _copy_ledger(cp.ledger_state, world.store)
        parent, checkpoint_round = _write_lineage(world.store, cp, branch_id, replay)
        live = {**world.fingerprint(), "ledger": ledger_hash(world.store)}
        differs = sorted(k for k, v in cp.fingerprint().items() if live.get(k) != v)
        if differs:
            raise BranchMismatch(f"{branch_id} restored differently from its checkpoint: "
                                 f"{differs}")
        if memory_client is not None:
            memory = BranchMemory(memory_client, cp.world_id, branch_id)
            # A replay of the checkpoint's own branch shares its namespace, on its own client,
            # so the pinned records are written as they were rather than restored "into" it.
            for r in cp.memory.records if cp.memory is not None else ():
                memory.write_record(r.actor_id, r.key, r.value, r.round)
    except BaseException:
        try:
            await world.close()
        finally:
            if created:
                world.db_path.unlink(missing_ok=True)
            if memory is not None:
                memory.client.graph.delete(memory.graph_id)
        raise
    return Branch(world, memory, parent, checkpoint_round, replay)


async def replay(
    cp: Checkpoint,
    transcript: Transcript,
    *,
    workdir: str | Path,
    rounds: int | None = None,
    store: LedgerStore | None = None,
    coordinator: Any = None,
    memory_client: Any = None,
    scenario: Sequence[Mapping[str, Any]] = (),
) -> Branch:
    """Re-run ``transcript``'s branch from ``cp`` with recorded answers only.

    The transcript must begin with the checkpoint's calls; ``rounds`` defaults to every round it
    recorded after the checkpoint. ``coordinator``, ``memory_client`` and ``scenario`` are the
    branch's own, as it was forked. The returned branch has run and is labelled a replay.
    """
    start = cp.transcript_cursor
    calls = transcript.calls()
    if transcript.world_id != cp.world_id or calls[:start] != cp.transcript_calls:
        raise BranchMismatch(f"{transcript.namespace} does not descend from {cp.memory_ns} "
                             f"at round {cp.round}")
    later = calls[start:]
    if rounds is None:
        rounds = later[-1].round - cp.round if later else 0

    def model(actor_id: str, world: World) -> Any:
        return transcript.replay_model(
            actor_id, lambda: world.clock.round,
            lambda: world.agents[actor_id].observation.obs_hash, start=start)

    branch = await _fork(cp, transcript.branch_id, model=model, workdir=workdir, store=store,
                         coordinator=coordinator, memory_client=memory_client,
                         scenario=scenario, replay=True)
    try:
        await branch.world.run(rounds)
    except BaseException:
        try:
            await branch.world.close()
        finally:
            branch.world.db_path.unlink(missing_ok=True)
            if branch.memory is not None:
                branch.memory.client.graph.delete(branch.memory.graph_id)
        raise
    return branch

"""Durable job state and the API's records, in the ledger store's database.

Two tables of their own beside the ledger's (they are not ledger tables, so a branch's ledger
copy and `LedgerStore.dump` never see them):

- ``api_jobs``: one row per job. Its ``state`` is the truth; Redis only carries the order of work
  and the leases, so a Redis that loses its data loses no job (``JobQueue.reap`` pushes a queued
  row back). Every state change is a guarded UPDATE from the states it may leave, so two workers
  never both move one job.
- ``api_records``: JSON documents by ``(kind, key)``: a run, a run's decisions, a branch's
  transcript, the run an approval was made for, the prepared demonstration context.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)

metadata = MetaData()

jobs = Table(
    "api_jobs", metadata,
    Column("job_id", String(64), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("run_id", String(128), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("state", String(12), nullable=False),  # queued | running | done | failed | cancelled
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False),
    Column("cancel_requested", Boolean, nullable=False, default=False),
    Column("worker", String(128)),
    Column("error", Text),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)

records = Table(
    "api_records", metadata,
    Column("kind", String(32), primary_key=True),
    Column("key", String(200), primary_key=True),
    Column("body", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)

STATES = ("queued", "running", "done", "failed", "cancelled")
FINAL = ("done", "failed", "cancelled")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str
    run_id: str
    payload: dict[str, Any]
    state: str
    attempts: int
    max_attempts: int
    cancel_requested: bool
    worker: str | None
    error: str | None

    @classmethod
    def from_row(cls, row: Any) -> Job:
        return cls(row.job_id, row.kind, row.run_id, json.loads(row.payload), row.state,
                   row.attempts, row.max_attempts, bool(row.cancel_requested), row.worker,
                   row.error)


class JobStore:
    """The two tables on one engine (the ledger store's)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata.create_all(engine)

    # ----------------------------------------------------------------------------- jobs

    def create(self, job_id: str, kind: str, run_id: str, payload: dict, *,
               max_attempts: int) -> Job:
        now = _now()
        with self.engine.begin() as c:
            c.execute(insert(jobs).values(
                job_id=job_id, kind=kind, run_id=run_id, payload=json.dumps(payload),
                state="queued", attempts=0, max_attempts=max_attempts, cancel_requested=False,
                created_at=now, updated_at=now))
        return self.job(job_id)

    def job(self, job_id: str) -> Job | None:
        with self.engine.begin() as c:
            row = c.execute(select(jobs).where(jobs.c.job_id == job_id)).first()
        return None if row is None else Job.from_row(row)

    def jobs_of(self, run_id: str) -> list[Job]:
        with self.engine.begin() as c:
            rows = c.execute(select(jobs).where(jobs.c.run_id == run_id)
                             .order_by(jobs.c.created_at, jobs.c.job_id)).all()
        return [Job.from_row(r) for r in rows]

    def in_state(self, state: str) -> list[Job]:
        with self.engine.begin() as c:
            rows = c.execute(select(jobs).where(jobs.c.state == state)
                             .order_by(jobs.c.created_at, jobs.c.job_id)).all()
        return [Job.from_row(r) for r in rows]

    def move(self, job_id: str, from_states: Iterable[str], to_state: str, *,
             owner: str | None = None, **values: Any) -> bool:
        """``job_id`` to ``to_state`` only from one of ``from_states`` (and, with ``owner``,
        only while that worker holds it); false when it was not moved."""
        if to_state not in STATES:
            raise ValueError(f"unknown job state {to_state!r}")
        guard = [jobs.c.job_id == job_id, jobs.c.state.in_(list(from_states))]
        if owner is not None:
            guard.append(jobs.c.worker == owner)
        with self.engine.begin() as c:
            moved = c.execute(update(jobs).where(*guard).values(
                state=to_state, updated_at=_now(), **values)).rowcount
        return moved == 1

    def request_cancel(self, job_id: str) -> bool:
        with self.engine.begin() as c:
            return c.execute(update(jobs).where(
                jobs.c.job_id == job_id, jobs.c.state.not_in(FINAL)).values(
                cancel_requested=True, updated_at=_now())).rowcount == 1

    # -------------------------------------------------------------------------- records

    def put(self, kind: str, key: str, body: Any) -> None:
        text = json.dumps(body, sort_keys=True)
        with self.engine.begin() as c:
            done = c.execute(update(records).where(
                records.c.kind == kind, records.c.key == key).values(
                body=text, updated_at=_now())).rowcount
            if not done:
                c.execute(insert(records).values(kind=kind, key=key, body=text,
                                                 updated_at=_now()))

    def get(self, kind: str, key: str) -> Any | None:
        with self.engine.begin() as c:
            row = c.execute(select(records.c.body).where(
                records.c.kind == kind, records.c.key == key)).first()
        return None if row is None else json.loads(row.body)

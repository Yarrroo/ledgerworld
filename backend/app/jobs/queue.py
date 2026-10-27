"""The job queue: Redis carries the order of work and the leases, the store carries the state.

- ``submit`` writes the ``queued`` row first, then pushes its id: what the API answers (202) is
  already durable, and a push Redis loses is re-pushed by ``reap``.
- ``claim`` moves an id from the queue list to the processing list, takes a lease
  (``SET … PX``) and moves the row ``queued → running`` with one more attempt; an id whose row is
  not queued any more (a duplicate push, a cancelled job) is dropped.
- A worker renews its lease between units of work (``heartbeat``) and stops when it lost it.
- ``fail`` re-queues a job while it has attempts left, else it is ``failed``; ``reap`` treats a
  running job whose lease expired (its worker died) as one failed attempt.
- ``cancel`` cancels a queued job at once and flags a running one; the worker sees the flag at
  its next heartbeat and ends the job ``cancelled``.
- A handler's ``ValueError`` is a request the world cannot run (a family it refuses, a checkpoint
  past the run): the same input fails the same way again, so it is not retried.

Every finishing move is guarded by the row's state and its worker, so a worker whose lease was
reaped cannot finish a job another worker now runs.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .store import Job, JobStore

LEASE_S = 120
MAX_ATTEMPTS = 3


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class Cancelled(Exception):
    """The job was cancelled while it ran."""


class LeaseLost(Exception):
    """This worker's lease on the job expired and was reaped."""


class JobQueue:
    def __init__(self, store: JobStore, redis: Any, *, prefix: str = "ledgerworld:jobs",
                 lease_s: float = LEASE_S, max_attempts: int = MAX_ATTEMPTS) -> None:
        self.store = store
        self.redis = redis
        self.queue_key = f"{prefix}:queue"
        self.processing_key = f"{prefix}:processing"
        self.lease_prefix = f"{prefix}:lease:"
        self.lease_ms = int(lease_s * 1000)
        self.max_attempts = max_attempts

    def _lease(self, job_id: str) -> str:
        return self.lease_prefix + job_id

    # --------------------------------------------------------------------------- submit

    def submit(self, kind: str, run_id: str, payload: dict, *, job_id: str | None = None) -> Job:
        job = self.store.create(job_id or f"job-{uuid.uuid4().hex[:16]}", kind, run_id, payload,
                                max_attempts=self.max_attempts)
        self.redis.lpush(self.queue_key, job.job_id)
        return job

    def cancel(self, job_id: str) -> Job | None:
        """Cancel a queued job now; flag a running one for its worker. None: no such job."""
        if self.store.job(job_id) is None:
            return None
        self.store.request_cancel(job_id)
        if self.store.move(job_id, ["queued"], "cancelled"):
            self.redis.lrem(self.queue_key, 0, job_id)
        return self.store.job(job_id)

    # ---------------------------------------------------------------------------- claim

    def claim(self, worker: str) -> Job | None:
        while True:
            raw = self.redis.rpoplpush(self.queue_key, self.processing_key)
            if raw is None:
                return None
            job_id = _text(raw)
            job = self.store.job(job_id)
            if job is None or job.state != "queued":
                self.redis.lrem(self.processing_key, 0, job_id)
                continue
            if job.cancel_requested:
                self.store.move(job_id, ["queued"], "cancelled")
                self.redis.lrem(self.processing_key, 0, job_id)
                continue
            self.redis.set(self._lease(job_id), worker, px=self.lease_ms)
            if not self.store.move(job_id, ["queued"], "running", attempts=job.attempts + 1,
                                   worker=worker):
                self._release(job_id)
                continue
            return self.store.job(job_id)

    def heartbeat(self, job: Job, worker: str) -> bool:
        """Renew the lease; false when it is no longer this worker's."""
        held = self.redis.get(self._lease(job.job_id))
        if held is None or _text(held) != worker:
            return False
        self.redis.pexpire(self._lease(job.job_id), self.lease_ms)
        return True

    # --------------------------------------------------------------------------- finish

    def _release(self, job_id: str) -> None:
        self.redis.lrem(self.processing_key, 0, job_id)
        self.redis.delete(self._lease(job_id))

    def complete(self, job: Job, worker: str) -> bool:
        done = self.store.move(job.job_id, ["running"], "done", owner=worker, error=None)
        if done:
            self._release(job.job_id)
        return done

    def finish_cancelled(self, job: Job, worker: str) -> bool:
        done = self.store.move(job.job_id, ["running"], "cancelled", owner=worker)
        if done:
            self._release(job.job_id)
        return done

    def fail(self, job: Job, worker: str | None, error: str, *, retry: bool = True) -> str:
        """Re-queue while attempts remain (and it is not cancelled), else fail; the new state."""
        current = self.store.job(job.job_id)
        again = (retry and current is not None and current.attempts < current.max_attempts
                 and not current.cancel_requested)
        to = "queued" if again else ("cancelled" if current and current.cancel_requested
                                     else "failed")
        if not self.store.move(job.job_id, ["running"], to, owner=worker, error=error[:2000],
                               worker=None):
            return current.state if current else "failed"
        self._release(job.job_id)
        if to == "queued":
            self.redis.lpush(self.queue_key, job.job_id)
        return to

    def reap(self) -> list[str]:
        """Expired leases count as a failed attempt; queued rows Redis lost are pushed again."""
        touched = []
        for raw in self.redis.lrange(self.processing_key, 0, -1):
            job_id = _text(raw)
            if self.redis.exists(self._lease(job_id)):
                continue
            job = self.store.job(job_id)
            if job is not None and job.state == "running":
                self.fail(job, job.worker, "lease expired: the worker stopped renewing it")
                touched.append(job_id)
            elif job is None or job.state != "queued":
                self.redis.lrem(self.processing_key, 0, job_id)
        listed = {_text(x) for key in (self.queue_key, self.processing_key)
                  for x in self.redis.lrange(key, 0, -1)}
        for job in self.store.in_state("queued"):
            if job.job_id not in listed:
                self.redis.lpush(self.queue_key, job.job_id)
                touched.append(job.job_id)
        return touched


@dataclass
class JobContext:
    """What a handler gets besides its job: ``checkpoint`` between units of work."""

    queue: JobQueue
    job: Job
    worker: str

    def checkpoint(self) -> None:
        """Renew the lease and honour a cancellation; raises ``LeaseLost`` or ``Cancelled``."""
        if not self.queue.heartbeat(self.job, self.worker):
            raise LeaseLost(self.job.job_id)
        current = self.queue.store.job(self.job.job_id)
        if current is None or current.cancel_requested:
            raise Cancelled(self.job.job_id)


Handler = Callable[[Job, JobContext], None]


class Worker:
    """Claims one job at a time and runs its kind's handler."""

    def __init__(self, queue: JobQueue, handlers: Mapping[str, Handler],
                 worker: str | None = None) -> None:
        self.queue = queue
        self.handlers = dict(handlers)
        self.worker = worker or f"worker-{uuid.uuid4().hex[:8]}"

    def run_once(self) -> Job | None:
        """Reap, claim and run one job; the job as it ended, or None when none was queued."""
        self.queue.reap()
        job = self.queue.claim(self.worker)
        if job is None:
            return None
        handler = self.handlers.get(job.kind)
        ctx = JobContext(self.queue, job, self.worker)
        try:
            if handler is None:
                self.queue.fail(job, self.worker, f"no handler for job kind {job.kind!r}",
                                retry=False)
                return self.queue.store.job(job.job_id)
            ctx.checkpoint()
            handler(job, ctx)
        except Cancelled:
            self.queue.finish_cancelled(job, self.worker)
        except LeaseLost:
            pass  # the reaper re-queued it; another attempt owns it now
        except Exception as error:  # noqa: BLE001 — any handler failure is one failed attempt
            self.queue.fail(job, self.worker, f"{type(error).__name__}: {error}",
                            retry=not isinstance(error, ValueError))
        else:
            self.queue.complete(job, self.worker)
        return self.queue.store.job(job.job_id)

    def run_forever(self, *, idle_s: float = 1.0,
                    stop: Callable[[], bool] = lambda: False) -> None:
        while not stop():
            if self.run_once() is None:
                time.sleep(idle_s)

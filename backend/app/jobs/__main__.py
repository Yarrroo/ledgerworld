"""`python -m app.jobs`: one simulation worker, on `LEDGER_DATABASE_URL` and `REDIS_URL`.

It runs in the simulation role: nothing here reads a provider credential or imports a connector.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..finance.store import LedgerStore
from .queue import JobQueue, Worker
from .runner import Runner
from .store import JobStore


def main() -> None:
    import redis

    url = os.environ.get("REDIS_URL")
    if not url:
        raise SystemExit("REDIS_URL is not set: the worker has no queue to read")
    store = JobStore(LedgerStore().engine)
    queue = JobQueue(store, redis.Redis.from_url(url))
    runner = Runner(store, Path("var") / "jobs")  # each job works in its own temporary dir
    Worker(queue, runner.handlers()).run_forever()


if __name__ == "__main__":
    main()

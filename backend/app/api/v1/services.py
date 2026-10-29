"""What the /api/v1 routes read and write, built once per app.

- the observed snapshot and its ledger store: the state Overview, Treasury and Lending show and
  every plan is decided on (the demo world's snapshot, LF-1's treasury beside LF-2's pool, unless
  the caller passes another). Once the operator has prepared the demo, the screens show that
  run's observed snapshot at its own as_of instead (`observed()`): the store holds the prepared
  execution's postings, which show on Execution only;
- the job queue and its records (runs, decisions, transcripts, the demo context) in the ledger
  store's database;
- the execution gateway on the observed store, built on first use (it reads the provider);
- the demo token, the provider mode, and the clock the observed state is read at: the snapshot's
  `as_of` plus the wall time since the store first served it (the anchor is stored, so a restart
  or a second process never runs the clock back), so a frozen snapshot goes stale and an approval
  expires as they would on the provider's clock. A prepared demo's baseline is the exception: the
  screens read it at its own `as_of`, while approvals still run on this clock.

`Services.from_env()` is the deployed wiring; tests build one directly with fakes.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ...execution.gateway import Gateway
from ...finance.ledger import from_snapshot
from ...finance.schemas import Mode, Snapshot
from ...finance.store import LedgerStore
from ...jobs.queue import JobQueue
from ...jobs.store import JobStore
from ...simulation.scenarios import load_world
from .views import treasury_entity

API_VERSION = "v1"
APPROVER = "operator"


log = logging.getLogger("ledgerworld.api")


def beneficiaries_for(snapshot: Snapshot) -> dict[str, str]:
    """Each treasury obligation's payee: the allowlisted beneficiary `ben-<obligation_id>`."""
    treasury = treasury_entity(snapshot)
    return {o.obligation_id: f"ben-{o.obligation_id}" for o in snapshot.obligations
            if o.entity == treasury}


@dataclass
class Services:
    snapshot: Snapshot
    store: LedgerStore
    jobs: JobStore
    queue: JobQueue | None
    epoch: datetime
    mode: Mode
    token: str | None
    make_gateway: Callable[[Services], Gateway] | None = None
    clock: Callable[[], datetime] | None = None  # None: as_of + wall time since the anchor
    wall_ms: Callable[[], int] = field(default=lambda: int(time.time() * 1000))
    webhook_secret: str | None = None
    connected_setting: str = "auto"
    model_kind: str = "scripted"
    live_runs: bool = False  # a worker with a live model runs families off their parameters
    interview_model: Callable[[str], Any] | None = None
    terms: dict[str, dict] = field(default_factory=dict)
    beneficiaries: dict[str, str] | None = None
    report_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    lock: threading.RLock = field(default_factory=threading.RLock)
    _gateway: Gateway | None = None
    _baseline: tuple[str, LedgerStore, Snapshot] | None = None  # the prepared run's

    def __post_init__(self) -> None:
        if self.beneficiaries is None:
            self.beneficiaries = beneficiaries_for(self.snapshot)
        if self.clock is None:
            anchor = self.jobs.get("clock", self.snapshot.snapshot_id)
            if anchor is None:
                anchor = time.time()
                self.jobs.put("clock", self.snapshot.snapshot_id, anchor)
            as_of = self.snapshot.as_of
            self.clock = lambda: as_of + timedelta(seconds=max(0.0, time.time() - anchor))

    @classmethod
    def build(cls, snapshot: Snapshot, *, store: LedgerStore | None = None,
              redis: Any = None, **kwargs: Any) -> Services:
        """Load ``snapshot`` into an empty observed store (or reuse a loaded one)."""
        store = store or LedgerStore("sqlite://")
        if not store.rows("accounts"):
            from_snapshot(store, snapshot)
        jobs = JobStore(store.engine)
        queue = JobQueue(jobs, redis) if redis is not None else None
        return cls(snapshot=snapshot, store=store, jobs=jobs, queue=queue, **kwargs)

    @classmethod
    def from_env(cls) -> Services:
        from ...connectors.airwallex.client import connected_setting
        from ...connectors.airwallex.transport import mode_from

        world = load_world()
        redis = None
        if os.environ.get("REDIS_URL"):
            import redis as redis_lib

            redis = redis_lib.Redis.from_url(os.environ["REDIS_URL"])
        services = cls.build(
            world.snapshot, store=LedgerStore(), redis=redis, epoch=world.epoch,
            mode=mode_from(os.environ), token=os.environ.get("LEDGERWORLD_DEMO_TOKEN") or None,
            make_gateway=gateway_from_env,
            webhook_secret=os.environ.get("AIRWALLEX_WEBHOOK_SECRET") or None,
            connected_setting=connected_setting())
        try:  # at start, so no public read ever builds it (and probes the provider)
            services.gateway()
        except Exception:  # a POST that needs it tries again
            log.exception("the execution gateway could not start")
        return services

    # -------------------------------------------------------------------------- reading

    def now(self) -> datetime:
        return self.clock()

    @property
    def has_gateway(self) -> bool:
        return self._gateway is not None

    @property
    def connected(self) -> bool:
        if self._gateway is not None:
            return self._gateway.leg_mode == "A"
        return self.connected_setting == "on"

    def gateway(self) -> Gateway:
        with self.lock:
            if self._gateway is None:
                if self.make_gateway is None:
                    raise LookupError("no execution gateway is configured")
                self._gateway = self.make_gateway(self)
            return self._gateway

    def observed(self, demo: dict | None = None) -> tuple[LedgerStore, Snapshot, datetime]:
        """The store, snapshot and time Overview, Treasury and Lending read. With a prepared demo:
        its run's observed snapshot, loaded into a store of its own and read at that snapshot's
        as_of, so the screens show the baseline its plan was decided on, never the ledger the
        execution moved since or a clock that ran on past it. Otherwise the observed store now.
        ``demo`` is a `demo()` the caller already read, so one response reads one context."""
        run_id = (demo or self.demo())["run_id"]
        if run_id is None:
            return self.store, self.snapshot, self.now()
        with self.lock:
            if self._baseline is None or self._baseline[0] != run_id:
                from ...demo.run import observed_snapshot  # the snapshot prepare decided on

                snapshot = observed_snapshot(load_world(), run_id)
                store = LedgerStore("sqlite://")
                from_snapshot(store, snapshot)
                self._baseline = (run_id, store, snapshot)
            _, store, snapshot = self._baseline
        return store, snapshot, snapshot.as_of

    def authorised(self, header: str | None) -> bool:
        """`Authorization: Bearer <LEDGERWORLD_DEMO_TOKEN>`; no configured token admits nobody."""
        if not self.token or not header or not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[len("Bearer "):].encode(), self.token.encode())

    def demo(self) -> dict:
        """The prepared demonstration run and its execution; null where none is associated."""
        context = self.jobs.get("demo", "current") or {}
        run_id = context.get("run_id")
        if run_id is None or self.jobs.get("run", run_id) is None:
            return {"run_id": None, "execution_id": None}
        execution_id = context.get("execution_id")
        if execution_id is not None and self.jobs.get("approval_run", execution_id) != run_id:
            execution_id = None
        return {"run_id": run_id, "execution_id": execution_id}

    def prepare_demo(self, run_id: str, execution_id: str | None = None) -> dict:
        """Name the demonstration run, and the execution approved from its decision. An
        execution approved from another run is refused, never shown beside this one."""
        if self.jobs.get("run", run_id) is None:
            raise LookupError(f"no run {run_id}")
        if execution_id is not None and self.jobs.get("approval_run", execution_id) != run_id:
            raise ValueError(f"execution {execution_id} was not approved from run {run_id}")
        self.jobs.put("demo", "current", {"run_id": run_id, "execution_id": execution_id})
        return self.demo()


def gateway_from_env(services: Services) -> Gateway:
    """The gateway on the observed store, through the client `AIRWALLEX_MODE` selects."""
    from ...connectors.airwallex.client import client_from_env

    client = client_from_env()
    leg_mode = client.probe_connected(services.connected_setting)
    treasury = treasury_entity(services.snapshot)
    currency = next(a.currency for a in services.snapshot.accounts if a.entity == treasury)
    global_account = (os.environ.get("AIRWALLEX_GLOBAL_ACCOUNT_ID")
                      or client.global_account_in(currency))
    return Gateway(services.store, client, mode=services.mode, leg_mode=leg_mode,
                   beneficiaries=set(services.beneficiaries.values()),
                   clock=services.now, global_account_id=global_account)

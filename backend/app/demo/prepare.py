"""Prepare the fake judge path in the app container's own database and simulation queue.

Run ``python -m app.demo.prepare`` inside the app container, with the same
LEDGER_DATABASE_URL and REDIS_URL as the API. The simulation worker must be running.
This is an operator command, not a public route; no demo token or browser POST is needed.
A completed preparation is reused, never another financial operation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import uuid
from contextlib import contextmanager

from redis.exceptions import WatchError

from ..api.v1.services import Services, beneficiaries_for
from ..decisions.candidates import ALL, plan_for_now
from ..execution import reconcile
from ..execution.approval import bind
from ..finance import contracts
from ..jobs.runner import FORK, RUN, family_of, new_run, pending_decisions
from ..simulation.scenarios import DemoWorld, load_world
from .provider import PreparedGateway as Gateway
from .provider import client_for
from .run import APPROVER, TERMS, observed_snapshot, pay

LOCK = "ledgerworld:demo:prepare"
SCENARIO = {"family": "delayed-receipt", "seed": 7}
POLICIES = [p.id for p in ALL]


class PreparationError(RuntimeError):
    """A safe, operator-facing failure; dependency exception messages are never public."""


@contextmanager
def _exclusive(redis, timeout: float):
    token = uuid.uuid4().hex.encode()
    if not redis.set(LOCK, token, nx=True, ex=math.ceil(timeout) + 60):
        raise PreparationError("demo preparation is already running")
    try:
        yield
    finally:
        # WATCH makes the ownership check and deletion atomic, also if the lease expired.
        with redis.pipeline() as pipe:
            try:
                pipe.watch(LOCK)
                if pipe.get(LOCK) == token:
                    pipe.multi()
                    pipe.delete(LOCK)
                    pipe.execute()
            except WatchError:
                pass  # a newer command owns the lock


def _job(services: Services, kind: str, run_id: str, payload: dict, deadline: float) -> None:
    job_id = f"{run_id}-{kind}"
    job = services.jobs.job(job_id)
    if job is None:
        job = services.queue.submit(kind, run_id, payload | {"prepared_demo": True}, job_id=job_id)
    while job.state not in ("done", "failed", "cancelled", "lost"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PreparationError(f"demo preparation timed out waiting for {kind}; check the sim worker")
        time.sleep(min(0.1, remaining))
        job = services.jobs.job(job_id)
    if job.state != "done":
        raise PreparationError(f"demo {kind} job {job_id} is {job.state}; check the worker log")


def _execution(services: Services, run_id: str, selected: str, world: DemoWorld | None = None) -> str:
    # The synthetic shock is the observed input to this fake plan, not a branch's snapshot.
    # Use the app's current clock/store for all monetary checks; never reset its balances.
    world = world or load_world()
    snapshot = observed_snapshot(world, run_id)
    beneficiaries = beneficiaries_for(snapshot)
    plan = plan_for_now(next(p for p in ALL if p.id == selected), snapshot, epoch=world.epoch,
                        terms=TERMS, beneficiaries=beneficiaries)
    if plan is None:
        raise PreparationError("the selected demo policy has no executable plan")
    client = client_for(services.jobs, run_id)
    leg_mode = client.probe_connected("off")
    gateway = Gateway(services.store, client, mode="fake", leg_mode=leg_mode,
                      beneficiaries=set(beneficiaries.values()), clock=services.now)
    approval = bind(plan, snapshot, APPROVER, "fake", now=services.now())
    stored = gateway.stored(approval.approval_id)
    # Only the advance used by this plan may be added; never silently adopt different terms.
    facility_ids = {leg.facility_id for leg in approval.legs if leg.facility_id}
    for contract in snapshot.contracts:
        if contract.contract_id not in facility_ids:
            continue
        try:
            facility = contracts.facility(services.store, contract.contract_id)
        except LookupError:
            contracts.register(services.store, contract, as_of=services.now())
        else:
            actual = (facility.pool, facility.borrower, facility.currency, facility.kind,
                      facility.limit_minor, facility.fee_bps, facility.repay_share_bps)
            expected = (contract.lender, contract.borrower, contract.principal.currency,
                        contract.kind, contract.principal.minor, contract.fee_bps,
                        contract.repay_share_bps)
            if actual != expected:
                raise PreparationError("the stored demo advance terms differ from its simulation")
    if stored is None:
        gateway.record(approval)
        stored = approval
    elif not gateway.legs(stored.approval_id) and stored.expires_at <= services.now():
        # No leg was queued: reapprove identical terms, under the same operation ids.
        with gateway.transaction():
            gateway.conn.execute("UPDATE approvals SET expires_at = ? WHERE approval_id = ?",
                                 (approval.expires_at.isoformat(), approval.approval_id))
            gateway.conn.execute("UPDATE approval_terms SET terms = ? WHERE approval_id = ?",
                                 (approval.model_dump_json(), approval.approval_id))
        stored = approval
    services.jobs.put("approval_run", stored.approval_id, run_id)
    legs = gateway.legs(stored.approval_id)
    if not legs:
        outcome = gateway.execute(stored, current_snapshot_id=snapshot.snapshot_id)
        if not outcome.ok:
            raise PreparationError(f"demo execution refused: {outcome.code}")
    # Recover only this preparation, not another execution in the shared app outbox.
    for leg in gateway.legs(stored.approval_id):
        if leg.state == "submitted" and leg.provider_id is None:
            sent = leg.attempts == gateway.outbox._claims(leg)
            gateway.outbox._move(leg, "unknown", "restart_after_send" if sent else "restart",
                                 incident=("outcome_unknown", "prepared execution resumed"))
    # The fake's transactionally stored objects are authoritative, unlike a sandbox lookup.
    # A send that died before committing any fake object can safely reuse the same request id.
    for leg in gateway.legs(stored.approval_id):
        if leg.state == "unknown" and not gateway.provider.find(leg):
            gateway.outbox._move(leg, "pending", "local_fake_lookup_found_none",
                                 close=("outcome_unknown",))
    for _ in stored.legs:
        legs = gateway.run(stored.approval_id)
        if all(leg.state == "settled" and leg.reconciled for leg in legs):
            break
        for leg in legs:
            if leg.state == "settled" and leg.reconciled:
                continue
            if leg.kind == "payout" and leg.state == "submitted" and leg.provider_id:
                pay(client, leg.provider_id, gateway.provider.get(leg).status)
            reconcile.reconcile_leg(gateway, leg.leg_id)
    legs = gateway.legs(stored.approval_id)
    if len(legs) != len(stored.legs) or not all(
            leg.state == "settled" and leg.reconciled for leg in legs):
        raise PreparationError("demo execution has unreconciled legs; no prepared context published")
    return stored.approval_id


def prepare(services: Services, *, timeout: float = 300) -> dict:
    """Run and publish once, resuming the same jobs/approval after an interruption."""
    if services.mode != "fake":
        raise PreparationError("demo preparation requires AIRWALLEX_MODE=fake")
    if services.queue is None:
        raise PreparationError("demo preparation requires REDIS_URL")
    if not math.isfinite(timeout) or timeout <= 0:
        raise PreparationError("timeout must be positive and finite")
    with _exclusive(services.queue.redis, timeout):
        current = services.demo()
        if current["run_id"] and current["execution_id"]:
            return current
        deadline = time.monotonic() + timeout
        state = services.jobs.get("demo_preparation", "current")
        if state is None:
            state = {"run_id": f"demo-{uuid.uuid4().hex[:12]}"}
            services.jobs.put("demo_preparation", "current", state)
        run_id = state["run_id"]
        world = load_world()
        if services.jobs.get("run", run_id) is None:
            services.jobs.put("run_spec", run_id, {"scenario": SCENARIO, "rounds": 5,
                                                   "prepared_demo": True})
            services.jobs.put("run", run_id, new_run(run_id, world.snapshot.snapshot_id,
                                                      world.snapshot.as_of))
        _job(services, RUN, run_id, {"run_id": run_id, "scenario": SCENARIO, "rounds": 5},
             deadline)
        fork_id = f"{run_id}-{FORK}"
        if services.jobs.get("decisions", run_id) is None:
            services.jobs.put("decisions", run_id, pending_decisions(
                run_id, world.snapshot.snapshot_id, 2, family_of(SCENARIO), fork_id))
        _job(services, FORK, run_id, {"run_id": run_id, "scenario": SCENARIO,
                                     "checkpoint_round": 2, "policies": POLICIES}, deadline)
        decisions = services.jobs.get("decisions", run_id)
        if decisions["status"] != "selected":
            raise PreparationError("demo decisions selected no feasible policy")
        execution_id = _execution(services, run_id, decisions["selected"], world)
        return services.prepare_demo(run_id, execution_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timeout", type=float, default=300,
                        help="seconds to wait for the deployed simulation worker (default: 300)")
    args = parser.parse_args(argv)
    try:
        if os.environ.get("AIRWALLEX_MODE", "fake") != "fake":
            raise PreparationError("demo preparation requires AIRWALLEX_MODE=fake")
        for name in ("LEDGER_DATABASE_URL", "REDIS_URL"):
            if not os.environ.get(name):
                raise PreparationError(f"{name} is not set; use the app container's store and queue")
        context = prepare(Services.from_env(), timeout=args.timeout)
    except Exception as error:  # noqa: BLE001 — redact every dependency failure at the CLI boundary
        # Provider/database exceptions can contain request data or credentials; never print them.
        detail = str(error) if isinstance(error, PreparationError) else type(error).__name__
        print(f"prepare-demo: {detail}", file=sys.stderr)
        return 1
    print(json.dumps(context, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The /api/v1 routes (system brief §11, contract C6).

Every body leaves through `_reply`, which validates it against its C6 model first: a response
outside the contract is a server error, never a reply. Reads are public and write nothing; every
user POST, the read-only interview too, needs the demo token; the signed provider webhook is the
one POST without it.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from flask import Blueprint, current_app, request
from pydantic import BaseModel, ValidationError

from ...decisions.candidates import plan_for_now
from ...execution import reconcile
from ...execution.approval import Refusal, bind
from ...finance import schemas as c6
from ...finance.schemas import Money, to_provider_decimal
from ...jobs.runner import (
    FORK,
    POLICIES,
    RUN,
    base_branch,
    family_of,
    fork_branch,
    load_transcript,
)
from ...simulation.clock import HORIZON_ROUNDS
from ...simulation.interview import Interview, ReadOnlyViolation
from ...simulation.scenarios import load_world
from . import reports, views
from .services import API_VERSION, APPROVER, Services

bp = Blueprint("api_v1", __name__)
log = logging.getLogger("ledgerworld.api")


class Refused(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def services() -> Services:
    return current_app.extensions["ledgerworld"]


def _reply(model: type[BaseModel], body: dict[str, Any], status: int = 200,
           as_of: Any = None) -> tuple[dict, int]:
    s = services()
    full = {"as_of": as_of or s.now(), "mode": s.mode, **body}
    return model.model_validate(full).model_dump(mode="json"), status


@bp.errorhandler(Refused)
def _refused(error: Refused) -> tuple[dict, int]:
    return _reply(c6.ErrorResponse, {"error": {"code": error.code, "detail": error.detail[:4000]}},
                  error.status)


def _token() -> None:
    if not services().authorised(request.headers.get("Authorization")):
        raise Refused(401, "token_required",
                      "this route needs Authorization: Bearer <LEDGERWORLD_DEMO_TOKEN>")


def _body(model: type[BaseModel]) -> Any:
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        raise Refused(422, "invalid_request", f"the body is one JSON object: {model.__name__}")
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        raise Refused(422, "invalid_request", str(error)) from None


def _queue():
    queue = services().queue
    if queue is None:
        raise Refused(503, "queue_unavailable", "no job queue is configured (REDIS_URL)")
    return queue


def _run(run_id: str) -> dict:
    doc = services().jobs.get("run", run_id)
    if doc is None:
        raise Refused(404, "unknown_run", f"no run {run_id}")
    return doc


def _job_state(run_id: str, kind: str) -> tuple[str | None, str | None]:
    jobs = [j for j in services().jobs.jobs_of(run_id) if j.kind == kind]
    return (jobs[-1].state, jobs[-1].error) if jobs else (None, None)


# ----------------------------------------------------------------------- observed state

@bp.get("/health")
def health():
    s = services()
    return _reply(c6.HealthResponse, {"ok": True, "airwallex": s.mode, "connected": s.connected,
                                      "model": s.model_kind, "version": API_VERSION})


@bp.get("/overview")
def overview():
    s = services()
    with s.lock:
        body = views.overview(s.store, s.snapshot, s.now(), s.demo())
    return _reply(c6.OverviewResponse, body)


@bp.get("/treasury")
def treasury():
    s = services()
    with s.lock:
        body = views.treasury(s.store, s.snapshot, s.now())
    return _reply(c6.TreasuryResponse, body)


@bp.get("/lending")
def lending():
    s = services()
    with s.lock:
        body = views.lending(s.store, s.snapshot, s.now())
    if body is None:
        raise Refused(404, "no_pool", "the observed snapshot has no lending pool")
    return _reply(c6.LendingResponse, body)


# --------------------------------------------------------------------------------- runs

@bp.post("/runs")
def submit_run():
    _token()
    req: c6.RunRequest = _body(c6.RunRequest)
    s = services()
    world = load_world().snapshot
    world_snapshot = world.snapshot_id
    if req.snapshot_id != world_snapshot:
        raise Refused(422, "unknown_snapshot",
                      f"runs start from the demo world's snapshot {world_snapshot}")
    scenario = req.scenario.model_dump(mode="json")
    try:
        family = family_of(scenario)
    except (ValueError, TypeError) as error:
        raise Refused(422, "invalid_scenario", str(error)) from None
    if not family.scripted and not s.live_runs:
        raise Refused(422, "model_unavailable",
                      f"{family.id} off its file's parameters needs a live model; none is set")
    queue = _queue()
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    s.jobs.put("run_spec", run_id, {"scenario": scenario, "rounds": req.rounds})
    s.jobs.put("run", run_id, {"run_id": run_id, "snapshot_id": req.snapshot_id,
                               "committed_round": None, "rounds": [], "feed": [],
                               "cash_paths": [], "branches": [],
                               "as_of": world.as_of.isoformat()})  # the run's own clock
    job = queue.submit(RUN, run_id, {"run_id": run_id, "scenario": scenario,
                                     "rounds": req.rounds})
    return _reply(c6.JobAccepted, {"job_id": job.job_id, "run_id": run_id,
                                   "branch_ids": [base_branch(run_id)]}, 202)


@bp.get("/runs/<run_id>")
def get_run(run_id: str):
    doc = _run(run_id)
    state, _ = _job_state(run_id, RUN)
    body = {k: doc[k] for k in ("run_id", "snapshot_id", "committed_round", "rounds", "feed",
                                "cash_paths", "branches")}
    return _reply(c6.RunResponse, {**body, "status": state or "queued"}, as_of=doc["as_of"])


@bp.post("/runs/<run_id>/fork")
def fork_run(run_id: str):
    _token()
    req: c6.ForkRequest = _body(c6.ForkRequest)
    s = services()
    doc = _run(run_id)
    state, _ = _job_state(run_id, RUN)
    if state != "done":
        raise Refused(409, "run_not_done", f"run {run_id} is {state}; fork a finished run")
    if not 1 <= req.checkpoint_round <= min(doc["committed_round"] or 0, HORIZON_ROUNDS - 1):
        raise Refused(422, "checkpoint_out_of_range",
                      f"fork at a committed round in 1..{doc['committed_round']}, before the "
                      f"horizon round {HORIZON_ROUNDS}")
    spec = s.jobs.get("run_spec", run_id)
    family = family_of(spec["scenario"])
    policies = list(dict.fromkeys(req.policies))
    queue = _queue()
    job = queue.submit(FORK, run_id, {"run_id": run_id, "checkpoint_round": req.checkpoint_round,
                                      "policies": policies, "scenario": spec["scenario"]})
    s.jobs.put("decisions", run_id, {
        "run_id": run_id, "snapshot_id": doc["snapshot_id"],
        "checkpoint_round": req.checkpoint_round,
        "cohort": f"{family.id} seed {family.seed}: 1 scenario, each policy in a fresh branch",
        "weight_kind": "unweighted", "status": "pending", "results": [], "selected": None,
        "escalation": None, "job_id": job.job_id})
    return _reply(c6.JobAccepted, {
        "job_id": job.job_id, "run_id": run_id,
        "branch_ids": [fork_branch(run_id, family.id, p) for p in policies]}, 202)


# ---------------------------------------------------------------------------- decisions

DECISION_FIELDS = ("run_id", "snapshot_id", "checkpoint_round", "cohort", "weight_kind",
                   "status", "results", "selected", "escalation")


def _decisions(run_id: str) -> dict:
    doc = services().jobs.get("decisions", run_id)
    if doc is None:
        raise Refused(404, "no_decisions", f"run {run_id} has not been forked")
    if doc["status"] == "pending":
        state, error = _job_state(run_id, FORK)
        if state in ("failed", "cancelled"):
            raise Refused(409, "fork_failed", f"the fork of {run_id} {state}: {error or ''}")
    return doc


@bp.get("/decisions/<run_id>")
def decisions(run_id: str):
    doc = _decisions(run_id)
    return _reply(c6.DecisionsResponse, {k: doc[k] for k in DECISION_FIELDS})


# ----------------------------------------------------------------- approval, execution

@bp.post("/approvals")
def approve():
    _token()
    req: c6.ApprovalRequest = _body(c6.ApprovalRequest)
    s = services()
    doc = _decisions(req.run_id)
    if doc["status"] != "selected":
        raise Refused(409, f"decision_{doc['status']}",
                      f"run {req.run_id}'s decision is {doc['status']}: nothing to approve")
    if req.policy != doc["selected"]:
        raise Refused(409, "not_selected",
                      f"{req.policy} is not the policy selected for {req.run_id}")
    with s.lock:
        now = s.now()
        try:
            plan = plan_for_now(POLICIES[req.policy], s.snapshot, epoch=s.epoch,
                                beneficiaries=s.beneficiaries, terms=s.terms)
        except ValueError as error:
            raise Refused(409, "no_plan", str(error)) from None
        if plan is None:
            raise Refused(409, "nothing_to_approve",
                          f"{req.policy} does nothing on the observed snapshot "
                          f"{s.snapshot.snapshot_id}")
        approval = bind(plan, s.snapshot, APPROVER, s.mode, now=now)
        gateway = s.gateway()
        if gateway.stored(approval.approval_id) is not None:
            raise Refused(409, "already_approved",
                          f"this plan is already approval {approval.approval_id}")
        gateway.record(approval)
        s.jobs.put("approval_run", approval.approval_id, req.run_id)
    return _reply(c6.ApprovalResponse, {"approval": approval.model_dump(mode="json")}, 201)


@bp.post("/executions")
def execute():
    _token()
    req: c6.ExecutionRequest = _body(c6.ExecutionRequest)
    s = services()
    with s.lock:
        gateway = s.gateway()
        stored = gateway.stored(req.approval_id)
        if stored is None:
            raise Refused(404, "unknown_approval", f"no approval {req.approval_id}")
        outcome = gateway.execute(stored.model_dump(mode="json"),
                                  current_snapshot_id=s.snapshot.snapshot_id)
        if isinstance(outcome, Refusal):
            raise Refused(409, outcome.code, outcome.detail)
        try:
            reconcile.sweep(gateway)
        except Exception:  # the legs are queued and recorded; the next read sweeps again
            log.exception("reconciliation sweep after %s failed", req.approval_id)
    return _reply(c6.ExecutionAccepted, {"execution_id": stored.approval_id}, 202)


def _leg(gateway: Any, leg: Any, mode: str) -> dict:
    receipt = None
    if leg.provider_id and leg.provider_status:
        event = gateway.conn.execute(
            "SELECT raw_keys, at FROM leg_events WHERE leg_id = ? AND provider_status IS NOT NULL"
            " ORDER BY event_seq DESC LIMIT 1", (leg.leg_id,)).fetchone()
        receipt = {
            "provider_id": leg.provider_id, "request_id": leg.request_id, "kind": leg.kind,
            "status": leg.provider_status,
            "amount": to_provider_decimal(Money(minor=leg.amount_minor, currency=leg.currency)),
            "currency": leg.currency, "label": leg.receipt_label, "mode": mode,
            "raw_keys": json.loads(event[0]) if event and event[0] else [],
            "observed_at": event[1] if event else None,
        }
    return {"leg_id": leg.leg_id, "request_id": leg.request_id, "kind": leg.kind,
            "provider_id": leg.provider_id, "state": leg.state, "receipt": receipt,
            "reconciled": leg.reconciled, "journal_id": leg.journal_id,
            "label": leg.receipt_label}


@bp.get("/executions/<execution_id>")
def execution(execution_id: str):
    s = services()
    with s.lock:
        gateway = s.gateway()
        approval = gateway.stored(execution_id)
        if approval is None:
            raise Refused(404, "unknown_execution", f"no execution {execution_id}")
        legs = gateway.legs(execution_id)
        ids = {leg.leg_id for leg in legs}
        incidents = [{"incident_id": i["incident_id"], "leg_id": i["leg_id"], "kind": i["kind"],
                      "state": "open" if i["closed_at"] is None else "closed",
                      "opened_at": i["opened_at"]}
                     for i in gateway.incidents() if i["leg_id"] in ids]
        body = {"execution_id": execution_id, "approval_id": approval.approval_id,
                "snapshot_id": approval.snapshot_id,
                "legs": [_leg(gateway, leg, approval.mode) for leg in legs],
                "incidents": incidents}
    return _reply(c6.ExecutionResponse, body)


@bp.post("/webhooks/airwallex")
def webhook():
    s = services()
    if not s.webhook_secret:
        raise Refused(503, "webhook_not_configured", "AIRWALLEX_WEBHOOK_SECRET is not set")
    with s.lock:
        verifier = reconcile.webhook_verifier(s.gateway(), s.webhook_secret)
        status = verifier.verify_and_ingest(dict(request.headers), request.get_data(),
                                            s.wall_ms())
    if status != 200:
        raise Refused(401, "bad_signature", "the webhook's signature or timestamp does not verify")
    return _reply(c6.WebhookAck, {"accepted": True})


# ------------------------------------------------------------------- interview, report

class _NoMemory:
    """A run's world keeps no graph memory: the interview reads the transcript alone."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace

    def retrieve(self, **_: Any) -> list:
        return []


@bp.post("/interview")
def interview():
    _token()
    req: c6.InterviewRequest = _body(c6.InterviewRequest)
    s = services()
    transcript = load_transcript(s.jobs, req.run_id, req.branch_id)
    if transcript is None:
        raise Refused(404, "no_transcript",
                      f"no transcript of {req.branch_id} in run {req.run_id}")
    if not any(c.actor_id == req.actor_id for c in transcript.calls()):
        raise Refused(404, "not_interviewable",
                      f"{req.actor_id} gave no model answer in {req.branch_id}")
    try:
        session = Interview.open(_NoMemory(transcript.namespace), transcript, req.actor_id,
                                 as_of_round=req.round)
    except ValueError as error:
        raise Refused(422, "invalid_round", str(error)) from None
    model = s.interview_model(req.actor_id) if s.interview_model else None
    if model is None:
        raise Refused(503, "model_unavailable", "no interview model is configured")
    try:
        answer = session.ask(model, req.question)
    except ReadOnlyViolation as error:
        raise Refused(409, "read_only_violation", str(error)) from None
    evidence = list(dict.fromkeys(c.obs_hash for c in session.calls))
    return _reply(c6.InterviewResponse, {
        "run_id": req.run_id, "branch_id": req.branch_id, "round": req.round,
        "actor_id": req.actor_id, "answer": answer.answer[:4000], "read_only": True,
        "replay": False, "evidence_ids": evidence})


@bp.get("/reports/<run_id>")
def report(run_id: str):
    doc = _run(run_id)
    state, _ = _job_state(run_id, RUN)
    if state != "done":
        raise Refused(409, "run_not_done", f"run {run_id} is {state}; a report reads a "
                      "finished run")
    s = services()
    body = reports.report(doc, s.jobs.get("decisions", run_id), key=s.report_key)
    return _reply(c6.ReportResponse, body, as_of=doc["as_of"])

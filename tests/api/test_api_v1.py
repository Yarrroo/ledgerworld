"""/api/v1 (T16): every C6 route on LF-1/LF-2, the token boundary, runs as durable jobs.

The observed state is LF-1's treasury beside LF-2's pool in one C5 snapshot (as the execution
tests join them), read at t = 12 h after the receivable's delay was observed: settled 70,000.00,
payroll 50,000.00 held, the receivable now due after the horizon. Every body is validated twice,
against `contracts/c6_api.schema.json` and against its pydantic model. Runs and forks go through
the real queue (fakeredis) and a real worker on the demo world's scripted families; the provider
is the connector's fake behind the real client.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import fakeredis
import pytest
from app import create_app
from app.api.v1 import Services, register
from app.api.v1.services import beneficiaries_for
from app.connectors.airwallex.client import AirwallexClient
from app.connectors.airwallex.fake import FakeClock, FakeTransport
from app.execution.gateway import Gateway
from app.finance import schemas as c6
from app.finance.schemas import Snapshot
from app.jobs import JobQueue, JobStore, Worker
from app.jobs.runner import Runner, base_branch
from app.simulation.scenarios import load_world
from app.simulation.world import import_oasis
from app.testing.scripted_model import ScriptedPlan
from flask import Flask
from jsonschema import Draft202012Validator

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

ROOT = Path(__file__).resolve().parents[2]
C6 = json.loads((ROOT / "contracts/c6_api.schema.json").read_text(encoding="utf-8"))
LF1 = json.loads((ROOT / "fixtures/lf1_treasury.json").read_text(encoding="utf-8"))
LF2 = json.loads((ROOT / "fixtures/lf2_lender.json").read_text(encoding="utf-8"))
T0 = datetime.fromisoformat(LF1["t0"])
NOW = T0 + timedelta(hours=12)
TOKEN = "test-demo-token"  # a test value, not a credential
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TERMS = {"adv-a": {"arrive_by_h": 18}}  # LF-1: the advance is eligible when it lands by t = 18
WEBHOOK_SECRET = "test-webhook-secret"  # a test value, not a credential
DELAYED = {"family": "delayed_receipt", "seed": 101, "params": {}}
WORLD = load_world()


def iso(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


def observed(stressed: bool = False) -> dict:
    """LF-2's pool (or its venue freeze) with LF-1's treasury, observed at t = 12 h after the
    receivable's 240 h delay: one C5 snapshot."""
    snap = copy.deepcopy(LF2["stressed"]["venue_freeze"] if stressed else LF2["snapshot"])
    lf1 = copy.deepcopy(LF1["snapshot"])
    snap["accounts"] += lf1["accounts"]
    snap["obligations"] += lf1["obligations"]
    snap["snapshot_id"] = "obs-lf-venue-freeze" if stressed else "obs-lf"
    snap["as_of"] = iso(NOW)
    for account in snap["accounts"]:
        account["as_of"] = iso(NOW)
        for flow in account["buckets"]["pending_in"]:
            if flow["flow_id"] == "rcv-1":
                flow["expected_at"] = iso(T0 + timedelta(hours=252))
    return snap


def fake_gateway(services: Services) -> Gateway:
    fake = FakeTransport(clock=FakeClock())
    client = AirwallexClient(fake, fake.clock, api_version="2024-06-30", sleep=lambda _: None)
    return Gateway(services.store, client, mode="fake", leg_mode="B",
                   beneficiaries=set(services.beneficiaries.values()), clock=services.now,
                   global_account_id="ga-usd-1")


def interview_model(actor_id: str):
    return ScriptedPlan([{"default": True, "content": "I held the payroll reservation."}]).model(
        actor_id, lambda: 0)


def build(snapshot: dict | None = None, *, clock=None, token: str | None = TOKEN,
          redis=None) -> Services:
    snap = Snapshot.model_validate(snapshot or observed())
    return Services.build(snap, redis=redis or fakeredis.FakeRedis(), epoch=T0, mode="fake",
                          token=token, make_gateway=fake_gateway, clock=clock, terms=TERMS,
                          webhook_secret=WEBHOOK_SECRET, interview_model=interview_model,
                          wall_ms=lambda: 1_700_000_000_000)


def client(services: Services):
    app = Flask(__name__)
    register(app, services)
    return app.test_client()


def check(resp, name: str, status: int = 200) -> dict:
    """The body answers C6's `name` (JSON Schema and pydantic) with `status`."""
    body = resp.get_json()
    assert resp.status_code == status, body
    schema = {"$schema": C6["$schema"], "$defs": C6["$defs"], "$ref": f"#/$defs/{name}"}
    Draft202012Validator(schema).validate(body)
    getattr(c6, name).model_validate(body)
    assert {"as_of", "mode"} <= set(body)
    return body


def refused(resp, status: int, code: str) -> dict:
    body = check(resp, "ErrorResponse", status)
    assert body["error"]["code"] == code, body
    return body


def state_of_store(services: Services) -> dict:
    """Everything a read could write: the ledger, the job rows and records, the queue."""
    from app.jobs.store import jobs, records

    with services.store.engine.begin() as c:
        api = {t.name: [tuple(r) for r in c.execute(t.select())] for t in (jobs, records)}
    return {"ledger": services.store.dump(), "api": api,
            "redis": sorted(services.queue.redis.keys())}


def worker(services: Services, tmp_path: Path) -> Worker:
    runner = Runner(services.jobs, tmp_path / "jobs", world=WORLD)
    return Worker(services.queue, runner.handlers(), worker="w-test")


# --------------------------------------------------------------------------- the routes

def test_create_app_mounts_exactly_the_c6_routes():
    def shape(route: str) -> str:
        return re.sub(r"[<{][^>}]+[>}]", "{}", route)

    app = create_app()
    mounted = {shape(f"{m} {r.rule}") for r in app.url_map.iter_rules()
               if r.rule.startswith("/api/v1/") for m in r.methods - {"HEAD", "OPTIONS"}}
    assert mounted == {shape(route) for route in C6["x-routes"]}
    assert set(C6["x-routes"]) == set(c6.C6_ROUTES)


def test_health_names_the_provider_mode_and_the_model():
    body = check(client(build()).get("/api/v1/health"), "HealthResponse")
    assert (body["ok"], body["airwallex"], body["mode"], body["model"]) == (
        True, "fake", "fake", "scripted")
    assert body["connected"] is False


# --------------------------------------------------------------------- observed screens

def test_overview_on_lf1_lf2_after_the_delay():
    body = check(client(build()).get("/api/v1/overview"), "OverviewResponse")
    usd = {"currency": "USD", "status": "known"}
    assert body["snapshot_id"] == "obs-lf" and body["as_of"] == iso(NOW)
    assert body["cash"] | {"as_of": None} == {**usd, "minor": 7_000_000, "as_of": None}
    assert body["spendable"]["minor"] == 2_000_000  # S = 70,000 − 50,000 held
    # LF-1 shocked: P(t=40) after payroll = 20,000.00 < floor 30,000.00, short 10,000.00.
    cov = body["coverage"]
    assert (cov["min_projected"]["minor"], cov["at"]) == (2_000_000, iso(T0 + timedelta(hours=40)))
    assert (cov["floor"]["minor"], cov["headroom"]["minor"]) == (3_000_000, -1_000_000)
    assert body["upcoming_outflows"] == [{
        "obligation_id": "payroll-1", "kind": "payroll", "reserved": True,
        "amount": {"minor": 5_000_000, "currency": "USD"},
        "due_at": iso(T0 + timedelta(hours=40))}]
    assert body["lender_capacity"]["minor"] == 4_200_000  # LF-2: K_p = 42,000.00
    assert body["completeness"] == {"status": "complete", "missing": []}
    assert body["demo"] == {"run_id": None, "execution_id": None}  # nothing prepared: null


def test_venue_freeze_is_partial_and_unknown_is_never_zero():
    services = build(observed(stressed=True))
    http = client(services)
    body = check(http.get("/api/v1/overview"), "OverviewResponse")
    assert body["lender_capacity"]["minor"] == 2_700_000  # LF-2 stressed: K_p = 27,000.00
    assert body["completeness"] == {"status": "partial", "missing": ["lender/venue"]}
    lending = check(http.get("/api/v1/lending"), "LendingResponse")
    assert lending["capacity"]["authority"] == "reduced"
    assert lending["capacity"]["parts"]["settled_known"]["minor"] == 4_500_000


def test_lending_shows_k_p_its_parts_and_an_unassessed_revenue():
    body = check(client(build()).get("/api/v1/lending"), "LendingResponse")
    assert (body["pool"], body["capacity"]["K_p"]["minor"]) == ("lender", 4_200_000)
    parts = {k: v["minor"] for k, v in body["capacity"]["parts"].items()}
    assert parts == {"settled_known": 6_000_000, "committed_undrawn": 1_000_000, "pledged": 0,
                     "obligations_due": 0, "floor": 800_000}
    adv = next(f for f in body["facilities"] if f["facility_id"] == "adv-a")
    assert (adv["principal"]["minor"], adv["fee"]["minor"], adv["owed"]["minor"]) == (
        1_000_000, 80_000, 1_080_000)
    assert adv["observed_revenue"] == {"minor": None, "currency": "USD", "status": "unassessed",
                                       "as_of": None}


def test_treasury_shows_s_and_p_apart_and_a_stale_balance_keeps_its_value():
    fresh = check(client(build()).get("/api/v1/treasury"), "TreasuryResponse")
    (account,) = fresh["accounts"]
    assert (account["id"], account["authority"]) == ("borrower-a/operating", "full")
    assert account["spendable"]["minor"] == 2_000_000
    assert [p["value"]["minor"] for p in account["projected"]][-2:] == [2_000_000, 3_500_000]
    assert fresh["obligations"][0]["reservation_id"] == "res-payroll-1"
    later = build(clock=lambda: NOW + timedelta(hours=7))  # 7 h > STALE_AFTER (6 h)
    stale = check(client(later).get("/api/v1/treasury"), "TreasuryResponse")
    (account,) = stale["accounts"]
    assert account["spendable"]["status"] == "stale" and account["spendable"]["minor"] == 2_000_000
    assert account["authority"] == "reduced"
    over = check(client(later).get("/api/v1/overview"), "OverviewResponse")
    assert (over["cash"]["status"], over["cash"]["minor"]) == ("stale", 7_000_000)
    assert over["completeness"]["status"] == "partial"


def test_an_unknown_treasury_balance_has_no_value():
    snap = observed()
    acct = next(a for a in snap["accounts"] if a["id"] == "borrower-a/operating")
    acct["observability"], acct["buckets"]["settled"] = "unknown", None
    http = client(build(snap))
    body = check(http.get("/api/v1/overview"), "OverviewResponse")
    assert body["cash"]["status"] == "unknown" and body["cash"]["minor"] is None
    assert body["coverage"]["min_projected"]["minor"] is None
    (account,) = check(http.get("/api/v1/treasury"), "TreasuryResponse")["accounts"]
    assert (account["spendable"]["status"], account["authority"]) == ("unknown", "reduced")


# -------------------------------------------------------------------------- the token

WRITES = [
    ("/api/v1/runs", {"snapshot_id": "demo-world", "scenario": DELAYED, "rounds": 3}),
    ("/api/v1/runs/run-x/fork", {"checkpoint_round": 1, "policies": ["integrated"]}),
    ("/api/v1/approvals", {"run_id": "run-x", "policy": "integrated"}),
    ("/api/v1/executions", {"approval_id": "apr-x"}),
    ("/api/v1/interview", {"run_id": "run-x", "branch_id": "b", "round": 1,
                           "actor_id": "treasury", "question": "why?"}),
]


@pytest.mark.parametrize("path,body", WRITES, ids=[w[0].rsplit("/", 1)[-1] for w in WRITES])
@pytest.mark.parametrize("header", [None, "Bearer wrong-token", TOKEN])
def test_every_user_post_needs_the_token_and_a_refusal_writes_nothing(path, body, header):
    services = build()
    before = state_of_store(services)
    headers = {"Authorization": header} if header else {}
    refused(client(services).post(path, json=body, headers=headers), 401, "token_required")
    assert state_of_store(services) == before


def test_no_configured_token_admits_nobody():
    services = build(token=None)
    refused(client(services).post("/api/v1/approvals", json=WRITES[2][1],
                                  headers={"Authorization": "Bearer "}), 401, "token_required")


def test_the_judge_path_reads_without_a_token_and_writes_nothing():
    services = build()
    http = client(services)
    before = state_of_store(services)
    for path in ("health", "overview", "treasury", "lending"):
        assert http.get(f"/api/v1/{path}").status_code == 200
    for path in ("runs/run-x", "decisions/run-x", "executions/apr-x", "reports/run-x"):
        assert http.get(f"/api/v1/{path}").status_code == 404
    assert state_of_store(services) == before


# -------------------------------------------------------------------- runs as jobs

@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """One delayed-receipt run through the queue and a worker, then forked at round 2."""
    tmp = tmp_path_factory.mktemp("ran")
    services = build()
    http = client(services)
    started = time.monotonic()
    accepted = check(http.post("/api/v1/runs", headers=AUTH, json={
        "snapshot_id": "demo-world", "scenario": DELAYED, "rounds": 5}), "JobAccepted", 202)
    submit_s = time.monotonic() - started
    queued = check(http.get(f"/api/v1/runs/{accepted['run_id']}"), "RunResponse")
    done = worker(services, tmp).run_once()
    finished = check(http.get(f"/api/v1/runs/{accepted['run_id']}"), "RunResponse")
    fork = check(http.post(f"/api/v1/runs/{accepted['run_id']}/fork", headers=AUTH, json={
        "checkpoint_round": 2, "policies": ["no-action", "fixed-reserve", "integrated"]}),
        "JobAccepted", 202)
    pending = check(http.get(f"/api/v1/decisions/{accepted['run_id']}"), "DecisionsResponse")
    forked = worker(services, tmp).run_once()
    return {"services": services, "http": http, "accepted": accepted, "submit_s": submit_s,
            "queued": queued, "job": done, "run": finished, "fork": fork, "pending": pending,
            "fork_job": forked}


def test_a_run_is_accepted_in_under_a_second_and_reads_queued(ran):
    assert ran["submit_s"] < 1.0
    run_id = ran["accepted"]["run_id"]
    assert ran["accepted"]["branch_ids"] == [base_branch(run_id)]
    queued = ran["queued"]
    assert (queued["status"], queued["committed_round"], queued["rounds"]) == ("queued", None, [])
    assert queued["as_of"] == iso(WORLD.epoch)  # the run's simulated clock, not the observed one


def test_the_worker_runs_the_family_and_every_committed_round_is_readable(ran):
    assert (ran["job"].state, ran["job"].attempts) == ("done", 1)
    run = ran["run"]
    assert (run["status"], run["committed_round"], run["snapshot_id"]) == ("done", 5, "demo-world")
    assert [r["round"] for r in run["rounds"]] == [1, 2, 3, 4, 5]
    assert all(r["branch_id"] == base_branch(run["run_id"]) for r in run["rounds"])
    assert any(c["status"] == "accepted" and r["intents"] for r in run["rounds"]
               for c in r["cleared"])
    (path,) = [p for p in run["cash_paths"] if p["branch_id"] == base_branch(run["run_id"])]
    assert path["account_id"] == "treasury/operating" and len(path["points"]) == 6
    assert path["points"][0]["value"]["minor"] == 7_000_000
    assert run["as_of"] == path["points"][-1]["t"]


def test_a_fork_is_pending_then_decided_on_fresh_branches(ran):
    run_id = ran["accepted"]["run_id"]
    assert ran["pending"]["status"] == "pending" and ran["pending"]["results"] == []
    assert ran["fork_job"].state == "done", ran["fork_job"].error
    decided = check(ran["http"].get(f"/api/v1/decisions/{run_id}"), "DecisionsResponse")
    assert decided["status"] in ("selected", "all_infeasible")
    assert decided["checkpoint_round"] == 2 and decided["weight_kind"] == "unweighted"
    assert {r["branch_id"] for r in decided["results"]} == set(ran["fork"]["branch_ids"])
    run = check(ran["http"].get(f"/api/v1/runs/{run_id}"), "RunResponse")
    forks = [b for b in run["branches"] if b["policy"]]
    assert {b["branch_id"] for b in forks} == set(ran["fork"]["branch_ids"])
    assert {(b["parent_branch_id"], b["checkpoint_round"]) for b in forks} == {
        (base_branch(run_id), 2)}


def test_interview_is_read_only_and_needs_the_token(ran):
    services, http = ran["services"], ran["http"]
    run_id = ran["accepted"]["run_id"]
    ask = {"run_id": run_id, "branch_id": base_branch(run_id), "round": 2,
           "actor_id": "treasury", "question": "Why did you hold cash?"}
    before = state_of_store(services)
    body = check(http.post("/api/v1/interview", headers=AUTH, json=ask), "InterviewResponse")
    assert (body["read_only"], body["answer"]) == (True, "I held the payroll reservation.")
    assert body["evidence_ids"]
    assert state_of_store(services) == before
    refused(http.post("/api/v1/interview", json=ask), 401, "token_required")
    refused(http.post("/api/v1/interview", headers=AUTH, json=ask | {"round": 99}), 422,
            "invalid_round")


def test_the_report_figures_trace_to_the_run(ran):
    run_id = ran["accepted"]["run_id"]
    body = check(ran["http"].get(f"/api/v1/reports/{run_id}"), "ReportResponse")
    assert body["model"] == "scripted" and body["sections"]
    cash = body["sections"][0]
    assert "USD 70,000.00" in cash["text"]
    assert {f["source"]["run_id"] for s in body["sections"] for f in s["figures"]} == {run_id}


def test_a_run_request_the_world_cannot_run_is_refused_before_it_queues():
    services = build()
    http = client(services)
    refused(http.post("/api/v1/runs", headers=AUTH, json={
        "snapshot_id": "obs-lf", "scenario": DELAYED, "rounds": 3}), 422, "unknown_snapshot")
    refused(http.post("/api/v1/runs", headers=AUTH, json={
        "snapshot_id": "demo-world", "scenario": DELAYED | {"params": {"nope": 1}},
        "rounds": 3}), 422, "invalid_scenario")
    refused(http.post("/api/v1/runs", headers=AUTH, json={
        "snapshot_id": "demo-world", "scenario": DELAYED | {"params": {"delay_h": 120}},
        "rounds": 3}), 422, "model_unavailable")
    refused(http.post("/api/v1/runs", headers=AUTH, json={"rounds": 0}), 422, "invalid_request")
    assert services.jobs.in_state("queued") == []


# -------------------------------------------------------------- the job queue itself

def queue(**kwargs) -> JobQueue:
    from app.finance.store import LedgerStore

    return JobQueue(JobStore(LedgerStore("sqlite://").engine), fakeredis.FakeRedis(), **kwargs)


def test_an_expired_lease_is_retried_and_attempts_run_out():
    q = queue(lease_s=0.05, max_attempts=2)
    job = q.submit("run", "run-1", {})
    assert q.claim("w1").attempts == 1
    time.sleep(0.1)  # w1 died: its lease expires
    assert q.reap() == [job.job_id]
    assert q.store.job(job.job_id).state == "queued"
    again = q.claim("w2")
    assert (again.attempts, again.worker) == (2, "w2")
    assert not q.complete(job, "w1")  # the dead worker cannot finish w2's attempt
    time.sleep(0.1)
    q.reap()
    assert q.store.job(job.job_id).state == "failed"
    assert "lease expired" in q.store.job(job.job_id).error


def test_a_failed_attempt_retries_and_a_value_error_does_not():
    q = queue(max_attempts=3)
    calls = []

    def flaky(job, ctx):
        calls.append(job.attempts)
        if len(calls) < 2:
            raise RuntimeError("transient")

    w = Worker(q, {"run": flaky, "bad": lambda job, ctx: (_ for _ in ()).throw(
        ValueError("the world cannot run this"))})
    job = q.submit("run", "run-1", {})
    assert w.run_once().state == "queued"
    assert w.run_once().state == "done" and calls == [1, 2]
    bad = q.submit("bad", "run-2", {})
    assert w.run_once().state == "failed"
    assert q.store.job(bad.job_id).attempts == 1
    assert q.store.job(job.job_id).error is None


def test_cancel_a_queued_job_and_a_running_one():
    q = queue()
    ran = []
    queued = q.submit("run", "run-1", {})
    assert q.cancel(queued.job_id).state == "cancelled"

    def long(job, ctx):
        ran.append(job.job_id)
        q.cancel(job.job_id)  # an operator cancels while it runs
        ctx.checkpoint()
        raise AssertionError("a cancelled job does not go on")

    running = q.submit("run", "run-2", {})
    assert Worker(q, {"run": long}).run_once().state == "cancelled"
    assert ran == [running.job_id]  # the queued one never ran
    assert q.redis.lrange(q.processing_key, 0, -1) == []


def test_a_cancelled_run_reads_cancelled(tmp_path):
    services = build()
    http = client(services)
    run_id = check(http.post("/api/v1/runs", headers=AUTH, json={
        "snapshot_id": "demo-world", "scenario": DELAYED, "rounds": 3}),
        "JobAccepted", 202)["run_id"]
    services.queue.cancel(services.jobs.jobs_of(run_id)[0].job_id)
    assert worker(services, tmp_path).run_once() is None
    assert check(http.get(f"/api/v1/runs/{run_id}"), "RunResponse")["status"] == "cancelled"


def test_job_state_survives_a_redis_that_lost_its_data():
    q = queue()
    job = q.submit("run", "run-1", {})
    q.redis.flushall()
    assert q.reap() == [job.job_id]
    assert q.claim("w1").job_id == job.job_id


# ---------------------------------------------------------- approval and execution

def decided(services: Services, run_id: str = "run-demo", status: str = "selected") -> str:
    """A finished run whose decision selected the integrated policy (as a fork records it)."""
    services.jobs.put("run", run_id, {"run_id": run_id, "snapshot_id": "demo-world",
                                      "committed_round": 0, "rounds": [], "feed": [],
                                      "cash_paths": [], "branches": [], "as_of": iso(NOW)})
    services.jobs.put("decisions", run_id, {
        "run_id": run_id, "snapshot_id": "demo-world", "checkpoint_round": 2,
        "cohort": "delayed-receipt seed 101", "weight_kind": "unweighted", "status": status,
        "results": [], "selected": "integrated" if status == "selected" else None,
        "escalation": None})
    return run_id


def test_approve_then_execute_the_plan_on_the_observed_snapshot():
    services = build()
    http = client(services)
    run_id = decided(services)
    approval = check(http.post("/api/v1/approvals", headers=AUTH, json={
        "run_id": run_id, "policy": "integrated"}), "ApprovalResponse", 201)["approval"]
    assert (approval["snapshot_id"], approval["mode"], approval["approver"]) == (
        "obs-lf", "fake", "operator")
    legs = [(leg["kind"], leg["amount"]["minor"]) for leg in approval["legs"]]
    assert legs == [("advance", 1_000_000), ("payout", 5_000_000)]  # LF-1's integrated plan
    assert approval["legs"][1]["counterparty"] == beneficiaries_for(services.snapshot)["payroll-1"]
    refused(http.post("/api/v1/approvals", headers=AUTH, json={
        "run_id": run_id, "policy": "integrated"}), 409, "already_approved")
    executed = check(http.post("/api/v1/executions", headers=AUTH, json={
        "approval_id": approval["approval_id"]}), "ExecutionAccepted", 202)
    assert executed["execution_id"] == approval["approval_id"]
    body = check(http.get(f"/api/v1/executions/{approval['approval_id']}"), "ExecutionResponse")
    assert [leg["kind"] for leg in body["legs"]] == ["advance", "payout"]
    assert body["legs"][0]["state"] in ("submitted", "settled")
    refused(http.post("/api/v1/executions", headers=AUTH, json={
        "approval_id": approval["approval_id"]}), 409, "approval_used")


def test_approval_needs_a_selected_policy():
    services = build()
    http = client(services)
    refused(http.post("/api/v1/approvals", headers=AUTH, json={
        "run_id": decided(services, "run-p", "pending"), "policy": "integrated"}),
        409, "decision_pending")
    refused(http.post("/api/v1/approvals", headers=AUTH, json={
        "run_id": decided(services), "policy": "no-action"}), 409, "not_selected")
    refused(http.post("/api/v1/approvals", headers=AUTH, json={
        "run_id": "run-none", "policy": "integrated"}), 404, "no_decisions")


def test_overview_names_the_demo_execution_only_when_it_came_from_the_demo_run():
    services = build()
    http = client(services)
    demo_run = decided(services, "run-demo")
    approval_id = check(http.post("/api/v1/approvals", headers=AUTH, json={
        "run_id": demo_run, "policy": "integrated"}), "ApprovalResponse", 201)[
        "approval"]["approval_id"]
    other = decided(services, "run-other")
    with pytest.raises(ValueError):
        services.prepare_demo(other, approval_id)  # never an unrelated execution
    services.prepare_demo(other)
    demo = check(http.get("/api/v1/overview"), "OverviewResponse")["demo"]
    assert demo == {"run_id": other, "execution_id": None}
    services.prepare_demo(demo_run, approval_id)
    demo = check(http.get("/api/v1/overview"), "OverviewResponse")["demo"]
    assert demo == {"run_id": demo_run, "execution_id": approval_id}


# ------------------------------------------------------------------------- webhook

def signed(body: bytes, ts: int, secret: str = WEBHOOK_SECRET) -> dict:
    sig = hmac.new(secret.encode(), str(ts).encode() + body, hashlib.sha256).hexdigest()
    return {"x-timestamp": str(ts), "x-signature": sig, "Content-Type": "application/json"}


def test_the_webhook_is_verified_by_signature_not_by_token():
    services = build()
    http = client(services)
    raw = json.dumps({"id": "evt-1", "name": "payout.transfer.paid",
                      "data": {"object": {"id": "tr-unknown"}}}).encode()
    now = services.wall_ms()
    refused(http.post("/api/v1/webhooks/airwallex", data=raw,
                      headers=signed(raw, now, "wrong")), 401, "bad_signature")
    refused(http.post("/api/v1/webhooks/airwallex", data=raw,
                      headers=signed(raw, now - 6 * 60_000)), 401, "bad_signature")
    body = check(http.post("/api/v1/webhooks/airwallex", data=raw, headers=signed(raw, now)),
                 "WebhookAck")
    assert body["accepted"] is True


# --------------------------------------------------------------------- the fence

def test_the_simulation_worker_loads_no_connector_and_no_gateway(tmp_path):
    code = ("import sys, app.jobs.runner, app.jobs.__main__\n"
            "bad = sorted(m for m in sys.modules if ('airwallex' in m and not m.endswith('.fake')"
            " and not m.endswith('airwallex')) or m == 'app.execution.gateway')\n"
            "print(bad)\n")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        str(ROOT / p) for p in ("backend", "packages/oasis-finance/src"))}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=tmp_path, env=env, check=True)
    assert out.stdout.strip() == "[]", out.stdout + out.stderr

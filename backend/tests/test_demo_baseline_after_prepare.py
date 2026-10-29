"""After the operator prepares the demo, the public screens show the prepared run's observed
snapshot, fresh at its own as_of; the executed legs show on Execution only."""
from __future__ import annotations

import threading
from datetime import timedelta

import fakeredis
import pytest
from app.api.v1 import register
from app.api.v1.services import Services, gateway_from_env
from app.demo import prepare
from app.demo.run import observed_snapshot
from app.finance.store import LedgerStore
from app.jobs.queue import JobQueue, Worker
from app.jobs.runner import Runner
from app.jobs.store import JobStore
from app.simulation.scenarios import load_world
from flask import Flask

USD = "USD"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRWALLEX_MODE", "fake")
    world = load_world()
    url = f"sqlite:///{tmp_path / 'app.sqlite'}"
    store = LedgerStore(url)
    redis = fakeredis.FakeRedis()

    def build():
        return Services.build(world.snapshot, store=store, redis=redis, epoch=world.epoch,
                              mode="fake", token=None, make_gateway=gateway_from_env)

    services = build()
    worker_store = JobStore(LedgerStore(url).engine)
    worker = Worker(JobQueue(worker_store, redis),
                    Runner(worker_store, tmp_path / "jobs").handlers())
    stop = threading.Event()

    def work():
        while not stop.is_set():
            worker.run_once()
            stop.wait(0.01)

    thread = threading.Thread(target=work)
    thread.start()
    try:
        context = prepare.prepare(services, timeout=90)
    finally:
        stop.set()
        thread.join(timeout=30)
    assert context["run_id"] and context["execution_id"]
    # A separate API process reads the same database after the command has executed the plan.
    api = build()
    api.gateway()
    api.clock = lambda: world.epoch + timedelta(days=3)  # long after the observed as_of
    return api, context, observed_snapshot(world, context["run_id"])


def money(minor: int) -> dict:
    return {"minor": minor, "currency": USD}


def test_public_screens_show_the_observed_baseline_not_the_executed_ledger(prepared):
    api, context, observed = prepared
    as_of = "2026-01-01T12:00:00Z"  # the observed snapshot, t = 12 h
    assert observed.as_of.isoformat() == "2026-01-01T12:00:00+00:00"
    http = register(Flask(__name__), api).test_client()

    overview = http.get("/api/v1/overview").get_json()
    assert overview["snapshot_id"] == observed.snapshot_id
    assert overview["demo"] == context
    assert overview["completeness"]["status"] == "complete"
    assert overview["cash"] == {**money(7_000_000), "status": "known", "as_of": as_of}
    assert overview["spendable"]["status"] == "known"
    assert overview["spendable"]["minor"] >= 0
    assert [(o["obligation_id"], o["amount"], o["due_at"]) for o in
            overview["upcoming_outflows"]] == [
        ("payroll-1", money(5_000_000), "2026-01-02T16:00:00Z")]  # due at h40
    coverage = overview["coverage"]
    assert coverage["floor"]["minor"] == 3_000_000
    assert coverage["headroom"]["status"] == "known"
    assert coverage["headroom"]["minor"] >= 0  # the floor holds
    assert overview["lender_capacity"] == {**money(4_200_000), "status": "known",
                                           "as_of": as_of}

    treasury = http.get("/api/v1/treasury").get_json()
    assert treasury["snapshot_id"] == observed.snapshot_id
    operating = next(a for a in treasury["accounts"] if a["id"] == "treasury/operating")
    assert operating["buckets"]["settled"] == money(7_000_000)
    assert operating["spendable"]["status"] == "known"
    payroll = next(o for o in treasury["obligations"] if o["obligation_id"] == "payroll-1")
    assert payroll["state"] == "open"

    lending = http.get("/api/v1/lending").get_json()
    assert lending["snapshot_id"] == observed.snapshot_id
    assert lending["capacity"]["K_p"] == {**money(4_200_000), "status": "known", "as_of": as_of}
    assert lending["capacity"]["unobserved"] == []


def test_executed_legs_stay_on_execution_and_in_the_store(prepared):
    api, context, _ = prepared
    http = register(Flask(__name__), api).test_client()
    before = api.store.rows("postings")
    assert before  # the prepared execution posted to the app's ledger
    execution = http.get(f"/api/v1/executions/{context['execution_id']}").get_json()
    assert {leg["kind"] for leg in execution["legs"]} == {"advance", "payout"}
    assert all(leg["state"] == "settled" and leg["reconciled"] for leg in execution["legs"])
    for path in ("overview", "treasury", "lending"):
        assert http.get(f"/api/v1/{path}").status_code == 200
    assert api.store.rows("postings") == before  # reading the baseline never writes the ledger


def test_without_a_prepared_demo_the_screens_read_the_observed_store():
    world = load_world()
    services = Services.build(world.snapshot, epoch=world.epoch, mode="fake", token=None,
                              clock=lambda: world.snapshot.as_of)
    http = register(Flask(__name__), services).test_client()
    overview = http.get("/api/v1/overview").get_json()
    assert overview["snapshot_id"] == world.snapshot.snapshot_id
    assert overview["demo"] == {"run_id": None, "execution_id": None}
    assert overview["spendable"]["minor"] == 2_000_000

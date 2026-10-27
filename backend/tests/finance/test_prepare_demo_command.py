"""The operator prepares the deployed judge path without a browser write or a live provider."""
from __future__ import annotations

import threading

import fakeredis
import pytest
from app.api.v1 import register
from app.api.v1.services import Services, gateway_from_env
from app.demo import prepare
from app.finance.store import LedgerStore
from app.jobs.queue import JobQueue, Worker
from app.jobs.runner import Runner
from app.jobs.store import JobStore
from app.simulation.scenarios import load_world
from flask import Flask


@pytest.fixture
def deployed(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRWALLEX_MODE", "fake")
    monkeypatch.setenv("LEDGER_DATABASE_URL", f"sqlite:///{tmp_path / 'app.sqlite'}")
    monkeypatch.setenv("REDIS_URL", "redis://unused/0")
    world = load_world()
    store = LedgerStore(f"sqlite:///{tmp_path / 'app.sqlite'}")
    redis = fakeredis.FakeRedis()

    def build():
        return Services.build(world.snapshot, store=store, redis=redis, epoch=world.epoch,
                              mode="fake", token=None, make_gateway=gateway_from_env)

    services = build()
    worker_store = JobStore(LedgerStore(f"sqlite:///{tmp_path / 'app.sqlite'}").engine)
    worker = Worker(JobQueue(worker_store, redis),
                    Runner(worker_store, tmp_path / "jobs").handlers())
    stop = threading.Event()

    def work():
        while not stop.is_set():
            worker.run_once()
            stop.wait(0.01)

    thread = threading.Thread(target=work)
    thread.start()
    yield services, build
    stop.set()
    thread.join(timeout=30)
    assert not thread.is_alive()


def test_command_prepares_the_real_store_and_all_read_only_screens(deployed, monkeypatch, capsys):
    services, build = deployed
    import redis

    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **kw: services.queue.redis)
    assert services.demo() == {"run_id": None, "execution_id": None}
    assert prepare.main(["--timeout", "90"]) == 0
    context = services.demo()
    assert context["run_id"] and context["execution_id"]
    assert context["run_id"] in capsys.readouterr().out

    # A separate API process reads the same database; it does not share command memory.
    api_services = build()
    api_services.gateway()
    app = register(Flask(__name__), api_services)
    http = app.test_client()
    overview = http.get("/api/v1/overview").get_json()
    assert overview["demo"] == context
    run = http.get(f"/api/v1/runs/{context['run_id']}")
    assert run.status_code == 200
    assert run.get_json()["committed_round"] >= 5
    decisions = http.get(f"/api/v1/decisions/{context['run_id']}").get_json()
    assert decisions["status"] == "selected"
    assert decisions["selected"] == "integrated"
    assert {r["policy"] for r in decisions["results"]} == {
        "no-action", "fixed-reserve", "integrated"}
    execution = http.get(f"/api/v1/executions/{context['execution_id']}")
    assert execution.status_code == 200
    legs = execution.get_json()["legs"]
    assert {leg["kind"] for leg in legs} == {"advance", "payout"}
    assert all(leg["state"] == "settled" and leg["reconciled"] for leg in legs)
    assert execution.get_json()["mode"] == "fake"
    assert not execution.get_json()["incidents"]

    before = (services.store.rows("postings"), services.jobs.jobs_of(context["run_id"]))
    assert prepare.main([]) == 0
    assert services.demo() == context
    assert (services.store.rows("postings"), services.jobs.jobs_of(context["run_id"])) == before


def test_partial_preparation_reuses_its_execution_after_restart(deployed, monkeypatch):
    services, build = deployed
    publish = services.prepare_demo
    def interrupted(*args):
        raise RuntimeError("interrupted before publication")

    monkeypatch.setattr(services, "prepare_demo", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        prepare.prepare(services, timeout=90)
    before = services.store.rows("postings")
    assert services.demo()["run_id"] is None
    # The fake transport is new on restart, so recovery must not query/resend settled legs.
    restarted = build()
    context = prepare.prepare(restarted, timeout=90)
    assert context["execution_id"]
    assert services.store.rows("postings") == before
    assert publish(context["run_id"], context["execution_id"]) == context


@pytest.mark.parametrize("mode", ["sandbox", "production", "invalid"])
def test_command_refuses_non_fake_mode_before_building_services(monkeypatch, mode, capsys):
    monkeypatch.setenv("AIRWALLEX_MODE", mode)
    monkeypatch.setattr(Services, "from_env", lambda: pytest.fail("provider wiring reached"))
    assert prepare.main([]) == 1
    assert "fake" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["LEDGER_DATABASE_URL", "REDIS_URL"])
def test_command_requires_the_deployed_store_and_queue(monkeypatch, missing, capsys):
    monkeypatch.setenv("AIRWALLEX_MODE", "fake")
    monkeypatch.setenv("LEDGER_DATABASE_URL", "sqlite:///unused.sqlite")
    monkeypatch.setenv("REDIS_URL", "redis://unused/0")
    monkeypatch.delenv(missing)
    monkeypatch.setattr(Services, "from_env", lambda: pytest.fail("local fallback reached"))
    assert prepare.main([]) == 1
    assert missing in capsys.readouterr().err


def test_timeout_leaves_no_prepared_context(tmp_path):
    world = load_world()
    services = Services.build(world.snapshot, redis=fakeredis.FakeRedis(), epoch=world.epoch,
                              mode="fake", token=None)
    with pytest.raises(RuntimeError, match="timed out"):
        prepare.prepare(services, timeout=0.01)
    assert services.demo() == {"run_id": None, "execution_id": None}


def test_second_operator_cannot_prepare_concurrently(deployed):
    services, _ = deployed
    services.queue.redis.set(prepare.LOCK, "another-command", ex=60)
    with pytest.raises(RuntimeError, match="already running"):
        prepare.prepare(services)
    assert services.demo()["run_id"] is None
    assert services.queue.redis.get(prepare.LOCK) == b"another-command"


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_is_refused_before_a_job_is_written(timeout):
    world = load_world()
    services = Services.build(world.snapshot, redis=fakeredis.FakeRedis(), epoch=world.epoch,
                              mode="fake", token=None)
    with pytest.raises(RuntimeError, match="timeout"):
        prepare.prepare(services, timeout=timeout)
    assert services.jobs.get("demo_preparation", "current") is None


def test_failed_job_is_not_published_or_replaced(deployed):
    services, _ = deployed
    run_id = "demo-failed"
    services.jobs.put("demo_preparation", "current", {"run_id": run_id})
    job_id = f"{run_id}-run"
    services.jobs.create(job_id, "run", run_id, {}, max_attempts=1)
    assert services.jobs.move(job_id, ["queued"], "failed")
    with pytest.raises(RuntimeError, match="failed"):
        prepare.prepare(services)
    assert services.demo()["run_id"] is None
    assert len(services.jobs.jobs_of(run_id)) == 1


def test_cli_redacts_unexpected_dependency_errors(monkeypatch, capsys):
    monkeypatch.setenv("AIRWALLEX_MODE", "fake")
    monkeypatch.setenv("LEDGER_DATABASE_URL", "sqlite:///unused.sqlite")
    monkeypatch.setenv("REDIS_URL", "redis://unused/0")

    def broken():
        raise RuntimeError("private connection details")

    monkeypatch.setattr(Services, "from_env", broken)
    assert prepare.main([]) == 1
    assert capsys.readouterr().err == "prepare-demo: RuntimeError\n"


def test_prepared_job_configuration_is_simulation_safe(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    code = ("import sys\n"
            "from pathlib import Path\n"
            "from app.demo.jobs import demo_runner\n"
            "from app.finance.store import LedgerStore\n"
            "from app.jobs.store import JobStore\n"
            "from app.jobs.runner import Runner\n"
            "runner = Runner(JobStore(LedgerStore('sqlite://').engine), Path('jobs'))\n"
            "demo = demo_runner(runner)\n"
            "assert len(demo.world.snapshot.contracts) == len(runner.world.snapshot.contracts) + 1\n"
            "assert not runner.terms and demo.terms\n"
            "assert 'app.execution.gateway' not in sys.modules\n"
            "assert not any('airwallex' in m for m in sys.modules)\n")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        str(root / p) for p in ("backend", "packages/oasis-finance/src"))}
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True,
                   capture_output=True, text=True)


@pytest.mark.parametrize("point", ["after_submitted_before_send", "after_response_before_state_write",
                                  "before_payout_settlement", "before_execution"])
def test_interrupted_execution_can_resume_without_duplicate_money(deployed, monkeypatch, point):
    from datetime import timedelta

    services, build = deployed
    original_gateway = prepare.Gateway
    original_pay = prepare.pay
    interrupted = False

    def crash(at, leg):
        nonlocal interrupted
        if not interrupted and at == point and leg.kind == "payout":
            interrupted = True
            raise KeyboardInterrupt("simulated process exit")

    def gateway(*a, **kw):
        gw = original_gateway(*a, **kw, on_point=crash)
        if point == "before_execution":
            gw.execute = lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt())
        return gw

    def pay(*a, **kw):
        if point == "before_payout_settlement":
            raise KeyboardInterrupt()
        return original_pay(*a, **kw)

    monkeypatch.setattr(prepare, "Gateway", gateway)
    monkeypatch.setattr(prepare, "pay", pay)
    with pytest.raises(KeyboardInterrupt):
        prepare._execution(services, "demo-crash", "integrated")
    monkeypatch.setattr(prepare, "Gateway", original_gateway)
    monkeypatch.setattr(prepare, "pay", original_pay)
    restarted = build()
    if point == "before_execution":
        now = restarted.now() + timedelta(minutes=16)
        restarted.clock = lambda: now
    execution_id = prepare._execution(restarted, "demo-crash", "integrated")
    gw = restarted.gateway()
    legs = gw.legs(execution_id)
    assert len(legs) == 2
    assert all(leg.state == "settled" and leg.reconciled for leg in legs)
    before = restarted.store.rows("postings")
    assert prepare._execution(restarted, "demo-crash", "integrated") == execution_id
    assert restarted.store.rows("postings") == before


def test_changed_advance_terms_are_refused_before_execution(deployed):
    from app.demo.run import ADVANCE
    from app.finance import contracts
    from app.finance.schemas import RevenueAdvance

    services, _ = deployed
    contract = RevenueAdvance.model_validate(ADVANCE | {"fee_bps": 5000})
    contracts.register(services.store, contract, as_of=services.now())
    before = services.store.rows("postings")
    with pytest.raises(RuntimeError, match="terms"):
        prepare._execution(services, "demo-changed", "integrated")
    assert services.store.rows("postings") == before


def test_prepared_run_cannot_be_reforked_with_a_different_world(deployed):
    services, _ = deployed
    run_id = "demo-read-only"
    services.token = "test-demo-token"
    doc = prepare.new_run(run_id, "demo-world", services.snapshot.as_of)
    doc["committed_round"] = 5
    services.jobs.put("run", run_id, doc)
    services.jobs.put("run_spec", run_id, {"scenario": prepare.SCENARIO, "rounds": 5,
                                          "prepared_demo": True})
    services.jobs.create("job-read-only", "run", run_id, {}, max_attempts=1)
    assert services.jobs.move("job-read-only", ["queued"], "done")
    http = register(Flask(__name__), services).test_client()
    response = http.post(f"/api/v1/runs/{run_id}/fork", headers={
        "Authorization": "Bearer test-demo-token"}, json={
            "checkpoint_round": 2, "policies": prepare.POLICIES})
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "prepared_demo_read_only"
    assert services.jobs.get("decisions", run_id) is None

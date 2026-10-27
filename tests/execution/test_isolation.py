"""Runtime checks of the unchanged execution isolation fixture (T14).

These check the application's process and tool boundary, not an OS sandbox: the fixture
assigns database credentials and network policy to deployment (T24).
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/isolation.json"
FIXTURE = json.loads(DESIGN.read_text(encoding="utf-8"))
CASES = {case["id"]: case["expect"] for case in FIXTURE["cases"]}
SOURCES = [ROOT / "backend", ROOT / "packages/oasis-finance/src"]
SENTINEL = "isolation-fixture-not-a-secret"


def child(code, *, env=None, args=()):
    settings = dict(os.environ) if env is None else dict(env)
    settings["PYTHONPATH"] = os.pathsep.join(map(str, SOURCES))
    settings.setdefault("PYTHON_DOTENV_DISABLED", "1")
    return subprocess.run([sys.executable, "-c", code, *map(str, args)], env=settings,
                          cwd=ROOT, capture_output=True, text=True, timeout=180, check=False)


@pytest.mark.parametrize("case,module", [
    ("live-import-refused", "app.connectors.airwallex.live"),
    ("client-import-refused", "app.execution.gateway"),
    ("fake-allowed", "app.connectors.airwallex.fake"),
])
def test_simulation_imports_obey_the_fixture(case, module):
    probe = """
import importlib, sys
try:
    importlib.import_module(sys.argv[1])
except Exception as error:
    print(type(error).__name__)
else:
    print('allowed')
"""
    result = child(probe, env=dict(os.environ) | {"LEDGERWORLD_ROLE": "sim"}, args=[module])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (CASES[case]["raises"] or "allowed")


def test_spawn_sim_scrubs_the_fixture_without_mutating_the_parent():
    from app.execution.boundary import spawn_sim

    parent = FIXTURE["parent_env"] | {"AIRWALLEX_FUTURE_SETTING": SENTINEL,
                                    "PYTHON_DOTENV_DISABLED": "0"}
    original = dict(parent)
    env = spawn_sim(parent)
    expected = CASES["sim-env-scrubbed"]
    assert not any(name.startswith("AIRWALLEX_") for name in env)
    assert not (set(expected["absent"][:-1]) & env.keys())
    assert all(env[name] == parent[name] for name in expected["present"])
    assert env["LEDGERWORLD_ROLE"] == expected["LEDGERWORLD_ROLE"]
    assert env["PYTHON_DOTENV_DISABLED"] == "1"
    assert parent == original


@pytest.mark.parametrize("entry", ["app", "worker"])
def test_runtime_entry_scrubs_credentials_before_simulation(entry):
    probe = """
import os, runpy, sys
if sys.argv[1] == 'worker':
    os.environ.pop('REDIS_URL', None)
    try:
        runpy.run_module('app.jobs', run_name='__main__')
    except SystemExit as error:
        assert 'REDIS_URL is not set' in str(error), str(error)
else:
    import app
assert os.environ['LEDGERWORLD_ROLE'] == 'sim'
assert os.environ['PYTHON_DOTENV_DISABLED'] == '1'
assert not any(name.startswith('AIRWALLEX_') for name in os.environ)
assert 'LEDGERWORLD_DEMO_TOKEN' not in os.environ
print('isolated')
"""
    env = dict(os.environ) | {name: SENTINEL for name in FIXTURE["parent_env"]
                              if name.startswith("AIRWALLEX_") or name == "LEDGERWORLD_DEMO_TOKEN"}
    env["LEDGERWORLD_ROLE"] = "sim" if entry == "app" else "worker"
    result = child(probe, env=env, args=[entry])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated"


@pytest.mark.parametrize("platform", ["twitter", "reddit", "parallel"])
def test_upstream_launchers_share_the_scrubbed_environment(platform, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.services import simulation_runner as module

    runner = module.SimulationRunner
    simulation_id = "isolation-launch"
    sim_dir = tmp_path / simulation_id
    sim_dir.mkdir()
    (sim_dir / "simulation_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"run_{platform}_simulation.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(runner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "SCRIPTS_DIR", str(tmp_path))
    for name in ("_run_states", "_processes", "_action_queues", "_stdout_files",
                 "_stderr_files", "_graph_memory_enabled", "_monitor_threads"):
        monkeypatch.setattr(runner, name, {})
    monkeypatch.setattr(runner, "_sync_simulation_status", lambda *a, **k: None)
    monkeypatch.setattr(module.threading, "Thread",
                        lambda **kwargs: SimpleNamespace(start=lambda: None))
    environments = []

    def popen(*args, **kwargs):
        environments.append(kwargs["env"])
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setenv("AIRWALLEX_API_KEY", SENTINEL)
    monkeypatch.setenv("AIRWALLEX_FUTURE_SETTING", SENTINEL)
    monkeypatch.setenv("LEDGERWORLD_DEMO_TOKEN", SENTINEL)
    try:
        runner.start_simulation(simulation_id, platform=platform)
        (env,) = environments
        assert not any(name.startswith("AIRWALLEX_") for name in env)
        assert "LEDGERWORLD_DEMO_TOKEN" not in env
        assert env["LEDGERWORLD_ROLE"] == "sim"
        assert env["PYTHON_DOTENV_DISABLED"] == "1"
        assert env["PYTHONUTF8"] == "1" and env["PYTHONIOENCODING"] == "utf-8"
        assert os.environ["AIRWALLEX_API_KEY"] == SENTINEL
    finally:
        for stream in runner._stdout_files.values():
            stream.close()


def test_sim_bootstrap_disables_dotenv_before_config_import():
    probe = """
import os, dotenv
def checked_load(*args, **kwargs):
    assert os.environ['PYTHON_DOTENV_DISABLED'] == '1'
    assert 'AIRWALLEX_API_KEY' not in os.environ
    return False
dotenv.load_dotenv = checked_load
import app
assert os.environ['LEDGERWORLD_ROLE'] == 'sim'
"""
    env = dict(os.environ) | {"LEDGERWORLD_ROLE": "sim", "PYTHON_DOTENV_DISABLED": "0"}
    env["AIRWALLEX_API_KEY"] = SENTINEL
    result = child(probe, env=env)
    assert result.returncode == 0, result.stderr


def test_a_sim_role_loaded_from_dotenv_is_scrubbed_before_app_returns():
    probe = """
import os, dotenv
os.environ.pop('LEDGERWORLD_ROLE', None)
def fixture_dotenv(*args, **kwargs):
    os.environ.update(LEDGERWORLD_ROLE='sim', AIRWALLEX_API_KEY='placeholder-dotenv',
                      LEDGERWORLD_DEMO_TOKEN='placeholder-dotenv')
    return True
dotenv.load_dotenv = fixture_dotenv
import app
assert os.environ['LEDGERWORLD_ROLE'] == 'sim'
assert os.environ['PYTHON_DOTENV_DISABLED'] == '1'
assert not any(name.startswith('AIRWALLEX_') for name in os.environ)
assert 'LEDGERWORLD_DEMO_TOKEN' not in os.environ
"""
    result = child(probe, env=dict(os.environ) | {"PYTHON_DOTENV_DISABLED": "0"})
    assert result.returncode == 0, result.stderr


def test_dotenv_cannot_restore_a_provider_variable_or_change_the_role(tmp_path):
    from app.execution.boundary import spawn_sim

    dotenv = tmp_path / ".env"
    dotenv.write_text(f"AIRWALLEX_API_KEY={SENTINEL}\nLEDGERWORLD_ROLE=api\n", encoding="utf-8")
    probe = """
import os, sys
from dotenv import load_dotenv
load_dotenv(sys.argv[1], override=True)
assert 'AIRWALLEX_API_KEY' not in os.environ
assert os.environ['LEDGERWORLD_ROLE'] == 'sim'
"""
    result = child(probe, env=spawn_sim(dict(os.environ)), args=[dotenv])
    assert result.returncode == 0, result.stderr


def test_the_import_fence_includes_lazy_worker_and_decision_paths(tmp_path, monkeypatch):
    import test_import_fence as fence

    trees = (*fence.SIM_TREES, "backend/app/jobs", "backend/app/decisions")
    monkeypatch.setattr(fence, "SIM_TREES", trees)
    scanned = {str(path.relative_to(ROOT)) for path in fence.sim_modules(ROOT)}
    assert {"backend/app/jobs/runner.py", "backend/app/decisions/candidates.py"} <= scanned
    assert not fence.scan(ROOT)
    for tree in trees[-2:]:
        planted = tmp_path / tree / "handler.py"
        planted.parent.mkdir(parents=True)
        planted.write_text("def handler():\n    from app.execution.gateway import Gateway\n",
                           encoding="utf-8")
    hits = fence.scan(tmp_path)
    assert any("jobs/handler.py" in hit for hit in hits)
    assert any("decisions/handler.py" in hit for hit in hits)


def test_no_actor_is_offered_an_execution_tool(tmp_path):
    from app.demo.run import model_factory
    from app.simulation.scenarios import load_world
    from app.simulation.world import World
    from oasis_finance.actions import make_finance_tools

    spec = load_world()
    world = World(spec.world_id, "tool-check", spec.snapshot, spec.actors,
                  model=model_factory("family"), workdir=tmp_path)
    forbidden = CASES["no-execution-tool"]["none_named_like"]
    for actor in spec.actors:
        names = actor["tools"]
        assert not any(fragment in name for name in names for fragment in forbidden)
        if actor["llm"]:
            agent = world.agents[actor["actor_id"]]
            assert set(agent.tool_dict) == set(names)
            finance = set(make_finance_tools(world.queue, agent.finance_actor))
            assert finance == set(names) - {"create_post"}
    world.store.engine.dispose()


def test_an_intent_changes_only_its_branch_not_the_observed_outbox(tmp_path, monkeypatch):
    from app.connectors.airwallex.client import client_from_env
    from app.demo.run import demo_snapshot, model_factory, shock_events
    from app.execution.gateway import Gateway
    from app.finance.ledger import from_snapshot
    from app.finance.store import LedgerStore
    from app.simulation.scenarios import load_world
    from app.simulation.world import World
    from sqlalchemy import inspect

    spec = load_world()
    snapshot = demo_snapshot(spec)
    observed = LedgerStore("sqlite://")
    from_snapshot(observed, snapshot)
    client = client_from_env({"AIRWALLEX_MODE": "fake"})
    gateway = Gateway(observed, client, mode="fake", leg_mode="B", beneficiaries=set())
    calls = []
    monkeypatch.setattr(client.transport, "send", lambda *a, **k: calls.append((a, k)))

    async def run_branch():
        world = World(spec.world_id, "intent-check", snapshot, spec.actors,
                      model=model_factory("family"), workdir=tmp_path, scenario=shock_events())
        async with world:
            results = await world.run(4)
            assert any(action.type == "request_advance" for result in results
                       for action in result.records)
            assert not {"approvals", "execution_legs"} & set(inspect(world.store.engine).get_table_names())
            assert world.store is not observed
        world.store.engine.dispose()

    asyncio.run(run_branch())
    assert gateway.conn.execute("SELECT COUNT(*) FROM execution_legs").fetchone()[0] == CASES["intent-cannot-reach-gateway"]["outbox_rows"]
    assert len(calls) == CASES["intent-cannot-reach-gateway"]["provider_calls"]
    observed.engine.dispose()


def test_the_gateway_refuses_a_plan_that_is_not_c3():
    from app.connectors.airwallex.client import client_from_env
    from app.execution.gateway import Gateway
    from app.finance.ledger import from_snapshot
    from app.finance.store import LedgerStore
    from app.simulation.scenarios import load_world

    spec = load_world()
    store = LedgerStore("sqlite://")
    from_snapshot(store, spec.snapshot)
    client = client_from_env({"AIRWALLEX_MODE": "fake"})
    gateway = Gateway(store, client, mode="fake", leg_mode="B", beneficiaries=set())
    verdict = gateway.execute({"policy": "integrated", "legs": []},
                              current_snapshot_id=spec.snapshot.snapshot_id)
    assert verdict.code == CASES["plan-only-as-c3"]["refused"]
    assert gateway.conn.execute("SELECT COUNT(*) FROM execution_legs").fetchone()[0] == 0
    store.engine.dispose()


def test_secret_sentinel_stays_out_of_the_whole_fake_demo_and_api(tmp_path, monkeypatch,
                                                                capsys, caplog):
    import fakeredis
    from app.api.v1 import register
    from app.api.v1.services import Services
    from app.demo import run
    from app.jobs import Worker
    from app.jobs.runner import Runner
    from app.simulation.scenarios import load_world
    from flask import Flask

    for name in FIXTURE["parent_env"]:
        if name.startswith("AIRWALLEX_") or name == "LEDGERWORLD_DEMO_TOKEN":
            monkeypatch.setenv(name, SENTINEL)
    monkeypatch.setenv("AIRWALLEX_FUTURE_SETTING", SENTINEL)
    traces = []
    real_run = subprocess.run

    def capture_child(*args, **kwargs):
        result = real_run(*args, **kwargs)
        traces.extend((result.stdout or "", result.stderr or ""))
        return result

    monkeypatch.setattr(subprocess, "run", capture_child)
    out = tmp_path / "fake.json"
    assert run.main(["--mode", "fake", "--out", str(out), "--seed", "101"]) == 0
    receipt = out.read_text(encoding="utf-8")
    assert json.loads(receipt)["mode"] == "fake"

    spec = load_world()
    services = Services.build(spec.snapshot, redis=fakeredis.FakeRedis(), epoch=spec.epoch,
                              mode="fake", token=SENTINEL)
    app = register(Flask(__name__), services)
    http = app.test_client()
    responses = []

    def request(method, path, **kwargs):
        response = getattr(http, method)("/api/v1" + path, **kwargs)
        responses.append(response.get_data(as_text=True))
        assert response.status_code < 300, responses[-1]
        return response.get_json()

    for path in ("/health", "/overview", "/treasury", "/lending"):
        request("get", path)
    auth = {"Authorization": f"Bearer {SENTINEL}"}
    accepted = request("post", "/runs", headers=auth, json={
        "snapshot_id": spec.snapshot.snapshot_id,
        "scenario": {"family": "delayed_receipt", "seed": 101, "params": {}},
        "rounds": 4})
    runner = Runner(services.jobs, tmp_path / "jobs", world=spec)
    job = Worker(services.queue, runner.handlers(), worker="isolation-check").run_once()
    assert job is not None and job.state == "done"
    run_id = accepted["run_id"]
    request("get", f"/runs/{run_id}")
    request("get", f"/reports/{run_id}")
    from app.jobs.store import records
    from sqlalchemy import select

    with services.jobs.engine.connect() as conn:
        responses.extend(row.body for row in conn.execute(select(records)))
    captured = capsys.readouterr()
    surfaces = receipt + captured.out + captured.err + caplog.text + "".join(responses + traces)
    assert surfaces.count(SENTINEL) == CASES["secret-sentinel"]["sentinel_occurrences"]
    services.store.engine.dispose()

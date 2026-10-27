"""Parse the deploy freeze gate; exercise the monitor with offline HTTP responses only."""

import io
import json
import re
from pathlib import Path
from urllib import error, request

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name):
    # BaseLoader preserves the Actions `on` key, which YAML 1.1 otherwise treats as True.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def test_workflow_refuses_when_repository_freeze_is_set():
    deploy = workflow("deploy.yml")
    guard = deploy["jobs"]["freeze"]
    assert guard["runs-on"] == "ubuntu-latest"
    assert len(guard["steps"]) == 1
    refusal = guard["steps"][0]
    assert refusal["if"] == "${{ vars.LEDGERWORLD_FREEZE == '1' }}"
    # The selected step must fail, not merely print a warning or silently skip a deploy.
    assert re.search(r"^exit 1\s*$", refusal["run"], re.MULTILINE)
    assert "continue-on-error" not in refusal
    assert "continue-on-error" not in guard
    assert "uses" not in refusal


def test_every_deployment_path_is_guarded_and_default_branch_only():
    deploy = workflow("deploy.yml")
    assert deploy["on"] == {"workflow_dispatch": ""}
    assert deploy["permissions"] == {"contents": "read"}
    assert deploy["concurrency"] == {
        "group": "ledgerworld-deploy", "cancel-in-progress": "false"
    }
    assert set(deploy["jobs"]) == {"freeze", "deploy"}
    job = deploy["jobs"]["deploy"]
    assert job["needs"] == "freeze"
    assert job["if"] == (
        "${{ vars.LEDGERWORLD_FREEZE != '1' && github.ref == "
        "format('refs/heads/{0}', github.event.repository.default_branch) }}"
    )
    assert "continue-on-error" not in job
    assert job["runs-on"] == ["self-hosted", "linux", "ledgerworld"]
    assert job["env"]["LEDGERWORLD_ENV_FILE"] == "${{ vars.LEDGERWORLD_ENV_FILE }}"
    assert job["env"]["VITE_SOURCE_URL"].endswith("/tree/${{ github.sha }}")
    validation, checkout, mutation = job["steps"]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["persist-credentials"] == "false"
    assert "realpath -e" in validation["run"]
    assert '"$workspace"|"$workspace"/*)' in validation["run"]
    assert mutation["if"] == "${{ vars.LEDGERWORLD_FREEZE != '1' }}"
    assert "set -euo pipefail" in mutation["run"]
    assert 'docker compose --project-name ledgerworld -f deploy/compose.yml' in mutation["run"]
    assert '--env-file "$LEDGERWORLD_ENV_FILE"' in mutation["run"]
    assert "up --detach --no-build --wait --wait-timeout 180" in mutation["run"]
    assert "continue-on-error" not in mutation


def test_deploy_uses_canonical_host_env_path_after_checkout():
    job = workflow("deploy.yml")["jobs"]["deploy"]
    host = job["steps"][0]
    assert host["id"] == "host"
    assert 'printf \'env_file=%s\\n\' "$env_file" >> "$GITHUB_OUTPUT"' in host["run"]
    assert job["steps"][-1]["env"]["LEDGERWORLD_ENV_FILE"] == (
        "${{ steps.host.outputs.env_file }}"
    )


def test_deploy_checks_current_freeze_after_build_before_activation():
    step = workflow("deploy.yml")["jobs"]["deploy"]["steps"][-1]
    shell = step["run"]
    assert shell.index(" build\n") < shell.index("python3 - <<'PY'\n")
    assert shell.index("python3 - <<'PY'\n") < shell.index("up --detach --no-build")
    assert step["env"]["FREEZE_READ_TOKEN"] == "${{ secrets.LEDGERWORLD_FREEZE_READ_TOKEN }}"


def test_missing_freeze_reader_is_rejected_before_image_build():
    shell = workflow("deploy.yml")["jobs"]["deploy"]["steps"][-1]["run"]
    assert shell.index('${FREEZE_READ_TOKEN:?') < shell.index(" build\n")


@pytest.mark.parametrize("value,allowed", [("0", True), ("1", False), ("", False), (None, False)])
def test_deploy_live_freeze_refuses_changes_after_admission(monkeypatch, value, allowed):
    monkeypatch.setenv("FREEZE_READ_TOKEN", "offline-placeholder")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/demo")

    def urlopen(req, timeout):
        assert req.full_url == (
            "https://api.github.com/repos/example/demo/actions/variables/LEDGERWORLD_FREEZE"
        )
        assert req.get_header("Authorization") == "Bearer offline-placeholder"
        assert req.get_method() == "GET" and timeout == 20
        response = io.BytesIO(json.dumps({"value": value}).encode())
        response.status = 200
        return response

    monkeypatch.setattr(request, "urlopen", urlopen)
    shell = workflow("deploy.yml")["jobs"]["deploy"]["steps"][-1]["run"]
    if allowed:
        run_embedded_python(shell)
    else:
        with pytest.raises(SystemExit):
            run_embedded_python(shell)


@pytest.mark.parametrize("failure", [error.URLError("unavailable"), TimeoutError("timeout")])
def test_deploy_refuses_when_current_freeze_cannot_be_read(monkeypatch, failure):
    monkeypatch.setenv("FREEZE_READ_TOKEN", "offline-placeholder")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/demo")

    def urlopen(*args, **kwargs):
        raise failure

    monkeypatch.setattr(request, "urlopen", urlopen)
    shell = workflow("deploy.yml")["jobs"]["deploy"]["steps"][-1]["run"]
    with pytest.raises((error.URLError, TimeoutError)):
        run_embedded_python(shell)


def test_deploy_refuses_without_freeze_reader_before_network(monkeypatch):
    monkeypatch.delenv("FREEZE_READ_TOKEN", raising=False)

    def urlopen(*args, **kwargs):
        pytest.fail("A missing freeze reader must fail without a network request")

    monkeypatch.setattr(request, "urlopen", urlopen)
    shell = workflow("deploy.yml")["jobs"]["deploy"]["steps"][-1]["run"]
    with pytest.raises(SystemExit, match="freeze reader is not configured"):
        run_embedded_python(shell)


def run_embedded_python(shell):
    marker = "python3 - <<'PY'\n"
    assert marker in shell
    source = shell.split(marker, 1)[1].split("\nPY\n", 1)[0]
    code = compile(source, "workflow.yml", "exec")
    exec(code, {})  # noqa: S102 -- Repository-owned code; HTTP is mocked by each caller.


def run_monitor():
    monitor = workflow("monitor.yml")
    job = monitor["jobs"]["monitor"]
    assert len(job["steps"]) == 1
    shell = job["steps"][0]["run"]
    prefix = "set -euo pipefail\npython3 - <<'PY'\n"
    assert shell.startswith(prefix) and shell.endswith("\nPY\n")
    run_embedded_python(shell)


def test_monitor_stays_active_every_thirty_minutes_during_freeze():
    monitor = workflow("monitor.yml")
    assert monitor["on"] == {
        "schedule": [{"cron": "*/30 * * * *"}], "workflow_dispatch": ""
    }
    assert monitor["permissions"] == {}
    assert "LEDGERWORLD_FREEZE" not in json.dumps(monitor)
    job = monitor["jobs"]["monitor"]
    assert job["timeout-minutes"] == "3"
    assert job["env"] == {"LEDGERWORLD_URL": "${{ vars.LEDGERWORLD_URL }}"}
    assert "if" not in job
    assert "continue-on-error" not in job


@pytest.fixture
def monitor_http(monkeypatch):
    bodies = {
        path: json.loads((ROOT / "contracts" / "examples" / "c6_api" / example).read_text())[
            "instance"
        ]
        for path, example in [
            ("/api/v1/health", "valid-health.json"),
            ("/api/v1/overview", "valid-overview-lf1.json"),
        ]
    }
    calls = []
    monkeypatch.setenv("LEDGERWORLD_URL", "https://demo.example/")

    def urlopen(req, timeout):
        assert req.get_method() == "GET"
        assert req.get_header("Accept") == "application/json"
        assert timeout == 20
        assert req.full_url.startswith("https://demo.example/")
        path = req.full_url.removeprefix("https://demo.example")
        calls.append(path)
        body = bodies[path]
        if isinstance(body, Exception):
            raise body
        response = io.BytesIO(json.dumps(body).encode())
        response.status = 200
        return response

    monkeypatch.setattr(request, "urlopen", urlopen)
    return bodies, calls


def test_monitor_reads_only_health_and_cached_overview(monitor_http, capsys):
    _, calls = monitor_http
    run_monitor()
    assert calls == ["/api/v1/health", "/api/v1/overview"]
    assert capsys.readouterr().out.splitlines() == [
        "/api/v1/health: OK", "/api/v1/overview: OK"
    ]


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/overview"])
@pytest.mark.parametrize("failure", [error.URLError("unavailable"), TimeoutError("timeout")])
def test_monitor_fails_on_either_unreachable_read(monitor_http, path, failure):
    bodies, _ = monitor_http
    bodies[path] = failure
    with pytest.raises((error.URLError, TimeoutError)):
        run_monitor()


@pytest.mark.parametrize("path,body", [
    ("/api/v1/health", {"ok": False, "as_of": "now", "mode": "fake"}),
    ("/api/v1/health", {"ok": "true", "as_of": "now", "mode": "fake"}),
    ("/api/v1/health", {"ok": True}),
    ("/api/v1/overview", {"as_of": "now", "mode": "fake"}),
    ("/api/v1/overview", []),
    ("/api/v1/overview", {
        "as_of": "now", "mode": "fake", "snapshot_id": "lf1", "cash": {}, "coverage": {},
        "demo": {"run_id": None, "execution_id": None},
    }),
])
def test_monitor_fails_on_unhealthy_or_missing_cached_data(monitor_http, path, body):
    bodies, _ = monitor_http
    bodies[path] = body
    with pytest.raises(SystemExit):
        run_monitor()


@pytest.mark.parametrize("url", [
    "", "http://demo.example", "https://demo.example/path", "https://demo.example?x=1",
    "https://demo.example#fragment", "https://name@demo.example",
])
def test_monitor_rejects_missing_or_non_origin_url(monitor_http, monkeypatch, url):
    _, calls = monitor_http
    monkeypatch.setenv("LEDGERWORLD_URL", url)
    with pytest.raises(SystemExit):
        run_monitor()
    assert calls == []

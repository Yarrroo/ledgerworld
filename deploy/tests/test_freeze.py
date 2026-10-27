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


def freeze_condition(expression, value):
    """Evaluate only the parsed variable comparison, never a workflow or its shell."""
    match = re.fullmatch(
        r"\$\{\{\s*vars\.LEDGERWORLD_FREEZE\s*(==|!=)\s*'1'\s*\}\}", expression
    )
    assert match, "Expected an explicit repository freeze-variable comparison"
    return value == "1" if match[1] == "==" else value != "1"


@pytest.mark.parametrize("value,refused", [("1", True), ("0", False), ("", False)])
def test_workflow_refuses_when_repository_freeze_is_set(value, refused):
    deploy = workflow("deploy.yml")
    guard = deploy["jobs"]["freeze"]
    assert guard["runs-on"] == "ubuntu-latest"
    assert len(guard["steps"]) == 1
    refusal = guard["steps"][0]
    assert freeze_condition(refusal["if"], value) is refused
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
    assert freeze_condition(mutation["if"], "1") is False
    assert freeze_condition(mutation["if"], "0") is True
    assert "set -euo pipefail" in mutation["run"]
    assert 'docker compose --project-name ledgerworld -f deploy/compose.yml' in mutation["run"]
    assert '--env-file "$LEDGERWORLD_ENV_FILE"' in mutation["run"]
    assert "up --detach --build --wait --wait-timeout 180" in mutation["run"]
    assert "continue-on-error" not in mutation


def run_monitor():
    monitor = workflow("monitor.yml")
    job = monitor["jobs"]["monitor"]
    assert len(job["steps"]) == 1
    shell = job["steps"][0]["run"]
    prefix = "set -euo pipefail\npython3 - <<'PY'\n"
    assert shell.startswith(prefix) and shell.endswith("\nPY\n")
    code = compile(shell[len(prefix):-len("PY\n")], "monitor.yml", "exec")
    exec(code, {})  # noqa: S102 -- Repository-owned monitor code; HTTP is mocked by each caller.


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

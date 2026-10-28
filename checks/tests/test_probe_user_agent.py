"""Public demo probes identify themselves instead of using Python-urllib's default agent."""

import io
import json
import tomllib
import urllib.request
from pathlib import Path

import pytest
import yaml

from checks import recording_ready, submission_links, url_ok

ROOT = Path(__file__).resolve().parents[2]
DEMO = "https://ledgerworld.moonward.net"


def run_monitor():
    workflow = yaml.load(
        (ROOT / ".github/workflows/monitor.yml").read_text(), Loader=yaml.BaseLoader
    )
    shell = workflow["jobs"]["monitor"]["steps"][0]["run"]
    source = shell.split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    exec(compile(source, "monitor.yml", "exec"), {})  # noqa: S102 -- Local workflow, mocked HTTP.


@pytest.mark.parametrize("probe", ["url_ok", "recording_ready", "submission_links", "monitor"])
def test_each_probe_sends_named_user_agent(monkeypatch, probe):
    calls = []
    body = {
        "ok": True,
        "as_of": "2026-10-28T00:00:00Z",
        "mode": "fake",
        "snapshot_id": "fixture",
        "cash": [],
        "coverage": {},
        "demo": {"run_id": "fixture-run"},
    }

    def urlopen(request, timeout):
        assert request.get_header("User-agent", "").startswith("ledgerworld-")
        assert request.get_method() == "GET"
        assert timeout > 0
        calls.append(request.full_url)
        response = io.BytesIO(json.dumps(body).encode())
        response.status = 200
        response.geturl = lambda: request.full_url
        return response

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("LEDGERWORLD_URL", DEMO)
    if probe == "url_ok":
        assert url_ok.main([DEMO]) == 0
    elif probe == "recording_ready":
        assert recording_ready.http_get(DEMO + "/api/v1/health") == (200, body)
    elif probe == "submission_links":
        assert submission_links.fetch(DEMO) == (200, json.dumps(body))
    else:
        run_monitor()
    assert calls == (
        [DEMO + "/api/v1/health", DEMO + "/api/v1/overview"]
        if probe == "monitor"
        else [DEMO + "/api/v1/health"] if probe == "recording_ready" else [DEMO]
    )


@pytest.mark.parametrize("path", ["docs/submission.md", "README.md", "deploy/host.toml"])
def test_entry_and_host_use_stable_demo_address(path):
    text = (ROOT / path).read_text()
    if path == "docs/submission.md":
        assert f"- Demo: {DEMO}" in text.splitlines()
    elif path == "README.md":
        assert f"**Live:** <{DEMO}>" in text
    else:
        assert tomllib.loads(text)["host"]["url"] == DEMO

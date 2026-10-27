"""checks/recording_ready.py: GO only when the API behind the take is ready, else the first spoiler."""

from __future__ import annotations

import copy
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

CHECKS = Path(__file__).resolve().parents[1]
ROOT = CHECKS.parent
sys.path.insert(0, str(CHECKS))

import recording_ready

BASE = "https://demo.example"
API = BASE + "/api/v1"
EXAMPLES = ROOT / "contracts" / "examples" / "c6_api"


def _instance(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())["instance"]


def _decisions(*feasible: bool) -> dict:
    policies = ["hold", "draw", "defer"][: len(feasible)]
    results = [{"policy": p, "scenario_id": "shock-1", "branch_id": f"b-{p}", "replay": True,
                "obligations_unmet": 0 if ok else 1, "floor_kept": ok,
                "min_cash": {"minor": 1, "currency": "USD", "status": "known"},
                "funding_cost": {"minor": 0, "currency": "USD"}, "feasible": ok}
               for p, ok in zip(policies, feasible, strict=True)]
    selected = next((r["policy"] for r in results if r["feasible"]), None)
    return {"as_of": "2026-11-05T10:02:00Z", "mode": "fake", "run_id": "run-1",
            "snapshot_id": "obs-1", "checkpoint_round": 3, "cohort": "c", "weight_kind": "equal",
            "status": "selected" if selected else "all_infeasible", "results": results,
            "selected": selected,
            "escalation": None if selected else {"earliest_unmet": "payroll", "binding": "floor",
                                                 "contact": "treasurer"}}


def answers() -> dict[str, tuple[int, object]]:
    """The deployed API ready for the take: recorded contract examples plus a prepared demo."""
    overview = _instance("valid-overview-lf1.json")
    overview["demo"] = {"run_id": "run-1", "execution_id": "apr-1"}
    return {f"{API}/overview": (200, overview),
            f"{API}/decisions/run-1": (200, _decisions(True, False, True)),
            f"{API}/executions/apr-1": (200, _instance("valid-execution.json"))}


def check(table: dict, capsys) -> tuple[int, list[str]]:
    def fetch(url: str) -> tuple[int, object]:
        return table.get(url, (404, {"code": "not_found"}))

    code = recording_ready.main([BASE], fetch)
    return code, capsys.readouterr().out.splitlines()


def test_go(capsys):
    code, out = check(answers(), capsys)
    assert code == 0
    assert out[-1] == "GO"
    assert [line.split()[0] for line in out[:-1]] == ["ok"] * len(recording_ready.CHECKS)
    assert "feasible defer, hold; selected hold" in "\n".join(out)


def test_api_suffix_is_not_doubled(capsys):
    def fetch(url: str) -> tuple[int, object]:
        return answers()[url]

    assert recording_ready.main([API + "/"], fetch) == 0


def test_no_prepared_run(capsys):
    table = answers()
    table[f"{API}/overview"][1]["demo"] = {"run_id": None, "execution_id": None}
    code, out = check(table, capsys)
    assert code == 1
    assert out[-1].startswith("NO-GO: prepared_run: no prepared run")
    assert out[-2].startswith("skip execution_reconciled")


def test_prepared_run_without_execution(capsys):
    table = answers()
    table[f"{API}/overview"][1]["demo"]["execution_id"] = None
    code, out = check(table, capsys)
    assert code == 1
    assert out[-1].startswith("NO-GO: prepared_execution:")


def test_all_infeasible(capsys):
    table = answers()
    table[f"{API}/decisions/run-1"] = (200, _decisions(False, False, False))
    code, out = check(table, capsys)
    assert code == 1
    assert out[-1] == "NO-GO: feasible_policy: every policy of run-1 is infeasible"


def test_pending_decisions(capsys):
    table = answers()
    pending = _decisions(True)
    pending.update(status="pending", selected=None)
    table[f"{API}/decisions/run-1"] = (200, pending)
    code, out = check(table, capsys)
    assert code == 1
    assert out[-1] == "NO-GO: decisions: decisions of run-1 are still pending"


def test_unreconciled_receipt(capsys):
    table = answers()
    execution = copy.deepcopy(table[f"{API}/executions/apr-1"][1])
    execution["legs"][0].update(reconciled=False, state="pending")
    table[f"{API}/executions/apr-1"] = (200, execution)
    code, out = check(table, capsys)
    assert code == 1
    assert out[-1].startswith("NO-GO: execution_reconciled: execution apr-1 not reconciled: leg ")
    assert "is not reconciled (state pending)" in out[-1]


def test_missing_receipt_and_open_incident(capsys):
    table = answers()
    execution = copy.deepcopy(table[f"{API}/executions/apr-1"][1])
    execution["incidents"] = [{"incident_id": "inc-1", "leg_id": "x", "kind": "unknown",
                               "state": "open", "opened_at": "2026-11-05T10:01:00Z"}]
    table[f"{API}/executions/apr-1"] = (200, execution)
    assert check(table, capsys)[1][-1].endswith("open incident inc-1")
    execution["legs"][0]["receipt"] = None
    assert "has no provider receipt" in check(table, capsys)[1][-1]


def test_500_on_execution_read(capsys):
    table = answers()
    table[f"{API}/executions/apr-1"] = (500, {"code": "internal"})
    code, out = check(table, capsys)
    assert code == 1
    assert out[-1] == "NO-GO: execution_read: execution apr-1 answered HTTP 500 (internal)"


def test_500_on_overview(capsys):
    table = answers()
    table[f"{API}/overview"] = (500, None)
    code, out = check(table, capsys)
    assert code == 1
    assert out[-1] == "NO-GO: reachable: overview answered HTTP 500"


def test_unreachable_exits_2():
    with socket.socket() as sock:  # a port nothing listens on
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    done = subprocess.run([sys.executable, str(CHECKS / "recording_ready.py"),
                           f"http://127.0.0.1:{port}"], check=False, capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 2
    assert done.stdout.startswith(f"UNREACHABLE http://127.0.0.1:{port}/api/v1")


@pytest.mark.parametrize("argv", [[], ["ftp://x"], [BASE, BASE]])
def test_bad_usage_exits_2(argv, capsys):
    assert recording_ready.main(argv) == 2

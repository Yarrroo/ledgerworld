"""checks/kpi.py: one number per goal, the baseline before its inputs exist."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CHECKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKS))

from goals import g1, g3

BASELINES = {"g1": "0", "g2": "0", "g3": "0", "g4": "999", "g5": "0"}


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    """A checkout holding only the runner, the goals and the real required.json."""
    (tmp_path / "checks").mkdir()
    shutil.copy(CHECKS / "kpi.py", tmp_path / "checks" / "kpi.py")
    shutil.copy(CHECKS / "required.json", tmp_path / "checks" / "required.json")
    shutil.copytree(CHECKS / "goals", tmp_path / "checks" / "goals")
    return tmp_path


def kpi(root: Path, goal: str, *flags: str, **env: str) -> subprocess.CompletedProcess:
    environ = {k: v for k, v in os.environ.items() if k != "LEDGERWORLD_URL"} | env
    return subprocess.run(
        [sys.executable, str(root / "checks" / "kpi.py"), goal, *(flags or ("--print",))],
        capture_output=True,
        text=True,
        env=environ,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("goal", sorted(BASELINES))
def test_every_goal_prints_its_baseline_in_a_bare_checkout(bare: Path, goal: str) -> None:
    done = kpi(bare, goal)
    assert done.returncode == 0
    assert done.stdout == BASELINES[goal] + "\n"
    assert done.stderr == ""


def test_without_print_the_goal_and_kpi_are_named(bare: Path) -> None:
    done = kpi(bare, "g4", "--root", str(bare))
    assert done.stdout == "g4 judge_path_s 999\n"


def test_an_error_prints_the_baseline_and_the_reason(bare: Path) -> None:
    (bare / "var" / "demo").mkdir(parents=True)
    (bare / "var" / "demo" / "live.json").write_text("{not json", encoding="utf-8")
    done = kpi(bare, "g3")
    assert (done.returncode, done.stdout) == (0, "0\n")
    assert "JSONDecodeError" in done.stderr


RECEIPTS = json.loads(
    (
        CHECKS.parent
        / "prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/demo-receipt.json"
    ).read_text(encoding="utf-8")
)


def live_receipt() -> dict:
    """The fixture's valid fake receipt, as the sandbox run writes it."""
    receipt = copy.deepcopy(RECEIPTS["valid_fake"])
    receipt |= {"mode": "sandbox", "started_at": "2026-11-01T10:00:00Z"}
    receipt["setup"] = [{"kind": "wallet_funding", "provider_id": "dep-setup-1"}]
    checkpoints = receipt["checkpoints"]
    checkpoints["fresh_branch"]["created_at"] = "2026-11-01T10:00:05Z"
    checkpoints["advance_reconciled"] |= {"mode": "sandbox", "provider_id": "dep-1"}
    checkpoints["payout_reconciled"] |= {"mode": "sandbox", "provider_id": "t-1"}
    return receipt


def test_g3_ignores_a_fake_receipt(bare: Path) -> None:
    (bare / "var" / "demo").mkdir(parents=True)
    live = bare / "var" / "demo" / "live.json"
    live.write_text(json.dumps(RECEIPTS["valid_fake"]), encoding="utf-8")
    assert kpi(bare, "g3").stdout == "0\n"
    live.write_text(json.dumps(live_receipt()), encoding="utf-8")
    assert kpi(bare, "g3").stdout == "3\n"


def broken(patch) -> dict:
    receipt = live_receipt()
    patch(receipt, receipt["checkpoints"])
    return receipt


@pytest.mark.parametrize(
    ("case", "patch", "expected"),
    [
        ("fake checkpoint", lambda r, c: c["payout_reconciled"].update(mode="fake"), 2),
        ("cached-branch", lambda r, c: c["fresh_branch"].update(cached=True), 2),
        (
            "branch-before-run",
            lambda r, c: c["fresh_branch"].update(created_at="2026-11-01T09:59:00Z"),
            2,
        ),
        (
            "advance-not-reconciled",
            lambda r, c: c["advance_reconciled"].update(reconciled=False),
            2,
        ),
        ("payout-only-sent", lambda r, c: c["payout_reconciled"].update(status="SENT"), 2),
        ("open-incident", lambda r, c: r.update(incidents_open=1), 0),
        (
            "mode-b-mislabelled",
            lambda r, c: c["advance_reconciled"].update(
                label="advance (connected-account transfer)"
            ),
            2,
        ),
        (
            "setup-counted",
            lambda r, c: c["advance_reconciled"].update(provider_id="dep-setup-1"),
            2,
        ),
        (
            "live-missing-provider-id",
            lambda r, c: c["payout_reconciled"].update(provider_id=None),
            2,
        ),
        ("mode-a-advance", lambda r, c: r.update(connected=True), 3),
        (
            "sub-second-created-at",
            lambda r, c: c["fresh_branch"].update(created_at="2026-11-01T10:00:00.250Z"),
            3,
        ),
        (
            "offset-created-at",
            lambda r, c: c["fresh_branch"].update(created_at="2026-11-01T11:00:00+02:00"),
            2,
        ),
        ("no-created-at", lambda r, c: c["fresh_branch"].pop("created_at"), 2),
        ("no-started-at", lambda r, c: r.pop("started_at"), 2),
        ("no-rounds", lambda r, c: c["fresh_branch"].update(rounds=0), 2),
        ("advance-pending", lambda r, c: c["advance_reconciled"].update(status="PENDING"), 2),
        (
            "connected-missing-mislabelled",
            lambda r, c: (
                r.pop("connected"),
                c["advance_reconciled"].update(label="advance (connected-account transfer)"),
            ),
            2,
        ),
    ],
)
def test_g3_counts_only_checkpoints_that_hold_live(case: str, patch, expected: int) -> None:
    assert g3.count(broken(patch)) == expected, case


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="tests.a.test_x" name="test_ok"/>
  <testcase classname="tests.a.test_x" name="test_fail"><failure message="no"/></testcase>
  <testcase classname="tests.a.test_x" name="test_skip"><skipped message="live"/></testcase>
  <testcase classname="tests.a.test_x" name="test_param[1]"/>
  <testcase classname="tests.a.test_x" name="test_param[2]"/>
  <testcase classname="tests.a.test_x.TestK" name="test_m"/>
</testsuite></testsuites>
"""


def test_g1_share_counts_a_check_only_when_every_listed_test_passed(tmp_path: Path) -> None:
    xml = tmp_path / "g1.xml"
    xml.write_text(JUNIT, encoding="utf-8")
    outcomes = g1.junit_outcomes(xml)
    f = "tests/a/test_x.py::"
    checks = [
        {"id": "ok", "tests": [f + "test_ok", f + "test_param", f + "TestK::test_m"]},
        {"id": "one_param", "tests": [f + "test_param[2]"]},
        {"id": "failed", "tests": [f + "test_ok", f + "test_fail"]},
        {"id": "skipped", "tests": [f + "test_skip"]},
        {"id": "missing", "tests": [f + "test_not_written_yet"]},
        {"id": "no_tests", "tests": []},
        {"id": "prefix_is_not_a_match", "tests": [f + "test_o"]},
        {"id": "no_file", "tests": ["tests/b/test_y.py::test_ok"]},
    ]
    assert g1.share(checks, outcomes) == 100 * 2 // 8
    assert g1.share(checks[:2], outcomes) == 100
    assert g1.share([], outcomes) == 0


def test_g4_prints_the_judge_path_seconds_or_999(bare: Path) -> None:
    script = bare / "scripts" / "judge-path.sh"
    script.parent.mkdir()
    script.write_text('echo "judge path: 42.5 s"\n', encoding="utf-8")
    assert kpi(bare, "g4").stdout == "999\n"
    assert kpi(bare, "g4", LEDGERWORLD_URL="http://localhost:9").stdout == "42.5\n"
    script.write_text("echo 12; exit 1\n", encoding="utf-8")
    assert kpi(bare, "g4", LEDGERWORLD_URL="http://localhost:9").stdout == "999\n"


def test_g5_reads_the_submission_count(bare: Path) -> None:
    script = bare / "checks" / "submission.py"
    script.write_text('import sys\nprint("5/8")\nsys.exit(1)\n', encoding="utf-8")
    assert kpi(bare, "g5").stdout == "5\n"


def test_g4_reads_the_seconds_off_the_last_line() -> None:
    from goals import g4

    assert g4.seconds("navigating\njudge path: 42.5 s (max over 1440 px)\n") == 42.5
    assert g4.seconds("390 px: 30.1\n1440 px: 41\n41.0\n") == 41.0


def test_g1_a_file_that_cannot_be_collected_fails_only_its_own_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "checks").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n")  # pins the rootdir to the checkout
    (tmp_path / "tests" / "test_kpi_ok.py").write_text("def test_ok():\n    pass\n")
    (tmp_path / "tests" / "test_kpi_unbuilt.py").write_text(
        "import a_module_not_built_yet\n\n\ndef test_x():\n    pass\n"
    )
    required = {
        "g1": [
            {"id": "ok", "tests": ["tests/test_kpi_ok.py::test_ok"]},
            {"id": "unbuilt", "tests": ["tests/test_kpi_unbuilt.py::test_x"]},
        ]
    }
    (tmp_path / "checks" / "required.json").write_text(json.dumps(required))
    monkeypatch.setattr(g1, "PYTEST", [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"])
    assert g1.group_share(tmp_path, "g1") == 50


def test_g1_measures_against_the_lockfile_as_the_merge_gate_does() -> None:
    assert g1.PYTEST[:3] == ["uv", "run", "--locked"]


# Every money check g1 counts, and how many tests they list: a speed-up of the measurement may
# change how the checks run, never which of them count.
G1_CHECKS = [
    "lf1_reproduction", "ledger_balance", "ledger_no_orphan_posting", "ledger_reserved_le_settled",
    "ledger_no_double_pledge", "ledger_unknown_not_zero", "lf2_reproduction",
    "draw_beyond_kp_rejected", "no_duplicate_movement", "no_movement_from_unowned_funds",
    "altered_approval_refused", "timeout_resolved_by_query", "reconciliation_closes_advance",
    "clairvoyant_policy_rejected", "credential_isolation", "money_safety_hunts",
]


def test_g1_counts_every_money_check_and_every_test_they_list() -> None:
    checks = json.loads((CHECKS / "required.json").read_text(encoding="utf-8"))["g1"]
    assert [c["id"] for c in checks] == G1_CHECKS
    assert all(c.get("tests") for c in checks)
    assert len({t for c in checks for t in c["tests"]}) == 119


def test_g5_a_progress_line_is_not_a_count() -> None:
    from goals import g5

    assert g5.items("checking\n5/8\n") == 5
    assert g5.items("6\n") == 6
    with pytest.raises(ValueError):
        g5.items("checked 5/8\nchecking item 6 of 8\n")


def test_a_goal_that_cannot_load_prints_its_baseline(bare: Path) -> None:
    (bare / "checks" / "goals" / "g4.py").write_text("import a_module_not_built_yet\n")
    done = kpi(bare, "g4")
    assert (done.returncode, done.stdout) == (0, "999\n")
    assert "a_module_not_built_yet" in done.stderr


def test_the_runner_baselines_match_the_goal_modules() -> None:
    import importlib

    import kpi as runner

    for goal, (name, baseline) in runner.GOALS.items():
        module = importlib.import_module(f"goals.{goal}")
        assert getattr(module, "BASELINE", baseline) == baseline, goal

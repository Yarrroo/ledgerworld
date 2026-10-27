"""g1 Money is correct: `money_checks_pct`, the passing share of checks/required.json group g1.

A required check passes when it lists at least one test and every listed test passed. A test id
whose file does not exist yet, that pytest did not report, or that was skipped counts as failing.
The share is floored, so 100 means every check passed.
"""

from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

KPI = "money_checks_pct"
BASELINE = 0
PYTEST_TIMEOUT_S = 1800


def junit_outcomes(xml_path: Path) -> dict[tuple[str, str], bool]:
    """(classname, name) -> passed, for every testcase in a junit report."""
    outcomes = {}
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        bad = any(child.tag in ("failure", "error", "skipped") for child in case)
        key = (case.get("classname", ""), case.get("name", ""))
        outcomes[key] = outcomes.get(key, True) and not bad
    return outcomes


def node_passed(node_id: str, outcomes: dict[tuple[str, str], bool]) -> bool:
    """A node id passes when pytest reported it (every parametrisation of it) and all passed."""
    path, *rest = node_id.split("::")
    if not rest or not path.endswith(".py"):
        return False
    classname = ".".join([path[: -len(".py")].replace("/", "."), *rest[:-1]])
    name = rest[-1]
    found = [
        passed
        for (cls, case), passed in outcomes.items()
        if cls == classname and (case == name or ("[" not in name and case.startswith(name + "[")))
    ]
    return bool(found) and all(found)


def share(checks: list[dict], outcomes: dict[tuple[str, str], bool]) -> int:
    if not checks:
        return 0
    passing = sum(
        1
        for check in checks
        if check.get("tests") and all(node_passed(t, outcomes) for t in check["tests"])
    )
    return 100 * passing // len(checks)


def group_share(root: Path, group: str) -> int:
    checks = json.loads((root / "checks" / "required.json").read_text(encoding="utf-8"))[group]
    ids = [t for check in checks for t in check.get("tests", [])]
    # Whole files run, not node ids: one id that does not exist would make pytest refuse them all.
    files = sorted({t.split("::")[0] for t in ids if (root / t.split("::")[0]).is_file()})
    if not files:
        return share(checks, {})
    xml_path = root / "var" / "kpi" / f"{group}.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.unlink(missing_ok=True)
    subprocess.run(
        ["uv", "run", "pytest", "-q", "--junitxml", str(xml_path), *files],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=PYTEST_TIMEOUT_S,
        check=False,  # failing tests are the measurement, not an error
    )
    if not xml_path.is_file():
        raise RuntimeError(f"pytest wrote no report at {xml_path}")
    return share(checks, junit_outcomes(xml_path))


def measure(root: Path) -> int:
    return group_share(root, "g1")

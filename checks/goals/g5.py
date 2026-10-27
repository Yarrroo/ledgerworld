"""g5 The entry is complete and honest: `submission_items`, from `checks/submission.py --count`.

0 until checks/submission.py exists. Its output is `n/8` or `n`; the first number is the count.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

KPI = "submission_items"
BASELINE = 0
SCRIPT_TIMEOUT_S = 600
COUNT = re.compile(r"\d+")


def items(stdout: str) -> int:
    lines = [line for line in stdout.splitlines() if line.strip()]
    found = COUNT.search(lines[-1]) if lines else None
    if not found:
        raise ValueError("submission.py printed no count")
    return int(found.group())


def measure(root: Path) -> int:
    script = root / "checks" / "submission.py"
    if not script.is_file():
        return BASELINE
    done = subprocess.run(
        [sys.executable, str(script), "--count"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT_S,
        check=False,
    )
    # submission.py may exit non-zero while items are missing; the count is still the measure.
    return items(done.stdout)

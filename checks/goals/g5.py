"""g5 The entry is complete and honest: `submission_items`, from `checks/submission.py --count`.

0 until checks/submission.py exists. Its last line is `n/8` or `n`; anything else (a crash after a
progress line) is an error, so the runner prints the baseline.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BASELINE = 0
SCRIPT_TIMEOUT_S = 600
COUNT = re.compile(r"\s*(\d+)\s*(?:/\s*\d+)?\s*")


def items(stdout: str) -> int:
    lines = [line for line in stdout.splitlines() if line.strip()]
    found = COUNT.fullmatch(lines[-1]) if lines else None
    if not found:
        raise ValueError("submission.py did not end with its count")
    return int(found.group(1))


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

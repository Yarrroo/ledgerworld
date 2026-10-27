"""g4 A judge can follow it: `judge_path_s`, seconds of `scripts/judge-path.sh $LEDGERWORLD_URL`.

999 when LEDGERWORLD_URL is unset, the script does not exist yet, or it fails.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

BASELINE = 999  # also the reading of any failed or unrunnable path
SCRIPT_TIMEOUT_S = 1800
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def seconds(stdout: str) -> float:
    """The first number on the last line the script printed."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    found = NUMBER.search(lines[-1]) if lines else None
    if not found:
        raise ValueError("judge-path printed no seconds on its last line")
    return float(found.group())


def measure(root: Path) -> float:
    url = os.environ.get("LEDGERWORLD_URL", "").strip()
    script = root / "scripts" / "judge-path.sh"
    if not url or not script.is_file():
        return BASELINE
    done = subprocess.run(
        ["bash", str(script), url],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0:
        return BASELINE
    return seconds(done.stdout)

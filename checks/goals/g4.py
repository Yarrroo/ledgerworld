"""g4 A judge can follow it: `judge_path_s`, seconds of `scripts/judge-path.sh $LEDGERWORLD_URL`.

999 when LEDGERWORLD_URL is unset, the script does not exist yet, or it fails.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

KPI = "judge_path_s"
BASELINE = 999
FAILED = 999
SCRIPT_TIMEOUT_S = 1800
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def seconds(stdout: str) -> float:
    """The last number the script printed."""
    found = NUMBER.findall(stdout)
    if not found:
        raise ValueError("judge-path printed no number")
    return float(found[-1])


def measure(root: Path) -> float:
    url = os.environ.get("LEDGERWORLD_URL", "").strip()
    script = root / "scripts" / "judge-path.sh"
    if not url or not script.is_file():
        return FAILED
    done = subprocess.run(
        ["bash", str(script), url],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0:
        return FAILED
    return seconds(done.stdout)

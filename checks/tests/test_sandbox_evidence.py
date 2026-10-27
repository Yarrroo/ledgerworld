"""docs/evidence/sandbox-receipt.json: the committed sandbox receipt is live, clean and cited."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "docs" / "evidence" / "sandbox-receipt.json"
RUN_ID = "demo-20261027T190757Z-9674"

# A key, a token or a host path has no place in committed evidence.
LEAKS = re.compile(
    r"(?i)(api[_-]?key|client[_-]?secret|bearer\s|authorization|access[_-]?token|"
    r"/home/|/root/|/Users/|/docker/|/tmp/|\.env\b)"
)


def test_receipt_passes_require_live():
    done = subprocess.run(
        [sys.executable, str(ROOT / "checks" / "demo_receipt.py"), str(RECEIPT), "--require-live"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "3/3" in done.stdout


def test_receipt_is_the_labelled_sandbox_run():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["run_id"] == RUN_ID
    assert receipt["mode"] == "sandbox"
    assert receipt["connected"] is False
    assert receipt["model"] == "scripted"


def test_receipt_holds_no_key_token_or_host_path():
    assert not LEAKS.findall(RECEIPT.read_text())


def test_submission_cites_the_receipt():
    text = (ROOT / "docs" / "submission.md").read_text()
    assert "evidence/sandbox-receipt.json" in text
    assert RUN_ID in text
    assert "no sandbox receipt is committed" not in text.lower()


def test_evidence_readme_labels_the_run():
    text = (ROOT / "docs" / "evidence" / "README.md").read_text()
    for label in (RUN_ID, "2024-09-27", "Mode B", "scripted", "command-line demo store"):
        assert label in text, label

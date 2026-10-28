"""docs/evidence/sandbox-receipt.json: the committed sandbox receipt is live, clean and cited."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

CHECKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKS))

import demo_receipt
import no_secrets

ROOT = CHECKS.parent
EVIDENCE = ROOT / "docs" / "evidence"
RECEIPT = EVIDENCE / "sandbox-receipt.json"
RUN_ID = "demo-20261027T190757Z-9674"

# A host path names the machine the run was made on; committed evidence carries none.
HOST_PATH = re.compile(r"/home/|/root/|/Users/|/docker/|/tmp/")


def test_receipt_passes_require_live():
    receipt = json.loads(RECEIPT.read_text())
    assert demo_receipt.check(receipt, require_live=True) == []
    assert demo_receipt.live_checkpoints(receipt) == 3


def test_receipt_is_the_labelled_sandbox_run():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["run_id"] == RUN_ID
    assert receipt["mode"] == "sandbox"
    assert receipt["connected"] is False
    assert receipt["model"] == "scripted"


def test_receipt_holds_no_key_token_or_host_path():
    text = RECEIPT.read_text()
    assert [label for label, p in no_secrets.PATTERNS.items() if p.search(text)] == []
    assert not HOST_PATH.findall(text)


def test_submission_cites_the_receipt():
    text = (ROOT / "docs" / "submission.md").read_text()
    assert "evidence/sandbox-receipt.json" in text
    assert RUN_ID in text


@pytest.mark.parametrize("doc", ["README.md", "docs/submission.md"])
def test_doc_no_longer_says_no_receipt_is_committed(doc):
    text = " ".join((ROOT / doc).read_text().lower().split())
    assert "evidence/sandbox-receipt.json" in text
    assert "no sandbox receipt is committed" not in text


def test_airwallex_contract_points_at_the_committed_receipt():
    text = " ".join((ROOT / "docs" / "airwallex-contract.md").read_text().split())
    assert RUN_ID in text
    assert "evidence/sandbox-receipt.json" in text
    assert "the receipt stays in `var/demo/`" not in text.lower()


def test_evidence_readme_labels_the_run():
    text = (EVIDENCE / "README.md").read_text()
    for label in (RUN_ID, "2024-09-27", "Mode B", "scripted", "command-line demo store"):
        assert label in text, label

"""g3 It executes for real (sandbox): `demo_checkpoints_live`, sandbox checkpoints in the receipt.

The receipt is var/demo/live.json, written by `scripts/demo.sh --mode sandbox`, in the shape of
prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/demo-receipt.json. A fake receipt,
or one with an open incident, counts 0. Each of the three checkpoints counts when it ran in
sandbox mode (its own `mode`, else the receipt's) and holds as `--require-live` reads it:
- fresh_branch: not cached, created no earlier than the run started;
- advance_reconciled / payout_reconciled: a provider id that is not a setup movement's,
  reconciled; the payout PAID; a Mode B advance carries the simulation label.
"""

from __future__ import annotations

import json
from pathlib import Path

KPI = "demo_checkpoints_live"
BASELINE = 0
CHECKPOINTS = ("fresh_branch", "advance_reconciled", "payout_reconciled")


def _holds(name: str, cp: dict, receipt: dict) -> bool:
    if cp.get("mode", receipt.get("mode")) != "sandbox":
        return False
    if name == "fresh_branch":
        started, created = receipt.get("started_at"), cp.get("created_at")
        return cp.get("cached") is False and not (started and created and created < started)
    setup_ids = {s.get("provider_id") for s in receipt.get("setup") or [] if isinstance(s, dict)}
    provider_id = cp.get("provider_id")
    if not provider_id or provider_id in setup_ids or cp.get("reconciled") is not True:
        return False
    if name == "payout_reconciled":
        return cp.get("status") == "PAID"
    return receipt.get("connected") is not False or "simulation" in str(cp.get("label", ""))


def count(receipt: dict) -> int:
    if receipt.get("mode") != "sandbox" or receipt.get("incidents_open", 0):
        return 0
    checkpoints = receipt.get("checkpoints") or {}
    return sum(
        1
        for name in CHECKPOINTS
        if isinstance(checkpoints.get(name), dict) and _holds(name, checkpoints[name], receipt)
    )


def measure(root: Path) -> int:
    path = root / "var" / "demo" / "live.json"
    if not path.is_file():
        return BASELINE
    return count(json.loads(path.read_text(encoding="utf-8")))

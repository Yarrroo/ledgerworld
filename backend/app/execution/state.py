"""C4 leg states and the only transitions the outbox accepts.

The machine is read from the execution design's `leg-state-machine.json`, so the fixture the tests
load is the table the code enforces. A transition outside it raises `IllegalTransition`; the
conditional rules (`unknown → pending` only when a lookup proved nothing was sent) are the
outbox's to apply before it asks.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[3] / "prp/2026-10-20-ledgerworld/design/modules/execution"
MACHINE = json.loads((DESIGN / "fixtures/leg-state-machine.json").read_text())

STATES: tuple[str, ...] = tuple(MACHINE["states"])
ALLOWED: frozenset[tuple[str, str]] = frozenset((t["from"], t["to"]) for t in MACHINE["allowed"])
# Forbidden without a condition: never allowed, whatever the leg. `*` rows are rules on fields.
FORBIDDEN: frozenset[tuple[str, str]] = frozenset(
    (t["from"], t["to"]) for t in MACHINE["forbidden"] if "when" not in t and t["from"] != "*"
)
LEDGER_ONLY: frozenset[tuple[str, str]] = frozenset(pairwise(MACHINE["ledger_only"]["path"]))
LEDGER_ONLY_LABEL: str = MACHINE["ledger_only"]["receipt_label"]

if not ALLOWED.isdisjoint(FORBIDDEN) or {s for pair in ALLOWED for s in pair} - set(STATES):
    raise ValueError("leg-state-machine.json allows a transition it forbids or names no state")

# Provider statuses a `GET` reports (system brief §10): terminal success, terminal failure.
SETTLED_STATUSES = frozenset({"PAID", "SETTLED"})
FAILED_STATUSES = frozenset({"FAILED", "CANCELLED", "REVERSED"})


class IllegalTransition(ValueError):
    """A state change the machine does not allow."""


def check(from_state: str, to_state: str, *, ledger_only: bool = False) -> None:
    """Raise unless `from_state → to_state` is allowed; a ledger-only leg also has its own path."""
    if (from_state, to_state) in ALLOWED or (ledger_only and (from_state, to_state) in LEDGER_ONLY):
        return
    raise IllegalTransition(f"{from_state} → {to_state} is not a leg transition")

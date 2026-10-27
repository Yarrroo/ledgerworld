"""g2 The world is coupled: `coupling_checks_pct`, the passing share of required group g2."""

from __future__ import annotations

from pathlib import Path

from goals.g1 import group_share

BASELINE = 0


def measure(root: Path) -> int:
    return group_share(root, "g2")

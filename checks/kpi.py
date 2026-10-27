"""Print one goal's KPI as one number (system brief §17).

Usage: python3 checks/kpi.py gN [--print] [--root DIR]
Runs checks/goals/gN.py against the repository at DIR (default: this checkout). With --print the
output is the bare number; without it, `gN kpi_name number`. Any error while measuring prints the
goal's baseline instead and the reason on stderr; the exit code is still 0, so the board always
reads a number. Standard library only: this runs outside the uv environment too.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

CHECKS = Path(__file__).resolve().parent
GOALS = ("g1", "g2", "g3", "g4", "g5")


def fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("goal", choices=GOALS)
    parser.add_argument("--print", dest="bare", action="store_true", help="print the number only")
    parser.add_argument("--root", type=Path, default=CHECKS.parent, help="repository to measure")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(CHECKS))
    goal = importlib.import_module(f"goals.{args.goal}")
    try:
        value = goal.measure(args.root.resolve())
    except Exception as exc:  # noqa: BLE001 — any failure reads as the baseline
        print(f"kpi {args.goal}: baseline ({type(exc).__name__}: {exc})", file=sys.stderr)
        value = goal.BASELINE
    shown = fmt(value)
    print(shown if args.bare else f"{args.goal} {goal.KPI} {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

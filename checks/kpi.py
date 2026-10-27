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
# goal -> (KPI name, baseline). The baseline is also what prints when a goal cannot be measured,
# even when its module cannot be loaded.
GOALS = {
    "g1": ("money_checks_pct", 0),
    "g2": ("coupling_checks_pct", 0),
    "g3": ("demo_checkpoints_live", 0),
    "g4": ("judge_path_s", 999),
    "g5": ("submission_items", 0),
}


def fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("goal", choices=GOALS)
    parser.add_argument("--print", dest="bare", action="store_true", help="print the number only")
    parser.add_argument("--root", type=Path, default=CHECKS.parent, help="repository to measure")
    args = parser.parse_args(argv)

    name, baseline = GOALS[args.goal]
    sys.path.insert(0, str(CHECKS))
    try:
        value = importlib.import_module(f"goals.{args.goal}").measure(args.root.resolve())
    except Exception as exc:  # noqa: BLE001 — any failure reads as the baseline
        print(f"kpi {args.goal}: baseline ({type(exc).__name__}: {exc})", file=sys.stderr)
        value = baseline
    shown = fmt(value)
    print(shown if args.bare else f"{args.goal} {name} {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The word budget of each finance screen (prp/2026-10-29-ux-pass/MATCH.md, shared item 8).

    uv run python checks/word_budget.py --budget overview        prints the budget
    uv run python checks/word_budget.py COUNTS.json              exit 1 when a screen is over

A screen at 1487 px shows no more words than its mockup (prp/2026-10-29-ux-pass/mockups/, drawn at
1487 x 1058) plus 15 %. MOCKUP_WORDS is the mockup's visible words counted by hand, the way
e2e/ux/words.ts counts the live page: every label on the page, sidebar, header, chart axes and
legends included; a token counts when it carries a letter or a digit, so "·", "/" and "→" do not.
COUNTS.json maps a screen to its measured count, {"overview": 171, ...}; the interaction checks
(e2e/ux/match-*.spec.ts) measure it and ask this file for the budget, so the rule lives here once.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

#: The mockup's visible words per screen; 07 Approval flow is a dialog over Execution.
MOCKUP_WORDS: dict[str, int] = {
    "overview": 160,
    "treasury": 192,
    "lending": 167,
    "simulation": 210,
    "decisions": 185,
    "execution": 206,
}

#: How far above the mockup a screen may go.
SLACK = 0.15


def budget(screen: str) -> int:
    """The most words ``screen`` may show at 1487 px."""
    return math.floor(MOCKUP_WORDS[screen] * (1 + SLACK))


def over(counts: dict[str, int]) -> list[str]:
    """One line per screen whose count is above its budget, or names no known screen."""
    lines = []
    for screen, count in sorted(counts.items()):
        if screen not in MOCKUP_WORDS:
            lines.append(f"{screen}: no mockup budget (known: {', '.join(MOCKUP_WORDS)})")
        elif count > budget(screen):
            lines.append(f"{screen}: {count} words, budget {budget(screen)} (mockup {MOCKUP_WORDS[screen]} + 15 %)")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--budget", metavar="SCREEN", help="print SCREEN's budget")
    parser.add_argument("counts", nargs="?", type=Path, help="a JSON file of measured counts per screen")
    args = parser.parse_args(argv)
    if bool(args.budget) == bool(args.counts):
        parser.error("give either --budget SCREEN or COUNTS.json")
    if args.budget:
        if args.budget not in MOCKUP_WORDS:
            print(f"word_budget: no screen {args.budget!r}", file=sys.stderr)
            return 2
        print(budget(args.budget))
        return 0
    problems = over(json.loads(args.counts.read_text(encoding="utf-8")))
    for line in problems:
        print(f"word_budget: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

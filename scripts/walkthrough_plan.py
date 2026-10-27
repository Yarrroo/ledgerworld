"""Turn the seven timed beats of docs/video-script.md into a rehearsal plan and its subtitles.

    uv run python scripts/walkthrough_plan.py [--script docs/video-script.md] --json PLAN --srt SRT

The plan is JSON: one entry per beat with its name, start and end in seconds, the app route the
rehearsal visits, the caption (the beat's **Shot:**) and the subtitle (the first paragraph of its
**Voice:**). The SRT carries the subtitles at the planned times. The beats, their order and their
timing rules are checks/submission.py's; this file reads them, it does not restate them.

The route is the screen that beat is filmed on. The rehearsal is anonymous and read-only, so a
beat whose shot needs an operator POST (the fresh fork, the interview) is rehearsed on its screen
without that action, and its `note` says so. Exit 1 when the script does not hold seven valid beats.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.submission import BEATS, TIMED, outside_fences, section, timed_beats

ROUTES = {
    "State": "/overview",
    "World": "/simulation",
    "Shock": "/simulation",
    "Fork": "/decisions",
    "Break": "/decisions",
    "Execute": "/execution",
    "Explain": "/overview",
}
NOTES = {
    "Fork": "the fresh branch is an operator POST; the rehearsal shows the comparison only",
    "Explain": "the interview is an operator POST; the rehearsal ends on the labels and links",
}


def field(body: str, label: str) -> str:
    found = re.search(rf"^\*\*{label}:\*\*(.*?)(?=^\*\*(?:Shot|Voice):\*\*|\Z)",
                      body, re.MULTILINE | re.DOTALL)
    return found[1].strip() if found else ""


def one_line(text: str) -> str:
    return " ".join(text.split())


def build(text: str) -> list[dict]:
    """The seven beats in order; ValueError when the script does not pass its own check."""
    if not timed_beats(text):
        raise ValueError("docs/video-script.md does not hold the seven contiguous timed beats")
    beats = []
    for shot in TIMED.finditer(outside_fences(text)):
        body = section(text, shot[0].removeprefix("## ").strip())
        voice = field(body, "Voice").split("\n\n", 1)[0]
        beats.append({
            "beat": shot[5],
            "start": int(shot[1]) * 60 + int(shot[2]),
            "end": int(shot[3]) * 60 + int(shot[4]),
            "route": ROUTES[shot[5]],
            "caption": one_line(field(body, "Shot")),
            "subtitle": one_line(voice).strip("“”\""),
            "note": NOTES.get(shot[5], ""),
        })
    if tuple(b["beat"] for b in beats) != BEATS:
        raise ValueError(f"the beats are not {', '.join(BEATS)}")
    return beats


def clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d},000"


def srt(beats: list[dict]) -> str:
    cues = [f"{n}\n{clock(b['start'])} --> {clock(b['end'])}\n[{b['beat']}] {b['subtitle']}\n"
            for n, b in enumerate(beats, 1)]
    return "\n".join(cues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--script", type=Path, default=ROOT / "docs" / "video-script.md")
    parser.add_argument("--json", type=Path, required=True, help="where to write the plan")
    parser.add_argument("--srt", type=Path, required=True, help="where to write the subtitles")
    args = parser.parse_args(argv)
    try:
        beats = build(args.script.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        print(f"walkthrough-plan: {error}", file=sys.stderr)
        return 1
    args.json.write_text(json.dumps({"total": beats[-1]["end"], "beats": beats}, indent=2) + "\n",
                         encoding="utf-8")
    args.srt.write_text(srt(beats), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

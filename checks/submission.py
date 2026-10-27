"""Check eight submission-pack items offline; --count prints only n/8.

Items: title, one-liner, description, Airwallex usage, testing instructions,
links, timed seven-beat shot list, and evidence rules. Exit 1 means incomplete.
This checks the documented format, not link availability, a finished recording,
provider receipts, arbitrary prose truth or event acceptance. g5 consumes --count.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BEATS = ("State", "World", "Shock", "Fork", "Break", "Execute", "Explain")
TIMED = re.compile(r"^## (\d{2}):([0-5]\d)-(\d{2}):([0-5]\d) (\w+)\s*$", re.MULTILINE)
UNFINISHED = re.compile(r"\b(?:TODO|TBD|placeholder)\b", re.IGNORECASE)
EVIDENCE = {
    "Run identity": ("run_id", "branch_id", "seed", "checkpoint_round", "snapshot_id"),
    "Model provenance": ("scripted|live", "fake|sandbox", "run's own source"),
    "Freshness and replay": ("fresh branch", "created_at", "cached", "Replay"),
    "Scripted wiring": ("shock/control", "wiring, not independent live-model choice"),
    "Trace chain": ("post_id", "intent_id", "evidence_ids", "journal_id", "source_intent_id",
                    "obs_hash", "hash alone cannot prove causal reasoning"),
    "Sandbox receipt": ("request_id", "reconciliation", "Mode B",
                        "sandbox receipt never proves live-model choice"),
}


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def section(text: str, heading: str, level: int = 2) -> str:
    mark = "#" * level
    found = re.search(
        rf"^{mark} {re.escape(heading)}\s*\n(.*?)(?=^#{{1,{level}}} |\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    return found[1].strip() if found else ""


def complete(text: str) -> bool:
    return bool(text.strip()) and not UNFINISHED.search(text)


def https_url(value: str) -> bool:
    if re.search(r"\s|[<>{}]", value):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        return (url.scheme == "https" and "." in host and not url.username and not url.password
                and host not in ("example.com", "example.org", "example.net")
                and not host.endswith((".invalid", ".example", ".test", ".localhost"))
                and not UNFINISHED.search(value))
    except ValueError:
        return False


def links_ok(root: Path, text: str) -> bool:
    links = section(text, "Links")
    for label in ("Repository", "Demo", "Video"):
        found = re.search(rf"^- {label}: (\S+)\s*$", links, re.MULTILINE)
        if not found or not https_url(found[1]):
            return False
    local = re.findall(r"\]\(([^)]+)\)", links)
    if not local:
        return False
    for target in local:
        path = (root / "docs" / target.split("#", 1)[0]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            return False
    return True


def timed_beats(text: str) -> bool:
    shots = list(TIMED.finditer(text))
    if tuple(shot[5] for shot in shots) != BEATS:
        return False
    previous = 0
    for shot in shots:
        start = int(shot[1]) * 60 + int(shot[2])
        end = int(shot[3]) * 60 + int(shot[4])
        if start != previous or end <= start:
            return False
        body = section(text, shot[0].removeprefix("## ").strip())
        if not complete(body) or "**Shot:**" not in body or "**Voice:**" not in body:
            return False
        previous = end
    return previous <= 280


def evidence_ok(text: str) -> bool:
    rules = section(text, "Evidence rules")
    return all(
        all(term.casefold() in section(rules, heading, 3).casefold() for term in terms)
        for heading, terms in EVIDENCE.items()
    )


def assess(root: Path) -> dict[str, bool]:
    submission = read(root / "docs/submission.md")
    video = read(root / "docs/video-script.md")
    title = re.search(r"^# (.+)$", submission, re.MULTILINE)
    airwallex = section(submission, "Airwallex usage")
    testing = section(submission, "Testing instructions")
    return {
        "title": bool(title and complete(title[1])),
        "one-liner": complete(section(submission, "One-liner")),
        "description": complete(section(submission, "Description")),
        "Airwallex usage": complete(airwallex) and all(
            term in airwallex for term in
            ("Mode A", "Mode B", "sandbox simulation", "ledger-only", "FakeTransport")
        ),
        "testing instructions": complete(testing) and all(
            term in testing for term in
            ("No login", "scripts/demo.sh", "checks/demo_receipt.py", "../README.md")
        ) and (root / "README.md").is_file(),
        "links": links_ok(root, submission),
        "timed seven-beat shot list": timed_beats(video),
        "evidence rules": evidence_ok(video),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print only n/8 (still exits 1 if missing)")
    args = parser.parse_args(argv)
    items = assess(ROOT)
    if not args.count:
        for name, present in items.items():
            print(f"{'ok' if present else 'missing'}: {name}")
    count = sum(items.values())
    print(f"{count}/8")
    return 0 if count == 8 else 1


if __name__ == "__main__":
    raise SystemExit(main())

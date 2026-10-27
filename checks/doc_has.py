"""Exit 0 when every given Markdown heading exists in FILE.

Usage: python checks/doc_has.py FILE HEADING [HEADING ...]
A heading matches a line `#… HEADING` exactly, ignoring the level and surrounding spaces.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")


def headings(path: Path) -> set[str]:
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING.match(line)
        if match:
            found.add(match.group(1).strip())
    return found


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(argv[0])
    if not path.is_file():
        print(f"doc_has: {path} does not exist", file=sys.stderr)
        return 1
    present = headings(path)
    missing = [h for h in argv[1:] if h.strip() not in present]
    for heading in missing:
        print(f"doc_has: {path} has no heading '{heading}'", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

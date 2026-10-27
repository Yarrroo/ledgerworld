"""Fail when an upstream file is modified or deleted but missing from ATTRIBUTION.md.

Compares the working tree with the unmodified upstream import. The base is the tag
`upstream-7657031` when it exists, otherwise the parentless commit whose tree is the
pinned upstream tree.

Usage: python checks/attribution.py [--repo PATH] [--base REV]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM_TAG = "upstream-7657031"
UPSTREAM_TREE = "dcc88f9b1da4145a06769a7f979d50d77e1dba25"
MODIFIED_HEADING = "## Upstream files modified"
ROW_PATH = re.compile(r"^\|\s*`([^`]+)`\s*\|")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    )


def tree_of(repo: Path, rev: str) -> str:
    return git(repo, "rev-parse", f"{rev}^{{tree}}").stdout.strip()


def find_base(repo: Path) -> str | None:
    """The upstream import; a tag pointing anywhere else is refused, not trusted."""
    tagged = git(repo, "rev-parse", "-q", "--verify", f"{UPSTREAM_TAG}^{{commit}}")
    if tagged.returncode == 0:
        base = tagged.stdout.strip()
        if tree_of(repo, base) != UPSTREAM_TREE:
            print(
                f"attribution: tag {UPSTREAM_TAG} does not point at tree {UPSTREAM_TREE}",
                file=sys.stderr,
            )
            return None
        return base
    for root in git(repo, "rev-list", "--max-parents=0", "HEAD").stdout.split():
        if tree_of(repo, root) == UPSTREAM_TREE:
            return root
    return None


def listed_modified(attribution: Path) -> set[str]:
    paths: set[str] = set()
    in_table = False
    for line in attribution.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_table = line.strip() == MODIFIED_HEADING
            continue
        match = ROW_PATH.match(line) if in_table else None
        if match:
            paths.add(match.group(1))
    return paths


def changed_upstream(repo: Path, base: str) -> list[tuple[str, str]]:
    # -z: paths arrive unquoted (non-ASCII, tabs), as status\0path\0 pairs.
    diff = git(repo, "diff", "--name-status", "--no-renames", "-z", base)
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.strip())
    fields = diff.stdout.split("\0")
    changes = []
    for status, path in zip(fields[0::2], fields[1::2], strict=False):
        if status[:1] in {"M", "D", "T"}:
            changes.append((status[:1], path))
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--base", help="revision of the unmodified upstream import")
    args = parser.parse_args(argv)

    base = args.base or find_base(args.repo)
    if base is None:
        print(
            f"attribution: no upstream base (tag {UPSTREAM_TAG} or a root commit with "
            f"tree {UPSTREAM_TREE}); fetch full history",
            file=sys.stderr,
        )
        return 1
    attribution = args.repo / "ATTRIBUTION.md"
    if not attribution.is_file():
        print("attribution: ATTRIBUTION.md is missing", file=sys.stderr)
        return 1

    listed = listed_modified(attribution)
    missing = [(s, p) for s, p in changed_upstream(args.repo, base) if p not in listed]
    for status, path in missing:
        kind = "deleted" if status == "D" else "modified"
        print(
            f"attribution: upstream file {kind} but not listed in ATTRIBUTION.md: {path}",
            file=sys.stderr,
        )
    if missing:
        return 1
    print(f"attribution: ok (base {base[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

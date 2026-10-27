"""Fail when a tracked file carries a credential shape or a tracked file is a .env file.

Usage: python checks/no_secrets.py [--repo PATH]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Each pattern is assembled from pieces so this file never matches itself.
PATTERNS = {
    "airwallex api key": re.compile("AIRWALLEX_API_KEY" + r"=[A-Za-z0-9_\-]{8,}"),
    "sk- api key": re.compile(r"(?<![A-Za-z0-9])" + "sk" + r"-[A-Za-z0-9_\-]{20,}"),
    "bearer token": re.compile("Bear" + r"er [A-Za-z0-9._~+/=\-]{20,}"),
    "zep api key": re.compile(r"(?<![A-Za-z0-9_])" + "z" + r"_[A-Za-z0-9._\-]{30,}"),
}
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")


def tracked_files(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return [p for p in out.decode().split("\0") if p]


def is_env_file(path: str) -> bool:
    name = Path(path).name
    if name == ".env":
        return True
    return name.startswith(".env.") and not name.endswith(ENV_TEMPLATE_SUFFIXES)


def scan(repo: Path) -> list[str]:
    problems = []
    for rel in tracked_files(repo):
        if is_env_file(rel):
            problems.append(f"{rel}: tracked .env file")
            continue
        path = repo / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    problems.append(f"{rel}:{lineno}: {label}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    problems = scan(args.repo)
    for problem in problems:
        print(f"no_secrets: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("no_secrets: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

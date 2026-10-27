"""Fail when a tracked file carries a credential shape or a tracked file is a .env file.

Scans the staged (index) content of every tracked file, which is what a commit carries.

Usage: python checks/no_secrets.py [--repo PATH]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Variables whose value is a credential (system brief §14).
SECRET_NAMES = (
    "AIRWALLEX_API_KEY", "AIRWALLEX_CLIENT_ID", "AIRWALLEX_WEBHOOK_SECRET",
    "LLM_API_KEY", "LLM_BOOST_API_KEY", "ZEP_API_KEY", "LEDGERWORLD_DEMO_TOKEN",
)
# Each pattern is assembled from pieces so this file never matches itself.
PATTERNS = {
    # NAME=v, NAME = "v", NAME: v, "NAME": "v" with a literal value; not a call, an
    # attribute or a documentation placeholder.
    "assigned credential": re.compile(
        r"\b(?:" + "|".join(SECRET_NAMES) + r")[\"']?\s*[:=]\s*[\"']?"
        r"(?!your[_-]|x{3}|changeme|placeholder|example)"
        r"[A-Za-z0-9_\-]{8,}(?![\w.(\[])"
    ),
    "sk- api key": re.compile(r"(?<![A-Za-z0-9])" + "sk" + r"-[A-Za-z0-9_\-]{20,}"),
    "bearer token": re.compile("bear" + r"er [A-Za-z0-9._~+/=\-]{20,}", re.IGNORECASE),
    "zep api key": re.compile(r"(?<![A-Za-z0-9_])" + "z" + r"_[A-Za-z0-9._\-]{30,}"),
}
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def staged_blobs(repo: Path) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-s", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    blobs = []
    for entry in out.decode().split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        mode, sha = meta.split()[:2]
        if mode != "160000":  # a submodule has no blob
            blobs.append((path, sha))
    return blobs


def read_blobs(repo: Path, shas: list[str]) -> list[bytes]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="".join(f"{sha}\n" for sha in shas).encode(),
        check=True,
        capture_output=True,
    )
    data, contents, pos = proc.stdout, [], 0
    for _ in shas:
        header_end = data.index(b"\n", pos)
        size = int(data[pos:header_end].split()[2])
        start = header_end + 1
        contents.append(data[start : start + size])
        pos = start + size + 1
    return contents


def is_env_file(path: str) -> bool:
    name = Path(path).name
    if name.endswith(ENV_TEMPLATE_SUFFIXES):
        return False
    return name in {".env", ".envrc"} or name.startswith(".env.") or name.endswith(".env")


def as_text(data: bytes) -> str | None:
    if data.startswith(UTF16_BOMS):
        return data.decode("utf-16", errors="replace")
    if b"\0" in data:
        return None  # binary
    return data.decode("utf-8", errors="replace")


def scan(repo: Path) -> list[str]:
    problems = []
    blobs = staged_blobs(repo)
    for (rel, _), data in zip(blobs, read_blobs(repo, [sha for _, sha in blobs]), strict=True):
        if is_env_file(rel):
            problems.append(f"{rel}: tracked .env file")
            continue
        text = as_text(data)
        if text is None:
            continue
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

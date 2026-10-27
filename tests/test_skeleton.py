"""The repository skeleton: merge gate, attribution and secret checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ROOT / "checks"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, cwd=cwd, capture_output=True, text=True)


def git(repo: Path, *args: str) -> str:
    result = run(
        "git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "-C", str(repo), *args,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def make_repo(path: Path, files: dict[str, str]) -> str:
    git(path, "init", "-q")
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return git(path, "rev-parse", "HEAD")


def attribution(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, str(CHECKS / "attribution.py"), "--repo", str(repo), "--base", base)


def no_secrets(repo: Path) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, str(CHECKS / "no_secrets.py"), "--repo", str(repo))


ATTRIBUTION_EMPTY = "# Attribution\n\n## Upstream files modified\n\n| Path | Why |\n|---|---|\n"


def test_merge_gate_is_executable():
    assert os.access(CHECKS / "merge.sh", os.X_OK)
    mode = git(ROOT, "ls-files", "-s", "checks/merge.sh").split()[0]
    assert mode == "100755"


def test_attribution_flags_unlisted_modified_upstream_file(tmp_path):
    base = make_repo(tmp_path, {"backend/app/core.py": "x = 1\n", "README.md": "upstream\n"})
    (tmp_path / "ATTRIBUTION.md").write_text(ATTRIBUTION_EMPTY)
    (tmp_path / "backend/app/core.py").write_text("x = 2\n")

    flagged = attribution(tmp_path, base)
    assert flagged.returncode == 1
    assert "backend/app/core.py" in flagged.stderr

    listed = ATTRIBUTION_EMPTY + "| `backend/app/core.py` | wires a new module in |\n"
    (tmp_path / "ATTRIBUTION.md").write_text(listed)
    assert attribution(tmp_path, base).returncode == 0


def test_attribution_flags_unlisted_deleted_upstream_file(tmp_path):
    base = make_repo(tmp_path, {"frontend/main.js": "1\n"})
    (tmp_path / "ATTRIBUTION.md").write_text(ATTRIBUTION_EMPTY)
    (tmp_path / "frontend/main.js").unlink()
    flagged = attribution(tmp_path, base)
    assert flagged.returncode == 1
    assert "deleted" in flagged.stderr


def test_attribution_ignores_added_files_and_other_tables(tmp_path):
    base = make_repo(tmp_path, {"a.py": "1\n"})
    (tmp_path / "ATTRIBUTION.md").write_text(
        "## Files added by this project\n\n| `a.py` | not the modified table |\n\n"
        + ATTRIBUTION_EMPTY.split("\n", 2)[2]
    )
    (tmp_path / "new.py").write_text("2\n")
    git(tmp_path, "add", "new.py")
    assert attribution(tmp_path, base).returncode == 0
    (tmp_path / "a.py").write_text("3\n")
    assert attribution(tmp_path, base).returncode == 1


def test_no_secrets_flags_planted_key(tmp_path):
    make_repo(tmp_path, {"app.py": "print('hello')\n"})
    assert no_secrets(tmp_path).returncode == 0

    planted = "s" + "k-" + "a1B2" * 6
    (tmp_path / "config.py").write_text(f"KEY = '{planted}'\n")
    git(tmp_path, "add", "config.py")
    flagged = no_secrets(tmp_path)
    assert flagged.returncode == 1
    assert "config.py:1" in flagged.stderr
    assert planted not in flagged.stderr + flagged.stdout


def test_no_secrets_flags_tracked_env_file_but_not_example(tmp_path):
    make_repo(tmp_path, {".env.example": "AIRWALLEX_API_KEY=\nLLM_API_KEY=\n"})
    assert no_secrets(tmp_path).returncode == 0
    (tmp_path / ".env").write_text("LLM_MODEL_NAME=small\n")
    git(tmp_path, "add", "-f", ".env")
    flagged = no_secrets(tmp_path)
    assert flagged.returncode == 1
    assert ".env: tracked .env file" in flagged.stderr


def test_env_example_names_every_variable_without_values():
    lines = [
        line for line in (ROOT / ".env.example").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    names = [line.split("=", 1)[0] for line in lines]
    assert all(line.endswith("=") for line in lines)
    for name in ("AIRWALLEX_API_KEY", "LLM_API_KEY", "ZEP_API_KEY", "LEDGERWORLD_DEMO_TOKEN"):
        assert name in names


def test_required_checks_cover_both_goals():
    required = json.loads((CHECKS / "required.json").read_text())
    assert len(required["g1"]) == 16 and len(required["g2"]) == 8
    ids = [c["id"] for goal in ("g1", "g2") for c in required[goal]]
    assert len(ids) == len(set(ids))


def test_doc_has(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n## Setup\ntext\n")
    script = str(CHECKS / "doc_has.py")
    assert run(sys.executable, script, str(doc), "Title", "Setup").returncode == 0
    assert run(sys.executable, script, str(doc), "Setup", "Missing").returncode == 1

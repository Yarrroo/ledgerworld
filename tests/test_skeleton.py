"""The repository skeleton: merge gate, attribution and secret checks."""

from __future__ import annotations

import json
import os
import re
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


def check(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, str(CHECKS / script), *args)


def attribution(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    return check("attribution.py", "--repo", str(repo), "--base", base)


def no_secrets(repo: Path) -> subprocess.CompletedProcess[str]:
    return check("no_secrets.py", "--repo", str(repo))


def env_example_names() -> list[str]:
    lines = (ROOT / ".env.example").read_text().splitlines()
    return [line for line in lines if line and not line.startswith("#")]


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


KEY_VALUE = "a1B2c3D4" * 3


def plant(repo: Path, rel: str, text: str | bytes) -> subprocess.CompletedProcess[str]:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_text(text)
    git(repo, "add", "-f", rel)
    return no_secrets(repo)


def test_no_secrets_flags_assigned_credentials_in_every_common_form(tmp_path):
    make_repo(tmp_path, {"app.py": "x = 1\n"})
    name = "AIRWALLEX" + "_API_KEY"
    forms = {
        "a.py": f'{name} = "{KEY_VALUE}"\n',
        "compose.yml": f"    {name}: {KEY_VALUE}\n",
        "trace.json": f'{{"{name}": "{KEY_VALUE}"}}\n',
        "hook.txt": "AIRWALLEX_WEBHOOK" + f"_SECRET={KEY_VALUE}\n",
    }
    for rel, text in forms.items():
        flagged = plant(tmp_path, rel, text)
        assert flagged.returncode == 1, rel
        assert f"{rel}:1: assigned credential" in flagged.stderr
        git(tmp_path, "rm", "-q", "--cached", rel)


def test_no_secrets_ignores_placeholders_and_code_references(tmp_path):
    make_repo(tmp_path, {
        "README.md": "LLM_API_KEY=your_api_key\nZEP_API_KEY=your_zep_api_key\n",
        "config.py": "LLM_API_KEY = os.environ.get('LLM_API_KEY')\n"
                     "ZEP_API_KEY = Config.ZEP_API_KEY\n"
                     "client(zep_api_key=zep_api_key_from_settings)\n",
    })
    assert no_secrets(tmp_path).returncode == 0


def test_no_secrets_reads_utf16_and_lowercase_bearer(tmp_path):
    make_repo(tmp_path, {"app.py": "x = 1\n"})
    utf16 = f"KEY = '{'s' + 'k-' + KEY_VALUE}'\n".encode("utf-16")
    assert plant(tmp_path, "win.cfg", utf16).returncode == 1
    git(tmp_path, "rm", "-q", "--cached", "win.cfg")
    lower = "authorization: " + "bea" + f"rer {KEY_VALUE}\n"
    assert plant(tmp_path, "cassette.yml", lower).returncode == 1


def test_no_secrets_flags_env_files_by_any_common_name(tmp_path):
    make_repo(tmp_path, {"app.py": "x = 1\n"})
    for rel in ("prod.env", "backend/app.env", ".envrc", ".env.local"):
        flagged = plant(tmp_path, rel, "MODE=fake\n")
        assert f"{rel}: tracked .env file" in flagged.stderr, rel
        git(tmp_path, "rm", "-q", "--cached", rel)
    assert plant(tmp_path, "deploy/.env.example", "MODE=\n").returncode == 0


def test_no_secrets_scans_what_is_staged_not_the_working_copy(tmp_path):
    make_repo(tmp_path, {"app.py": "x = 1\n"})
    plant(tmp_path, "config.py", f"KEY = '{'s' + 'k-' + KEY_VALUE}'\n")
    (tmp_path / "config.py").write_text("KEY = None\n")
    assert no_secrets(tmp_path).returncode == 1


def test_attribution_matches_non_ascii_paths(tmp_path):
    base = make_repo(tmp_path, {"docs/说明.md": "a\n"})
    (tmp_path / "docs/说明.md").write_text("b\n")
    (tmp_path / "ATTRIBUTION.md").write_text(
        ATTRIBUTION_EMPTY + "| `docs/说明.md` | translated |\n"
    )
    assert attribution(tmp_path, base).returncode == 0


def test_attribution_defaults_to_the_pinned_tree_and_needs_it(tmp_path):
    make_repo(tmp_path, {"a.py": "1\n"})
    (tmp_path / "ATTRIBUTION.md").write_text(ATTRIBUTION_EMPTY)
    result = check("attribution.py", "--repo", str(tmp_path))
    assert result.returncode == 1
    assert "not in this clone" in result.stderr


def test_merge_gate_refuses_a_stale_lock():
    assert "export UV_LOCKED=1" in (CHECKS / "merge.sh").read_text()


def test_url_ok_refuses_non_http_schemes_cleanly():
    result = check("url_ok.py", "file:///etc/hostname")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_env_example_lists_every_variable_the_backend_reads():
    pattern = re.compile(r"os\.(?:environ\.get|getenv)\(['\"]([A-Z_]+)|os\.environ\[['\"]([A-Z_]+)")
    read = {
        name
        for path in (ROOT / "backend/app").rglob("*.py")
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
        for name in match.groups() if name
    }
    read.discard("WERKZEUG_RUN_MAIN")  # set by the dev server itself
    listed = {line.split("=", 1)[0] for line in env_example_names()}
    assert read <= listed, sorted(read - listed)


def test_env_example_names_every_variable_without_values():
    lines = env_example_names()
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
    assert check("doc_has.py", str(doc), "Title", "Setup").returncode == 0
    assert check("doc_has.py", str(doc), "Setup", "Missing").returncode == 1


def test_doc_has_ignores_code_fences_and_keeps_trailing_hash(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n```bash\n# Setup\n```\n\n## C#\n\n## Usage ##\n")
    assert check("doc_has.py", str(doc), "Setup").returncode == 1
    assert check("doc_has.py", str(doc), "C#", "Usage").returncode == 0

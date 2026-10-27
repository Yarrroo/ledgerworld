"""The pack check is offline, partial counts are honest, and each item can fail."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from checks import submission
from checks.goals import g5

ROOT = Path(__file__).resolve().parents[2]
# Syntactic fixture only; no test opens this URL or claims a published video.
VIDEO = "https://www.youtube.com/watch?v=offline-fixture"


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "checks").mkdir()
    for path in ("docs/submission.md", "docs/video-script.md", "docs/architecture.md",
                 "docs/schema.md", "README.md", "LICENSE", "ATTRIBUTION.md", "checks/submission.py"):
        shutil.copy(ROOT / path, tmp_path / path)
    path = tmp_path / "docs/submission.md"
    text = path.read_text(encoding="utf-8")
    lines = [f"- Video: {VIDEO}" if line.startswith("- Video:") else line
             for line in text.splitlines()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def replace(root: Path, name: str, old: str, new: str) -> None:
    path = root / "docs" / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "checks/submission.py"), *args],
        cwd=root.parent, capture_output=True, text=True, check=False, timeout=10,
    )


def test_repository_copy_and_shot_list_satisfy_the_document_items():
    items = submission.assess(ROOT)
    assert len(items) == 8
    assert all(present for name, present in items.items() if name != "links"), items


def test_complete_pack_counts_eight_and_runs_outside_the_checkout(pack):
    assert all(submission.assess(pack).values())
    result = cli(pack)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "8/8"
    assert len(result.stdout.splitlines()) == 9
    count = cli(pack, "--count")
    assert (count.returncode, count.stdout, count.stderr) == (0, "8/8\n", "")
    assert g5.measure(pack) == 8


@pytest.mark.parametrize(("old", "new", "item"), [
    ("# LedgerWorld\n", "", "title"),
    ("## One-liner", "## Removed", "one-liner"),
    ("## Description", "## Removed", "description"),
    ("## Airwallex usage", "## Removed", "Airwallex usage"),
    ("## Testing instructions", "## Removed", "testing instructions"),
    ("## Links", "## Removed", "links"),
])
def test_each_submission_item_is_actually_checked(pack, old, new, item):
    replace(pack, "submission.md", old, new)
    items = submission.assess(pack)
    assert not items[item]
    assert sum(items.values()) == 7


@pytest.mark.parametrize("heading", submission.EVIDENCE)
def test_each_evidence_rule_is_required(pack, heading):
    replace(pack, "video-script.md", f"### {heading}", "### Removed")
    assert not submission.assess(pack)["evidence rules"]


@pytest.mark.parametrize("term", [
    "checkpoint_round", "scripted|live", "created_at", "cached",
    "wiring, not independent live-model choice", "source_intent_id",
    "hash alone cannot prove causal reasoning", "sandbox receipt never proves live-model choice",
])
def test_provenance_and_trace_safeguards_cannot_be_dropped(pack, term):
    replace(pack, "video-script.md", term, "removed")
    assert not submission.assess(pack)["evidence rules"]


@pytest.mark.parametrize(("old", "new"), [
    ("03:55-04:35", "03:55-04:41"),  # too long
    ("00:15-00:25", "00:16-00:25"),  # gap
    ("00:15-00:25", "00:14-00:25"),  # overlap
    ("00:15-00:25", "00:15-00:15"),  # empty interval
    ("03:55-04:35", "03:55-03:65"),  # invalid seconds
    ("## 00:15-00:25 World", "## World"),  # missing timing
    ("## 00:15-00:25 World", "## 00:15-00:25 State"),  # duplicated/out-of-order beat
    ("**Shot:**", "Shot removed:"),
    ("**Voice:**", "Voice removed:"),
])
def test_invalid_shot_lists_fail(pack, old, new):
    replace(pack, "video-script.md", old, new)
    assert not submission.assess(pack)["timed seven-beat shot list"]


def test_exactly_four_minutes_forty_is_allowed(pack):
    replace(pack, "video-script.md", "03:55-04:35", "03:55-04:40")
    assert submission.assess(pack)["timed seven-beat shot list"]


@pytest.mark.parametrize("url", [
    "pending recording", "TODO", "https://example.com/video", "https://video.invalid/watch",
    "http://video.org/watch", "https://user:password@video.org/watch", "https://<video>/watch",
    "https://[broken", "javascript:alert(1)", "../video-script.md",
])
def test_missing_or_placeholder_video_never_counts_as_a_link(pack, url):
    replace(pack, "submission.md", VIDEO, url)
    assert not submission.assess(pack)["links"]
    result = cli(pack, "--count")
    assert (result.returncode, result.stdout, result.stderr) == (1, "7/8\n", "")
    assert g5.measure(pack) == 7


@pytest.mark.parametrize("name", ["Repository", "Demo", "Video"])
def test_all_three_external_links_are_required(pack, name):
    replace(pack, "submission.md", f"- {name}:", f"- Missing {name}:")
    assert not submission.assess(pack)["links"]


def test_missing_local_setup_does_not_count(pack):
    (pack / "README.md").unlink()
    items = submission.assess(pack)
    assert not items["testing instructions"]
    assert not items["links"]


def test_a_local_link_cannot_escape_the_checkout(pack):
    replace(pack, "submission.md", "../LICENSE", "../../outside")
    (pack.parent / "outside").write_text("not part of this pack", encoding="utf-8")
    assert not submission.assess(pack)["links"]


def test_an_empty_checkout_reports_zero_without_a_traceback(tmp_path):
    (tmp_path / "checks").mkdir()
    shutil.copy(ROOT / "checks/submission.py", tmp_path / "checks/submission.py")
    result = cli(tmp_path, "--count")
    assert (result.returncode, result.stdout, result.stderr) == (1, "0/8\n", "")


def test_unreadable_document_is_missing_not_a_crash(pack):
    (pack / "docs/video-script.md").write_bytes(b"\xff")
    items = submission.assess(pack)
    assert not items["timed seven-beat shot list"]
    assert not items["evidence rules"]


def test_unknown_option_is_a_usage_error(pack):
    assert cli(pack, "--unknown").returncode == 2


@pytest.mark.parametrize("body", [
    "**Shot:**\n\n**Voice:** Narration.",
    "**Shot:** Frame description.\n\n**Voice:**",
    "**Shot:**\n\n**Voice:**",
])
def test_shot_and_voice_each_need_content(pack, body):
    path = pack / "docs/video-script.md"
    text = path.read_text(encoding="utf-8")
    original = submission.section(text, "00:00-00:15 State")
    replace(pack, "video-script.md", original, body)
    assert not submission.assess(pack)["timed seven-beat shot list"]


@pytest.mark.parametrize("heading", submission.EVIDENCE)
def test_evidence_drafts_are_not_complete(pack, heading):
    replace(pack, "video-script.md", f"### {heading}",
            f"### {heading}\n\nTODO: replace this draft.")
    assert not submission.assess(pack)["evidence rules"]


@pytest.mark.parametrize("name", ["submission.md", "video-script.md"])
@pytest.mark.parametrize("fence", ["`````", "~~~", "````"])
def test_example_markdown_is_not_the_document(pack, name, fence):
    path = pack / "docs" / name
    path.write_text(f"{fence}markdown\n{path.read_text(encoding='utf-8')}\n{fence}\n",
                    encoding="utf-8")
    items = submission.assess(pack)
    expected = 2 if name == "submission.md" else 6
    assert sum(items.values()) == expected


@pytest.mark.parametrize("url", [
    "https://video.org:not-a-port/watch", "https://video.org:99999/watch",
    "https://video.example.com/watch", "https://videos.org/pending",
])
def test_malformed_and_draft_urls_do_not_complete_the_pack(pack, url):
    replace(pack, "submission.md", VIDEO, url)
    assert not submission.assess(pack)["links"]


def test_recording_plan_handles_the_prepared_approvals_one_shot_contract():
    text = (ROOT / "docs/video-script.md").read_text(encoding="utf-8")
    prerequisites = submission.section(text, "Recording prerequisites")
    execute = submission.section(text, "02:00-03:55 Execute")
    assert "already_approved" in prerequisites
    assert "earlier capture" in execute
    assert "Do not approve or execute that same plan again" in execute

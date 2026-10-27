"""Video intake refuses what a judge could not watch, and the probe names every dead link."""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

from checks import submission, submission_links

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "submission_links"
REPO = "https://github.com/Yarrroo/ledgerworld"
DEMO = "https://peterson-prefix-assumptions-hits.trycloudflare.com"
# Offline ids only; no test opens these URLs or claims a published video.
SHORT = "https://www.youtube.com/watch?v=Fixture0001"
LONG = "https://www.youtube.com/watch?v=Fixture0002"
BARE = "https://youtu.be/Fixture0003"
PRIVATE = "https://www.youtube.com/watch?v=Fixture0004"
VIMEO = "https://vimeo.com/100000001"
LOOM = "https://www.loom.com/share/" + "0123456789abcdef" * 2
DRIVE = "https://drive.google.com/file/d/FixtureDriveFile00000001/view"


def oembed(url: str) -> str:
    return f"https://www.youtube.com/oembed?format=json&url={urllib.parse.quote(url, safe='')}"


ANSWERS = {
    REPO: (200, ""),
    DEMO: (200, "<html></html>"),
    f"{DEMO}/api/v1/health": (200, "health.json"),
    oembed(SHORT): (200, "youtube_oembed.json"),
    SHORT: (200, "youtube_watch_short.html"),
    oembed(LONG): (200, "youtube_oembed.json"),
    LONG: (200, "youtube_watch_long.html"),
    oembed(BARE): (200, "youtube_oembed.json"),
    "https://www.youtube.com/watch?v=Fixture0003": (200, "youtube_watch_no_metadata.html"),
    oembed(PRIVATE): (401, ""),
    f"https://vimeo.com/api/oembed.json?url={urllib.parse.quote(VIMEO, safe='')}":
        (200, "vimeo_oembed_long.json"),
    f"https://www.loom.com/v1/oembed?url={urllib.parse.quote(LOOM, safe='')}": (200, "loom_oembed.json"),
    DRIVE: (200, "drive_signin.html"),
}


class Recorded:
    """A fetch that answers from fixtures and remembers every URL it was asked for."""

    def __init__(self, **overrides: tuple[int, str] | None):
        self.answers = {**ANSWERS, **overrides}
        self.asked: list[str] = []

    def __call__(self, url: str) -> tuple[int, str]:
        self.asked.append(url)
        answer = self.answers.get(url)
        if answer is None:
            raise OSError(f"no recorded answer for {url}")
        status, name = answer
        body = (FIXTURES / name).read_text(encoding="utf-8") if name.endswith((".json", ".html")) else name
        return status, body


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "submission.md"
    shutil.copy(ROOT / "docs/submission.md", path)
    return path


def test_short_public_youtube_video_passes_with_its_length():
    assert submission_links.vet_video(SHORT, Recorded()) == (True, "youtube: public, 4:13")


def test_duration_the_host_does_not_expose_is_unknown_not_guessed():
    passes, reason = submission_links.vet_video(BARE, Recorded())
    assert passes and reason == "youtube: public, duration unknown"


def test_loom_duration_comes_from_oembed():
    assert submission_links.vet_video(LOOM, Recorded()) == (True, "loom: public, 3:07")


@pytest.mark.parametrize("url, reason", [
    (LONG, "youtube: 5:00 is at or over the 5:00 limit"),
    (VIMEO, "vimeo: 5:12 is at or over the 5:00 limit"),
])
def test_video_at_or_over_five_minutes_is_refused(url, reason):
    assert submission_links.vet_video(url, Recorded()) == (False, reason)


def test_private_video_is_refused():
    passes, reason = submission_links.vet_video(PRIVATE, Recorded())
    assert not passes and "private" in reason


def test_drive_file_behind_a_sign_in_is_refused():
    passes, reason = submission_links.vet_video(DRIVE, Recorded())
    assert not passes and "sign-in" in reason


@pytest.mark.parametrize("url, words", [
    ("https://example.org/watch?v=Fixture0001", "not an https URL"),
    ("http://www.youtube.com/watch?v=Fixture0001", "not an https URL"),
    ("https://dailymotion.com/video/x1", "not an allowed video host"),
    ("https://studio.youtube.com/video/Fixture0001/edit", "not a published video link"),
    ("https://www.youtube.com/channel/UCfixture", "not a published video link"),
    ("https://drive.google.com/drive/folders/FixtureFolder", "not a published video link"),
    ("pending recording", "not an https URL"),
])
def test_unknown_host_draft_or_malformed_url_is_refused_before_any_request(url, words):
    fetch = Recorded()
    passes, reason = submission_links.vet_video(url, fetch)
    assert not passes and words in reason
    assert fetch.asked == []


def test_apply_rewrites_only_the_video_line(doc):
    before = doc.read_bytes()
    assert submission_links.main(["--video", SHORT, "--apply", "--file", str(doc)], Recorded()) == 0
    after = doc.read_bytes()
    old = [line for line in before.splitlines(keepends=True) if line.startswith(b"- Video:")]
    assert len(old) == 1
    assert after == before.replace(old[0], f"- Video: {SHORT}\n".encode())
    assert submission.links_ok(ROOT, after.decode("utf-8"))


def test_apply_refuses_a_failing_url_and_leaves_the_file_alone(doc, capsys):
    before = doc.read_bytes()
    assert submission_links.main(["--video", LONG, "--apply", "--file", str(doc)], Recorded()) == 1
    assert doc.read_bytes() == before
    assert capsys.readouterr().out.startswith("refused: Video")


def test_apply_ignores_a_video_line_outside_the_links_section(tmp_path):
    path = tmp_path / "s.md"
    path.write_text("## Notes\n\n- Video: keep me\n\n## Links\n\n- Video: pending\n- Setup: x\n",
                    encoding="utf-8")
    submission_links.apply_video(path, SHORT)
    assert path.read_text(encoding="utf-8") == (
        f"## Notes\n\n- Video: keep me\n\n## Links\n\n- Video: {SHORT}\n- Setup: x\n")


def test_probe_reports_every_link_ok_once_the_video_is_in(doc, capsys):
    submission_links.apply_video(doc, SHORT)
    fetch = Recorded()
    assert submission_links.main(["--probe", "--file", str(doc)], fetch) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:2] for line in lines] == [
        ["ok:", "Repository"], ["ok:", "Demo"], ["ok:", "Demo"], ["ok:", "Video"]]
    assert f"{DEMO}/api/v1/health" in fetch.asked


def test_dead_demo_and_missing_video_each_fail_the_probe(doc, capsys):
    fetch = Recorded(**{f"{DEMO}/api/v1/health": (530, ""), DEMO: (530, "")})
    assert submission_links.main(["--probe", "--file", str(doc)], fetch) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("ok: Repository")
    assert lines[1] == f"dead: Demo {DEMO} (HTTP 530)"
    assert lines[2].startswith("dead: Demo health") and "HTTP 530" in lines[2]
    assert lines[3].startswith("dead: Video")


def test_private_repository_and_unreachable_demo_are_dead(doc, capsys):
    submission_links.apply_video(doc, SHORT)
    answers = {**ANSWERS, REPO: (404, "")}
    del answers[DEMO]
    fetch = Recorded()
    fetch.answers = answers
    assert submission_links.main(["--probe", "--file", str(doc)], fetch) == 1
    out = capsys.readouterr().out
    assert f"dead: Repository {REPO} (HTTP 404)" in out
    assert f"dead: Demo {DEMO} (no answer" in out


def test_cli_without_a_mode_is_bad_usage():
    result = subprocess.run([sys.executable, str(ROOT / "checks/submission_links.py")],
                            capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 2
    assert "--video" in result.stderr

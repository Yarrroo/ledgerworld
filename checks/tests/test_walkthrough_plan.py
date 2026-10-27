"""scripts/walkthrough_plan.py: the seven beats in order, contiguous, captioned, within 4:40."""

from __future__ import annotations

import importlib.util
import itertools
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("walkthrough_plan", ROOT / "scripts" / "walkthrough_plan.py")
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)

BEATS = ("State", "World", "Shock", "Fork", "Break", "Execute", "Explain")
SCRIPT = ROOT / "docs" / "video-script.md"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, str]:
    out = tmp_path_factory.mktemp("walkthrough")
    assert plan.main(["--json", str(out / "plan.json"), "--srt", str(out / "plan.srt")]) == 0
    return (json.loads((out / "plan.json").read_text(encoding="utf-8")),
            (out / "plan.srt").read_text(encoding="utf-8"))


def test_beats_in_order_contiguous_within_limit(built: tuple[dict, str]) -> None:
    beats = built[0]["beats"]
    assert tuple(b["beat"] for b in beats) == BEATS
    assert beats[0]["start"] == 0
    for before, after in itertools.pairwise(beats):
        assert after["start"] == before["end"]
    assert all(b["end"] > b["start"] for b in beats)
    assert built[0]["total"] == beats[-1]["end"] <= 280


def test_every_beat_has_caption_subtitle_and_route(built: tuple[dict, str]) -> None:
    for beat in built[0]["beats"]:
        assert beat["caption"].strip(), beat["beat"]
        assert beat["subtitle"].strip(), beat["beat"]
        assert beat["route"].startswith("/"), beat["beat"]
        assert "\n" not in beat["caption"] + beat["subtitle"]
    execute = next(b for b in built[0]["beats"] if b["beat"] == "Execute")
    assert "no sandbox execution" not in execute["subtitle"]  # the Voice's first paragraph only


def test_srt_is_well_formed(built: tuple[dict, str]) -> None:
    beats = built[0]["beats"]
    cues = built[1].strip().split("\n\n")
    assert len(cues) == len(beats)
    stamp = r"(\d\d):(\d\d):(\d\d),(\d{3})"
    for n, (cue, beat) in enumerate(zip(cues, beats, strict=True), 1):
        index, times, text = cue.split("\n")
        assert index == str(n)
        found = re.fullmatch(rf"{stamp} --> {stamp}", times)
        assert found
        start = int(found[1]) * 3600 + int(found[2]) * 60 + int(found[3])
        end = int(found[5]) * 3600 + int(found[6]) * 60 + int(found[7])
        assert (start, end) == (beat["start"], beat["end"])
        assert text == f"[{beat['beat']}] {beat['subtitle']}"


def test_broken_script_is_refused(tmp_path: Path) -> None:
    text = SCRIPT.read_text(encoding="utf-8").replace("## 00:25-00:40 Shock", "## 00:26-00:40 Shock")
    (tmp_path / "script.md").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        plan.build(text)
    code = plan.main(["--script", str(tmp_path / "script.md"),
                      "--json", str(tmp_path / "p.json"), "--srt", str(tmp_path / "p.srt")])
    assert code == 1
    assert not (tmp_path / "p.json").exists()

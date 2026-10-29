"""scripts/voiceover.py and the narrated take, offline: Voice lines, window fit, card, mux command."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("voiceover", ROOT / "scripts" / "voiceover.py")
voiceover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voiceover)

BEATS = ("State", "World", "Shock", "Fork", "Break", "Execute", "Explain")


def test_seven_voice_lines_in_order_from_the_script() -> None:
    lines = voiceover.lines()
    assert tuple(line["beat"] for line in lines) == BEATS
    assert lines[0]["text"].startswith("This is synthetic treasury cash.")
    assert lines[0]["start"] == 0 and lines[-1]["end"] == 275
    for line in lines:
        assert line["text"] and "**" not in line["text"] and "\n" not in line["text"]
        assert not line["text"].startswith(("“", '"'))
    # the Execute beat speaks its Voice paragraph only, never the fallback note after it
    assert "If sandbox evidence is unavailable" not in lines[5]["text"]


@pytest.mark.parametrize(("seconds", "window", "rate"), [
    (5.0, 15, 0), (14.6, 15, 0), (12.53, 10, 31), (13.0, 10, 36), (13.5, 10, None), (60.0, 15, None),
])
def test_rate_fits_a_clip_to_its_window_or_refuses(seconds: float, window: int, rate: int | None) -> None:
    assert voiceover.rate_for(seconds, window) == rate


def test_every_line_is_estimated_to_fit_its_beat() -> None:
    for line in voiceover.lines():
        assert voiceover.rate_for(voiceover.estimate(line["text"]), line["end"] - line["start"]) is not None


def test_dry_run_writes_the_estimate_and_needs_no_network(tmp_path: Path) -> None:
    assert voiceover.main(["voice", "--out", str(tmp_path), "--dry-run"]) == 0
    clips = json.loads((tmp_path / "voice.json").read_text(encoding="utf-8"))["clips"]
    assert [c["beat"] for c in clips] == list(BEATS)
    assert all(c["rate"] is not None and c["seconds"] is None for c in clips)
    assert not list(tmp_path.glob("*.mp3"))


def test_duration_is_read_from_ffmpeg() -> None:
    assert voiceover.parse_duration("  Duration: 00:01:02.53, start: 0.000000, bitrate: 48 kb/s") == 62.53
    with pytest.raises(ValueError):
        voiceover.parse_duration("Input #0, mp3, from 't.mp3':")


@pytest.mark.parametrize("operator", [True, False])
def test_opening_card_says_the_voice_is_synthetic(operator: bool) -> None:
    card = voiceover.label(operator)
    text = " ".join([card["title"], *card["lines"]])
    assert card["seconds"] == 3
    assert "machine take" in card["title"]
    assert "synthetic voice, not a person" in text and voiceover.VOICE in text
    assert "synthetic" in card["lines"][1]
    if operator:
        assert "off-screen with the demo token" in text and "no execution" in text
    else:
        assert "No operator action was sent" in text and "read-only" in text


def _docs(began: dict[str, float]) -> tuple[dict, dict]:
    clips = [{"beat": b, "file": f"/v/{n:02d}-{b}.mp3", "seconds": 5.0, "start": 0, "end": 15}
             for n, b in enumerate(BEATS, 1)]
    beats = [{"beat": b, "began": t, "ready": t + 1, "left": t + 10, "reached": True, "actions": []}
             for b, t in began.items()]
    return {"clips": clips}, {"offset": 3.02, "beats": beats}


def test_mux_places_each_clip_at_its_beats_actual_start_after_the_card() -> None:
    voice, beats = _docs({b: 10.0 * i for i, b in enumerate(BEATS)})
    beats["beats"][3]["began"] = 41.234  # a late beat: its voice moves with it
    command = voiceover.mux_command("ffmpeg", "/v/take.webm", voiceover.placements(voice, beats), "/v/take.mp4")
    assert command[:6] == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i"]
    assert command[6] == "/v/take.webm" and command[-1] == "/v/take.mp4"
    inputs = [command[i + 1] for i, arg in enumerate(command) if arg == "-i"]
    assert inputs == ["/v/take.webm", *(c["file"] for c in voice["clips"])]
    graph = command[command.index("-filter_complex") + 1]
    assert "[1:a]adelay=3020:all=1[a1]" in graph
    assert "[4:a]adelay=44254:all=1[a4]" in graph
    assert "amix=inputs=7:duration=longest:normalize=0,apad[voice]" in graph
    for pair in (["-map", "0:v"], ["-map", "[voice]"], ["-c:v", "libx264"], ["-c:a", "aac"]):
        assert any(command[i:i + 2] == pair for i in range(len(command)))
    assert "-shortest" in command  # the padded voice ends with the video, never after it


def test_mux_refuses_a_take_missing_a_beat() -> None:
    voice, beats = _docs({b: 10.0 * i for i, b in enumerate(BEATS[:-1])})
    with pytest.raises(ValueError, match="Explain"):
        voiceover.placements(voice, beats)


def test_summary_marks_voice_running_past_its_beat() -> None:
    voice, beats = _docs({b: 10.0 * i for i, b in enumerate(BEATS)})
    voice["clips"][0]["seconds"] = 12.0  # began 0, left 10
    beats["beats"][3]["actions"] = [{"method": "POST", "path": "/runs", "status": 202}]
    rows = voiceover.summary(voice, beats).splitlines()
    assert "OVERRUN" in rows[1] and "OVERRUN" not in rows[2]
    assert rows[4].endswith("POST /runs 202")


def test_the_token_never_reaches_the_browser() -> None:
    config = (ROOT / "e2e" / "narrated-take.config.ts").read_text(encoding="utf-8")
    spec = (ROOT / "e2e" / "narrated-take.spec.ts").read_text(encoding="utf-8")
    shell = (ROOT / "scripts" / "narrated_take.sh").read_text(encoding="utf-8")
    assert "extraHTTPHeaders" not in config + spec and "LEDGERWORLD_DEMO_TOKEN" not in config
    assert spec.count("Authorization") == 1 and "readOnly(page" in spec
    assert "POST', '/executions" not in spec
    assert "$LEDGERWORLD_DEMO_TOKEN" not in shell and "${LEDGERWORLD_DEMO_TOKEN}" not in shell

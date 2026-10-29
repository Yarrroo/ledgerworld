"""scripts/voiceover.py and the narrated take, offline: Voice lines, window fit, card, mux command."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
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
        assert "off-screen with the demo token" in text and "a refusal included" in text
        assert "No execution was started" in text
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
    command = voiceover.mux_command("ffmpeg", "/v/take.webm", voiceover.placements(voice, beats), "/v/take.mp4",
                                    voiceover.ending(beats))
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
    # Explain left at 70.0: the MP4 stops a second later, not when the recorder closed
    assert command[command.index("-t") + 1] == "74.020"


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


def test_dry_mux_without_a_take_places_clips_at_the_planned_starts(tmp_path: Path, capsys) -> None:
    assert voiceover.main(["voice", "--out", str(tmp_path), "--dry-run"]) == 0
    capsys.readouterr()
    assert voiceover.main(["mux", "--dry-run", "--video", "v.webm", "--voice", str(tmp_path / "voice.json"),
                           "--out", "t.mp4"]) == 0
    graph = capsys.readouterr().out
    assert "[1:a]adelay=3000:all=1[a1]" in graph and "[7:a]adelay=238000:all=1[a7]" in graph
    assert "-t 279.000" in graph  # card 3 s + 4:35 + 1 s: inside the 4:40 limit


def test_subtitles_follow_the_voice_as_placed_in_the_mp4() -> None:
    voice, beats = _docs({b: 10.0 * i for i, b in enumerate(BEATS)})
    for clip in voice["clips"]:
        clip["text"] = f"line {clip['beat']}"
    cues = voiceover.subtitles(voice, voiceover.placements(voice, beats)).split("\n\n")
    assert cues[0] == "1\n00:00:03,020 --> 00:00:08,020\nline State"
    assert cues[6].startswith("7\n00:01:03,020 --> 00:01:08,020\nline Explain")


def test_the_fresh_run_request_is_one_the_api_accepts() -> None:
    from app.finance.schemas import RunRequest
    from app.jobs.runner import family_of

    spec = (ROOT / "e2e" / "narrated-take.spec.ts").read_text(encoding="utf-8")
    scenario = json.loads(re.search(r"^const SCENARIO = (\{.*\})$", spec, re.MULTILINE)[1])
    rounds = int(re.search(r"^const ROUNDS = (\d+)$", spec, re.MULTILINE)[1])
    request = RunRequest.model_validate({"snapshot_id": "demo-world", "scenario": scenario,
                                         "rounds": rounds})
    assert family_of(request.scenario.model_dump(mode="json")).scripted


def _take(url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "LEDGERWORLD_DEMO_TOKEN": "placeholder-not-a-token"}
    return subprocess.run(["bash", str(ROOT / "scripts" / "narrated_take.sh"), url], env=env,
                          capture_output=True, text=True, timeout=120, check=False)


def test_the_token_never_rides_plain_http_to_another_machine() -> None:
    done = _take("http://demo.example.test")
    assert done.returncode == 2 and "must be https" in done.stderr
    # this machine's own app is allowed: the take goes on to the pre-flight, which finds nothing
    done = _take("http://127.0.0.1:9")
    assert "must be https" not in done.stderr and "no GO" in done.stderr
    assert "placeholder-not-a-token" not in done.stdout + done.stderr


def test_a_dropped_tts_connection_is_tried_again(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import sys
    import types

    calls = []

    class Communicate:
        def __init__(self, text: str, voice: str, rate: str) -> None:
            calls.append(rate)

        async def save(self, path: str) -> None:
            if len(calls) < 3:
                raise ConnectionResetError("Cannot write to closing transport")
            Path(path).write_bytes(b"mp3")

    fake = types.ModuleType("edge_tts")
    fake.Communicate = Communicate
    fake.exceptions = types.SimpleNamespace(EdgeTTSException=RuntimeError)
    monkeypatch.setitem(sys.modules, "edge_tts", fake)
    asyncio.run(voiceover._speak("line", tmp_path / "c.mp3", 5, pause_s=0))
    assert calls == ["+5%"] * 3 and (tmp_path / "c.mp3").read_bytes() == b"mp3"
    calls.clear()
    # two drops in a row with two tries: the last one is raised
    with pytest.raises(ConnectionResetError):
        asyncio.run(voiceover._speak("line", tmp_path / "d.mp3", 0, tries=2, pause_s=0))

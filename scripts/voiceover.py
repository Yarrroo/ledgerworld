"""Voice the seven beats of docs/video-script.md and mux them into the narrated machine take.

    uv run --with edge-tts==7.3.1 --with imageio-ffmpeg==0.7.0 \\
        python scripts/voiceover.py voice --out DIR          one clip per beat + DIR/voice.json
    uv run python scripts/voiceover.py voice --out DIR --dry-run   estimate the fit; no network
    uv run python scripts/voiceover.py label [--operator]  the opening card, as JSON on stdout
    uv run --with imageio-ffmpeg==0.7.0 python scripts/voiceover.py mux \\
        --video WEBM --voice VOICE --beats BEATS --out MP4   [--dry-run: print the command only]
    uv run python scripts/voiceover.py summary --voice VOICE --beats BEATS

The Voice lines, beats and windows are scripts/walkthrough_plan.py's (the first paragraph of each
**Voice:**); this file reads them, it does not restate them. A clip longer than its beat's window
is voiced again faster, up to MAX_RATE; past that the beat fails rather than spill into the next.
The voice is synthetic and the opening card says so. Exit 1 on any failure, 2 on bad usage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from walkthrough_plan import build

VOICE = "en-US-AriaNeural"
ENGINE = "Microsoft Edge neural text-to-speech, through edge-tts"
CARD_S = 3
MAX_RATE = 40  # percent faster than the voice's own pace; beyond it speech stops being clear
MARGIN_S = 0.4  # silence kept between a clip's end and its beat's end
WPS = 2.3  # edge-tts words per second at +0%, its trailing pause included (measured, 2026-10-29)


def lines(script: Path = ROOT / "docs" / "video-script.md") -> list[dict]:
    """Each beat with its window and the line spoken over it."""
    return [{"beat": b["beat"], "start": b["start"], "end": b["end"], "text": b["subtitle"]}
            for b in build(script.read_text(encoding="utf-8"))]


def rate_for(seconds: float, window: float) -> int | None:
    """The smallest rate (percent) at which `seconds` of speech at +0% fits `window`, or None."""
    room = window - MARGIN_S
    if seconds <= room:
        return 0
    need = math.ceil((seconds / room - 1) * 100)
    return need if need <= MAX_RATE else None


def estimate(text: str) -> float:
    return len(text.split()) / WPS


def parse_duration(ffmpeg_stderr: str) -> float:
    found = re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", ffmpeg_stderr)
    if not found:
        raise ValueError("ffmpeg reported no duration")
    return int(found[1]) * 3600 + int(found[2]) * 60 + float(found[3])


def ffmpeg() -> str:
    import imageio_ffmpeg  # fetched by `uv run --with`, never a project dependency

    return imageio_ffmpeg.get_ffmpeg_exe()


def media_seconds(path: Path) -> float:
    done = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], check=False, capture_output=True,
                          text=True)
    return parse_duration(done.stderr)


def label(operator: bool) -> dict:
    """The opening card: what made this video, before any of it plays."""
    action = ("Operator actions (a fresh fork, an approval request, an actor interview) were sent "
              "off-screen with the demo token; no execution was started for this take."
              if operator else
              "No operator action was sent: this take is read-only, and the fork, approval and "
              "interview beats say so where they would happen.")
    return {"seconds": CARD_S, "title": "LedgerWorld — machine take",
            "lines": [f"Narrated by a synthetic voice, not a person ({ENGINE}, voice {VOICE}).",
                      ("Recorded by a script driving the live demo in real time. "
                       "All treasury data is synthetic; the provider mode is shown on screen."),
                      action]}


async def _speak(text: str, path: Path, rate: int) -> None:
    import edge_tts  # fetched by `uv run --with`, never a project dependency

    await edge_tts.Communicate(text, VOICE, rate=f"+{rate}%").save(str(path))


def voice(out: Path, dry: bool) -> int:
    out.mkdir(parents=True, exist_ok=True)
    clips, failed = [], []
    for n, line in enumerate(lines(), 1):
        window, path = line["end"] - line["start"], out / f"{n:02d}-{line['beat']}.mp3"
        if dry:
            rate, seconds = rate_for(estimate(line["text"]), window), None
        else:
            rate, seconds = 0, 0.0
            while True:
                asyncio.run(_speak(line["text"], path, rate))
                seconds = media_seconds(path)
                if seconds <= window - MARGIN_S:
                    break
                faster = rate_for(seconds * (100 + rate) / 100, window)
                rate = None if faster is None else max(faster, rate + 5)
                if rate is None or rate > MAX_RATE:
                    rate = None
                    break
        if rate is None:
            failed.append(line["beat"])
        clips.append({**line, "window": window, "rate": rate, "seconds": seconds,
                      "file": str(path)})
        shown = "estimated" if dry else f"{seconds:5.1f}s"
        print(f"{line['beat']:<8} window {window:>3}s  rate "
              f"{'-' if rate is None else f'+{rate}%':>5}  {shown}", file=sys.stderr)
    (out / "voice.json").write_text(json.dumps({"voice": VOICE, "clips": clips}, indent=2) + "\n",
                                    encoding="utf-8")
    if failed:
        print(f"voiceover: {', '.join(failed)} cannot fit its window at +{MAX_RATE}%",
              file=sys.stderr)
        return 1
    return 0


def placements(voice_doc: dict, beats_doc: dict) -> list[tuple[str, float]]:
    """(clip file, seconds into the video): each clip at its beat's actual start, after the card."""
    began = {b["beat"]: b["began"] for b in beats_doc["beats"]}
    missing = [c["beat"] for c in voice_doc["clips"] if c["beat"] not in began]
    if missing:
        raise ValueError(f"the take has no record of {', '.join(missing)}")
    return [(c["file"], beats_doc["offset"] + began[c["beat"]]) for c in voice_doc["clips"]]


def mux_command(exe: str, video: str, clips: list[tuple[str, float]], out: str) -> list[str]:
    """The video as recorded, each clip delayed to its place, padded with silence to the end."""
    command = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", video]
    chains = []
    for i, (path, at) in enumerate(clips, 1):
        command += ["-i", path]
        chains.append(f"[{i}:a]adelay={round(at * 1000)}:all=1[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(1, len(clips) + 1))
    chains.append(f"{mix}amix=inputs={len(clips)}:duration=longest:normalize=0,apad[voice]")
    return command + ["-filter_complex", ";".join(chains), "-map", "0:v", "-map", "[voice]",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                      "-r", "25", "-c:a", "aac", "-b:a", "128k", "-shortest",
                      "-movflags", "+faststart", out]


def mux(video: Path, voice_path: Path, beats: Path, out: Path, dry: bool) -> int:
    voice_doc = json.loads(voice_path.read_text(encoding="utf-8"))
    beats_doc = json.loads(beats.read_text(encoding="utf-8"))
    try:
        command = mux_command("ffmpeg" if dry else ffmpeg(), str(video),
                              placements(voice_doc, beats_doc), str(out))
    except ValueError as error:
        print(f"voiceover: {error}", file=sys.stderr)
        return 1
    if dry:
        print(" ".join(command))
        return 0
    done = subprocess.run(command, check=False, capture_output=True, text=True)
    if done.returncode or not out.exists():
        print(f"voiceover: ffmpeg failed: {done.stderr.strip()[-400:]}", file=sys.stderr)
        return 1
    return 0


def mmss(seconds: float | None) -> str:
    if seconds is None:
        return "  -  "
    tenths = round(seconds * 10)
    return f"{tenths // 600}:{tenths % 600 / 10:04.1f}"


def summary(voice_doc: dict, beats_doc: dict) -> str:
    """Per beat: planned window, actual start, ready and end, the voice's end, and what was sent."""
    done = {b["beat"]: b for b in beats_doc["beats"]}
    rows = ["beat     planned        began    ready    left     voice to  reached  sent"]
    for clip in voice_doc["clips"]:
        b = done.get(clip["beat"])
        spoken = b["began"] + clip["seconds"] if b and clip["seconds"] else None
        overrun = " OVERRUN" if b and spoken and spoken > b["left"] else ""
        sent = "; ".join(f"{a['method']} {a['path']} {a['status']}" for a in b["actions"]) if b else ""
        rows.append(" ".join([
            clip["beat"].ljust(8), f"{mmss(clip['start'])}-{mmss(clip['end'])}".ljust(14),
            mmss(b and b["began"]).ljust(8), mmss(b and b["ready"]).ljust(8),
            mmss(b and b["left"]).ljust(8), (mmss(spoken) + overrun).ljust(9),
            ("yes" if b and b["reached"] else "NO" if b else "not run").ljust(8), sent or "-"]))
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("voice")
    v.add_argument("--out", type=Path, required=True)
    v.add_argument("--dry-run", action="store_true")
    lab = verbs.add_parser("label")
    lab.add_argument("--operator", action="store_true", help="operator actions will be sent")
    m = verbs.add_parser("mux")
    for name in ("video", "voice", "beats", "out"):
        m.add_argument(f"--{name}", type=Path, required=True)
    m.add_argument("--dry-run", action="store_true")
    s = verbs.add_parser("summary")
    s.add_argument("--voice", type=Path, required=True)
    s.add_argument("--beats", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.verb == "voice":
            return voice(args.out, args.dry_run)
        if args.verb == "label":
            print(json.dumps(label(args.operator), indent=2))
            return 0
        if args.verb == "mux":
            return mux(args.video, args.voice, args.beats, args.out, args.dry_run)
        print(summary(json.loads(args.voice.read_text(encoding="utf-8")),
                      json.loads(args.beats.read_text(encoding="utf-8"))))
        return 0
    except (OSError, UnicodeError, ValueError, KeyError) as error:
        print(f"voiceover: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

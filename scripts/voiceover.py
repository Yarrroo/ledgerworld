"""Voice the seven beats of docs/video-script.md and mux them into the narrated machine take.

    uv run --with edge-tts==7.3.1 --with imageio-ffmpeg==0.7.0 \\
        python scripts/voiceover.py voice --out DIR          one clip per beat + DIR/voice.json
    uv run python scripts/voiceover.py voice --out DIR --dry-run   estimate the fit; no network
    uv run python scripts/voiceover.py label [--operator]  the opening card, as JSON on stdout
    uv run --with imageio-ffmpeg==0.7.0 python scripts/voiceover.py mux \\
        --video WEBM --voice VOICE --beats BEATS --out MP4   the MP4 and its .srt beside it
        (--dry-run: print the command only; without --beats: the planned starts)
    uv run python scripts/voiceover.py summary --voice VOICE --beats BEATS
    uv run --with imageio-ffmpeg==0.7.0 python scripts/voiceover.py gate \
        --voice VOICE --beats BEATS --video MP4 [--keep DIR]   fail a take past 4:40 or a
        beat 2 s late; --keep copies the MP4, SRT and beats.json into DIR, under a name that says
        `not-held` when the gate failed (--dry-run: the plan itself, without a take)

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
import shutil
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
TAIL_S = 1.0  # the MP4 ends this long after the last beat or line, never at the recorder's close
WPS = 2.3  # edge-tts words per second at +0%, its trailing pause included (measured, 2026-10-29)
MAX_TAKE_S = 280  # 4:40, the script's target; the event allows five minutes
MAX_LATE_S = 2.0  # how long after its planned end a beat may leave its screen


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


def next_rate(rate: int, seconds: float, window: float) -> int | None:
    """The rate to voice again at after `seconds` at `rate` ran long: at least 5 points faster,
    never past MAX_RATE; None once MAX_RATE itself ran long."""
    faster = rate_for(seconds * (100 + rate) / 100, window)
    if faster is None or rate >= MAX_RATE:
        return None
    return min(max(faster, rate + 5), MAX_RATE)


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
              "off-screen with the demo token; each answer, a refusal included, is shown where it "
              "happens. No execution was started for this take."
              if operator else
              "No operator action was sent: this take is read-only, and the fork, approval and "
              "interview beats say so where they would happen.")
    return {"seconds": CARD_S, "title": "LedgerWorld — machine take",
            "lines": [f"Narrated by a synthetic voice, not a person ({ENGINE}, voice {VOICE}).",
                      ("Recorded by a script driving the live demo in real time. "
                       "All treasury data is synthetic; the provider mode is shown on screen."),
                      action]}


async def _speak(text: str, path: Path, rate: int, tries: int = 3, pause_s: float = 2.0) -> None:
    """One clip; the service drops a connection now and then, so a failed call is tried again."""
    import edge_tts  # fetched by `uv run --with`, never a project dependency

    for attempt in range(1, tries + 1):
        try:
            await edge_tts.Communicate(text, VOICE, rate=f"+{rate}%").save(str(path))
            return
        except Exception:  # aiohttp's disconnects are not OSError; the last try's error is raised
            if attempt == tries:
                raise
            await asyncio.sleep(pause_s * attempt)


def voice(out: Path, dry: bool) -> int:
    out.mkdir(parents=True, exist_ok=True)
    clips, failed = [], []
    for n, line in enumerate(lines(), 1):
        window, path = line["end"] - line["start"], out / f"{n:02d}-{line['beat']}.mp3"
        if dry:
            rate, seconds = rate_for(estimate(line["text"]), window), None
        else:
            rate = 0
            while True:
                asyncio.run(_speak(line["text"], path, rate))
                seconds = media_seconds(path)
                if seconds <= window - MARGIN_S:
                    break
                rate = next_rate(rate, seconds, window)
                if rate is None:
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


def ending(voice_doc: dict, beats_doc: dict) -> float:
    """Where the MP4 stops: TAIL_S after the last beat left its screen or its line was spoken,
    whichever is later; a late beat never has its line cut off."""
    last = beats_doc["beats"][-1]
    spoken = last["began"] + (voice_doc["clips"][-1]["seconds"] or 0)
    return beats_doc["offset"] + max(last["left"], spoken) + TAIL_S


def mux_command(exe: str, video: str, clips: list[tuple[str, float]], out: str,
                end: float) -> list[str]:
    """The video as recorded, its last frame held, each clip delayed to its place over silence;
    both cut at `end`, so a line that outlasts the recording is still heard to its end."""
    command = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", video]
    chains = []
    for i, (path, at) in enumerate(clips, 1):
        command += ["-i", path]
        chains.append(f"[{i}:a]adelay={round(at * 1000)}:all=1[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(1, len(clips) + 1))
    chains.append(f"{mix}amix=inputs={len(clips)}:duration=longest:normalize=0,apad[voice]")
    chains.append(f"[0:v]tpad=stop_mode=clone:stop_duration={math.ceil(end)}[video]")
    return command + ["-filter_complex", ";".join(chains), "-map", "[video]", "-map", "[voice]",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                      "-r", "25", "-c:a", "aac", "-b:a", "128k", "-t", f"{end:.3f}",
                      "-movflags", "+faststart", out]


def planned(voice_doc: dict) -> dict:
    """A take that kept to plan: each beat began at its planned start, after the card."""
    return {"offset": CARD_S, "beats": [{"beat": c["beat"], "began": c["start"], "left": c["end"]}
                                        for c in voice_doc["clips"]]}


def srt_clock(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def subtitles(voice_doc: dict, clips: list[tuple[str, float]]) -> str:
    """Each Voice line from where its clip plays in the MP4 to where it ends."""
    return "\n".join(f"{n}\n{srt_clock(at)} --> {srt_clock(at + (c['seconds'] or 0))}\n{c['text']}\n"
                     for n, (c, (_, at)) in enumerate(zip(voice_doc["clips"], clips, strict=True), 1))


def mux(video: Path, voice_path: Path, beats: Path | None, out: Path, dry: bool) -> int:
    voice_doc = json.loads(voice_path.read_text(encoding="utf-8"))
    beats_doc = json.loads(beats.read_text(encoding="utf-8")) if beats else planned(voice_doc)
    try:
        clips = placements(voice_doc, beats_doc)
        command = mux_command("ffmpeg" if dry else ffmpeg(), str(video), clips, str(out),
                              ending(voice_doc, beats_doc))
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
    out.with_suffix(".srt").write_text(subtitles(voice_doc, clips), encoding="utf-8")
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


def gate(voice_doc: dict, beats_doc: dict, seconds: float) -> list[str]:
    """What keeps a take from upload: an MP4 of `seconds` past MAX_TAKE_S, a beat that left its
    screen more than MAX_LATE_S after its planned end, a beat that never ran. Empty when it may go."""
    problems = [f"the MP4 runs {mmss(seconds)}, past {mmss(MAX_TAKE_S)}"] if seconds > MAX_TAKE_S else []
    done = {b["beat"]: b for b in beats_doc["beats"]}
    for clip in voice_doc["clips"]:
        b = done.get(clip["beat"])
        if b is None:
            problems.append(f"{clip['beat']} did not run")
        elif b["left"] - clip["end"] > MAX_LATE_S:
            problems.append(f"{clip['beat']} left at {mmss(b['left'])}, {b['left'] - clip['end']:.1f} s "
                            f"after its planned {mmss(clip['end'])}")
    return problems


def keep(take: Path, beats: Path, into: Path, held: bool) -> list[Path]:
    """Copy the MP4, its SRT and beats.json into `into`. A take that failed the gate keeps a name
    that says so, never the name an upload would use."""
    stem = take.stem if held else f"{take.stem}.not-held"
    kept = []
    for source, name in ((take, f"{stem}.mp4"), (take.with_suffix(".srt"), f"{stem}.srt"),
                         (beats, beats.name)):
        if source.is_file():
            shutil.copy2(source, into / name)
            kept.append(into / name)
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("voice")
    v.add_argument("--out", type=Path, required=True)
    v.add_argument("--dry-run", action="store_true")
    lab = verbs.add_parser("label")
    lab.add_argument("--operator", action="store_true", help="operator actions will be sent")
    m = verbs.add_parser("mux")
    for name in ("video", "voice", "out"):
        m.add_argument(f"--{name}", type=Path, required=True)
    m.add_argument("--beats", type=Path, help="the take's beats.json; omitted, the planned starts")
    m.add_argument("--dry-run", action="store_true")
    s = verbs.add_parser("summary")
    s.add_argument("--voice", type=Path, required=True)
    s.add_argument("--beats", type=Path, required=True)
    g = verbs.add_parser("gate")
    g.add_argument("--voice", type=Path, required=True)
    g.add_argument("--beats", type=Path, help="the take's beats.json; omitted, the planned starts")
    g.add_argument("--video", type=Path, help="the MP4 whose length is checked")
    g.add_argument("--dry-run", action="store_true", help="check the length the plan would give")
    g.add_argument("--keep", type=Path, help="copy the MP4, SRT and beats.json into this directory")
    args = parser.parse_args(argv)
    if args.verb == "gate" and not (args.video or args.dry_run):
        parser.error("gate needs --video MP4 or --dry-run")
    if args.verb == "gate" and args.keep and not (args.video and args.beats):
        parser.error("gate --keep needs the take: --video MP4 and --beats BEATS")
    try:
        if args.verb == "voice":
            return voice(args.out, args.dry_run)
        if args.verb == "label":
            print(json.dumps(label(args.operator), indent=2))
            return 0
        if args.verb == "mux":
            return mux(args.video, args.voice, args.beats, args.out, args.dry_run)
        if args.verb == "gate":
            voice_doc = json.loads(args.voice.read_text(encoding="utf-8"))
            beats_doc = json.loads(args.beats.read_text(encoding="utf-8")) if args.beats else planned(voice_doc)
            seconds = ending(voice_doc, beats_doc) if args.dry_run else media_seconds(args.video)
            problems = gate(voice_doc, beats_doc, seconds)
            for problem in problems:
                print(f"voiceover: {problem}", file=sys.stderr)
            print(f"gate: {mmss(seconds)} long, {'held' if not problems else 'NOT held'} "
                  f"(limit {mmss(MAX_TAKE_S)}, a beat at most {MAX_LATE_S:.0f} s late)", file=sys.stderr)
            if args.keep:
                for path in keep(args.video, args.beats, args.keep, not problems):
                    print(f"kept: {path}", file=sys.stderr)
            return 1 if problems else 0
        print(summary(json.loads(args.voice.read_text(encoding="utf-8")),
                      json.loads(args.beats.read_text(encoding="utf-8"))))
        return 0
    except (OSError, UnicodeError, ValueError, KeyError) as error:
        print(f"voiceover: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

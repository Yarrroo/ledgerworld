"""Vet the walkthrough video URL, write it into the Links section, and probe the three links.

Usage:
  python checks/submission_links.py --video URL            vet one video URL, change nothing
  python checks/submission_links.py --video URL --apply    vet it, then rewrite only `- Video:`
  python checks/submission_links.py --probe                GET Repository, Demo, Demo health, Video

`--file` names the submission document (default docs/submission.md); the Links section is read
the way checks/submission.py reads it. A video passes vetting when it is https on an allowed host
(YouTube, Vimeo, Loom, Google Drive), names a published video rather than an editor or draft page,
answers its host's public oEmbed (a private or deleted video does not), and is under 5:00 where the
host exposes a duration. Where it does not, the line says "duration unknown"; it never guesses.

Every request is an anonymous GET with no credential. Exit 0 when everything passes, 1 when the
video fails vetting or any probed link is dead, 2 on bad usage. Stdlib only. This checks a URL that
someone supplies; it never supplies one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checks.submission import ROOT, https_url, outside_fences, section

TIMEOUT_S = 15
USER_AGENT = "ledgerworld-submission-links/1"
LIMIT_S = 300
LABELS = ("Repository", "Demo", "Video")
VIDEO_LINE = re.compile(r"^- Video:[^\r\n]*", re.MULTILINE)

# fetch(url) -> (HTTP status, body text); raises OSError when no answer came.
Fetch = Callable[[str], tuple[int, str]]


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, ValueError) as exc:
        raise OSError(str(exc)) from exc


def host_of(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.").removeprefix("m.")


def video_kind(url: str) -> str | None:
    """The host family of a published-video URL, or None for anything else."""
    parts = urllib.parse.urlsplit(url)
    host, path = host_of(url), parts.path
    query = urllib.parse.parse_qs(parts.query)
    if host == "youtube.com":
        if path == "/watch" and re.fullmatch(r"[\w-]{11}", (query.get("v") or [""])[0]):
            return "youtube"
        return "youtube" if re.fullmatch(r"/(?:shorts|embed|live)/[\w-]{11}/?", path) else None
    if host == "youtu.be":
        return "youtube" if re.fullmatch(r"/[\w-]{11}/?", path) else None
    if host in ("vimeo.com", "player.vimeo.com"):
        return "vimeo" if re.fullmatch(r"(?:/video)?/\d+(?:/[0-9a-f]+)?/?", path) else None
    if host == "loom.com":
        return "loom" if re.fullmatch(r"/(?:share|embed)/[0-9a-f]{32}/?", path) else None
    if host == "drive.google.com":
        return "drive" if re.fullmatch(r"/file/d/[\w-]{20,}/(?:view|preview)/?", path) else None
    return None


def oembed_url(kind: str, url: str) -> str | None:
    quoted = urllib.parse.quote(url, safe="")
    return {
        "youtube": f"https://www.youtube.com/oembed?format=json&url={quoted}",
        "vimeo": f"https://vimeo.com/api/oembed.json?url={quoted}",
        "loom": f"https://www.loom.com/v1/oembed?url={quoted}",
    }.get(kind)


def watch_url(url: str) -> str:
    """The YouTube watch page for any YouTube video URL form; its metadata carries the length."""
    parts = urllib.parse.urlsplit(url)
    video = urllib.parse.parse_qs(parts.query).get("v") or [parts.path.rstrip("/").rsplit("/", 1)[-1]]
    return f"https://www.youtube.com/watch?v={video[0]}"


def iso_seconds(value: str) -> int | None:
    found = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not found or not any(found.groups()):
        return None
    hours, minutes, seconds = (int(part or 0) for part in found.groups())
    return hours * 3600 + minutes * 60 + seconds


def page_seconds(html: str) -> int | None:
    """A duration a page states about itself, or None; never an estimate."""
    found = re.search(r'itemprop="duration"\s+content="(PT[^"]+)"', html)
    if found:
        return iso_seconds(found[1])
    # Only the player's own videoDetails: recommendations carry lengthSeconds of other videos.
    found = re.search(r'"videoDetails"\s*:\s*\{[^{}]*?"lengthSeconds"\s*:\s*"(\d+)"', html)
    if found:
        return int(found[1])
    found = re.search(r'property="(?:og:)?video:duration"\s+content="(\d+)"', html)
    return int(found[1]) if found else None


def clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def vet_video(url: str, get: Fetch = fetch) -> tuple[bool, str]:
    """(passes, one-line reason). Form first, then the host's public view of the video."""
    if not https_url(url):
        return False, "not an https URL a judge can open"
    kind = video_kind(url)
    if kind is None:
        host = host_of(url)
        if host in ("studio.youtube.com", "loom.com", "youtube.com", "youtu.be", "vimeo.com",
                    "player.vimeo.com", "drive.google.com"):
            return False, f"{host}: not a published video link (an editor, draft or folder page?)"
        return False, f"{host or 'no host'}: not an allowed video host (YouTube, Vimeo, Loom, Google Drive)"
    seconds = None
    endpoint = oembed_url(kind, url)
    try:
        if endpoint:
            status, body = get(endpoint)
            if status in (401, 403):
                return False, f"{kind}: private or unlisted-with-embedding-off (oEmbed HTTP {status})"
            if status != 200:
                return False, f"{kind}: not publicly available (oEmbed HTTP {status})"
            try:
                data = json.loads(body)
            except ValueError:
                return False, f"{kind}: oEmbed answer is not JSON"
            if isinstance(data, dict) and isinstance(data.get("duration"), (int, float)):
                seconds = int(data["duration"])
        page = watch_url(url) if kind == "youtube" else url
        if seconds is None:
            status, body = get(page)
            if status != 200:
                return False, f"{kind}: video page answers HTTP {status}"
            if kind == "drive" and re.search(r"accounts\.google\.com/(?:ServiceLogin|v3/signin)", body):
                return False, "drive: asks for a sign-in, so the file is not shared publicly"
            seconds = page_seconds(body)
    except OSError as exc:
        return False, f"{kind}: no answer ({exc})"
    if seconds is None:
        return True, f"{kind}: public, duration unknown"
    if seconds >= LIMIT_S:
        return False, f"{kind}: {clock(seconds)} is at or over the 5:00 limit"
    return True, f"{kind}: public, {clock(seconds)}"


def read_links(text: str) -> dict[str, str]:
    links = section(text, "Links")
    found = {}
    for label in LABELS:
        line = re.search(rf"^- {label}: (\S+)\s*$", links, re.MULTILINE)
        found[label] = line[1] if line else ""
    return found


def probe_one(url: str, get: Fetch) -> tuple[bool, str]:
    if not https_url(url):
        return False, "not an https URL"
    try:
        status, _ = get(url)
    except OSError as exc:
        return False, f"no answer ({exc})"
    return 200 <= status < 300, f"HTTP {status}"


def probe(text: str, get: Fetch = fetch) -> list[tuple[str, str, bool, str]]:
    """One (label, url, alive, detail) per link: Repository, Demo, Demo health, Video."""
    links = read_links(text)
    demo = links["Demo"].rstrip("/")
    rows = [("Repository", links["Repository"], *probe_one(links["Repository"], get)),
            ("Demo", links["Demo"], *probe_one(links["Demo"], get)),
            ("Demo health", f"{demo}/api/v1/health" if demo else "",
             *probe_one(f"{demo}/api/v1/health" if demo else "", get))]
    video = links["Video"]
    rows.append(("Video", video, *(vet_video(video, get) if video else (False, "no URL"))))
    return rows


def apply_video(path: Path, url: str) -> None:
    """Rewrite only the `- Video:` line of the Links section; every other byte stays."""
    raw = path.read_bytes().decode("utf-8")
    links = re.search(r"^## Links[ \t]*\n(.*?)(?=^## |^# |\Z)", outside_fences(raw), re.MULTILINE | re.DOTALL)
    line = VIDEO_LINE.search(raw, links.start(1), links.end(1)) if links else None
    if line is None:
        raise ValueError(f"{path}: no '- Video:' line in a ## Links section")
    begin, end = line.span()
    path.write_bytes((raw[:begin] + f"- Video: {url}" + raw[end:]).encode("utf-8"))


def main(argv: list[str] | None = None, get: Fetch = fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", help="the walkthrough video URL to vet")
    parser.add_argument("--apply", action="store_true", help="write a vetted --video into --file")
    parser.add_argument("--probe", action="store_true", help="GET the three submission links")
    parser.add_argument("--file", type=Path, default=ROOT / "docs/submission.md")
    args = parser.parse_args(argv)
    if not (args.video or args.probe) or (args.apply and not args.video):
        parser.print_usage(sys.stderr)
        print("submission_links: give --video URL [--apply], --probe, or both", file=sys.stderr)
        return 2
    failed = False
    if args.video:
        passes, reason = vet_video(args.video, get)
        print(f"{'ok' if passes else 'refused'}: Video {args.video} ({reason})")
        if not passes:
            return 1
        if args.apply:
            try:
                apply_video(args.file, args.video)
            except (OSError, ValueError) as exc:
                print(f"submission_links: {exc}", file=sys.stderr)
                return 1
            print(f"written: {args.file}")
    if args.probe:
        try:
            text = args.file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"submission_links: {exc}", file=sys.stderr)
            return 1
        for label, url, alive, detail in probe(text, get):
            print(f"{'ok' if alive else 'dead'}: {label} {url or '-'} ({detail})")
            failed |= not alive
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The narrated take's clock and gate, offline: a stalled beat shortens itself and never the next.

e2e/clock.js is driven by node on a virtual clock (no browser, no waiting): each scenario replays
the seven planned beats with a stall where the first take's machine had one, and the result goes
through scripts/voiceover.py's gate, the same check scripts/narrated_take.sh runs on a real take.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("voiceover", ROOT / "scripts" / "voiceover.py")
voiceover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voiceover)

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# A virtual clock: sleep() queues a timer, and time jumps to the earliest one whenever every
# promise has settled. `naive` replays the hold the first take used, which awaited each scroll.
DRIVER = r"""
const { Clock, hold, runBeats } = require(process.argv[1])
const { beats, naive } = JSON.parse(process.argv[2])
let t = 0
const timers = []
const sleep = (ms) => new Promise((resolve) => timers.push({ at: t + Math.max(0, ms), resolve }))
const clock = new Clock(() => t, sleep)

async function play (beat) {
  const record = { beat: beat.beat, began: clock.now() }
  // the screen load: a goto whose timeout is the beat's budget
  if (beat.load_stall) await clock.within(sleep(beat.load_stall * 1000), 30_000)
  let stalled = false
  const step = async () => {
    if (beat.hold_stall && !stalled && clock.now() >= beat.stall_at) {
      stalled = true
      await sleep(beat.hold_stall * 1000)
    }
  }
  if (naive) {
    const steps = Math.max(1, Math.ceil(beat.end - clock.now()))
    for (let i = 1; i <= steps && clock.now() < beat.end; i++) {
      await step()
      await sleep(Math.max(0, Math.min(1000, (beat.end - clock.now()) * 1000)))
    }
  } else {
    await hold(clock, beat.end, step)
  }
  return record
}

async function main () {
  const records = []
  clock.start()
  let finished = false
  const take = runBeats(clock, beats, play, (r) => records.push(r)).then(() => { finished = true })
  while (!finished) {
    await new Promise((resolve) => setImmediate(resolve))
    if (finished) break
    if (!timers.length) throw new Error('nothing left to wait for')
    timers.sort((a, b) => a.at - b.at)
    const next = timers.shift()
    t = Math.max(t, next.at)
    next.resolve()
  }
  await take
  process.stdout.write(JSON.stringify(records))
}
main().catch((error) => { console.error(error); process.exit(1) })
"""


def take(stalls: dict[str, dict], naive: bool = False) -> list[dict]:
    """The planned beats, played on the virtual clock with `stalls` by beat name."""
    beats = [{"beat": line["beat"], "start": line["start"], "end": line["end"], **stalls.get(line["beat"], {})}
             for line in voiceover.lines()]
    done = subprocess.run([NODE, "-e", DRIVER, str(ROOT / "e2e" / "clock.js"),
                           json.dumps({"beats": beats, "naive": naive})],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def gate(records: list[dict], seconds: float = 279.0) -> list[str]:
    voice = {"clips": [{**line, "seconds": 1.0} for line in voiceover.lines()]}
    return voiceover.gate(voice, {"offset": 3.0, "beats": records}, seconds)


# the first take's stall: a scroll in Execute's hold stopped answering for 36 s just before the
# beat's end (planned 3:55; it left at 4:31.4)
EXECUTE_STALL = {"Execute": {"hold_stall": 36, "stall_at": 234}}


@needs_node
def test_a_take_without_stalls_keeps_every_beat_to_plan() -> None:
    records = take({})
    plan = {line["beat"]: line for line in voiceover.lines()}
    assert [r["beat"] for r in records] == list(plan)
    for r in records:
        assert r["began"] == pytest.approx(plan[r["beat"]]["start"])
        assert r["left"] == pytest.approx(plan[r["beat"]]["end"])
    assert gate(records) == []


@needs_node
def test_the_first_takes_36_s_stall_without_deadlines_pushes_explain_late() -> None:
    # the control: the hold #136 recorded with reproduces its overrun
    records = {r["beat"]: r for r in take(EXECUTE_STALL, naive=True)}
    assert records["Execute"]["left"] == pytest.approx(234 + 36, abs=1)
    assert records["Explain"]["began"] == records["Execute"]["left"]
    assert any(p.startswith("Execute left at") for p in gate(list(records.values())))


@needs_node
def test_a_36_s_stall_in_a_hold_shortens_only_its_own_beat() -> None:
    records = take(EXECUTE_STALL)
    plan = {line["beat"]: line for line in voiceover.lines()}
    for r in records:
        assert r["began"] <= plan[r["beat"]]["start"] + voiceover.MAX_LATE_S, r
        assert r["left"] <= plan[r["beat"]]["end"] + voiceover.MAX_LATE_S, r
    by = {r["beat"]: r for r in records}
    assert by["Explain"]["began"] == pytest.approx(235)
    assert gate(records) == []


@needs_node
def test_a_36_s_screen_load_is_cut_at_its_beats_end() -> None:
    # Break has 25 s: a load that would take 36 s is cut there and Execute starts on time
    records = {r["beat"]: r for r in take({"Break": {"load_stall": 36}, "World": {"hold_stall": 36, "stall_at": 24}})}
    assert records["World"]["left"] == pytest.approx(25, abs=0.2)
    assert records["Break"]["left"] == pytest.approx(120, abs=0.2)
    assert records["Execute"]["began"] == pytest.approx(120, abs=0.2)
    assert gate(list(records.values())) == []


HOLD_DRIVER = r"""
const { Clock, hold } = require(process.argv[1])
let t = 0
const timers = []
const sleep = (ms) => new Promise((resolve) => timers.push({ at: t + Math.max(0, ms), resolve }))
const clock = new Clock(() => t, sleep)
async function main () {
  clock.start()
  clock.deadline = 95  // the beat ends far later than the hold
  let done = false
  // each scroll answers in 0.7 s; the one after 11 s stalls for 36 s
  const step = async () => { await sleep(clock.now() > 11 ? 36_000 : 700) }
  hold(clock, 12, step).then(() => { done = true })
  while (!done) {
    await new Promise((resolve) => setImmediate(resolve))
    if (done) break
    timers.sort((a, b) => a.at - b.at)
    const next = timers.shift()
    t = Math.max(t, next.at)
    next.resolve()
  }
  process.stdout.write(JSON.stringify(clock.now()))
}
main()
"""


@needs_node
def test_a_hold_short_of_its_beats_end_stops_at_its_own_end() -> None:
    # Fork holds 12 s on the prepared comparison before its operator writes: a stall there is cut
    # at the hold's end, not the beat's
    done = subprocess.run([NODE, "-e", HOLD_DRIVER, str(ROOT / "e2e" / "clock.js")],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == pytest.approx(12.0, abs=0.01)


def test_the_gate_holds_the_mp4_to_4_40() -> None:
    records = [{"beat": line["beat"], "left": line["end"]} for line in voiceover.lines()]
    assert gate(records, 279.0) == [] and gate(records, 280.0) == []
    # the first take's file: 4:49.04
    assert gate(records, 289.04) == ["the MP4 runs 4:49.0, past 4:40.0"]


def test_the_gate_fails_a_beat_more_than_2_s_late() -> None:
    records = [{"beat": line["beat"], "left": line["end"]} for line in voiceover.lines()]
    records[3]["left"] = 95 + 1.9  # Fork, 1.9 s late: held
    assert gate(records) == []
    records[5]["left"] = 271.4  # Execute, as the first take recorded it
    assert gate(records) == ["Execute left at 4:31.4, 36.4 s after its planned 3:55.0"]
    assert gate(records[:-1])[-1] == "Explain did not run"


def test_gate_cli_checks_the_plan_on_a_dry_run(tmp_path: Path) -> None:
    assert voiceover.main(["voice", "--out", str(tmp_path), "--dry-run"]) == 0
    assert voiceover.main(["gate", "--dry-run", "--voice", str(tmp_path / "voice.json")]) == 0
    beats = {"offset": 3.0, "beats": [{"beat": line["beat"], "began": line["start"], "left": line["end"]}
                                      for line in voiceover.lines()]}
    beats["beats"][5]["left"] = 240.0  # Execute 5 s late
    (tmp_path / "beats.json").write_text(json.dumps(beats), encoding="utf-8")
    assert voiceover.main(["gate", "--dry-run", "--voice", str(tmp_path / "voice.json"),
                           "--beats", str(tmp_path / "beats.json")]) == 1
    with pytest.raises(SystemExit):
        voiceover.main(["gate", "--voice", str(tmp_path / "voice.json")])  # neither --video nor --dry-run


def _take_files(tmp: Path) -> tuple[Path, Path]:
    take = tmp / "scratch" / "ledgerworld-narrated-take.mp4"
    take.parent.mkdir()
    take.write_bytes(b"mp4")
    take.with_suffix(".srt").write_text("1\n", encoding="utf-8")
    beats = take.parent / "beats.json"
    beats.write_text(json.dumps({"offset": 3.0, "beats": [
        {"beat": line["beat"], "began": line["start"], "left": line["end"]} for line in voiceover.lines()]}),
        encoding="utf-8")
    return take, beats


@pytest.mark.parametrize(("seconds", "names"), [
    (279.0, ["beats.json", "ledgerworld-narrated-take.mp4", "ledgerworld-narrated-take.srt"]),
    # a take past 4:40 is kept, never under the name an upload would use
    (289.04, ["beats.json", "ledgerworld-narrated-take.not-held.mp4", "ledgerworld-narrated-take.not-held.srt"]),
])
def test_gate_keeps_the_take_under_a_name_that_says_whether_it_held(tmp_path: Path, monkeypatch,
                                                                   seconds: float, names: list[str]) -> None:
    assert voiceover.main(["voice", "--out", str(tmp_path / "voice"), "--dry-run"]) == 0
    take, beats = _take_files(tmp_path)
    kept = tmp_path / "kept"
    kept.mkdir()
    monkeypatch.setattr(voiceover, "media_seconds", lambda path: seconds)
    status = voiceover.main(["gate", "--voice", str(tmp_path / "voice" / "voice.json"), "--beats", str(beats),
                             "--video", str(take), "--keep", str(kept)])
    assert status == (0 if seconds <= voiceover.MAX_TAKE_S else 1)
    assert sorted(p.name for p in kept.iterdir()) == names
    with pytest.raises(SystemExit):  # --keep needs the take itself
        voiceover.main(["gate", "--dry-run", "--voice", str(tmp_path / "voice" / "voice.json"), "--keep", str(kept)])


def test_the_spec_runs_its_beats_on_the_deadline_clock() -> None:
    spec = (ROOT / "e2e" / "narrated-take.spec.ts").read_text(encoding="utf-8")
    assert re.search(r"from '\./clock'", spec) and "runBeats(clock, BEATS" in spec
    # nothing in a beat waits on the browser's own clock, a fixed grace or a fixed timeout
    assert "waitForTimeout" not in spec and "GRACE_S" not in spec
    assert not re.search(r"timeout:\s*[\d_]+", spec)


def test_keep_needs_a_directory() -> None:
    for args in (["--keep"], ["https://demo.example.test", "--keep"], ["https://demo.example.test", "--keep", "--dry-run"]):
        done = subprocess.run(["bash", str(ROOT / "scripts" / "narrated_take.sh"), *args],
                              capture_output=True, text=True, timeout=30, check=False)
        assert done.returncode == 2 and "--keep DIR" in done.stderr


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(ROOT / "scripts" / "narrated_take.sh"), *args],
                          capture_output=True, text=True, timeout=30, check=False)


def test_keep_refuses_a_dry_run_and_a_directory_holding_another_take(tmp_path: Path) -> None:
    done = _run("--dry-run", "--keep", str(tmp_path / "new"))
    assert done.returncode == 2 and "dry run makes no take" in done.stderr
    assert not (tmp_path / "new").exists()
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "ledgerworld-narrated-take.mp4").write_bytes(b"an earlier take")
    done = _run("https://demo.example.test", "--keep", str(tmp_path / "used"))
    assert done.returncode == 2 and "is not empty" in done.stderr

# Narrated take, kept and on time — workflow

> Workflow (Medium depth: requirements and design folded in). Source: the board's steps for this
> item. Follows `prp/2026-10-29-narrated-take/report.md`. Next: implement → report.md → close-out.

**Goal.** The narrated take leaves a file that can be uploaded: every beat ends at its planned
time even when the machine is loaded, the MP4 stays under 4:40, and the MP4, its SRT and
`beats.json` outlive the run's scratch directory.

**Accept.** `uv run pytest -q tests/demo/test_narrated_take_timing.py tests/demo/test_narrated_take.py && bash scripts/narrated_take.sh --dry-run`
exits 0 offline.

## What went wrong in the first take

1. Execute's hold ran 36 s late (left 4:31 instead of 3:55): `hold()` awaited a page scroll with no
   bound, and a page that stalls under load stalls the await. Every later beat started late.
2. The MP4 lived only in the run's `mktemp` directory and went with it.

## Design

- `e2e/clock.js` (new, plain CommonJS so node drives it in tests): a `Clock` whose zero is the first
  beat, a per-beat `deadline` (the beat's planned end), `budget(ms)` = a timeout cut to the time
  left, `within(work, ms)` = an await cut at that budget, `hold()` and `runBeats()`. A beat never
  waits on anything unbounded, so a stall shortens the beat it hit. Fork's 20 s grace goes.
- The spec runs its beats through `runBeats`; navigation, screen checks, captions, scrolls and
  operator calls all take their timeouts from `budget`. The card wait and the prepared run's reads
  run side by side, so the reads no longer lengthen the MP4.
- `scripts/voiceover.py gate`: fails a take whose MP4 runs past 4:40 (`MAX_TAKE_S` 280) or whose
  beat left its screen more than 2 s after its planned end (`MAX_LATE_S`); `--dry-run` checks the
  plan itself.
- `scripts/narrated_take.sh --keep DIR`: copies the MP4, SRT and `beats.json` into DIR (also on a
  failed take, whatever exists), then runs the gate; the dry run runs the gate on the plan.

## Phases

| Phase | Files | Gate |
|---|---|---|
| 1 clock + spec | `e2e/clock.js`, `e2e/narrated-take.spec.ts` | spec lists under `--dry-run` |
| 2 gate + keep | `scripts/voiceover.py`, `scripts/narrated_take.sh` | dry run green |
| 3 tests | `tests/demo/test_narrated_take_timing.py` | accept line green; a 36 s stall holds |
| 4 take | Demo URL, load average below the core count, token if present | gate green |
| 5 report | `report.md` here | one screen, numbers from the run |

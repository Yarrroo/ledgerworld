# Narrated take, kept and on time — Close-out
> Close-out (/dev-close). Source: workflow.md. Date: 2026-10-29

## What shipped
- `e2e/clock.js` (new): the take's clock. Every beat ends at its planned end, counted from the
  take's start; `budget`, `within`, `hold` and `runBeats` cut every wait at that end.
- `e2e/narrated-take.spec.ts`: beats run through `runBeats`. Navigation, screen checks, captions,
  scrolls and operator calls take their timeouts from the clock. Fork lost its 20 s grace; an
  operator write goes out only with 10 s of its beat left; the prepared run is read while the card
  shows.
- `scripts/voiceover.py gate [--keep DIR]`: fails a take past 4:40 or with a beat more than 2 s
  late, and keeps it under a `not-held` name when it fails.
- `scripts/narrated_take.sh --keep DIR` (new or empty, refused on a dry run); the dry run gates the
  plan's own length.
- `tests/demo/test_narrated_take_timing.py`: node drives the clock on a virtual clock (the first
  take's 36 s stall, a 36 s screen load, a hold short of its beat), plus the gate, keep, and
  argument tests.
- `docs/video-script.md`: names `--keep` and the gate.
- `report.md`: the kept take, 4:39.04, every beat on plan, read-only.

## Verification
- Accept line (`uv run pytest -q tests/demo/test_narrated_take_timing.py tests/demo/test_narrated_take.py && bash scripts/narrated_take.sh --dry-run`):
  exit 0, 39 passed. Timing tests 20× in a row: 0 red.
- ruff (e2e, scripts/voiceover.py, tests/demo, checks), `checks/no_secrets.py`, `checks/attribution.py`:
  green. Tests that read `docs/video-script.md` (`checks/tests/test_walkthrough_plan.py`,
  `test_submission.py`, tests/demo): 183 passed. `checks/submission.py` is 7/8 (links) on the base
  commit and after this change alike.
- Live: one take against the Demo URL held the gate (report.md).
- Vet: T2, 2 rounds, 7 applied (4 proven, 1 unproven: the 10 s write room, which no offline test
  executes), 2 recorded (the cut grace and the cut 90 s interview are the item's point; the
  timers `within` leaves behind are negligible), 0 open.

## Docs updated
- `docs/video-script.md`, the headers of the spec, the script and `voiceover.py`.

## Follow-ups / known gaps
- A take with the operator beats needs `LEDGERWORLD_DEMO_TOKEN` on the recording machine.
- The kept MP4 is in the slot checkout's git-ignored `var/narrated-take-kept/`. Handing it over
  privately (a private hub artifact) needs a run that may push one.
- Low: a write held back for lack of room reads on the caption as "refused (not sent …)"; the
  words "not sent" are there, but "refused" is not the right verb.
- `e2e/walkthrough.spec.ts` keeps the old hold on purpose: it is the rehearsal that measures
  lateness.

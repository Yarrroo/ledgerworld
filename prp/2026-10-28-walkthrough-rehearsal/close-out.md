# Walkthrough shot-runner — Close-out
> Close-out (/dev-close). Source: board item 112's steps (criteria given; Medium, design folded in).
> Date: 2026-10-28

## What shipped
- `scripts/walkthrough_plan.py`: reads the seven beats through `checks/submission.py` (`BEATS`,
  `TIMED`, `timed_beats`). It writes a JSON plan with beat, start, end, route, caption (Shot),
  subtitle (first Voice paragraph) and note, plus an SRT.
- `e2e/walkthrough.spec.ts` + `e2e/walkthrough.config.ts`: one anonymous chromium at 1280 × 720,
  video on. Any write is aborted, and the beats open on Overview's demo `run_id`. Each beat
  overlays its caption and holds to its planned end. A beat counts as reached when its source
  label shows and no load error does.
- `scripts/walkthrough.sh URL | --dry-run`: prints the webm and SRT paths and a planned-vs-actual
  table. `--dry-run` builds and validates the plan with no browser and no URL.
- `checks/tests/test_walkthrough_plan.py`: covers beat order, contiguity, the ≤ 280 s limit,
  non-empty captions, a well-formed SRT, and refusal of a broken script.
- `report.md`: the live pass against the Demo URL. All 7 beats were reached, the run ended at
  4:35.0, and no writes were sent.
- Wiring: `docs/video-script.md` names the rehearsal command, and the system brief's scripts list
  includes it.

## Verification
- `uv run pytest -q checks/tests/test_walkthrough_plan.py checks/tests/test_submission.py`: 74 passed.
- `bash scripts/walkthrough.sh --dry-run`: green. ruff, no_secrets and attribution: ok.
- Live: `bash scripts/walkthrough.sh <Demo URL>` exited 0 with 7/7 reached (table in `report.md`).
- `checks/submission.py`: 7/8, the same on the base tree. The missing item is the Video link (P7).
- Vet: T2, 2 rounds, 7 applied (4 proven, 1 unproven), 3 recorded, 0 open.

## Follow-ups / known gaps
- The Shot/Voice field regex is in both `walkthrough_plan.py` and `checks/submission.py`, and the
  read-only route guard is in both walkthrough and judge-path specs. Sharing them means editing
  files outside this item.
- The video stays on the recording machine and is not uploaded. Publishing it is the owner's call.

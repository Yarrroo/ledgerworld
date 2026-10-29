# Narrated machine take — Close-out
> Close-out (/dev-close). Source: workflow.md (Medium; design folded in). Evidence: report.md.
> Date: 2026-10-29

## What shipped
- `scripts/narrated_take.sh URL | --dry-run`: `GO` pre-flight, voice, recording, mux, a per-beat
  table, and the MP4's size and sha256. The token is refused over plain http to another machine and
  withheld from every child but the spec.
- `scripts/voiceover.py`: the Voice lines (read through `walkthrough_plan.py`), edge-tts clips
  re-voiced up to +40% until each fits its beat, the opening card, the mux (each clip at its beat's
  actual start, last frame held until the last line ends), actual-time subtitles and the summary.
- `e2e/narrated-take.spec.ts` + config: a 3-second card, then the seven beats in real time; Fork,
  approval request and interview as off-screen POSTs from their own request context, the browser
  read-only; `POST /executions` is never sent.
- `tests/demo/test_narrated_take.py`: 26 offline tests (Voice lines, fit and rate cap, card text,
  mux command and ending, subtitles, retry, the fresh-run request against `RunRequest`, the https
  rule).
- `docs/video-script.md`: one paragraph naming the narrated take after the rehearsal.

## Verification
- `uv run pytest -q tests/demo/test_narrated_take.py && bash scripts/narrated_take.sh --dry-run`:
  26 passed, dry run green. `checks/tests`: 182 passed. ruff, `no_secrets`, `attribution`: ok.
  `checks/submission.py`: 7/8 before and after the doc edit, output identical.
- Live: two read-only takes of the Demo URL (`GO`, every beat reached, no browser write) and one
  tokened take against the offline app (fork 202 + 202, approval 409, interview 503). Numbers in
  report.md.
- Vet: T2, two rounds, converged; 28 applied (10 proven, 6 unproven in the spec's TypeScript,
  12 quality or prose), 21 recorded with reasons, 0 open.

## Docs updated
- `docs/video-script.md` (the recording instructions); `report.md` and this file.

## Follow-ups / known gaps
- The submittable take still has to be recorded: with `LEDGERWORLD_DEMO_TOKEN` on the recording
  machine and with the machine quiet. At a load average above 400 the browser stalled and Execute
  ran 36 s late.
- The MP4 is not uploaded anywhere; that is the owner's step.
- The interview may answer 503 on the deployment, as it does on the offline app (scripted actors,
  no interview model). The caption then shows the refusal.

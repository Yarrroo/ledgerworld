# Narrated machine take — workflow

> Workflow output (dev-build, Medium depth: design folded in). Source: board item 136. Next: implement → report.md → close-out.

**Goal.** One MP4 the owner can upload if the human take does not arrive: the seven beats of
`docs/video-script.md`, recorded against the deployment, voiced by a synthetic voice that a
3-second opening card names as synthetic, with the script's operator actions sent off-screen.

**Accept.** `uv run pytest -q tests/demo/test_narrated_take.py && bash scripts/narrated_take.sh --dry-run`
exits 0 offline.

## Shape

```
narrated_take.sh URL
  ├─ checks/recording_ready.py URL      stop unless GO
  ├─ walkthrough_plan.py → plan.json    the beats, windows, Voice lines (not restated)
  ├─ voiceover.py voice → clips + voice.json   edge-tts, rate raised until each clip fits its beat
  ├─ voiceover.py label → label.json    the opening card text
  ├─ playwright narrated-take.spec.ts   card 3 s, then the beats in real time → webm + beats.json
  │     operator POSTs via a separate APIRequestContext (token never in the browser or the video)
  ├─ voiceover.py mux → take.mp4        clip i delayed to (card + beat i's actual start)
  └─ voiceover.py summary               planned vs actual, voice length, operator results
```

## Decisions (made here, no human in the pane)

- **TTS:** `edge-tts` (no key, needs the network), **ffmpeg:** `imageio-ffmpeg`'s static build.
  Both fetched per call with `uv run --with`, pinned; neither enters `pyproject.toml`.
- **Fit:** a clip longer than its beat window is re-voiced faster (edge-tts `rate`) up to +40%;
  past that the take fails rather than spill into the next beat.
- **Fork:** the prepared run refuses forks (`prepared_demo_read_only`), so the take starts a new
  run of the prepared scenario (`delayed-receipt`, seed 7, 5 rounds), forks it at the prepared
  checkpoint with the prepared policies, and shows its screens when they arrive.
- **Approval capture:** `POST /approvals` for the fresh run's selected policy (the prepared run's
  when the fresh one did not decide). A `409 already_approved` is shown as that refusal and the
  saved receipt is inspected; `POST /executions` is never sent.
- **Interview:** the prepared run's base branch, the lender at the checkpoint round. A refusal
  (e.g. `503 model_unavailable`) is shown as such.
- **No token:** the take still records, read-only; the card and every operator beat say so.

## Phases

1. `voiceover.py` + its offline tests (parse, fit, label, mux command) — gate: tests green.
2. spec + config — gate: `playwright test --list` loads.
3. `narrated_take.sh` — gate: `--dry-run` green offline.
4. Real take against the Demo URL → `report.md`.

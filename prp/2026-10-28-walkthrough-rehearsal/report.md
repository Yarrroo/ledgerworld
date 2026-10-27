# Walkthrough rehearsal — one timed pass of the deployed app

> A silent, captioned, read-only rehearsal of the seven beats in `docs/video-script.md`. Not the
> narrated video and not a claim that the script's operator actions (fresh fork, interview) ran.

**Verdict:** all seven beats load on the prepared demonstration run and hold to plan. The pass ends
at 4:35.0 against the 4:35 budget (4:40 limit), with no write request sent.

- Run: 2026-10-27 ~21:30 UTC, `bash scripts/walkthrough.sh <Demo URL from docs/submission.md>`, code at
  `e1085b8`, chromium 1280 × 720, light theme, anonymous.
- Output: a 62 MB webm and an SRT of the Voice lines at the planned times. Both stay on the
  recording machine (sha256 of the webm starts `6e24850a8e6a8395`). They are not committed or
  uploaded.

## Timing (seconds from the first navigation)

| Beat | Route | Planned | Screen ready | Left | Over plan |
|---|---|---|---|---|---|
| State | /overview | 0–15 | 1.2 | 15.0 | 0 |
| World | /simulation?run_id | 15–25 | 16.8 | 25.0 | 0 |
| Shock | /simulation?run_id | 25–40 | 25.0 (same screen) | 40.0 | 0 |
| Fork | /decisions?run_id | 40–95 | 42.5 | 95.0 | 0 |
| Break | /decisions?run_id | 95–120 | 95.0 (same screen) | 120.0 | 0 |
| Execute | /execution?run_id | 120–235 | 124.6 | 235.0 | 0 |
| Explain | /overview | 235–275 | 237.3 | 275.0 | 0 |

Every screen loads in under 5 s, so screen loads cost the narration at most 4.6 s per beat. The
slowest is Execute, which loses 4.6 s of its 115 s.

## Beats that could not be reached, and what this pass does not show

- **None unreached** in the pass above. "Reached" means the h1 rendered, `aria-busy` is false, the
  source label is present and no load error is shown.
- **The first pass was wrong, and it was rejected.** That take opened `/simulation` with no
  `run_id`. World and Shock were filmed on "Could not load. No run selected", but the pass still
  counted them as reached. The vet found it, the readiness check now fails on a load error, and
  beats open on Overview's demo `run_id`, as the judge path does.
- **Fork:** the fresh branch on camera is an operator POST, so this pass shows the comparison only.
- **Explain:** the interview is an operator POST, so this pass ends on the labels and links.
- **Execute:** this pass shows the prepared execution's receipt screen. It is not the earlier
  approval capture the script inserts.

The narrated take (P7) still has to perform those three actions live. Their timings are not
measured here.

# Narrated take, kept and on time — what this run produced

> Follows `prp/2026-10-29-narrated-take/report.md`. Built by `bash scripts/narrated_take.sh URL --keep DIR`.

**Verdict:** one MP4 that passes its own gate: 4:39.04 long (limit 4:40), every beat left its
screen within 4 ms of its planned end, every screen loaded, and the browser sent no write. It is
**read-only**: no `LEDGERWORLD_DEMO_TOKEN` was in this environment, so the fork, approval and
interview were not sent, and the card and captions say so. The machine was quiet for this take
(load average 6.5 on 16 cores), so the deadline clock was not tested live under load. The offline
tests replay the first take's 36 s stall instead (`tests/demo/test_narrated_take_timing.py`).

## The file

- Run: 2026-10-29 01:53–01:58 UTC against the Demo URL in `docs/submission.md`, pre-flight `GO`
  (mode fake, prepared run `demo-cf0d70441972`). Recorded at commit `a6f3d83`. The vet fixes that
  followed do not change a read-only take that held: they guard operator writes, cut stalled
  holds, and name a failed take differently.
- `ledgerworld-narrated-take.mp4`: H.264 1280 × 720 25 fps + AAC, **4:39.04**, 6,472,376 bytes,
  sha256 `fcaf9b5a70be7637140a2ff45d83579d3cfe23f35a3ed95693e13b3db2c96405`. Its `.srt` and
  `beats.json` sit beside it.
- Where: kept on the recording machine in the slot checkout's git-ignored
  `var/narrated-take-kept/`. It is not committed, uploaded, or put on the hub: sending the file
  anywhere is a separate decision that this run had no door for.
- Voice: edge-tts 7.3.1, `en-US-AriaNeural`. World and Shock were voiced at +31% and +30%; the
  rest at +0%.

| Beat | Planned | Began | Screen ready | Left | Line ends | Operator action |
|---|---|---|---|---|---|---|
| State | 0:00–0:15 | 0:00.0 | 0:04.2 | 0:15.0 | 0:11.0 | — |
| World | 0:15–0:25 | 0:15.0 | 0:18.8 | 0:25.0 | 0:24.6 | — |
| Shock | 0:25–0:40 | 0:25.0 | 0:25.0 | 0:40.0 | 0:39.5 | — |
| Fork | 0:40–1:35 | 0:40.0 | 0:42.0 | 1:35.0 | 0:58.1 | not sent (no token) |
| Break | 1:35–2:00 | 1:35.0 | 1:35.0 | 2:00.0 | 1:47.8 | — |
| Execute | 2:00–3:55 | 2:00.0 | 2:05.5 | 3:55.0 | 2:24.8 | not sent (no token) |
| Explain | 3:55–4:35 | 3:55.0 | 4:00.1 | 4:35.0 | 4:07.5 | not sent (no token) |

Times are seconds from the first beat. The card and its lead-in (3.02 s) come before them.

## What changed since the first take

- **Beats keep to plan.** `e2e/clock.js` counts every beat's end from the take's start, and
  every wait inside a beat is cut at that end. Under the first take's 36 s stall, Explain now
  starts at 3:55, not at 4:31 (offline test). Fork lost its 20 s grace, and an operator write goes
  out only with 10 s of its beat left.
- **The file outlives the run.** `--keep DIR` (new or empty) receives the MP4, SRT and
  `beats.json`. A take past 4:40, or with a beat more than 2 s late, exits 1 and is kept as
  `…not-held.mp4`, so it is never under the name an upload would use.

## Still open

- A take with the operator beats against the Demo URL needs `LEDGERWORLD_DEMO_TOKEN` on the
  recording machine. The same command with the token set makes it.
- Upload, and the video link in `docs/submission.md` (the 8th of 8 submission checks), are
  separate steps.

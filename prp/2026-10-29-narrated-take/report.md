# Narrated machine take — what the first takes produced

> A voiced, labelled walkthrough built by `bash scripts/narrated_take.sh URL`. Not the human take,
> and not uploaded.

**Verdict:** the pipeline works end to end. Against the Demo URL it produced one MP4 with a
synthetic voice, an opening card and every beat reached. The operator beats were **not**
performed there, because no demo token was available on the recording machine. They were
performed against this machine's offline app, where all three answered. The deployed take
overran its Execute beat by 36 s while the machine ran at a load average above 400 on 16 cores,
so this file is **not the one to submit**: re-run on a quiet machine, with the token.

## The take against the Demo URL (read-only)

- Run: 2026-10-29 ~00:43 UTC, `bash scripts/narrated_take.sh <Demo URL from docs/submission.md>`.
  Pre-flight `GO`; the browser sent no write; chromium 1280 × 720, light theme.
- Voice: edge-tts 7.3.1, `en-US-AriaNeural`. World and Shock were voiced at +31% and +30% to fit
  their 10 s and 15 s windows; the other five at +0%.
- File: `ledgerworld-narrated-take.mp4`, H.264 1280 × 720 25 fps + AAC, 4:49.04, 6,302,588 bytes,
  sha256 `4f5a277b8814cf9ec2c3b6a17f79fff27d5df77aab7c3f0ee60da5333adabd9e`. The `.srt` beside it times each
  line where its voice plays.
- Where: nowhere now. It was made in a scratch directory that was removed with the run; it was not
  committed, uploaded or put on the hub, since sending a file out is a separate decision. The
  hashes above identify this take; `bash scripts/narrated_take.sh <Demo URL>` makes the next one.

| Beat | Planned | Began | Screen ready | Left | Line ends | Operator action |
|---|---|---|---|---|---|---|
| State | 0:00–0:15 | 0:00.0 | 0:02.1 | 0:15.0 | 0:11.0 | — |
| World | 0:15–0:25 | 0:15.0 | 0:16.4 | 0:25.0 | 0:24.6 | — |
| Shock | 0:25–0:40 | 0:25.0 | 0:25.0 | 0:40.0 | 0:39.5 | — |
| Fork | 0:40–1:35 | 0:40.0 | 0:41.4 | 1:35.0 | 0:58.1 | not performed (no token) |
| Break | 1:35–2:00 | 1:35.0 | 1:35.0 | 2:00.0 | 1:47.8 | — |
| Execute | 2:00–3:55 | 2:00.0 | 2:03.1 | **4:31.4** | 2:24.8 | not performed (no token) |
| Explain | 3:55–4:35 | **4:31.4** | 4:34.4 | 4:35.0 | 4:44.0 | not performed (no token) |

Times are seconds from the first beat; the card and its lead-in come before them. Execute's hold
ran 36 s late, so Explain had 3.6 s of its 40 s. Its line still plays in full: the MP4 holds the last frame and
ends a second after the later of the last beat and the last line, which is why it runs 4:49,
past the script's 4:40 target and inside the event's five minutes. An earlier read-only take, at a lower
load (00:18 UTC), held every beat to plan and ended at 4:40.75.

## The operator beats, against this machine's offline app

`scripts/ux_app.py`'s app (fake provider, SQLite, a prepared run), started from a scratch copy
that admits a throwaway token, recorded with that token set:

| Beat | Sent off-screen | Answer |
|---|---|---|
| Fork | `POST /runs` (delayed_receipt, seed 7, 5 rounds) | 202 at 0:52; run done, then |
| | `POST /runs/{fresh}/fork` at round 2, three policies | 202 at 0:55; decided in the beat |
| Break | — | filmed on the fresh run's own decisions |
| Execute | `POST /approvals` for the fresh run's selected policy | 409: the same plan was already approved |
| Explain | `POST /interview`, the lender at round 2 | 503: no interview model on the offline app |

No `POST /executions` was sent. The fork beat holds to plan with the fresh run inside it. The
approval and interview refusals are what those calls answer on a prepared, scripted deployment;
the caption shows each one. That take's later beats also overran under the same load.

## What this does not show

- The operator beats against the Demo URL: they need `LEDGERWORLD_DEMO_TOKEN` on the recording
  machine. The deployed interview may answer 503 as the offline one did.
- The earlier approval capture the script asks for in Execute. The take asks for a new approval
  and shows its answer; it never approves or executes the prepared plan twice.
- Voice quality: edge-tts needs its network service, and the voice is synthetic by design. The
  opening card says so before anything else plays.

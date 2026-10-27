# T18 · Live Simulation — design

> Design output (build stage 2, Medium: the accept is pre-registered). Source: `briefs/T18.md`,
> `design/modules/ui/HANDOFF.md` (Simulation row), `fixtures/scrubber.json`. Next: implement.
> No visual twin: the module design page already exists and the accept is the check.

## Requirements (from the brief, unchanged)

Accept: `npm --prefix frontend ci && npm --prefix frontend run build && npm --prefix frontend run
test:unit -- tests/unit/simulation-view.spec.js`; `bash checks/merge.sh`. Scrubbing to round r
shows the feed and cash of round r; a replay branch carries a visible `Replay` label.

## Readers and writers

| Who | Reads / writes | Through |
|---|---|---|
| Judge (no token) | the run, its rounds, feed, cash paths, branches | GET `/api/v1/runs/{id}` |
| Operator (token in memory) | fork at the selected round; read-only interview at the selected round | POST `/runs/{id}/fork`, POST `/interview` |
| Overview (T17) | links here as `/simulation?run_id=<demo run>` | router |
| Decisions (T19) | the screen's `Compare policies` link goes to `/decisions?run_id=` when registered | router |
| Judge path (T26) | click 2 of four lands here | router |
| Agent world (runner) | produces `rounds`, `feed`, `cash_paths`, `branches`, `committed_round`, `status` | C6 RunResponse |

## Invariants

- **One cursor.** A single committed round number drives scrubber, feed, cash and graph. Ticks are
  rounds 1..`committed_round`; nothing past it (a running round's partial journal) is shown.
- **No substitution.** A round absent from `rounds` reads `Round not loaded` in every panel; a cash
  path with no point at the round's time reads `No point at round r` — never the latest value.
- **Round time.** Round r sits at `epoch + t_hours(r)`, epoch = the base branch's first cash point
  (the runner writes it before round 1). A cash point matches only at that exact instant.
- **States.** `running`/`queued` → `Round c+1 running; showing committed round c`; `failed` →
  `Branch invalid at round c+1`, fork and compare disabled; `cancelled`; `done`.
- **Replay.** A replay branch shows `Replay` in the header, on its cash path, in the feed and in
  the round export; it never counts as fresh.
- **Pause** stops local playback only (`Playback paused; simulation may continue`); polling of a
  running job continues. **Fork** (`checkpoint_round` = cursor, all three policies) needs a done
  run and the token; **interview** carries run, base branch, cursor round and the selected actor and
  needs the token too. No POST is retried.
- **Token** lives in a component ref: never storage, URL, export or log.

## Shape

`views/Simulation.vue` owns the reading, the cursor and the two POSTs (through `request` from
`api/v1.js`, unchanged) and renders inside the T17 `ScreenShell`. `Scrubber.vue` is a keyboard
slider (←/→/Home/End) with tick buttons; `ActionFeed.vue` lists the round's posts and intents with
their cleared status; `CashPaths.vue` lists each branch's value at the round and a small path drawn
from known points up to the round. The upstream `GraphPanel` is reused, fed actors and posts up to
the round with evidence edges; an actor inspector beside it selects the interview actor.

DOM order is the phone order (labels → scrubber and controls → cash → feed → graph/inspector);
desktop places graph and feed side by side over the cash path. The live section is dark in both
themes. Wiring: one `/simulation` route in `router/index.js` (listed in `ATTRIBUTION.md`).

## Contract gap (recorded, not patched)

The fixture's `capacity` (lender K_p per round) has no field in C6 RunResponse: cash paths carry
settled cash per account. The spec projects K_p onto a lender-account cash path, so the screen shows
it as that account's path; a real per-round capacity series needs a C6 change owned elsewhere.

## Run footer

ARCHITECT · tier=Brief · thresholds v2 · no reviewer pack (none applies; reversible screen).
GROUND/FRAME/SHAPE are inherited from the ui module run (`design/modules/ui/HANDOFF.md`, which
records consumers, invariants, options and the rejected shapes); this note narrows it to T18 and
adds the round-time rule and the capacity contract gap. Fresh-eyes pass (feasibility · failure
modes · simplicity) ran inline: the fork route refuses a run that is not done and a round outside
1..committed (server-side), so the UI disables those cases but never relies on it. Seam review and
publication skipped: unattended pane, no publish tap; readiness does not depend on publishing.

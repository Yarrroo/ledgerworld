# Round export keeps replay provenance per branch — Close-out
> Close-out (/dev-close). Source: cross-family review finding on the live-simulation screen
> (`frontend/src/views/Simulation.vue`, round export). Date: 2026-10-27

## What broke, and why
The round export took its document `label` from the base branch alone (`base.replay ? 'Replay' :
'Fresh run'`), yet its `cash` list holds every branch's path, forked children included, and kept
only `branch_id`, `account_id` and `value`. A fresh base with a replayed child therefore exported
as `Fresh run`, and nothing in the file said which cash came from a replay.

## What shipped
- `frontend/src/views/Simulation.vue` (`exportHref`): each cash row carries its branch's `replay`
  (`true`, `false`, or `null` when the branch has no boolean flag), `label`, `parent_branch_id`,
  `checkpoint_round` and `policy`. `round_label` covers the base branch's posts and intents.
  `label` covers every branch in the file: one label when they agree, `Mixed: Fresh run + Replay`
  when they differ. A branch with no replay flag reads `Provenance not loaded`, never `Fresh run`.
- `frontend/tests/unit/simulation-view.spec.js`: three regression tests (fresh base + replayed
  child; all-replay stays `Replay`; base with no flag reads `Provenance not loaded`). Each failed
  before its fix.

## Verification
- `npx vitest run` (frontend): 104 passed. The original T18 replay case (`replay: the Replay label
  is in the header, the feed, the cash path and the export`) still passes unchanged.
- `npm run build`: built.
- Browser, against `vite preview` with the run answered in-page: the export of a fresh base plus a
  replayed child read `label "Mixed: Fresh run + Replay"`, `round_label "Fresh run"`, cash
  `b-base: Fresh run`, `b-child: Replay (parent b-base)`. At 390, 768 and 1440 px: no horizontal
  scroll, export link 149×44 px, one Replay tag on the child's cash row.
- Vet T1, 2 rounds, converged: 1 correctness finding applied with its test, 2 quality tidy-ups
  applied, 1 reuse suggestion recorded (sharing the branch map with `CashPaths.vue` is outside
  this fix's files).
- Python suite not run here: no Python file changed; the landing train runs `checks/merge.sh`.

## Docs updated
- None beyond this file: the T18 design's Replay rule already says the export never counts a
  replay as fresh; the code now holds it per branch.

## Follow-ups / known gaps
- On screen, `CashPaths.vue` and the header treat a branch with no replay flag as not replayed (no
  tag), and `base` falls back to `replay: false` when no root branch is listed. The export now says
  `Provenance not loaded` in that case; the screen does not. Out of this item's scope.

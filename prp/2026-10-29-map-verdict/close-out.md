# World-map edges carry their clearing verdict (board item 145) — Close-out
> Close-out (/dev-close). Source: cross-family review finding l_60c7a29dd9 (correction).
> Date: 2026-10-29

## What shipped
- `frontend/src/views/Simulation.vue`: the world map joins each round's intents to that round's
  cleared actions. An intent edge is financial only when the coordinator accepted it and posted a
  journal; a rejected, pending or unverdicted answer is labelled "proposed" and drawn as part of
  the request, as is an accepted one with no journal. Before, every `disburse` citing a request
  was drawn financial, rejected ones included.
- The edge's evidence drawer adds Verdict (word and reason) and Journal ("no ledger change" when
  none), and says why nothing moved: a proposal awaits acceptance and a journal; an accepted
  intent with no journal changed no ledger. The feed's evidence sheet reads the same `verdictOf`
  and `ledgerNote`, so the two drawers cannot disagree; a post gets the information note.
- `frontend/tests/unit/simulation-map-verdict.spec.js`: accepted, rejected, pending,
  accepted-unjournalled and missing-verdict disbursements; journalled and plain accepts; the
  request edge's note; the feed sheet's notes. Fails on 6dd7657 (3 of 3), and on ee13a33 for the
  vet round's cases (3 of 5).

## Verification
- `npx vitest run` (frontend): 16 files, 287 tests passed. `vite build`: built.
- `bash scripts/ux-check.sh e2e/ux/simulation.spec.ts`: green at 1440, 834 and 390, then the
  judge path (6 runs, slowest 6.0 s of 60 s).
- `checks/no_secrets.py` and `checks/attribution.py`: ok.
- Playwright sweep on a dev server with a stubbed run (one accepted, one rejected, one pending
  disbursement):

| Check | 390 | 768 | 1440 |
|---|---|---|---|
| Rejected and pending drawn as request, accepted as financial | pass | pass | pass |
| Drawer shows Verdict, reason, Journal and the proposal note | pass | pass | pass |
| No sideways page scroll; the drawer does not overflow | pass | pass | pass |
| Edge opens by keyboard (Enter) | pass | pass | pass |

## Vet
T2 (the scan flagged money and concurrency words; on reading they were a fixture amount and the
test's awaits). Converged in 2 rounds: 12 findings, 5 applied (3 proven by tests), 7 dismissed
with reasons, 0 open. Dismissed: a journal id absent from `journal_ids` and a verdict cleared in
a later round (the coordinator clears every intent in its own round and posts the journal it
names, `backend/app/simulation/coordinator.py:249`); the shared `cite:` key (post ids and request
ids never collide); the twice-built verdict maps (a handful of rounds); the feed lookup reading
only the cursor round (the feed is fed exactly that round, `Simulation.vue:88`).

## Follow-ups / known gaps
- Parallel edges between the same two actors draw their labels on top of each other at 768 and
  1440 (pre-existing in `WorldMap.vue`; the drawer and the aria label carry the full text).
- `ActionFeed.vue` keeps its own verdict word table beside `VERDICT_WORD`; left as it was.

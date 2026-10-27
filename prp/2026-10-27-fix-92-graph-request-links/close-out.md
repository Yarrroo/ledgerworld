# Live simulation graph: request links — Close-out
> Close-out (/dev-close). Source: a review finding on the Live Simulation screen (T18).
> Date: 2026-10-27

## What broke
The world graph (`frontend/src/views/Simulation.vue`, `graphData`) mapped only post ids and intent
ids to owner nodes. A lender intent cites the request message the coordinator minted
(`req:borrower-c:r4`), never the borrower's intent id, so the cite resolved to nothing and the
borrower-to-lender link, the one that carries the rumour into cash movement, was dropped. The unit
fixture hid it: its lender intents cited `i-r4-borrower-c-1` instead of the request id.

## What shipped
- `Simulation.vue` — `requestOwners(views)` derives the request ids the shown rounds minted, by the
  coordinator's rule (`backend/app/simulation/coordinator.py`, `_request_advance`): a
  `request_advance` cleared `accepted` with no journal becomes `req:<actor>:r<round>`, then `-2`,
  `-3`… for that actor's later ones in the round. Each resolves to the asking actor's node. An id
  no shown intent minted (a drawn advance, a rejected request, a round not returned) still resolves
  to nothing.
- `tests/unit/simulation-view.spec.js` — the fixture carries the coupled-chain evidence and types
  (`accept`/`disburse` citing `req:borrower-c:r4`, the request posting no journal). New tests: the
  lender links to borrower-c through the request id at round 5 and not at round 4 (fails before
  the fix); a request id draws no link unless a shown `request_advance` minted it.

## Verification
- T18 accept: `npm --prefix frontend ci && npm --prefix frontend run build && npm --prefix frontend
  run test:unit -- tests/unit/simulation-view.spec.js` → exit 0, 21/21. Full frontend unit run
  103/103. `checks/no_secrets.py`, `checks/attribution.py` green. No Python changed.
- UX spot-check: Playwright (Chromium) against the Vite dev server with the run response served
  from the fixture, at 390×844, 768×1024 and 1440×900: no horizontal overflow, and the graph shows
  ACCEPT and DISBURSE edges from lender to borrower-c (`ux/sim-*.png`).
- Vet: T1, round 1, 1 applied (quality), 2 recorded, 0 open.

## Follow-ups / known gaps
- The view re-derives the coordinator's id rule. The root-level form is for C6 `RoundView` to carry
  the requests a round minted (id, borrower, intent); that is a contract change outside T18's files.
- At 390 px the upstream graph toolbar can cover a node near the top edge (force layout in
  `GraphPanel.vue`, upstream); not introduced here.

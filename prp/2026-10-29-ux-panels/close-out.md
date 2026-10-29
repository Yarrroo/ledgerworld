# UX 3–6 — Treasury, Lending, Simulation, Decisions — Close-out
> Close-out (/dev-close). Source: HANDOFF.md ← design.md ← prp/2026-10-29-ux-pass/HANDOFF.md.
> Date: 2026-10-29

## What shipped
- Board item 129, Treasury T1–T6 (`views/Treasury.vue`, `components/CashChart.vue`,
  `components/DetailSheet.vue`, `e2e/ux/treasury.spec.ts`). Merged with main's deep links: a
  `?focus=account:` or `?focus=obligation:` row is selected, marked and focused.
- Board item 130, Lending L1–L6 (`views/Lending.vue`, `components/WorldMap.vue`, `api/world.js`,
  `e2e/ux/lending.spec.ts`). The deploy image's frontend stage now copies `scenarios/`, which
  `api/world.js` imports, and a deploy test fails if the frontend imports a tree that stage omits.
- Board item 131, Simulation S1–S6 (`views/Simulation.vue`, `components/ActionFeed.vue`,
  `components/width.js`, `e2e/ux/simulation.spec.ts`). The fork asks for confirmation before
  it sends, the token field is labelled Operator access, and a Forget access button clears it.
  Both unit tests that send a fork click Confirm.
- Board item 132, Decisions D1–D6 (`views/Decisions.vue`, `e2e/ux/decisions.spec.ts`).
- Rules from both vet rounds are pinned in `frontend/tests/unit/ux-panels.spec.js`.

## Verification
- `bash scripts/ux-check.sh e2e/ux/<spec>` on the merged tree: green for treasury, lending,
  simulation, decisions and main's overview. Each run includes the judge path, light and dark.
  Treasury and overview ran before vet round 2, which changed no file they load.
- Frontend unit tests: 248/248. ruff (deploy, checks, e2e), `no_secrets` and `attribution` are
  ok. `pytest deploy/tests checks/tests tests/demo`: 357 passed. The full `checks/merge.sh`
  belongs to the landing train.
- Vet: T2, two rounds, converged; 13 findings (10 applied, 7 of them proven; 3 recorded).
- Sweep table and screenshots read: `ux-sweep.md`.

## Docs updated
- `design.md`, `HANDOFF.md`, `RUN.yaml`, `ux-sweep.md` and this file. README unchanged: no
  command changed. CLAUDE.md is untouched, as the order requires, and the dev-workflows block
  refresh is left to a later close-out.

## Recorded, not applied
- Lending and Treasury still read their sources in parallel. Every one of those routes holds
  `services.lock`; the SQLite refusal came from the decisions job store, which takes no lock.
- On a phone, the actor sheet reopens after a rotate-and-back because the actor stays selected.
  That keeps the user's choice, so it was left as is.
- The h252 timing row adds the family's `delay_h` to the receivable's time. The handoff names
  h252, and the row prints how it was derived.
- The link-button styles are still scoped to each view. A shared class would live in
  `tokens.css`, where sibling panes' merges collide.

## Follow-ups / known gaps
- Backend: the offline app answers `/treasury` with a 500 when a `/decisions` read runs at the
  same moment (`sqlite3.OperationalError: cannot start a transaction within a transaction`). The
  job store and the ledger share SQLite without a common lock.
- API: per-account pool balances, a repayment schedule and a venue-freeze scenario are not
  served. Lending names each one as not supplied (L2 evidence, L5 repayments, L4 rehearse disabled).
- `api/world.js` recognises the backend's observed-snapshot id format
  (`obs-<world>-r<round>-<run>`, `app/demo/run.py`). If that format changes, the world map and
  the Decisions floor drop out quietly; an API field naming the world would remove the coupling.

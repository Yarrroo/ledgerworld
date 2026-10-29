# UX 3–6 — Treasury, Lending, Simulation and Decisions panels

> Architect run, tier **Brief** (one outward reader: the judge; every change is reversible UI;
> no unbackfillable invariant). Source: `prp/2026-10-29-ux-pass/HANDOFF.md` panels T1–T6, L1–L6,
> S1–S6, D1–D6 and its integrity appendix. Board items 129, 130, 131, 132.

## Purpose

- **Goal:** each of the four screens answers its question in the handoff's panels, in motion, at
  1440, 834 and 390 px, with every figure from the API and no finance rebuilt in the browser.
- **Measured by (proxy):** `bash scripts/ux-check.sh e2e/ux/<screen>.spec.ts` green per screen,
  the judge path green behind each, the unit suite green.
- **Not the goal:** new API projections. Where a panel wants a field the API does not serve, the
  panel says so in words (handoff, "Panel projections": *show source evidence or unavailable*).

## The system in one paragraph

Each screen keeps its one reading (`useReading`) and its existing data rules; only the template,
the styles and a few selection states change. Four new shared pieces carry what the screens have
in common, and nothing outside `frontend/src/components/`, `frontend/src/api/world.js`, the four
views and their specs changes.

```
 GET /treasury ─┐                    ┌─ Treasury  T1 selector ─► T2 buckets, T3 S, T5 CashChart
 GET /lending  ─┤                    ├─ Lending   L2 bridge, L3 WorldMap(pool view), L5 DetailSheet
 GET /runs/:id ─┼─► useReading ──────┼─ Simulation S1 context, S2 WorldMap(round), S3 inspector,
 GET /decisions─┤                    │               S4 feed, S5 Scrubber = the one cursor
 GET /overview ─┘ (demo run, ctx)    └─ Decisions D2 gap+timing, D3 radio rows, D4 DetailSheet
 scenarios/world.json ─► api/world.js (topology only, used only when snapshot_id matches)
```

Caption: money comes only from the API readings on the left; the world file feeds topology
(who is linked to whom, and how), never an amount, and only for the snapshot it names.

## Contract registry

| C | Producer → consumer | Shape |
|---|---|---|
| C1 | `DetailSheet.vue` → T4, L3/L5, S3 (phone), D4 | `open`, `title`, `test`; emits `close`; native modal `<dialog>`, focus back to the opener |
| C2 | `CashChart.vue` → T5 | `points [{t, value}]`, `asOf`, `floor`, `selected`; emits `select(t)`; table is the caller's, from the same points |
| C3 | `WorldMap.vue` → L3, S2 | `nodes [{id, label, role}]`, `edges [{id, from, to, type, label}]`, `selected`; emits `select({kind, id})`; types: financial · exposure · information · request |
| C4 | `api/world.js` → L3, S1, S2, D2 | `worldFor(snapshotId)` → `{actors, edges, families}` or `null` |

## Binding vs free

- **B (the handoff, the board):** panel ids and contents; canonical edge directions (pool →
  Borrower B via line-b, never Treasury–Borrower B credit; a feed edge is never a cash flow);
  round n = 4n h; one cursor; policies as a radio group that approves nothing; unknown is never 0.
- **F (this design):** component split above; the world topology from `scenarios/world.json`
  keyed by snapshot id; phone actor sheet reusing C1.
- **U1** — the API serves no per-account pool balances, repayment schedule or venue-freeze run.
  Default: L2's account evidence lists the accounts K_p did not count and names the missing
  projection; L4 is a labelled hypothetical with its action disabled and the prerequisite named;
  L5's repayments show observed revenue only. Owner: the API module. Blast radius: Lending text.

## Per screen

- **Treasury.** T1 radio group of accounts (currency, freshness); the selection drives T2, T3, T4
  and T5 together; amounts are per account and never summed across accounts. T2 bucket rows each
  disclose inputs, account and source time. T3 S with an inline calculation. T4 one time-ordered
  list of arrivals, outflows and obligations of the account; a row opens C1 (amount, deadline,
  reservation, source, state; "not a payment action"). T5 C2 plus a text table of the same
  points; focusing a point shows P's terms at that instant. T6 *Rehearse a cash shock* →
  `/simulation?run_id=&account=&snapshot=`; no run → disabled, prerequisite named.
  *Deliberately not drawn:* per-bucket history.
- **Lending.** L1 pool, snapshot, currency, authority, source time. L2 every part, zeros included,
  as a signed bridge; calculation and account evidence disclosures. L3 C3 centred on the pool:
  facilities from the API (pool → borrower, labelled by facility), venue exposures from C4; a node
  or edge opens C1. L4 freeze: observed when authority is reduced, else hypothetical. L5 facility
  detail in C1. L6 *Compare funding plans* → Decisions for the prepared run, disabled with reason.
- **Simulation.** The existing script (cursor, polling, fork, interview, export) stays; the dark
  instrument goes. S1 run, branch, checkpoint, cohort, provenance, mode and the six families in a
  read-only drawer. S2 C3 with actors from C4 plus requests and citations from the rounds up to
  the cursor; selecting a node or an actor button sets the one `actor`, which drives S3 and the S4
  highlight. S3 inspector: role, objective, what it sees, its intents and verdicts up to the
  round, interview. On a phone S3 opens in C1. S5 the existing Scrubber (arrows, Home, End).
  Phone order: round control, cash, feed, actor list, map.
- **Decisions.** D1 cohort line (no probabilities). D2 no-action minimum against the treasury
  floor, with a timing disclosure (h0, payroll, venue arrival, delayed receipt from the family's
  `delay_h`). D3 `role=radiogroup`; the backend's selection is marked, choosing another row only
  changes the explanation. D4 C1 matrix, one row per scenario × policy. D5 review handoff; all
  infeasible shows escalation, approval absent. Phone: grouped rows, no carousel.

## Risks

- `world.json` drifting from the deployment's snapshot → used only on an exact `snapshot_id`
  match; otherwise the map says it has no topology for that snapshot.
- Unit tests pin `data-test` names → kept: `calculation`, `obligations`, `timeline`, `policies`,
  `policy-*`, `selected`, `cohort`, `controls`, `cash`, `feed`, `graph`, `scrubber-slider`…

## Gate and footer

Fresh-eyes pass: run in this context (solo engine, no fan-out), three lenses — feasibility (all
data exists in the five readings above, checked against the live offline app), failure modes
(unknown/stale/no-run states per panel), simplicity (four shared pieces, no new route, no new
dependency). Skipped: Mirror (not contested) · 9 (one module) · 10 (no seams beyond C1–C4) ·
11 and the reviewer sim (Brief tier, no reviewer pack on this node) · 13 publish (no tap here).
Tier Brief · thresholds v2 · no reviewer pack.

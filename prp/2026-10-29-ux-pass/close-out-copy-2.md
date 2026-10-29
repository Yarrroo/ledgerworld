# Copy pass 2 (Simulation, Decisions, Execution) — Close-out
> Close-out (/dev-close). Source: COPY.md ← HANDOFF.md; follows close-out-copy-1.md.
> Date: 2026-10-29

## What shipped
- Each screen leads with one sentence built from the API's figures (`data-test="lead"`):
  - Simulation: "What if your USD 20,000.00 receivable arrives 10 days late? Watch how it ripples
    through your partners, round by round." The amount and kind come from the treasury's pending
    flow that the family delays (read once per snapshot and run, after the run read, and read
    again after a failure). The delay is the family's `delay_h` (`hoursWords`).
  - Decisions: "Doing nothing leaves you <short> under your safety minimum on <day>. Borrowing just
    enough keeps you covered for a <fee> fee." The short is No action's lowest minimum cash against
    the floor. The day is the first payment still owed from the treasury's as of. The fee is the
    selected plan's branch funding cost. A selected plan that still breaks the floor says "is best,
    yet short in n of m what-ifs". The pending, all-infeasible and search states each say so.
  - Execution: "The plan you approved moved <in> in and paid <out> out — both checked against your
    books." The amounts are the provider receipts, converted to minor units by string arithmetic
    (`decimalMinor`). A ledger-only leg reads "plus 1 ledger-only entry". The other states read:
    before anything is sent, "Nothing moves until you approve and then send."; just sent and not
    recorded yet, "Do not send it twice."; a read still in progress or failed says so; an incident
    reads "Something needs a look".
- Plan names: Do nothing / Keep a fixed buffer / Borrow just enough (`PLANS`, `PLANS_DOING` in
  `api/v1.js`, shared by both screens). Headings, panel-index labels and buttons use plain words.
- Run, branch, checkpoint, cohort, evidence, journal and approval ids sit in closed How we know
  disclosures. Every `data-test` hook is kept. "Simulated bank connection" and "What-if" labels
  are visible on each screen (`.lw-labels` / `.lw-tag`).
- Simulation's Cash paths rows are named by plan name ("Do nothing", …) and tagged "What-if";
  the branch id stays on the row's second line (found by the close-out's reflect pass).
- The judge path's controls keep their fixture names: Compare policies, View execution, Open
  receipt, Open simulation.
- `feesAcross()` replaces two copies of the plan-fee sum. `e2e/ux/copy.ts` holds the helpers that
  copy-1 and copy-2 share.

## Verification
- `bash scripts/ux-check.sh e2e/ux/copy-2.spec.ts`: 24 passed at 1440/834/390, judge path 12
  passed, `ux-check: green`.
- Against one app, after the last change: copy-1, copy-2, decisions, execution, simulation,
  states, readable-labels, panel-jump, shell, smoke, meta and simulation-evidence-graph give 159
  passed, 6 skipped (phone-only or desktop-only by design).
- Every vet fix has a test that failed before the fix and passes after it.
- Vet: T2, converged in 2 rounds, 13 findings: 11 applied (7 correctness, each with a test that
  failed before its fix; 4 quality), 2 recorded (below), 0 open.
- `checks/no_secrets.py`, `checks/attribution.py` and `ruff check e2e checks` pass. No Python
  changed. The full pytest suite is the landing train's.

## Follow-ups / known gaps
- `e2e/ux/simulation-index.spec.ts` was already red before this pass. Board item 131 added a
  "Run context" panel (now "The what-if") after item 138 wrote the spec's panel list. This pass
  did not change that.
- Execution's first load reads decisions and the execution in parallel. The offline app's SQLite
  sometimes answers one of them with HTTP 500 ("Decision unavailable: HTTP 500"). Decisions.vue
  reads in sequence for this reason. copy-2 tolerates the 500 with a re-read; the loader itself
  is a dev-fix item.
- The shell bar above every screen still reads "Simulated provider" and "Hypothetical branch
  <id>" (`LABELS`); the judge-path fixture reads that bar, so it is a copy pass of its own.
- The Decisions day is the first payment still owed, not the computed day of the minimum. How we
  know says so.

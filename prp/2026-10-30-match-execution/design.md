# Execution and bound approval

## Purpose and consumers

Match mockups 06 and 07 in `prp/2026-10-29-ux-pass/MATCH.md` without changing the execution gateway. Consumers are the operator reviewing exact terms, the judge following receipts, keyboard and touch readers, and the existing unit and browser regression suites. The server remains the sole producer of approval terms and provider evidence.

## Scope and inventory

Extend `frontend/src/views/Execution.vue` and its existing unit tests; add `e2e/ux/match-execution.spec.ts`. Reuse ScreenShell, Tip, existing theme tokens, focus trap, polling and the tab-local token/quarantine. Do not change Decisions, Simulation, API, gateway or shared shell.

Observed mismatch: Execution currently renders “What you approved”, “Money moved, with receipts”, per-leg trackers and a single-column dialog, rather than the sections and two-stage columns specified in MATCH.md. The acceptance spec named on the task is absent.

## Shape

```text
GET decisions ──► Create approval (policy / cohort / fee context)
                       │ explicit POST approval
                       ▼
                 Check bound terms ──► explicit POST execution
                                             │
GET execution ◄───────────────────────────────┘
      │
      ├── status banner + aggregate evidence tracker
      ├── execution rows ──► folded receipts / ids / copy
      └── bound approval summary + incidents
```

The browser never reconstructs server approval terms from a scenario result.

Desktop: banner and four-step tracker above a legs-left / terms-and-incidents-right grid. Compact leg rows expose amount and status; request, provider and journal ids stay in expandable details. Use an explicit “View all terms” fold for technical context. Tablet stacks panels. Phone retains compact rows and shows only the active approval stage. Dialog desktop has Create approval and Check bound terms columns; its action footer stays reachable and its existing focus trap stays active. Add a password show/hide control, reset to hidden whenever the review closes.

## Contracts and invariants

- C6 execution feeds labels, receipts, timestamps and incidents; an absent amount is unavailable, never zero.
- C3 approval feeds the exact bound table before execution. Scenario-set cost is separate from current-plan fees.
- An execution read does not supply the original approval hash/entity/expiry or journal amounts. Omit unavailable fields and the ledger reconciliation comparison, rather than inventing them.
- Aggregate provider steps require evidence across provider-backed legs; ledger-only legs never claim provider submission or confirmation. An open incident prevents a reconciled aggregate state.
- Approval and execution remain separate explicit POSTs, never retried automatically. Unknown, expired, stale and mismatched states retain existing guards.
- Token remains tab-local memory, never storage, URL or logs. Show/hide is only an input presentation change.

## Alternatives

1. Replace the state machine: rejected; unnecessarily risks duplicate movement and timeout guards.
2. Extend presentation around existing state machine: selected; smallest scope preserving safety.
3. Copy mockup values: rejected; violates API provenance.

## Verification and handoff

First add the task's browser regression and demonstrate a failing layout assertion on the unchanged view. Then run it after the fix at 1487, 834 and 390 pixels, including both themes, expansion, password toggle and separate approval/execution actions. Preserve existing targeted unit and execution-browser safety tests. Capture screenshots and check no page overflow, touch controls, tooltip operation and visible word budget. Run the task-specific checks through the heavy-command queue. The full merge gate is owned by the landing train under this work order; do not claim its result locally. Independent diff review follows the task commit, with findings fixed and verified before receipts.

Design run: local shape only, as ordered; no publication, no reviewer pack, no added dependency. No backfill or persistent state change.

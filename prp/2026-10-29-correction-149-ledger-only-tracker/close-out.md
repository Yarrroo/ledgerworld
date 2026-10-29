# A ledger-only repayment is not provider progress (board item 149) — Close-out

> Close-out. Source: cross-family review of UX 7, finding 1 (`frontend/src/views/Execution.vue:823`,
> landed at 551a146). Date: 2026-10-29.

## What shipped

- `frontend/src/views/Execution.vue`: the E4 leg tracker put every settled, reconciled leg at
  Reconciled and marked every earlier step reached, so a mode-B repayment (the outbox's
  `ledger_only` move, pending → settled with no provider id and no receipt) read Submitted and
  Provider-confirmed. A settled leg with no provider id is that path: a provider-backed leg
  settles only on a provider object, which sets its provider id. Its Submitted and
  Provider-confirmed steps now read "not applicable" (mark –), Reconciled reads "ledger only",
  the status reads "Ledger only, no provider operation", and the mode reads "Ledger only
  (simulated)" instead of the provider's name. The dialog's leg list shares the same text.
- `frontend/tests/unit/decide-execute.spec.js`: a regression built from the leg state machine
  fixture's `ledger_only` path, serialised as `routes._leg` returns it.
- `e2e/ux/execution.spec.ts`: the same leg at 1440, 834 and 390 px, with no sideways scroll.
- `prp/2026-10-29-execution-dialog/design.md`: E4 names the ledger-only exception.

## Verification

- Unit: `npx vitest run` in `frontend/`: 15 files, 286 passed. The new test failed before the fix
  (`● Ready, reached | ● Submitted, reached | …`) and passes after.
- Accept: `bash scripts/ux-check.sh e2e/ux/execution.spec.ts` green on the final tree (execution
  spec 18 passed at three widths, judge path 12 passed). The landing train runs `checks/merge.sh`.
- Screenshots of the repayment tile at each width were looked at: the skipped steps sit muted
  and wrap cleanly at 390 px.
- Vet: T1, one round, 0 findings from the review; one simplify cleanup applied.

## Follow-ups / known gaps

- `e2e/judge-path.spec.ts:113-118` requires a receipt and a provider label on every leg; a
  sandbox run in mode B with a repayment would fail it (before this change too).
- A leg failed on a dependency (pending → failed, never sent) still shows "Submitted · failed".
  The read cannot tell it from a provider refusal; an explicit leg provenance field in
  `GET /executions` would settle both this and the provider-id inference above.

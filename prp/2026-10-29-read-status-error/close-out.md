# A failed Read status is said inside the dialog (board item 150) — Close-out
> Close-out (/dev-close). Source: the cross-family review of board item 133 (stage status returned
> before checking the read error, `frontend/src/views/Execution.vue` `stageStatus`).
> Date: 2026-10-29

## What shipped
- `stageStatus` composes the read failure once and says it beside the `reconciled` and `incident`
  stage text and beside a held block (unanswered execution POST), never in place of it. The
  stage, and the reconciled line's last successful read time, stay.
- `frontend/tests/unit/decide-execute.spec.js`: 5 regression tests (refused and unanswered reads
  after each terminal stage; a refused read under a held block), each failing before its fix.
- `e2e/ux/execution.spec.ts`: the refused read after reconciled and after incident, at 1440, 834
  and 390 px; `prp/2026-10-29-execution-dialog/design.md`: one line stating the rule.

## Verification
- `npx vitest run` (frontend): 15 files, 290 tests passed.
- `e2e/ux/execution.spec.ts` under `e2e/ux.config.ts` against `scripts/ux_app.py`: 21/21 passed
  (evidence: `ux-sweep.md`, `ux/`).
- `vite build` green; `checks/attribution.py` and `checks/no_secrets.py` ok. No Python changed.

## Docs updated
- `prp/2026-10-29-execution-dialog/design.md` — the read-failure rule for the dialog.

## Follow-ups / known gaps
- None. The page outside the dialog already said read failures (`poll-error`), unchanged.

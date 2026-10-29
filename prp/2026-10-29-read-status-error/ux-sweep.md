# UX sweep — a failed Read status after a terminal stage (board item 150)

Finding (cross-family review of board item 133): in the approval dialog's *reconciled* and
*incident* stages, `stageStatus` returned the stage text before it looked at `pollError`, so a
failed Read status was said nowhere inside the dialog. Fix: the read failure is composed once and
appended to the terminal stage's text; the stage and the last successful read time stay.

Engine: `e2e/ux/execution.spec.ts` under `e2e/ux.config.ts` (headless chromium, mocked `/api/v1`,
the app from `scripts/ux_app.py`), the whole spec: 21/21 passed.

| Check | 1440 | 834 | 390 |
| --- | --- | --- | --- |
| Reconciled, then Read status refused (403): failure said in the dialog, "reconciled as of" kept, stage kept | pass | pass | pass |
| Incident, then Read status refused (403): failure said in the dialog, stage kept, no resend | pass | pass | pass |
| Action footer in view; buttons ≥ 44 px; no sideways page scroll | pass | pass | pass |
| The spec's earlier flows (approve/execute, expired, unknown, incident, focus trap) | pass | pass | pass |

Screenshots in `ux/`: phone 390 reconciled and incident, desktop 1440 reconciled.
Unit regression: `frontend/tests/unit/decide-execute.spec.js`, "correction: a failed Read status
is said after a terminal stage (board item 150)" — 4 tests, failing before the fix.
Deferred: none.

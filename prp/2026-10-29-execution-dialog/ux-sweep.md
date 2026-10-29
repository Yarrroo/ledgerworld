# UX sweep — Execution and the approval dialog (board item 133)

Engine: `bash scripts/ux-check.sh e2e/ux/execution.spec.ts` (headless chromium, mocked `/api/v1`
from the contract examples), then the judge path against the same app. Screenshots kept in `ux/`: phone 390
(1 review · 2 approved · 3 incident · 4 page after Close) and the desktop page, taken before the step-tracker fix below.

| Check | 1440 | 834 | 390 |
| --- | --- | --- | --- |
| Review → submitting → approved → executing → reconciled, one POST each | pass | pass | pass |
| Expired approval: Execute disabled, reason said | pass | pass | pass |
| Approval with no answer: unknown stage, confirm disabled, no resend | pass | pass | pass |
| Incident: evidence kept on page and in dialog, no resend/reverse control | pass | pass | pass |
| Copy hash / approval id announces; clipboard holds the hash | pass | pass | pass |
| Focus trapped (Tab/Shift+Tab), Escape returns focus to Review plan | pass | pass | pass |
| Action footer in view; phone dialog full height, footer at its foot | pass | pass | pass |
| Dialog buttons ≥ 44 px; no sideways page scroll | pass | pass | pass |
| Judge path (read-only, 390/1280/1440 light+dark) | 12/12 pass | | |

Finding fixed in-scope: a leg with an open incident still marked *Reconciled* in the step tracker;
it now stops at *Provider-confirmed* (unit test in `decide-execute.spec.js`).
Deferred: none.

# Execution — leaving and returning keeps the quarantine (board item 95)

Spot-check depth: a behaviour-only change to `Execution.vue` (no markup or style changed).
Engine: Playwright MCP (Chromium) against the Vite dev server, run on the final code (2851c59). Every `/api/v1` call was answered by
`page.route` with the recorded LF1 overview and a selected decision for `run-1`; `POST /approvals`
answered 504, so the approval outcome is unknown. Flow per tier: Review plan → enter the operator
token → Confirm approval (504) → Cancel → the **Overview** nav link (Execution unmounts) → the
**Execution** nav link (a fresh mount) → read the screen → click Review plan.

| Check | Phone 390×844 | Tablet 768×1024 | Desktop 1440×900 |
|---|---|---|---|
| Block shown after return ("Approval outcome unknown; operator resolution required") | pass | pass | pass |
| Review plan disabled after return | pass | pass | pass |
| Token still held (Forget token offered) | yes | yes | yes |
| Review dialog opens on click after return | no (pass) | no (pass) | no (pass) |
| `POST /approvals` sent | 1 | 1 | 1 |
| No horizontal page scroll | pass | pass | pass |
| Review plan target height | 44 px | 44 px | 44 px |
| Screenshot | `ux/phone.png` | `ux/tablet.png` | `ux/desktop.png` |

Before the fix the same return re-enabled Review plan with the token still held (the regression
tests under "leaving and returning to Execution (board item 95)" in
`frontend/tests/unit/decide-execute.spec.js` fail on the previous component).

## Deferred (pre-existing, not this diff)

- After an unanswered approval POST, Confirm becomes disabled while it holds focus, so focus falls
  to `<body>` (measured at all three tiers) and Escape no longer closes the review: the dialog's
  `keydown.esc` handler sits on the dialog. Cancel still works. Same in the T19 component before
  this change.
- The vet rounds' cross-run cases (an answer arriving after moving to another run, the "not read on this
  screen" wording) are covered by unit tests; the browser sweep drove the leave-and-return flow only.

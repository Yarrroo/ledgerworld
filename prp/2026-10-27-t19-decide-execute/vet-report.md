# Vet report: Decisions and Execution

> Source: the change `be69ea6..HEAD` (board item 20). Tier T3: the operator token and the
> approval and execution POSTs on a payout path; 4 code files, about 1,200 lines, tests included.

**Outcome:** 18 findings after dedupe. 16 applied, 13 of them correctness fixes, each proven by a
test that fails before the fix and passes after. 0 unproven. 2 recorded, 0 open. Converged in 2
rounds.

## Round 1 (own read, security review, simplify)

| # | Finding | Grade | Outcome |
|---|---|---|---|
| 1 | A 5xx answer to `POST /executions` was read as a refusal, so the execution was never read back by its approval id | high | applied, proven |
| 2 | A 5xx answer to `POST /approvals` left Confirm usable instead of blocking for the operator | high | applied, proven |
| 3 | A failed decisions read blanked the receipts | medium | applied, proven |
| 4 | `review=1` reopened the review on every Refresh | medium | applied, proven |
| 5 | An expired or mismatched approval survived Close, so no new review could confirm | medium | applied, proven |
| 6 | The decision and the execution were read one after the other | low | applied (quality) |
| 7 | The scenario-cost label and the policy names are duplicated in both views | low | recorded: their shared home is `api/v1.js`, which another task owns; follow-up |
| 8 | The rule that a 5xx means the outcome is unknown belongs in `request()` | low | recorded: same owner; follow-up |

The security review found nothing at confidence 8 or above. It covered XSS, token leakage,
path injection, forged POSTs and auth bypass.

## Round 2 (code review, high)

| # | Finding | Grade | Outcome |
|---|---|---|---|
| 9 | A failed status read after an unanswered execution POST stopped polling for good | high | applied, proven |
| 10 | An execution with no legs yet read as finished and was not polled | high | applied, proven |
| 11 | Refresh never re-read an execution this tab had sent | high | applied, proven |
| 12 | A settled leg not yet reconciled stopped polling | medium | applied, proven |
| 13 | A query-only navigation reused the view without reloading it | medium | applied, proven |
| 14 | Close during an in-flight execution POST left a stale refusal for the next approval | medium | applied, proven |
| 15 | An execution id the server does not have was polled every 5 s forever | medium | applied, proven |
| 16 | A comment had been attached to the wrong flag | low | applied (quality) |
| 17 | The design notes named the tooling that builds the repo, against the repo rule | low | applied (prose; the contradiction is with `CLAUDE.md`, "Repo files never name…") |

| 18 | Re-reading the round-2 diff: a navigation during an in-flight POST skipped the reload, so the URL named another run | medium | applied, proven |

The code review also raised the duplication in #7; it is counted once.

**Coverage:** read `Decisions.vue`, `Execution.vue`, the router lines, the spec and the shared
`api/v1.js` it calls. The backend routes it talks to (`backend/app/api/v1/routes.py`) were read
for the 404 and the empty-legs behaviour. Not reached: the T17 views, which this change leaves
untouched.

# Execution diff review

## Verdict and coverage

T3, two fix rounds. All ten correctness findings were reproduced before correction and verified afterward. Three unique quality cleanups were applied. No finding was dismissed or left open; no correctness fix was applied without proof. Final corrections were checked inline and through the targeted gates rather than launching a third broad review.

Initial immutable range: `d35a310430364f3c27541691c1e29f4ad484f236..64e2835e42c33d129861fd3c424b2ce177e47653`. The independent second review covered `64e2835e42c33d129861fd3c424b2ce177e47653..cb8894d`. Both correctness calls requested `high`; neither result separately echoed the effort setting, so it is recorded as requested high, unconfirmed.

The production scope is one Vue view. Tests cover that view and align only Execution receipt/copy selectors in existing browser paths. Generated media and logs are evidence, not executable source. Tier T3 is warranted by password presentation and money-evidence/reconciliation UI; no gateway, backend authorization, schema or provider-request implementation was changed.

## Instruments

- Independent correctness review of the initial committed range: five findings.
- Four cleanup reads: reuse, simplification, efficiency and altitude. Reuse found the existing `$` helper. Simplification and altitude found the same repeated predicate; deduplicated into one cleanup. Efficiency found no material waste in that first range.
- Independent security read of the production delta and existing request transport: no new HIGH/MEDIUM exploitable issue. The security follow-up on `64e2835 → cb8894d` likewise found none.
- Independent correctness review of the correction range: five additional correctness findings and one efficiency cleanup. The final inline pass checked all corresponding edits, approval-context capture/drop, provider evidence and both tracker paths. Credential handling, request destinations, escaping and server authority remain unchanged by those final edits.

## Correctness resolutions

| Finding | Fails-before guard | Correction |
|---|---|---|
| F1: missing Decisions crashes an approved dialog | 404 on refresh after approval | Safe context rendering; bound terms remain usable |
| F2: unrelated run policy is attributed to an execution | Explicit mismatched run/execution pair | Remove unverified policy attribution |
| F3: aggregate tracker claims submission from state alone | Failed/unknown/claimed legs without provider evidence | Require provider evidence |
| F4: hero reconciliation count ignores an incident | Settled, journalled leg with an open mismatch | Shared incident-aware reconciliation predicate |
| F5: arbitrary payout is labelled payroll | Rent payment API label without a receipt | Use the API purpose or neutral kind |
| F6: held approval adopts a later selected policy | Change Decisions after approval and while POST is in flight | Capture context at POST start and retain it with the returned approval |
| F7: unavailable fee becomes “None” | Fail the Decisions refresh after a nonzero quote | Retain the approval's original scenario context; unavailable live data stays unavailable |
| F8: individual tracker contradicts aggregate submission | The same no-provider-evidence states, checking individual steps | Reuse the provider-evidence threshold |
| F9: pending local repayment blocks provider progress | Mode B's labelled ledger-only leg remains pending | Use the connector's explicit `repayment (simulated)` label before settlement; do not infer locality from missing pending ids |
| F10: long API label overflows compact rows | A 4000-character unbroken label at each viewport | Wrap long words within the name column |

The first seven regression cases failed before round-one corrections. In round two, seven unit cases and all three long-label browser cases failed before correction. The final suite passes 177 unit cases and all nine dedicated browser cases.

Quality resolutions: reuse the browser selector helper; reuse the reconciliation predicate; index open incident leg ids once per reading and reuse the reconciled count. Those quality changes are covered by the green gates and are not counted as executable correctness proofs.

## Evidence and limits

`ux-sweep.md` names the commands and screenshots. Dedicated mockup acceptance, existing Execution UX stages, Execution-only copy checks and judge-path/accessibility checks passed. Secrets, attribution and whitespace gates passed. The corrected auxiliary launcher previously passed all 60 stability cases with unchanged assertions/timeouts; its original RED stdout/video and pipe-backpressure diagnosis remain separate evidence. That 60-case result belongs to the pre-final-correction tree `cb8894d`; final source changes were verified with the targeted unit/browser gates, not represented as another 60-case run.

No dependency was added. The full merge gate and separately coordinated combined-head verification were not run locally and are not claimed green here.

Final accounting: 13 findings applied (10 correctness proven, 3 quality), 0 unproven, 0 recorded/dismissed, 0 open. Two rounds; no third broad review.

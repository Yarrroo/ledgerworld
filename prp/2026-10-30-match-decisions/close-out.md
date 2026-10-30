# Decisions mockup match — Close-out

> Close-out (/dev-close). Date: 2026-10-30. Contract: `prp/2026-10-29-ux-pass/MATCH.md`, Decisions, and mockup 05.

**Decisions is implemented and verified in the offline app; landing is still pending.** Only this task's screen and dependent tests changed. Simulation implementation and Execution implementation were not changed.

## What changed

The stepper leads to a large reserve gap, a sourced waterfall and visible timing, beside compact policy radio rows, the inspected minimum and Review current plan. Technical detail lives in Source evidence and the scenario drawer. The existing judge-path hook remains reachable through that disclosure. Inspecting another radio does not change which backend-selected policy is reviewed or create an approval.

Root cause: the previous Decisions view still used the older panel layout and the named mockup regression spec did not exist. The new regression fails against the original view. The retained work was merged without reverting newer Simulation fixes.

## Verification

| Check | Result |
|---|---|
| `bash scripts/ux-check.sh e2e/ux/match-decisions.spec.ts` | Green on the final code, including the judge-path accessibility suite |
| `npm --prefix frontend run test:unit` | All tests green on the final code |
| Legacy Decisions, copy, shared-layout, readable-labels and state browser specs | Green before the final review edge-case fixes; existing width-specific skips retained |
| Frontend production build | Green as part of the final UX command |
| Secret and upstream-attribution checks | Green |
| Correctness review and simplify | Closed; [review record](vet-report.md) |

The exact aggregate `bash checks/merge.sh` was not executed here: the work order reserves it for the landing train. The result above does not establish the separately tracked Simulation combined accept. [UX proof and screenshots](ux-sweep.md) record the browser checks and before/after regression evidence.

## Assumptions and deliberate differences

The mockup's screen-specific placement wins over the shared hero-action default. Actual amounts and source states win over the screenshot. The middle bar is Cash change, not Payroll: no API field attributes the branch's lowest balance to individual movements. Current plan fees remain a review-time fact. No API or dependency was added, and no stored state needs a backfill.

## Reflection and boundaries

Fixed now: the review exposed actual stale-state representation, elapsed-world-time labels, comparisons without a No action row and negative residual styling. Each received a regression that failed before its fix. Optional quality ideas were recorded with reasons, not silently widened into shared-module work.

No public publication, push, PR, deploy, owner-card verdict or Execution follow-up was attempted. README commands and repository doctrine did not change. CLAUDE.md, CHANGELOG.md and harness configuration were left untouched as ordered. No new vocabulary or setup requirement was introduced.

Final owner-only receipt validation was refused by the local tool boundary. It is not claimed green and was not retried. Stage instrumentation was likewise refused; declared ops logging is attempted separately. The final commit is the handoff for the landing checks, not a claim that the change has already landed.

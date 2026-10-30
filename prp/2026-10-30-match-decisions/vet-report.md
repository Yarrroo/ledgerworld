# Decisions review

**No unresolved findings.** Boundary: `e6f268b..4e20d86`, the Decisions screen and its seven test files. The screen has one consumer path from Simulation through Decisions to Execution. Snapshot identity, currency, unknown-state handling, backend selection and the approval boundary must survive the layout change.

Tier: **T2**, because the measured diff exceeds the normal small-change threshold and changes monetary presentation. It does not change postings, approval validation, provider requests, API contracts or storage. The first correctness review used medium effort; the targeted review of `4e20d86..6b0fe8e` used low effort. The instrument results did not explicitly echo effort, so the requested levels are recorded as unconfirmed. Both reviews executed and covered their supplied committed ranges. The four simplify lenses read the Decisions diff; no security-adjacent implementation changed, so a security instrument was not warranted.

## Applied

| Finding | Resolution | Proof |
|---|---|---|
| F1: Settled Money has no freshness status | Require the account's actual known spendable metric before drawing the bridge | New API-shaped stale fixture failed before and passed after |
| F2: Epoch hours were called time remaining | Derive relative labels from the treasury observation; keep world hours in source hooks | An observation after h0 now labels observed cash Now and payroll by remaining hours |
| F3: Inspected floor depended on No action | Read the floor for the inspected policy's currency | Integrated-only comparison failed before and passed after |
| F4: Negative Remaining bar received the healthy fill | Do not give a negative bar the green remaining class | Signed-scale regression failed before and passed after |
| F5: Minimum calculated twice | Compute once per policy | Behavior-preserving cleanup; unit and browser gates green |
| F6: Dead floorOf helper | Remove its unused declaration | Behavior-preserving cleanup; unit and browser gates green |

All four correctness regression IDs are in `frontend/tests/unit/ux-panels.spec.js`. They were executed together against the pre-fix view and all failed, then passed after `6b0fe8e`. The second correctness review returned no findings.

## Recorded, not applied

- F7: Extract repeated shortfall formatting. The occurrences are simple formatting calls over different inputs; a second abstraction would not remove a competing rule. Kept inline.
- F8: Unify feeWords and feesAcross. The former already existed and describes a maximum; the latter sums scenarios. Combining them risks changing a deliberate distinction and is outside this layout fix.
- F9: Move the waterfall model into shared API utilities. The bridge and scale have one screen consumer and do not decide or post money. Kept local rather than expanding the shared API module.
- F10: Reuse the policy aggregate inside gap. The duplicate scan predates this diff and is bounded by the small policy cohort. Deferred as optional cleanup, not an unresolved defect.

Summary: **vet: T2, round 2, 6 applied (4 proven, 0 unproven), 4 recorded; 0 open.** The review and simplify findings were deduplicated. No deferred correctness defect remains. Verification and screenshots: [UX proof](ux-sweep.md).

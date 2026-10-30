# Execution and approval close-out

Date: 2026-10-30. Scope: board item 163 only.

## Result

The existing `/execution` route follows mockups 06 and 07: evidence-backed banner and tracker, expandable receipt rows, folded technical terms, bound-approval and incident panels, and a two-column approval dialog with one active stage on phone. Password visibility resets on close. Approval and execution remain separate authenticated actions with no automatic POST retry.

Two independent review rounds found ten correctness issues. Each was reproduced before correction and verified afterward. Three unique quality cleanups were applied. `vet-report.md` records the findings, ranges and final inline verification after the second correction cycle. No third broad review was launched.

## Verification

- Targeted unit suite: 177 passed.
- `bash scripts/ux-check.sh e2e/ux/match-execution.spec.ts`: all nine browser cases passed, including the previously failing long-label regression, followed by its judge-path/accessibility stage.
- `bash scripts/ux-check.sh e2e/ux/execution.spec.ts`: all 33 cases passed, followed by its judge-path/accessibility stage.
- Execution-only copy checks passed. Screenshots, viewport assertions and measured word counts are in `ux/` and `ux-sweep.md`.
- Secrets, attribution and whitespace checks passed.

The auxiliary stability launcher originally failed because it stopped draining the app's stdout pipe. Original RED evidence, including the recovered partial stdout and first-failure video, is preserved in `stability-red/`. A pipe/drain/file-sink probe isolated the launcher defect. Its corrected run passed all 60 unchanged cases on the `cb8894d` source; see `stability-green.txt`. Final corrections were verified by targeted gates, not represented as another 60-case run. Assertions and test timeouts were not weakened.

All app-backed checks used the fake provider, scripted behavior and disposable SQLite data through the shared heavy-command queue. No real provider or model was called.

## Reflection and limits

- Fixed in scope: nullable and changing Decisions context, captured approval policy/fees, consistent provider and reconciliation evidence, pending ledger-only classification, long labels, tooltip taps and keyboard dismissal. Existing Execution-only receipt selectors were aligned; neighboring screens were not rebuilt.
- Intentional omission: C6 supplies journal ids but not journal amounts, so no reconciliation totals are invented. Original executed approval terms are not reconstructed from unrelated responses; a newly created C3 approval displays its exact bound terms.
- Deferred by authority: the full merge gate and separately coordinated combined-head verification. Neither was consumed or claimed green here. No owner-card or video verdict was cast.
- No dependency, backend/API change, persistent writer, migration or backfill. No changes under `.claude/`, `CLAUDE.md` or `CHANGELOG.md`. README commands remain valid.
- Workflow stage instrumentation was refused by the run allowlist and was not retried; this requires no product change.

## Delivery boundary

Local commits, receipts and the run report are the handoff. No push, PR, merge, deployment or publication. The final combined-head result remains the owning verification lane's responsibility.

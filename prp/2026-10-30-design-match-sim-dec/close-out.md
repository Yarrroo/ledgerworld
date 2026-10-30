# Simulation — mockup 04

**The reachable `/simulation` now follows mockup 04.** Its API, financial writers and approval
boundary are unchanged; no dependency or backfill is introduced. The brief was updated to name
the inline actor inspector and the new reading order.

```text
RunResponse + same-run Treasury → map + actor → committed-round cursor → policy cash outlook
                                      └──────── Source evidence ────────┘
```
The cursor changes what is inspected, never which financial operation runs.

## Verification

- `npm --prefix frontend run test:unit`: 333 passed.
- `bash scripts/ux-check.sh e2e/ux/match-simulation.spec.ts`: green at 1487, 834 and 390 px;
  layout, hero, icon nodes, timeline, cursor, three-policy paths, shortfall, hover/focus/tap,
  word budget and overflow. Screenshots in `ux/` cover all widths, both themes.
- Final combined UX run: 101 passed, four viewport-specific cases skipped (phone-only reading
  order; desktop-only shared word count). All 12 judge path/accessibility cases passed;
  final exact-command slowest timed path: 6.1 s, limit 60 s. Every run uses fake providers and a disposable
  SQLite database created by the UX harness; no real model, bank or graph-memory API is called.
- `ruff check checks e2e`, `checks/no_secrets.py`, `checks/attribution.py`, `git diff --check`:
  green. Frontend built by the UX harness. Full `checks/merge.sh` is reserved for the landing
  train by the work order and was not run in this slot.
- Vet: T2, two rounds, 11 applied (10 proven, 0 unproven), one scratch-only finding
  recorded, none open; dispositions and coverage are in `vet-report.md`.

## Honest differences and follow-ups

The API supplies no per-round lender capacity or display scenario name: neither is copied from
the image. The timeline shows only committed non-idle intents and received requests (up to the
last three), not the mockup's invented event chain. The selectors inspect the existing run;
settings remain read-only. Charts use run-owned settled cash, not today's projected balances;
unknown points break the line and prevent a shortfall claim. Narrow maps use two columns.

No push, PR, merge or deploy was performed. The `devw stage` command was refused by the route
hook as undeclared; workflow instrumentation needs a separate configuration follow-up.

# UX 3–6 sweep — Treasury, Lending, Simulation, Decisions

Engine: `@playwright/test` (headless chromium) through `scripts/ux-check.sh`, offline app (fake
provider, SQLite, prepared demo run), then the judge path against the same app. Widths 1440, 834
and 390 px (`e2e/ux.config.ts`), video on; full-page screenshots read at 1440 and 390 for each screen.

| Check | Treasury | Lending | Simulation | Decisions |
|---|---|---|---|---|
| Spec at 1440 / 834 / 390 | 12/12 | 12/12 | 13/13 (2 phone-only skips) | 10/10 (2 phone-only skips) |
| Judge path after the spec (light + dark) | 12/12 | 12/12 | 12/12 | 12/12 |
| No sideways page scroll | ✓ all widths | ✓ | ✓ | ✓ |
| Targets ≥ 44 px (radios, row and facility openers, rows) | ✓ | ✓ | ✓ (actor buttons are `.lw-button`) | ✓ |
| Sheet: full width and height on a phone, Escape closes, focus back to the opener | ✓ | ✓ | ✓ (actor sheet, evidence, settings) | ✓ (details drawer) |
| Keyboard path | chart points, table points | map nodes and edges, relation list | actor list, map, scrubber ←/→/Home/End | radio group arrows |
| Read-only (no write leaves the browser) | ✓ | ✓ | ✓ (fork never confirmed) | ✓ |

## Fixed during the sweep

- Treasury, all widths: the page scrolled sideways (127–276 px). A grid track sized to the
  table's and the chart's content; fixed with `minmax(0, 1fr)` tracks and `contain: inline-size`
  on the chart and the map.
- Treasury: no account radio was checked until one was clicked; the checked state now follows
  the account shown.
- Lending: bridge bars of unequal length per row (column sized per row); map labels truncated
  mid-word; facility rows wrapping their amount.
- Simulation: two map nodes both read "Northwind" (first-word shortening); labels now fall back
  to two words, then the actor id.
- Decisions: the gap read "floor Not assessed" one run in three. The offline app answers a
  treasury read beside a decisions read with a 500 (`sqlite3.OperationalError: cannot start a
  transaction within a transaction`); Decisions now reads them one after the other.

## Deferred

- The offline app's SQLite concurrency (a job-store read beside a ledger read under no shared
  lock) is a backend defect outside these items; any screen that reads both at once can meet it.

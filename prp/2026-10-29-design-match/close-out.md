# Design match 0 and 1 — close-out

**What changed.** The six finance screens now open the way the mockups do: the mockup header (LedgerWorld /
Page · provider and agents · date · snapshot line), the sidebar with the mockup icons, "Simulation" and the
company block, and a page hero (`PageHero.vue`) with the mockup headline, a one-line subtitle whose tooltip is
the old lead sentence, and the journey's next step as the one primary button. The panel-index tab row, the
header Refresh (a screen re-reads when its tab becomes visible), chip rows, visible "How we know" folds,
"Check again", lead paragraphs and visible ids are gone; that detail lives in one tooltip component
(`Tip.vue`: hover, focus and tap open; Escape, blur and a second tap close; fixed to the viewport so it never
covers its value or widens the page). `HowWeKnow.vue` is now an (i) control with a Tip. Money reads "$70,000"
(symbol, whole units when the cents are zero). Overview is rebuilt to mockup 01.

**Checks.** `checks/word_budget.py` holds each mockup's hand-counted words and the 15 % slack;
`e2e/ux/words.ts` counts the live page the same way. Measured at 1487 px: Overview 157 (budget 184),
Treasury at most 220 (220; 232 before its point readout waited for a chosen point), Lending 191 (192), Simulation 229 (241), Decisions 185 (212), Execution 101 (236).
`e2e/ux/match-shared.spec.ts` and `e2e/ux/match-overview.spec.ts` pass through `scripts/ux-check.sh` at 1440
(1487 for the budget), 834 and 390 px, and the judge path passes after each (slowest 6.1 s of 60).

**Left out, by MATCH.md's rule (the API has no field):** Overview's public-feed node; "Reserved $50,000" reads
"Reserved: Yes", since the API serves a reservation flag, not its amount.

**Not in this change (each its own later change):** the per-screen layout rebuilds 02–07 (Treasury tables, the
Lending bridge, the Simulation selector row, the Decisions stepper, the Execution tracker, the approval dialog).

**Seen, not fixed:** the offline app (`scripts/ux_app.py`, SQLite) answers concurrent reads with HTTP 500
"cannot start a transaction within a transaction" now and then; the shell now asks `/overview` for the
company only after the screen's own read, so it adds no concurrent request.

## Verification (final tree)

- `bash scripts/ux-check.sh e2e/ux/match-shared.spec.ts` and `… match-overview.spec.ts`: green at 1440 (1487
  for the budget), 834 and 390 px, each followed by a green judge path (slowest 6.0 s of 60).
- Every e2e/ux spec against one offline app: 229 passed, 8 skipped by design; `vitest run`: 299 passed.
- `ruff check checks e2e`, `checks/attribution.py`, `checks/no_secrets.py`, `checks/tests/test_word_budget.py`,
  `npm --prefix frontend run build`: green. The full pytest suite is the landing train's and was not run here.
- Vet: T2, two rounds, converged; three findings fixed with tests that fail before (a disabled action's
  reason reachable by keyboard and tap, a breached floor visible on Overview, a payee's obligations counted).

## Follow-ups

- The offline app's SQLite store shares one connection across threads; concurrent reads now and then answer
  HTTP 500 ("cannot start a transaction within a transaction", `backend/app/finance/store.py`). A fix of its own.
- `/simplify` did not run over this diff; a quality pass is owed.
- Chart notes are not checked against each other or the lowest-point box; the floor label's width is an
  estimate (130 px), short for a seven-figure floor.

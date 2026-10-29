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

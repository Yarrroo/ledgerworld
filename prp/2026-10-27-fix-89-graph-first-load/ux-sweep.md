# Live simulation graph — first-load sweep (board item 89)

Spot-check depth: one component changed (`LiveGraph.vue` adapter around the reused graph view).
Engine: Playwright MCP (Chromium) against the Vite dev server, `/api/v1/runs/run-demo` answered from
the UI fixture `scrubber.json` (the same body the unit suite builds), completed run, 5 rounds.
The viewport was set **before** navigation, so no window resize could trigger the drawing.

| Check | Phone 390×844 | Tablet 768×1024 | Desktop 1440×900 |
|---|---|---|---|
| Nodes drawn on first load, no scrub, no resize | 4 | 4 | 4 |
| Nodes drawn after an unchanged Refresh | 4 | 4 | 4 |
| Drawn nodes inside the graph viewport | 4 / 4 | 4 / 4 | 4 / 4 |
| No horizontal page scroll | pass | pass | pass |
| Graph toolbar target (min side) | 44 px | 44 px | 44 px |
| Screenshot | `ux/graph-phone.png` | `ux/graph-tablet.png` | `ux/graph-desktop.png` |

Before the fix the same first load drew 0 nodes (the regression test in
`frontend/tests/unit/simulation-view.spec.js`, "the real graph view", fails at `expected 0 to be
greater than 0` without the adapter). Browser console: no errors.

## Deferred (pre-existing, not this diff)

- Phone: the reused graph view's floating "Show Edge Labels" toggle and title overlay the top of
  the canvas, so a node laid out near the top edge sits under them (`ux/graph-phone.png`,
  `borrower-c`). The overlay is the upstream component's own layout, unchanged here.

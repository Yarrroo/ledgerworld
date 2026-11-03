# UX sweep: Overview around the 72-hour cash path

> dev-ux evidence (standard depth). Surface: `/overview`. Primary flow: read the answer, read the
> cash path against the floor, hide/show the late path, open the payroll row, Open simulation.
> House system: `frontend/src/styles/tokens.css` (breakpoints 767 / 1199 px, `--lw-*` tokens,
> 44 px `--lw-target`); the repo's matrix is 1440 / 834 / 390 (`e2e/ux.config.ts`).

| Check | 390×844 | 768×1024 | 834×1112 | 1440×900 |
|---|---|---|---|---|
| Answer, floor line, cash path, Open simulation in the first viewport (light and dark at 390 and 1440) | pass | pass (Open simulation bottom 954 of 1024) | pass | pass |
| No sideways scroll | pass | pass (0) | pass | pass |
| Floor, trough, late path read off the chart's axis equal the API | pass | — | pass | pass |
| Controls ≥ 44 px (Open simulation, Hide path, payroll link, folds) | pass | pass | pass | pass |
| Tooltips: hover/tap, focus, Escape (equation, chart point) | pass | — | pass | pass |
| Labels clear the floor line, its label and the step line (3 answers) | pass | — | pass | pass |
| Word budget at 1487 px (≤ 184) | — | — | — | pass |
| Judge path (390/1280/1440, light and dark) | pass | — | — | pass |

Engine: `bash scripts/ux-check.sh e2e/ux/match-overview.spec.ts` (headless chromium, fresh build,
offline app) green; `overview`, `overview-chart-labels`, `copy-1/2/3`, `states`, `match-shared`,
`shell`, `smoke`, `readable-labels`, `logo`, `treasury`, `match-treasury` green at 1440/834/390;
768×1024 driven through the Playwright MCP. Screenshots: `shots/`.

Found and fixed during the sweep: at 390 the floor label moved onto the late-path label (the
"crowded" rule fired on phone widths); the low-point label crossed the floor line when the low
point sat just above it at the right edge (now placed by a fit search).

Inherited, not changed: the chart's per-point tooltip buttons are 32 px (as on Treasury's chart);
every value they show is also in the "View cash data" table, whose rows need no tap.

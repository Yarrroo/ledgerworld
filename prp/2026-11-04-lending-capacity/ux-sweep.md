# UX sweep: Lending as one answer

> Source: raw.md, workflow.md. Evidence for the dev-ux bar; the check itself is
> `bash scripts/ux-check.sh e2e/ux/match-lending.spec.ts`.

| Width | Result |
|---|---|
| 1440x900, light and dark | headline, the whole main object and Compare funding plans in the first viewport; nothing sideways |
| 834 (tablet) | the object switches to its narrow layout under 1000 px of drawing; action in the hero; nothing sideways |
| 390x900, light and dark | headline, object (column, You, venue with both links) and the action under it in the first viewport (asserted by the check; 853 px measured before the last tightening); nothing sideways |
| 390 phone controls | every control of the screen (action, rehearsal, repayment toggle, folds) at least 44 px; Menu at least 44 px, lists the six screens, Escape closes it and focus returns to Menu |
| Word budget at 1487 | 320 visible words; the accepted design shows 356, so Lending's budget is now 356 + 15 % |

Runs in this slot, all green: `match-lending` (3 widths + judge path 12/12), `lending`,
`copy-1`, `copy-3`, `states`, `match-shared`, `shell`, `smoke`, `meta`; frontend unit tests 383.

Screenshots in `shots/` were taken before the last phone tightening (the column went from 180 to
160 px on a phone for more room under 900 px); the check re-takes both themes at
1440x900 and 390x900 on every run.

Recorded, not done here:
- The design's manual theme toggle is a shared-shell control (board step 4); dark follows the
  system as on every other screen.
- The shell's own breadcrumb and context-bar links stay under 44 px on a phone (shared shell).

# Panel index by drawn position (board item 138) — Close-out
> Close-out (/dev-close). Source: cross-family review finding l_b77b0d3e56 (correction).
> Date: 2026-10-29

## What shipped
- `frontend/src/api/v1.js` (`ScreenShell`): the panel index orders the marked panels by their
  boxes (top, then left) before choosing the one in view and the page-end fallback. A row reads
  as its left panel. Before, both walked the panels in DOM order, so on Live simulation at two
  columns (controls; graph beside feed; cash below) "World map and actors", last in the markup,
  was marked while Cash paths was read and at the page end.
- The index list keeps the screen's own order (the phone reading order); on a phone the drawn
  order is the DOM order, so nothing there changes.
- `frontend/tests/unit/simulation-panel-index.spec.js`: drawn geometry for 1440, 834, 390 and
  the expanded graph; 4 of 5 tests fail before the fix (phone passes either way).
- `e2e/ux/simulation-index.spec.ts`: the real layout at 1440, 834, 390, graph expanded and not;
  1440 and 834 fail before the fix ("at the page end: expected Cash paths, received World map
  and actors").
- `prp/2026-10-29-ux-shell/design.md`: the panel index rule now says "by where it is drawn".

## Verification
- `npx vitest run` (frontend): 13 files, 244 tests passed.
- `vite build`: built.
- `bash scripts/ux-check.sh e2e/ux/simulation-index.spec.ts`: passed at 1440, 834, 390, then
  the judge path (12 runs) green.
- `bash scripts/ux-check.sh e2e/ux/shell.spec.ts`: 13 passed (Treasury panel index unchanged),
  judge path green.

| Check | 1440 | 834 | 390 |
|---|---|---|---|
| Each drawn row read marks its panel (left panel of the row) | pass | pass | pass |
| Page end marks the bottom row: Cash paths (two columns), World map and actors (phone) | pass | pass | pass |
| Same with the graph expanded (feed and cash each a row under it) | pass | pass | pass |
| Index list keeps the screen's order | pass | pass | pass |

Screenshots of the page end per width, graph expanded and not, were taken with `UX_SHOTS` and
looked at (1440: Cash paths marked; 390: World map and actors marked).

## Follow-ups / known gaps
- At 390 px the index strip scrolls sideways and does not bring the marked link into view: at
  Simulation's page end the marked "World map and actors" sits off the strip's right edge.
  Present before this change; a separate fix.
- At two columns the index lists Cash paths second while the page draws it last. The finding
  asked to keep the phone reading order, so the list order stays as it was.

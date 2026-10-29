# Chosen panel kept through its scroll (board item 139) — Close-out
> Close-out (/dev-close). Source: cross-family review finding on l_b77b0d3e56 (correction).
> Date: 2026-10-29

## What broke
Choosing a panel from the index called a smooth `scrollIntoView` and pinned the panel, but the
shell's tracker cleared the pin on any scroll frame where the chosen panel was outside the view.
A smooth jump starts with its target below the view, so the pin dropped on the first frame; the
index then marked each panel the page passed, and a jump the page end stopped short of (a target
whose top cannot reach the sticky header) finished on the bottom row's panel instead of the chosen
one.

## The fix
`frontend/src/api/v1.js` (`ScreenShell`):
- A choice starts a *flight*: while it lasts the chosen panel is marked on every frame (without
  measuring the panels).
- The flight ends on the page's `scrollend`. Where the browser sends none, it ends after 150 ms
  without a scroll event; where it does, a stall before or during the scroll (a long task) does
  not end it, and 2 s without a scroll event is the backstop.
  Then the page decides as before, with the chosen panel kept at the page end while it is in view.
- The reader moving the page ends the flight and the choice: a page scroll within 250 ms of their
  wheel, touchmove, press on the page's own scrollbar or scroll key outside a form field. Input
  that does not move the page (a wheel at the end, a swipe of the index strip, Space on a button),
  a click in the page and typing in a field leave the choice. A route change ends it and re-tracks
  at once. The index then follows the page, and the page end marks the bottom row.
- Reduced motion takes the same path with an instant jump.

`prp/2026-10-29-ux-shell/design.md`: the panel index rule says so.

## Regression guard
- `frontend/tests/unit/panel-index-jump.spec.js`: a hand-drawn 2600 px page, the smooth scroll
  played frame by frame, timers faked, `scrollend` support set per test. 14 tests. Against the
  code before this item, 4 of the first 6 fail (intermediate frames; no `scrollend`; reader
  scrolls after the jump; reachable target); against the first fix, the 4 vet round 1 tests fail
  (a stall mid-scroll; input that does not move the page; a scrollbar drag; a route change
  mid-flight); against round 1, the 4 round 2 tests fail (a late first frame; a click mid-scroll;
  typing in a field mid-scroll; a route change with nothing on the page changing).
- `e2e/ux/panel-jump.spec.ts`: the real app at 1440, 834 and 390. It finds a panel below the view
  that the page end stops a jump short of and that is not the bottom row's (Overview's Exposure
  preview at 834; Lending's Facilities at 390, and at 1440 in a 640 px tall window, since no
  screen has one at 900 px), records the marked link on every frame from the click until the page
  is still, smooth and reduced motion, then PageUp and End. Fails at all three widths before the
  fix ("every frame after the click": other panels marked mid-scroll); passes after.

## Verification
- `npx vitest run` (frontend): 14 files, 258 tests passed.
- `vite build`: built.
- `bash scripts/ux-check.sh e2e/ux/panel-jump.spec.ts`: 3 passed (1440, 834, 390), judge path
  green; screenshots of each width after the jump looked at (chosen panel marked at the page end).
- Original accept re-run: `e2e/ux/shell.spec.ts` 13 passed and `e2e/ux/simulation-index.spec.ts`
  3 passed, judge path green each time.
- Repeat runs of the tests that read a clock: the unit spec 20 of 20 green; the e2e spec
  `--repeat-each=20` at three widths, 60 of 60 green, against one app boot.
- `checks/no_secrets.py`, `checks/attribution.py`: green. No Python changed (ruff, pytest untouched).
- Vet: T2 (size: 337 changed lines), `/code-review medium` and `/simplify`, two rounds (the cap).
  Round 1: 11 findings, 9 applied (6 proven by fails-before tests), 2 recorded. Round 2: 9
  findings, 8 applied (4 proven), 1 recorded (Firefox scrollbar, below). Round 2's fixes were
  checked by their tests and the browser specs, not by a third review.

## Docs updated
- `prp/2026-10-29-ux-shell/design.md`: the panel index rule.
- `ScreenShell`'s doc comment in `frontend/src/api/v1.js`.

## Known gaps
- Where the browser sends no `scrollend` (older Safari), a stall over 150 ms mid-scroll still ends
  the flight early; the chosen panel is then kept only once it is in view.
- A scrollbar drag is recognised only by a press on the page's own scrollbar that Chromium reports
  as a pointerdown on the root; Firefox sends none, so there a drag during a flight keeps the chosen
  panel marked until the drag stops (up to `scrollend`).
- No backfill: the change is client-side state only.

# Correction: the evidence graph draws when its disclosure opens. Close-out
> Close-out (/dev-close). Source: cross-family review of the UX 5 simulation panels
> (`Simulation.vue:149-153`, the graph blank on first opening). Date: 2026-10-29

## What shipped
- Cause: GraphPanel sizes its drawing from its box when its data changes, and redraws otherwise
  only on a window resize. The Live simulation graph first draws inside the closed "Evidence
  graph" disclosure, where the box has no height. Opening the disclosure changes neither the data
  nor the window, so the graph stayed drawn for a 0-height box: blank or scattered until the round
  changed or the window resized.
- `frontend/src/components/LiveGraph.vue`: exposes `redraw()`, which hands the same data over
  again as a new object, so GraphPanel draws it at the box's current size.
- `frontend/src/views/Simulation.vue`: the disclosure's `toggle` handler calls `redraw()` when it
  opens. The selected round is what is drawn. An unchanged poll still hands over the same object
  and redraws nothing. GraphPanel (upstream) is unchanged.
- `frontend/tests/unit/simulation-graph-selection.spec.js`: three cases with the real GraphPanel,
  where a box inside a closed disclosure measures 0. They cover first opening at the open size,
  opening after the cursor moved, and an unchanged poll after opening keeping the drawing and its
  selection.
- `e2e/ux/simulation-evidence-graph.spec.ts`: the same check in Chromium at 1440, 834 and 390 px.
  The viewBox matches the open box, nodes are visible, the round is kept and the page has no
  sideways scroll.

## Verification
- Reproduced first. The unit cases failed on the original view (viewBox stayed `0 0 0 0`). The
  e2e spec failed at all three widths, the drawn height differing from the box by 231, 418 and
  270 px (`ux/before-tablet-834-evidence-graph.png`).
- After the fix: `npx vitest run` 285 passed. `bash scripts/ux-check.sh
  e2e/ux/simulation-evidence-graph.spec.ts` passed 3 of 3 widths, and its judge path passed 12 of
  12. `checks/no_secrets.py` and `checks/attribution.py`: ok. Python is untouched, so pytest and
  ruff were not run in this slot.
- Vet: T1, 1 round, 2 low findings. 1 applied: the unit spec's layout stub moved into `beforeAll`
  so it no longer leaks into the file's other suite. 1 recorded: see below. 0 open.

| Check | 1440 | 834 | 390 |
|---|---|---|---|
| Drawn at the open box size on first opening | ✓ | ✓ | ✓ |
| Nodes visible | ✓ | ✓ | ✓ |
| Round chosen while closed kept | ✓ | ✓ | ✓ |
| No sideways page scroll | ✓ | ✓ | ✓ |

## Docs updated
- None beyond the two components' own comments. No brief describes the disclosure's drawing.

## Follow-ups / known gaps
- Recorded rather than applied: a `ResizeObserver` in LiveGraph would redraw on every box change,
  not only on opening. It would also redraw on unrelated layout shifts and drop the selection that
  an unchanged poll must keep.
- On a phone, right after opening, two nodes sit at the box edge while the upstream force layout
  settles (`ux/phone-390-evidence-graph.png`). This was there before the fix and is not part of
  this item.

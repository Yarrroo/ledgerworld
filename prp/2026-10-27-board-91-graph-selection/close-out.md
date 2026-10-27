# Graph selection follows the round cursor — Close-out
> Close-out (/dev-close). Source: cross-family review of T18 Live Simulation (finding at
> `frontend/src/views/Simulation.vue:209`).
> Date: 2026-10-27

## What broke, and why
Picking a node or edge in the Live Simulation graph and then scrubbing to an earlier round removed
it from the graph but left its details open. The upstream `GraphPanel` keeps its selection across
`graphData` changes, and the screen fed it a new graph per round and run without closing it.

## What shipped
- `frontend/src/views/Simulation.vue` — closes the graph's details when the shown run or the cursor
  round changes, an unloaded round included; a poll that moves neither keeps them.
- `frontend/src/components/GraphPanel.vue` (upstream) — `defineExpose({ closeDetailPanel })`, its
  own close action, nothing else; listed in `ATTRIBUTION.md`.
- `frontend/tests/unit/simulation-graph-selection.spec.js` — 5 tests on the real `GraphPanel`:
  node and edge picks closed by a scrub back, by an unloaded round, by a run change; kept by an
  unchanged poll. 4 fail before the fix.
- `frontend/tests/unit/simulation-view.spec.js` — the graph stub exposes the same method.

## Verification
- `npm --prefix frontend run test:unit` — 106 passed; the T18 accept's spec plus the new one, 24
  passed; the new spec run 20 times, 0 failures.
- `npm --prefix frontend run build` green; `checks/attribution.py` ok; `checks/no_secrets.py` ok.
- Browser: Playwright at 390 / 768 / 1440 — `ux-sweep.md`.
- Vet: T1, round 1, 0 applied, 2 recorded (shared spec helpers kept apart from the T18 spec to
  avoid merge collisions; a selection-reconciling `GraphPanel` would change upstream behaviour).

## Follow-ups / known gaps
- The upstream graph view draws on a data change or a resize, never on mount, and the screen
  mounts it only after the run loads: a finished run opens with an empty graph until the operator
  scrubs or resizes. Pre-existing; a fix for its own item.

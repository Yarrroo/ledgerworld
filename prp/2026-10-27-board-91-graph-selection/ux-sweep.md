# Graph selection follows the round cursor — UX spot-check

> Correction of the T18 Live Simulation screen: a node or edge picked in the graph stayed in the
> details panel after scrubbing to a round where it does not exist. Engine: Playwright MCP
> (Chromium) against the Vite dev server; GET /api/v1/runs/run-demo answered by a route stub
> serving a RunResponse built from `design/modules/ui/fixtures/scrubber.json`. Screenshots in `ux/`.

Flow per tier: open `/simulation?run_id=run-demo` (round 5) → pick the `actor:lender` node (first
acts in round 5) → details open → click tick 4 → details closed, graph redrawn with 3 nodes.

| Check | Phone 390×844 | Tablet 768×1024 | Desktop 1440×900 |
|---|---|---|---|
| Details open on pick at round 5 | pass | pass | pass |
| Details closed after scrub to round 4 | pass | pass | pass |
| Round 4 graph holds only its 3 nodes | pass | pass | pass |
| No horizontal page scroll | pass (0 px) | pass (0 px) | pass (0 px) |

Edge picks, unloaded rounds, a run change and an unchanged poll are held by
`frontend/tests/unit/simulation-graph-selection.spec.js` (real `GraphPanel`, not a stub).

Deferred (pre-existing, outside this item): the upstream graph view draws on a data change or a
window resize, not on mount, and the screen mounts it only once the run has loaded — so opening a
finished run shows an empty graph until the operator scrubs or resizes. The sweep and the spec
dispatch a resize to draw it.

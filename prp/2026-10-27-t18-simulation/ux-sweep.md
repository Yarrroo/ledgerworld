# T18 · Live Simulation — UX sweep

> Verification evidence (build stage 4, UX bar). Engine: Playwright MCP (Chromium) against the Vite
> dev server, API answered by a local stub serving a RunResponse built from `fixtures/scrubber.json`
> plus one replayed policy branch. Screenshots in `ux/`.

| Check | Phone 390×844 (light) | Tablet 768×1024 (dark) | Desktop 1440×900 (light, reduced motion) |
|---|---|---|---|
| No horizontal page scroll | pass (0 px) | pass (0 px) | pass (0 px) |
| Reading order | labels → controls → cash → feed → graph (tops 0/310/958/1329/1636) | graph beside feed, cash below | graph beside feed, cash below |
| Live panel dark in both themes | pass (`rgb(14,21,32)`) | pass | pass |
| Scrub flow | — | click 5, ←: round 4, feed `i-r4-borrower-c-1` only, `USD 42,000.00` | tick 4 → fork submitted (payload asserted in the unit spec) |
| 44 px targets in the live panel | fail → fixed (reused graph toolbar 32 px; overridden here) | pass | pass |
| Replay label on the replayed branch | pass | pass | pass |
| Token never in DOM, URL or storage | — | — | pass |
| Reduced motion: tick transition | — | — | pass (`0s`) |
| Failed POST is shown, not retried | — | — | pass (`role=alert`; the stub refused the preflight) |

Findings fixed in this round: graph toolbar under 44 px; the reused graph rendered on paper inside
the dark panel (now inverted with hues kept; the phone shot predates this fix, tablet and desktop show it); a 2xx fork reply without `branch_ids` crashed the
render (now reads as an empty list). Deferred: none. No durable Playwright harness exists in the
repo; the behaviour is held by `frontend/tests/unit/simulation-view.spec.js`.

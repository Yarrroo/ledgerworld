# HANDOFF — UX 3–6 panels

Build `design.md` in this order, one commit per board item, each with its spec under `e2e/ux/`:

1. 129 Treasury: `DetailSheet.vue`, `CashChart.vue`, `views/Treasury.vue`, `e2e/ux/treasury.spec.ts`.
2. 130 Lending: `WorldMap.vue`, `api/world.js`, `views/Lending.vue`, `e2e/ux/lending.spec.ts`.
3. 131 Simulation: `views/Simulation.vue` (template and styles; script rules kept),
   `e2e/ux/simulation.spec.ts`.
4. 132 Decisions: `views/Decisions.vue`, `e2e/ux/decisions.spec.ts`.

Accept per item: `bash scripts/ux-check.sh e2e/ux/<screen>.spec.ts` and the frontend unit suite.
Never: a new API field, a summed mixed-currency figure, a number not served by the API.

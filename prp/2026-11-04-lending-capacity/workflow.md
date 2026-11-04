# Workflow: Lending around what the capacity rests on

> Execution plan (design folded in). Source: raw.md. Next: implement → close-out.

## Shape

- **`CapacityLoop.vue`** (new, Lending only): one SVG with a text alternative. The column at a
  fixed height for settled known, each part a segment at the same scale (K_p solid, committed and
  any non-zero pledged or obligations hatched, the floor cross-hatched with its threshold line),
  the zero parts named once in words; the dependency arrow to the You box; the venue block at the
  same scale, the dashed "counted inside" link from the column and the line from your expected
  withdrawal back to You. Two layouts by the measured width (phone under 1000 px of drawing).
  Party groups carry `data-test="map-node"`; a visually hidden list `relations` states every link.
- **`Lending.vue`**: the hero's headline is the answer (the earlier lead variants for unknown,
  zero and reduced), its subtitle the "Not $60,000" sentence, the lead its tooltip; Compare
  funding plans in the hero action with its helper as text (on a phone, under the main object
  instead); the main object or, for a reading that is not whole, the earlier capacity block;
  then facility terms (definition lists, repayment disclosure) beside the venue freeze (reason
  as visible text); then three folds: Capacity breakdown, Source and authority (named so: the shared check keeps "How we know" off every screen), When the reading changes.

## Phases and gates

1. Component + view + `tests/unit/money-views.spec.js` (headline, column segments equal the
   API's parts at one scale, the venue block at the same scale, fallback on reduced/unobserved,
   freeze reason visible) — `npm --prefix frontend run test:unit`.
2. Old paths aligned: every e2e spec that read the bridge, the exposure map, the facility table
   or the old headline (`lending`, `copy-1`, `copy-3`, `states`, `routes.ts`, `match-lending`).
3. `bash scripts/ux-check.sh e2e/ux/match-lending.spec.ts` (first viewport at 390x900 and
   1440x900 in both themes, no sideways scroll, 44 px targets, word budget, judge path).

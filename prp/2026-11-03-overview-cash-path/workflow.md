# Workflow: Overview around the 72-hour cash path

> Execution plan (dev-build stage 3, design folded in). Source: raw.md. Next: implement → close-out.
> Tier: solo, one pane.

## Shape

- **API** — `ScenarioPreview.outlook` (C6, additive, default `[]`): `views._late_outlook` moves the
  scenario's `flow_id` by `delay_h` on a copy of the account views and runs the same `_outlook`
  as the observed path. Schema regenerated with `python -m app.finance.schemas`.
- **`CashPath.vue`** (new, Overview only) — step line from $0, floor as a full-width horizon with
  a hatched zone, split bar at h0, low point labelled with its gap, late path dashed with its
  breach in the warning colour, events under the axis (the obligation links to its Treasury row),
  one tooltip control per point. Treasury keeps `CashOutlook.vue` unchanged: its own design and
  checks still hold, so the new chart is a sibling, not a rewrite of the shared one.
- **`Overview.vue`** — the hero's headline is the answer, its subtitle the condition (the lead
  sentence stays its tooltip), the hero's action slot holds the equation; under the chart the
  what-if (tag, Hide path, heading, why, table, Open simulation); four folds: cash data, next
  obligation, world exposure, source & scenario.

## Phases and gates

1. API field + `tests/api` (late path equals the observed path with the receivable past the
   horizon; a scenario moving no known flow serves none) — `pytest tests/api tests/contracts`.
2. Chart + view + `tests/unit/overview-panels.spec.js` (floor, trough and late path read back off
   the chart's axis equal the API values) — `npm run test:unit`.
3. Old paths aligned: every e2e spec that read the four-figure strip, Preview scenario or the
   static headline (`overview`, `overview-chart-labels`, `copy-1`, `copy-3`, `states`,
   `match-shared`, `routes.ts`, `judge-path`) and `money-views.spec.js`.
4. `bash scripts/ux-check.sh e2e/ux/match-overview.spec.ts` (first viewport at 390x844 and
   1440x900 in both themes, no sideways scroll, 44 px targets, word budget, judge path).

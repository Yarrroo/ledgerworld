# Close-out: Overview around the 72-hour cash path

> Source: raw.md, workflow.md, ux-sweep.md.

## What changed

- **API** — `GET /api/v1/overview` serves `scenario.outlook`: the observed outlook with the
  prepared scenario's flow moved by its `delay_h` (`backend/app/api/v1/views.py:_late_outlook`).
  C6 change is additive (`ScenarioPreview.outlook`, default `[]`); schema regenerated.
- **Overview** — headline is the answer ("Payroll is covered."), subtitle its condition, the
  equation settled − reserved = spendable beside it; `CashPath.vue` draws the API path, the
  floor horizon, the low point, the split bar at now and the dashed late path; what-if table,
  Hide path and Open simulation under the chart; cash data, next obligation, world exposure and
  the scenario as run fold below. Covers the chart-as-data and phone-order
  requirements too.
- **Not changed** — Treasury's `CashOutlook.vue` (the plan named it; Treasury still uses it,
  so the Overview chart is a new sibling component instead of a rewrite of the shared one).

## Verified

| Gate | Result |
|---|---|
| `npm --prefix frontend run test:unit` | 378 passed |
| `bash scripts/ux-check.sh e2e/ux/match-overview.spec.ts` | green (1440/834/390 + judge path 12/12) |
| other aligned e2e specs (12 files) at 1440/834/390 | 164 passed; `overview` and `overview-chart-labels` re-run green through `ux-check.sh` after the review fixes |
| `pytest tests/api tests/contracts checks/tests deploy/tests backend/tests/test_demo_baseline_h0.py` | 438 passed (then 146 on `tests/api tests/contracts` after the review fixes) |
| ruff, `checks/no_secrets.py`, `checks/attribution.py` | green |

The full `checks/merge.sh` runs once over the merged batch; it was not run here.

## Review

Two review rounds (high, then medium on the fixes), plus a security read with no findings. 12
correctness findings applied, each with a test that fails before the fix, and 7 quality or doc
fixes. The correctness ones: the late path is not served when
moving the flow leaves P unchanged; "is covered" only for an obligation inside the projection;
the condition names the receipt only when its late path breaks the floor; the y axis steps over
the whole span; the late low label and its caption stay inside the chart and clear of the
observed label; Hide path hides the what-if from the tooltips; the cash data names a receipt
the what-if moves, onto a new time or a planned one; an unknown what-if point reads unknown.

Recorded, not applied:
- The chart's 32 px point buttons stay below 44 px (see ux-sweep.md).
- When the next obligation lies past the projection, the headline falls back to "Cash stays
  above the reserve floor."; that sentence is true over the projection, and the fold under the
  chart shows the obligation and its hours.
- On a chart too narrow for the late low label on either side, it can still run past the right
  edge; no recorded answer reaches it.
- With every value at or below $0 the axis keeps two steps above $0 (up to nine gridlines).
- The chart's own events row does not mark the moved receipt; the cash data does.

## Reflection

The late path had to come from the API: the accept ("late-path values equal the API
values") ruled out shifting a flow in the browser, and the server already had the projection
function, so the field cost twenty lines. Two label-placement bugs only showed up at 390 px
with a stressed answer; the chart-label spec caught both and now guards them.

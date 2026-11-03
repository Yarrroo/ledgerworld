# Close-out: Overview around the 72-hour cash path (board item 176)

> dev-build stage 5. Source: raw.md, workflow.md, ux-sweep.md.

## What changed

- **API** — `GET /api/v1/overview` serves `scenario.outlook`: the observed outlook with the
  prepared scenario's flow moved by its `delay_h` (`backend/app/api/v1/views.py:_late_outlook`).
  C6 change is additive (`ScenarioPreview.outlook`, default `[]`); schema regenerated.
- **Overview** — headline is the answer ("Payroll is covered."), subtitle its condition, the
  equation settled − reserved = spendable beside it; `CashPath.vue` draws the API path, the
  floor horizon, the low point, the split bar at now and the dashed late path; what-if table,
  Hide path and Open simulation under the chart; cash data, next obligation, world exposure and
  the scenario as run fold below. Absorbs board rows 171 (chart as data) and 172 (phone order);
  supersedes 175.
- **Not changed** — Treasury's `CashOutlook.vue` (the board step named it; Treasury still uses it,
  so the Overview chart is a new sibling component instead of a rewrite of the shared one).

## Verified

| Gate | Result |
|---|---|
| `npm --prefix frontend run test:unit` | 370 passed |
| `bash scripts/ux-check.sh e2e/ux/match-overview.spec.ts` | green (1440/834/390 + judge path 12/12) |
| other aligned e2e specs (12 files) at 1440/834/390 | 164 passed |
| `pytest tests/api tests/contracts checks/tests deploy/tests backend/tests/test_demo_baseline_h0.py` | 438 passed |
| ruff, `checks/no_secrets.py`, `checks/attribution.py` | green |

The full `checks/merge.sh` is the landing train's; it was not run in this slot.

## Reflection

The late path had to come from the API: the board's accept ("late-path values equal the API
values") ruled out shifting a flow in the browser, and the server already had the projection
function, so the field cost twenty lines. Two label-placement bugs only showed up at 390 px
with a stressed answer; the chart-label spec caught both and now guards them.

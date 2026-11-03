# Overview: one payroll decision around the 72-hour cash path

> Requirements. Next: workflow → implement. Depth: Medium (one screen and
> one additive API field; design inputs already approved, so the design is folded into the
> workflow).

## Goal

The Overview's first screen answers one question: is payroll covered over the next 72 hours,
and what breaks if the expected receipt is late. Design input: the accepted "R" candidate of the
2026-10-31 Overview trial (headline with its condition, settled − reserve = spendable, a step
chart with the reserve floor as a full-width horizon and a hatched zone below it, the trough
labelled with its distance to the floor, a dashed hypothetical late-receipt path, a short
what-if table beside Open simulation), merged with the judge's picks from P and S (split bar at
"now", event labels under the axis, Hide path, Inspect payroll link).

## Acceptance (pre-registered)

1. At 390x844 and 1440x900, light and dark: the headline answer, the cash-path chart with its
   floor line, and Open simulation are visible without scrolling.
2. The chart's floor, trough and late-path values equal the API's values for the same snapshot;
   nothing on the page invents a number.
3. No horizontal overflow at 390; key controls at least 44 px on a phone.
4. A viewport sweep at phone, tablet and desktop, with screenshots.
5. `npm --prefix frontend run test:unit -- tests/unit/overview-panels.spec.js`,
   `bash scripts/ux-check.sh e2e/ux/match-overview.spec.ts` and `bash checks/merge.sh` green.

## Settled decisions

- The late path is the API's: `scenario.outlook` on `GET /api/v1/overview` is the observed P
  with the scenario's flow moved by its `delay_h` (server side, `views._late_outlook`). The
  browser draws and formats it; it never shifts a flow itself.
- Without a prepared scenario the chart draws only the observed path, and the what-if block
  says no prepared run exists.
- The next obligation, the world exposure and the scenario's parameters stay on the page as
  folded depth below the decision, so no figure the product served is lost.

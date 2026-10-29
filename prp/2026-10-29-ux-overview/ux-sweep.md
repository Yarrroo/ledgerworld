# UX sweep — Overview O1–O6 (board item 128)

Engine: `@playwright/test` (headless chromium) through `bash scripts/ux-check.sh
e2e/ux/overview.spec.ts` against the offline app (fake provider, SQLite, prepared demo run),
video on; then `e2e/judge-path.spec.ts` (contrast, 44 px controls, overflow, focus, reduced
motion) on the same app. Tiers: 1440×900, 834×1112, 390×844. Two answers drive the spec: the
app's own, and the recorded baseline (`valid-overview-demo-baseline.json`) for the handoff's
numbers.

| Check | 1440 | 834 | 390 |
|---|---|---|---|
| O1: complete snapshot id, currency, company, provider, as of; Read context again re-reads | pass | pass | pass |
| O2: figures equal the API; one metric open at a time; inputs are the API's; 44 px picks; strip figures in the heading serif | pass | pass | pass |
| O2: settled and spendable open Treasury with the account row focused, in view, same snapshot | pass | pass | pass |
| O3: one focusable point per API point, tip with offset, UTC, P, event; hover (mouse) or tap (touch); View data table equals the points | pass | pass | pass |
| Baseline: 70k / 20k / 50k due t=40 h / 10k; P 70k, 90k, 40k, 55k, 55k at t=0, 12, 40, 48, 72; lowest kept and green; payroll opens its focused Treasury row | pass | pass | pass |
| O5: relations as text equal the API's; capacity links Lending; Explore world opens the prepared run | pass | pass | pass |
| O6: labelled Hypothetical; read-only preview; no observed figure changes; Open simulation follows the run | pass | pass | pass |
| No prepared run: Explore world, Open simulation and Preview say why; no obligation is a neutral state, not a zero | pass | pass | pass |
| No sideways scroll | pass | pass | pass |
| Judge path, light + dark: contrast AA, 44 px buttons, focus, reduced motion | pass (1440, 1280) | — | pass |

Screenshots were reviewed at each width, light and dark, with a metric open, the scenario preview
open and a point focused. Layout per the handoff: 60/40 outlook and obligation/exposure on
desktop; strip 2×2 and a single column at tablet; on phone the next obligation comes before
the chart. Found in the review, fixed in the vet: the strip figures had lost the heading serif
in a CSS merge (now asserted by the spec).

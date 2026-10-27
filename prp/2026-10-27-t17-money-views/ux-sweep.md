# UX sweep: Overview, Treasury, Lending

> Evidence (dev-ux, standard depth). Source: design.md. Engine: Playwright MCP (Chromium) against
> `vite` dev on :3000, the API answered by the recorded C6 examples (overview and lending under the
> venue freeze, treasury with the receivable delayed). Screenshots in `ux/`: a subset (phone and desktop in light, phone in dark); the measurements cover every tier.

| Check | Phone 390×844 | Tablet 768×1024 | Desktop 1440×900 | Dark (390, 1440) |
|---|---|---|---|---|
| No horizontal page scroll (all calculations open) | pass ×3 | pass ×3 | pass ×3 | pass ×6 |
| Primary controls ≥ 44 px (nav, Refresh, summaries, CTAs) | pass, 0 below | pass | pass | pass |
| Money figures do not clip | pass | pass | pass | pass |
| Mode label in view when scrolled to the bottom | pass (sticky banner, 73 px) | pass (44 px) | pass | pass |
| Tables scroll inside their own region | pass | pass | pass | pass |
| Keyboard: nav → Refresh → each calculation → table regions, visible 3 px focus ring; Enter opens a calculation | pass (phone, overview and lending) | — | — | — |
| Console warnings | 0 after the fix below | | | |

Flows driven: each screen loads, every "How this is calculated" opens, and Refresh is reachable.
On Lending under the freeze, "Fund from the pool" is disabled and says why. On Overview,
"Open simulation" is disabled because the recorded overview has no prepared run and there is no
simulation route yet.

Fixed during the sweep: the mode label scrolled out of view on phone, so the banner (mode and
source) is now sticky and as of and Refresh moved under the title. Probing for a missing route
logged three router warnings, so `routeExists` now reads `getRoutes()`. Scrollable table regions
had no focus ring and now have one.

Not done here: there is no durable viewport test, because this repo has no Playwright harness yet
(T26 owns `e2e/`). Contrast was not measured on the rendered page; the token pairs were computed
from their hex values, recorded in `tokens.css`.

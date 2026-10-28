# UX sweep — the shared shell (board item 127)

Engine: `@playwright/test` (headless chromium) through `bash scripts/ux-check.sh e2e/ux/shell.spec.ts`
against the offline app (fake provider, SQLite, prepared demo run), video on; then
`e2e/judge-path.spec.ts` (contrast, 44 px controls, overflow, keyboard focus, reduced motion) on
the same app. Tiers: 1440×900, 834×1112, 390×844 (the handoff's widths); judge path adds 1280 and
dark at each width.

| Check | 1440 | 834 | 390 |
|---|---|---|---|
| Layout: 208 px sidebar / 72 px rail / 48 px header + drawer | pass | pass | pass |
| Six labelled links, active state follows the route (3 hops) | pass | pass | pass |
| Drawer: focus to current link, Escape returns focus; closes on the current link and the logo; page behind inert; closes on leaving phone width | — | — | pass |
| Breadcrumb, mode, model, as of, snapshot, Refresh on all six screens | pass | pass | pass |
| No sideways page scroll on all six screens | pass | pass | pass |
| Ivory surface, ink, Source Serif 4 h1, Inter text, fonts loaded, no off-origin request | pass | pass | pass |
| Panel index: first marked at top, last at end; a chosen panel scrolls under the header and stays marked (second-to-last and first) | pass | pass | pass |
| Judge path, light + dark: contrast AA, 44 px buttons, focus ring, reduced motion | pass (1440, 1280) | — | pass |

The drawer and kept-choice rows were added in the vet round; both failed on the earlier shell
(phone drawer stayed open on the current link; at 834 px the chosen panel lost its mark) and pass
now. Screenshots were reviewed at 1440 light and dark, 834 and 390 (page and open drawer); each
spec run records a video per tier under the run's `artifacts/`.

Deferred, not defects of this item: the Simulation screen's live panel keeps its own dark
instrument styling (a later UX pass); the logo is a drawn faceted stand-in until the vector asset
exists; the upstream research screens now fall back to local fonts.

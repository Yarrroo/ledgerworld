# UX 1 — the shared shell and visual system

Source: `prp/2026-10-29-ux-pass/HANDOFF.md`, sections "Shared visual system & components" and
"Responsive layout & accessibility" (shell row). Tier: Brief (one module, reversible, no
reviewer pack on this node).

## What changes

One component, `ScreenShell` (`frontend/src/api/v1.js`), renders every finance screen. It is
rebuilt; the six views keep their bodies and gain only `data-panel` labels.

| Width | Shell |
|---|---|
| ≥1200 px | 208 px sidebar: logo + wordmark, six labelled links, active link marked (`aria-current="page"`, sage fill + forest rule) |
| 768–1199 px | 72 px icon rail; each link an icon with its name beneath (accessible name = the name) |
| <768 px | 48 px header: logo, mode, Menu button; a drawer (`nav.lw-nav`) lists all six; Escape and link choice close it, focus returns to Menu |

Above the page title on every width: breadcrumb (`LedgerWorld › Screen`, plus `run <id>` when the
route carries one) and a context bar — mode (`data-test="mode"`), model, as of (UTC · local),
snapshot / source (`data-test="source"`). Below it, the **panel index**: one link per element the
view marks `data-panel="<name>"`; the one nearest the top of the viewport carries
`aria-current="true"` and updates while scrolling (scroll listener + rAF, no focus moves).

Visual system: tokens in `frontend/src/styles/tokens.css` — ivory `#FAF8F3`, ink `#17251E`,
forest `#174A38` (primary/buttons), logo blue `#2469E8` (logo only), sage `#E9EEE7` (selected),
rule `#D8D7CD`, terracotta `#A8432E` (warning). Source Serif 4 for h1/h2, Inter for everything
else, both from `@fontsource-variable/*` (bundled woff2, no CDN). Radius 6 px, 44 px targets.
The dark scheme keeps the same roles on a dark forest-ink surface; every text pair stays ≥ 4.5:1,
which `e2e/judge-path.spec.ts` measures.

## Consumers (who reads this shell)

- **The six views** — their `data-test` hooks and `h1` text are unchanged.
- **`e2e/judge-path.spec.ts`** (goal g4, the engine's check): reads `mode`, `source`,
  `main.lw-main[aria-busy]`, `nav.lw-nav` links by name, contrast over `.lw-page`, 44 px
  `.lw-button`s at 390 px. Its Treasury/Lending visit opens the drawer first when Menu is shown.
- **`e2e/walkthrough.spec.ts`** (the recorded demo) navigates by `data-test` links, not the nav.
- **`e2e/ux/shell.spec.ts`** (new) checks the shell in motion at 1440 / 834 / 390.
- **Upstream MiroFish screens** do not use `ScreenShell`; their global styles in `App.vue` stay.

## Not done here

No new route, no per-panel redesign (UX 2+), no exact logo vector (the mark is a drawn
faceted SVG in brand blue until the vector asset exists).

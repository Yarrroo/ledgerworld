# Design match 0 and 1: the shared page and Overview

The live screens are brought onto `prp/2026-10-29-ux-pass/mockups/` per `MATCH.md` (shared items 1–8,
then 01 Overview). Figures still come from the API; an element the API has no field for is left out.

## Consumers

| Who reads it | What it needs from this change |
|---|---|
| A finance lead at 1487, 834, 390 px | The mockup's page: hero, four figures, chart, next obligation, exposure, what-if; detail on demand |
| The judge path (`scripts/judge-path.sh`, goal g4) | Open simulation → Compare policies → View execution → Open receipt, unchanged; the shell's `mode`/`source` hooks |
| Keyboard and screen-reader users | Every tooltip reachable by Tab, named by `aria-describedby`, closed by Escape |
| The six screens' own views | One shell (`ScreenShell`), one hero, one tooltip, one info control; no per-screen copies |
| `checks/word_budget.py` and `e2e/ux/match-*.spec.ts` | The budget rule in one place; the count method in `e2e/ux/words.ts` |

## Shape

```
ScreenShell (api/v1.js) ── header: crumb "LedgerWorld / Page" · "Simulated provider · Scripted agents" | date
   │                        second line "Snapshot … · USD · Synthetic data" (each with a Tip)
   ├─ PageHero.vue ──────── h1 headline · grey subtitle (Tip: the COPY.md lead) · one primary action slot
   ├─ sidebar ───────────── mockup icons, "Simulation", company block at the bottom (from /overview)
   └─ screen slot
Tip.vue ─────────────────── hover · focus · tap open; Escape · blur · second tap close; fixed-position bubble
HowWeKnow.vue ───────────── now an (i) control whose bubble is a Tip: every "How we know" fold becomes one
```

- **Removed everywhere** (shell or shared components, so all six screens change at once): the panel
  index tab row, the header Refresh (a read refreshes when the window regains focus; Retry stays on
  an error), the visible "How we know" folds, the context chips. Per-screen subtext, chips and ids
  under the hero go in this change; per-screen layout rebuilds are their own items (02–07).
- **Kept for its readers**: `data-test` hooks the judge path reads (`mode`, `source`, `settled`,
  `coverage`, `due`, `floor-status`, `open-simulation`) stay on the element that now carries the
  meaning, often inside a Tip; `h1` becomes the hero headline, so the judge path checks the
  breadcrumb's current item for the screen name.
- **Word budget**: `checks/word_budget.py` holds each mockup's hand-counted words and the 15 % slack;
  the specs count the live page with `e2e/ux/words.ts` and ask the script for the number.

## Rejected

- A tooltip library: one 100-line component covers hover, focus, tap and Escape; no new dependency.
- Hiding detail in one fold per page instead of tooltips: MATCH.md item 4 asks for tooltips on every
  metric, point, chip and action; the fold stays only where a screen already has a calculation.

Run footer: Brief tier, unattended pane, no reviewer pack on this node; no publish step (repo only).

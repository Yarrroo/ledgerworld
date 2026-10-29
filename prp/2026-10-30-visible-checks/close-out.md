# The checks read only what the page shows — Close-out
> Close-out (/dev-close). Source: a review of design match 0 (prp/2026-10-29-design-match): its checks
> could not see information move out of view.
> Date: 2026-10-30

## What shipped
- `frontend/tests/unit/visible.js`: one reader of what a page shows. It leaves out a closed tooltip, a
  closed dialog, a closed details' body (its bare text too), `[hidden]`, inline `display: none` and
  `.lw-visually-hidden`, on the element or around it. `onPage(wrapper, test)` is the helper that
  decide-execute, money-views, ux-panels and simulation-view import (they each had a copy that only
  dropped tooltips). `visible.spec.js` pins it.
- Every honesty label a unit spec read from a hidden tooltip (`context-provider`, `source`, How we
  know's Replay note) now also has its visible counterpart asserted: `mode`, `context-line`, the hero
  subtitle.
- `e2e/ux/match-shared.spec.ts`, at 1440, 834 and 390 px: `mode` and `context-line` visible on all six
  screens; What-if read from Simulation's header and from Decisions' subtitle; Replay required in the
  visible header when the API says the figures were replayed; every tooltip whose trigger is on the
  page opened by focus and closed by Escape (it used to count nodes and drive two).
  `e2e/judge-path.spec.ts`: a replayed run's Replay is read from the visible header.

The stronger checks found two labels that were only in a tooltip. Both were fixed by siblings that
landed first, and this change keeps their fixes as they are: Decisions says Replay in the header when
any result was replayed (prp/2026-10-30-decisions-replay-label), and Simulation shows a handoff mismatch
on the page (`e2e/ux/simulation-handoff.spec.ts`). This change is checks only; it touches no screen.

## Verification
- `npx vitest run`: 312 passed on the tree rebased onto main.
- `bash scripts/ux-check.sh e2e/ux/match-shared.spec.ts`: green at three widths, judge path green.
  `… match-overview.spec.ts`: green (before the rebase).
- `checks/attribution.py`, `checks/no_secrets.py`, `ruff check e2e`: green. No Python and no screen
  changed. The full pytest suite belongs to the landing train and was not run here.
- Vet: T2, two rounds, converged. Fixes in the reader (closed details' bare text, the visually hidden
  class) carry failing-first cases in `visible.spec.js`. Recorded, not changed: the e2e replay rule
  restates the API's, which an independent check has to do.

## Follow-ups / known gaps
- Decisions' header says Replay when only some what-ifs were replayed, so a fresh what-if can sit under
  a Replay header. That is item 164's rule as landed; a "partly replayed" wording is its own change.
- jsdom loads no stylesheet, so the unit reader cannot see text hidden by a CSS rule other than
  `.lw-visually-hidden`. The e2e `toBeVisible` checks cover real layout.
- The demo run is fresh, so the e2e Replay branches (match-shared, judge path) do not run offline. The
  unit specs cover them.
- Several e2e specs still use `source` / `context-provider` with `not.toBeEmpty()` to mean "the screen
  has loaded" (shell, copy-3, judge path, walkthrough, narrated take). They check the tooltip's facts on
  purpose and do not stand in for a visible label.

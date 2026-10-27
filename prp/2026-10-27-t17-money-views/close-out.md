# Overview, Treasury and Lending (T17) — close-out

> Close-out (/dev-close). Source: design.md ← briefs/T17.md + design/modules/ui/HANDOFF.md.
> Date: 2026-10-27. Board item 18.

## What landed

- `/overview`, `/treasury` and `/lending` in the existing Vue app: three routes added to
  `frontend/src/router/index.js` (listed in `ATTRIBUTION.md`), with the upstream views still
  reachable.
- `frontend/src/api/v1.js` has the read client (fetch, no retry), the late-answer guard and the
  formatters. It also holds the shared shell: a sticky mode/source banner, links to the screens
  whose routes exist, and the as of time with a Refresh button. T18 and T19 reuse it.
- `frontend/src/styles/tokens.css` has the brief's tokens and two darker status-text variants
  where a light pair fails AA.
- `contracts/examples/c6_api` has four responses recorded from the API on LF-1/LF-2.
- `frontend/tests/unit/money-views.spec.js` runs 30 cases on vitest 4, happy-dom and
  @vue/test-utils.

## Verification

- The item's check (`npm ci`, then `build`, then `test:unit` on the spec): exit 0, 30 passed.
- `uv run pytest -q tests/contracts tests/api`: 126 passed. `no_secrets` and `attribution`: ok.
  The full gate is the landing train's job.
- Vet: T2, 2 rounds, 28 applied (12 proven by tests that fail before the fix, 0 unproven),
  8 recorded, 0 open. Details in `vet-report.md`.
- UX: Playwright sweep at 390, 768 and 1440 px, light and dark, in `ux-sweep.md`. It found no
  horizontal scroll, no control under 44 px and no clipped figure; the mode label stays in view
  while scrolling, and keyboard order and focus are correct.

## Reflect

- Contract gap for the API: `LendingResponse` lists none of the pool's accounts. Lending reads the
  unobserved venue from the same snapshot's overview `completeness.missing` and refuses mixed
  contexts. A `pool_accounts` field on the API would remove the second read.
- Follow-up for the API (T16): serve a `floor_check` per treasury account, so the browser stops
  comparing the lowest point to the floor itself, and serve the terms of each projected point.
- The fixtures assume `as_of = t0`, so `t=N h` is hours from the response's `as_of`. The examples
  were recorded at t0 to match.
- `npm audit` reports high-severity advisories in upstream runtime dependencies (axios,
  @vue/server-renderer, follow-redirects, nanoid, postcss). They predate this change and are not
  this item's to fix.

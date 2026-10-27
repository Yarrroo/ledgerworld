# Lending carries its own completeness — Close-out
> Close-out (/dev-close). Source: cross-family review finding on the T17 money views (P2,
> `frontend/src/views/Lending.vue:103`). Date: 2026-10-27

## What broke
Lending.vue took the pool's unobserved accounts from a second request, `/overview`, and that
request was evaluated at its own `now`. Both responses named the same snapshot, so the context
guard passed. A Lending read at t + 6 h (pool fresh, authority full) could therefore be paired
with an overview read at t + 6 h + 1 s (pool accounts stale, listed missing). The screen then
showed full-authority K_p next to a "Not observed" tile, with funding enabled. Reproduced
against the API with an injected clock (see the API regression test).

## What shipped
- `backend/app/finance/lending.py`: `capacity()` records `unobserved` (the pool-currency cash
  accounts not known at `now`, each `Uncounted`: stale with its `as_of`, or unknown) in the same
  read. `authority` and `stale` are derived from it.
- `backend/app/api/v1/views.py`: Lending returns `capacity.unobserved`. K_p's status comes from
  `cap.stale` and no longer from a second read over every currency.
- `backend/app/finance/schemas.py` and `contracts/c6_api.schema.json` (regenerated): `Capacity`
  gains a required `unobserved`, a list of `NotCurrent` (the same shape as
  `completeness.accounts`, from board item 87). Both pydantic and JSON Schema enforce that authority is full
  exactly when `unobserved` is empty.
- `contracts/examples/c6_api/valid-lending-*.json`: the field has been added to all three examples
  (`lf-stale` is checked byte-for-byte against the API).
- `frontend/src/views/Lending.vue`: the "Not current, not counted" tile maps `capacity.unobserved`
  through `freshness`. The overview is read
  only for the demo run, with the same context check as before.
- `prp/2026-10-27-t17-money-views/design.md` item 7 is marked superseded.

## Verification
- Regressions, each failing before its fix:
  - `tests/api/test_api_v1.py::test_lending_carries_its_own_completeness_across_the_freshness_boundary`.
  - `…::test_lending_capacity_full_authority_means_nothing_unobserved`: the JSON Schema accepted
    a contradiction before the fix.
  - `…::test_k_p_status_reads_only_the_accounts_k_p_counts`: before the fix it returned
    `'stale' == 'known'`.
  - The vitest case "Lending shows one moment across the six-hour freshness boundary, not two":
    before the fix the tile rendered beside full authority.
- `uv run pytest -q` over the API, fixtures, simulation, execution, hunt, finance and decisions
  files that read capacity: 293 passed, 1 skipped, 1 xfailed. `npx vitest run`: 31 passed.
  ruff, `checks/attribution.py` and `checks/no_secrets.py` are ok. The full merge gate is the
  landing train's.
- UX spot-check (`ux-sweep.md`) at 390, 768 and 1440: all rows pass.
- Vet: T2, converged in 2 rounds. 4 findings applied (2 proven, 2 quality), 10 recorded, 0 open.

## Follow-ups / known gaps
- When a pool account is *unknown* (not stale), K_p's status stays `known` while authority is
  reduced. This predates the change and is intended: the `lf2-venue-freeze` UI fixture expects
  "(known funds only)". Revisit only if the design changes.
- Lending still fetches `/overview`, but only for `demo.run_id`. Moving the demo run into
  LendingResponse would remove that request.
- The simulation's capacity trace item (`backend/app/simulation/world.py:346`) carries authority
  but does not say which accounts are unobserved.
- No backfill is needed: the change is read-only and nothing stored was wrong.

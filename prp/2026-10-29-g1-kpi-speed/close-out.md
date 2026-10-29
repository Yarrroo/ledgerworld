# Money KPI reads inside the metric hook — Close-out
> Close-out (/dev-close). Source: board item 146 (goal g1, Money is correct).
> Date: 2026-10-29

## What shipped
- `packages/oasis-finance/src/oasis_finance/channel.py` (new): `PromptChannel`, an OASIS
  `Channel` whose reader wakes when its answer lands (one future per message id) instead of
  polling the answer dict every 0.1 s.
- `backend/app/simulation/world.py`: `import_oasis()` exposes it as `Channel`; `World.start`
  passes it to its `Platform`, so the env, the platform and every agent share it.
- `tests/simulation/test_channel.py` (new): prompt answer (counted in loop turns, no wall-clock
  bound), answer-before-read, a timed-out reader, and a started World wired to the channel.
- `checks/tests/test_kpi.py`: pins g1's 16 check ids and its 119 distinct test ids.

## Cause
Profiling the slowest g1 fixture (`test_policies` comparison, 43 s) showed 30 s idle in epoll:
every platform round trip waited for OASIS's 0.1 s poll tick. No check was narrowed or cached.

## Verification
- g1's 13 test files: 150.7 s before, 58.6 s after; 347 passed, 1 skipped, 1 xfailed both times.
- `timeout 100 python3 checks/kpi.py g1 --print`: `100`, in 61.6 s and later 52.3 s (the
  timeout this item was opened for came at 120 s).
- tests/simulation, tests/decisions, tests/api, tests/hunt, tests/execution, backend/tests,
  checks/tests/test_kpi.py: 1064 passed, 1 skipped, 1 xfailed. `test_channel.py` 20/20 green.
- ruff, `checks/attribution.py`, `checks/no_secrets.py`: ok.
- Vet: T3 (concurrency surface), 1 round, 6 applied (2 proven by fails-before tests), 3 dismissed.

## Docs updated
- None beyond this file: no brief or README describes the platform channel's polling.

## Follow-ups / known gaps
- The upstream `backend/scripts/run_*_simulation.py` launchers still use OASIS's polling channel
  (an upstream edit, outside this item).
- `tests/simulation/test_actions.py` builds a `Platform` on the polling channel directly.

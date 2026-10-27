# One RNG per world — Close-out
> Close-out (/dev-close). Source: cross-family review of l_9f97cfd532 (correction card, board item 74),
> against T08 at 2bcbe9c (`backend/app/simulation/world.py:241`).
> Date: 2026-10-27

## What shipped
- The finding reproduced. `World` seeded, captured and restored the process-global `random`, and
  OASIS's platform (`refresh`) and random recommender (`update_rec_table`) draw from it. So
  starting a sibling world (`random.seed`), running it, restoring it (`random.setstate`), or any
  other `random` draw in the process changed this world's recommendations and its captured RNG
  state.
- `packages/oasis-finance/src/oasis_finance/rng.py` (new): `WORLD_RNG`, a context variable, and
  `route_oasis_random()`, which points the `random` of `oasis.social_platform.platform` and
  `.recsys` at a proxy that resolves each draw on the context's RNG. A context that holds none
  falls back to the process `random`, so upstream scripts that run OASIS outside a `World` behave
  as before.
- `World` owns `self.rng = random.Random(seed)`. `start()` sets it around `env.reset()`, so the
  platform's task draws from it for its whole life. `Coordinator.run_round` sets it in the round
  context it already builds, so `env.step`'s direct recommender call draws from it too.
  `capture`, `restore` and `fingerprint` read and write it, with `setstate` in place, never by
  replacing the object. `World.seed` (dead) is gone.
- `checks/required.json`: the two new tests join `failed_round_rolls_back` (g2).

## Verification
- Regression test `test_a_sibling_world_leaves_this_worlds_random_stream_alone`. A seed-1 world
  runs beside a seed-2 sibling that starts, runs two rounds, fails a round and is restored, with a
  `random.seed(99)` in between. Each round, the world's recommendation table, every actor's
  refresh draw and its RNG digest must equal a solo control. It failed on d7e5adc. With the fix,
  it fails if either routing path is removed: the env.reset context (refresh draws differ) or the
  round context (recommendation table differs).
- `test_no_oasis_module_draws_from_the_process_random`: fails if routing is skipped (it names
  `platform` and `recsys`). It also fails if a camel-oasis upgrade adds a module that holds
  `random`.
- T08's accept: `uv run pytest -q tests/simulation/test_coupled.py` passes. Touched suites
  (`tests/simulation tests/execution/test_import_fence.py`): 214 passed.
  `checks/tests/test_kpi.py tests/test_skeleton.py`: 54 passed. ruff, `checks/attribution.py`
  and `checks/no_secrets.py` are clean. The full gate is the landing train's.
- Vet T3, concurrency: `/code-review high`, `/security-review` (no findings) and `/simplify`.
  Round 1 applied the move into oasis-finance, removed the instance patch of `update_rec_table`,
  added the platform-task draws to the test, plus the module guard and the cleanups.

## Docs updated
- `world.py` module docstring; `oasis_finance/rng.py` states the mechanism and the task-inheritance
  rule. The design docs already say "RNG state" without naming the global module, so they stay
  accurate.

## Follow-ups / known gaps
- camel's `ModelManager.random_model` (OASIS's `SocialAgent` sets that strategy) draws with
  `from random import choice` from the process stream. No `ModelFactory` in the repo gives an
  actor more than one backend, so with one backend the pick is constant and no outcome depends
  on it. A multi-backend actor would need `camel.models.model_manager.choice` routed through
  `WORLD_RNG` too.
- A seed's recommendation stream differs from the one before this change (seeded at construction,
  no longer shared with camel's draws). No fixture or stored evidence pins OASIS recommendations.
- T09 (`branches.fork`) must restore `rng_state` with `world.rng.setstate`, not by assigning a new
  `Random`: the platform task holds the object.

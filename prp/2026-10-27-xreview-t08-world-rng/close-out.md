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
- `packages/oasis-finance/src/oasis_finance/rng.py` (new): `WORLD_RNG`, a context variable;
  `route_oasis_random()`, which points the `random` of `oasis.social_platform.platform` and
  `.recsys` at a proxy that resolves each draw on the context's RNG; `using(rng)` and
  `drawing_from(rng, call)`. A context that holds no RNG falls back to the process `random`, so
  upstream scripts that run OASIS outside a `World` behave as before.
- `World` owns `self.rng = random.Random(seed)`. `start()` runs `env.reset()` under it, so the
  platform's task draws from it for its whole life, and wraps that env's `step`, so the
  recommender `env.step` runs directly draws from it whoever calls it. `capture`, `restore` and
  `fingerprint` read and write it, with `setstate` in place, never by replacing the object.
  `World.seed` stays: T09's checkpoint records it so a fork starts from the same stream. The
  coordinator is unchanged.
- `checks/required.json`: the three new tests join `failed_round_rolls_back` (g2).

## Verification
- Regression test `test_a_sibling_world_leaves_this_worlds_random_stream_alone`. A seed-1 world
  runs beside a seed-2 sibling that starts, runs two rounds, fails a round and is restored, with a
  `random.seed(99)` in between. Each round, the world's recommendation table, every actor's
  refresh draw and its RNG digest must equal a solo control. It failed on d7e5adc. With the fix,
  it fails if either routing is removed: the env.reset context (refresh draws differ) or the
  `env.step` wrapper (recommendation table differs).
- `test_a_direct_env_step_draws_from_the_worlds_rng`: an `env.step` called outside any round,
  after the process stream is reseeded, equals one without the reseed. It fails without the
  `env.step` wrapper.
- `test_no_oasis_module_draws_from_the_process_random`: fails when an imported `oasis` module
  holds the process `random` or one of its functions (`from random import sample`). It names
  `platform` and `recsys` if routing is skipped. A module first imported after the test
  collection, and numpy or torch draws, are not seen.
- T08's accept: `uv run pytest -q tests/simulation/test_coupled.py` passes. Touched suites
  (`tests/simulation tests/execution/test_import_fence.py checks/tests/test_kpi.py
  tests/test_skeleton.py`): 269 passed. ruff, `checks/attribution.py` and `checks/no_secrets.py`
  are clean. The full gate is the landing train's.
- Vet T3, concurrency, two rounds: `/code-review high` each round, `/security-review` (no
  findings) and `/simplify`. Round 1 moved the routing into oasis-finance, replaced the argcount-
  dependent patch of `update_rec_table`, added the platform-task draws to the test, the module
  guard and the cleanups. Round 2 moved the round routing out of the coordinator into a wrapper
  of the world's own `env.step`, so a caller other than a round is covered, widened the guard to
  imported names, and made a failed refresh fail by name.
- Recorded, not applied: a strict mode that raises when no RNG is set (it changes behaviour for
  OASIS code outside any world, and that is a design decision). The new module lives in
  `packages/oasis-finance`, a package T07's brief owns: the repo rule puts camel-oasis extensions
  there, and this adds a module without editing any T07 file.

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

## Red return from the landing train (d5d6b9a)
- The train failed this order's three RNG tests. Cause: the train's shared venv installs the
  workspace members editable from one train worktree, so a candidate gated in another worktree
  imported `app` and `oasis_finance` from that tree (without this change) while running its own
  tests. Reproduced by putting a `main` checkout's sources on `PYTHONPATH`: the same three fail.
  Fix: pytest's `pythonpath` now lists `backend` and `packages/oasis-finance/src` after `.`, ahead
  of site-packages. Under the same shadowing they pass, and the full collection passes
  (1049 passed, 1 skipped).
- Merging main brought T09 (`branches.py`), which reads `World.seed`; round 1 had removed it as
  dead, so it is back. T09's notes that the RNG is process-global are corrected, and
  `test_parent_unchanged` now compares the RNG too.

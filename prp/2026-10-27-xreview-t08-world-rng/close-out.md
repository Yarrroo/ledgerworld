# One RNG per world — Close-out
> Close-out (/dev-close). Source: cross-family review of l_9f97cfd532 (correction card, board item 74),
> against T08 at 2bcbe9c (`backend/app/simulation/world.py:241`).
> Date: 2026-10-27

## What shipped
- The finding reproduced on d7e5adc. `World` seeded, captured and restored the process-global
  `random`, and OASIS's platform (`refresh`) and random recommender (`update_rec_table`) draw
  from it. So starting a sibling world, running it, restoring it, or any other `random` draw in
  the process changed this world's recommendations and its captured RNG state.
- The mechanism on main is board item 76's (`oasis_finance.draws`, `World._own_draws` over the
  platform's `running` and the env's `step`, `World.rng`). It landed while this order was in the
  train and is the same design this order had built (a per-world `random.Random`, a
  `WORLD_RNG` context variable, a proxy over OASIS's `random`). It also routes camel's model
  choice. On merging main, this order's own `oasis_finance/rng.py` and its `World` wiring were
  dropped in favour of it, so one mechanism ships.
- What this order adds on top:
  - three regression tests in `tests/simulation/test_coupled.py`, registered under g2
    `failed_round_rolls_back` in `checks/required.json`;
  - pytest's `pythonpath` puts `backend` and `packages/oasis-finance/src` ahead of
    site-packages (see the red return below).

## Verification
- `test_a_sibling_world_leaves_this_worlds_random_stream_alone`: a seed-1 world runs beside a
  seed-2 sibling that starts, runs two rounds, fails a round and is restored, with a
  `random.seed(99)` in between. After each round the world's recommendation table, its actors'
  refresh draws (read from the platform's trace) and its RNG digest must equal a solo control.
  It failed on d7e5adc. It fails if either of item 76's wraps is removed (`running`, `step`).
- `test_a_direct_env_step_draws_from_the_worlds_rng`: an `env.step` outside any round, after the
  process stream is reseeded, equals one without the reseed. It fails without either wrap.
- `test_no_oasis_module_draws_from_the_process_random`: fails when an imported `oasis` module
  holds the process `random` or one of its functions (`from random import sample`). A module
  first imported later, and numpy or torch draws, are not seen.
- T08's accept: `uv run pytest -q tests/simulation/test_coupled.py` passes. Touched suites pass,
  as do ruff, `checks/attribution.py` and `checks/no_secrets.py`. The full gate is the train's.
- Vet: T3 over the original mechanism (two rounds, `/code-review high`, `/security-review` with
  no findings, `/simplify`); T1 over each red-return fix.

## Follow-ups / known gaps
- A strict mode that raises when no world RNG is set was recorded, not applied: it changes
  behaviour for OASIS code outside any world, and that is a design decision.

## Red returns from the landing train
- d5d6b9a: the train failed the three RNG tests. Its shared venv installs the workspace members
  editable from one train worktree, so a candidate gated in another worktree imported `app` and
  `oasis_finance` from that tree while running its own tests. Reproduced by putting a `main`
  checkout's sources on `PYTHONPATH`: the same three fail. Fix: the pytest `pythonpath` above.
  The full collection then passed (1049 passed, 1 skipped).
- cd10960: the merge probe found conflicts with item 76 in `world.py`, `branches.py`, T09's
  `design.md` and `test_branches.py`. Resolved to main's side in all four, and this order's
  `rng.py` was removed. Item 73 (a round's social writes on that round's clock) makes a second
  refresh in the same round collide with the trace table's unique key. The sibling test
  therefore reads the refreshes the agents already make in their turns from the trace, instead
  of adding its own.

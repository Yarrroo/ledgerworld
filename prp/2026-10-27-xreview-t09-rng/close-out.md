# Each world draws from its own RNG — Close-out
> Close-out (/dev-close). Source: review of T09 (branches), finding F1.
> Date: 2026-10-27

## What shipped
- `World` owns `random.Random(seed)`, reseeded once `start()` has reset the platform; `capture`,
  `restore` and `fingerprint` read and set that RNG, never the process-global one.
- `oasis_finance.draws.route_draws()` (called by `import_oasis`) points the module-level draws
  of `oasis.social_platform.platform`, `oasis.social_platform.recsys` and
  `camel.models.model_manager.choice` at the RNG in the `WORLD_RNG` context variable, falling
  back to the global `random` outside every world. No upstream file changes.
- `World.start` wraps its platform's `running` and its env's `step` so each runs with the
  world's RNG in context; asyncio copies it into the step's agent tasks.
- Root cause: `start()` seeded and `restore()` set the global RNG, so a fork of an earlier
  checkpoint rewound a parent that had gone on, and siblings consumed one shared stream.
- Docs: `branches.py` and `world.py` docstrings; T09's `design.md` limit and `close-out.md` gap.

## Verification
- Reproduced on 29b19e9: a late fork moved the parent's RNG fingerprint to the checkpoint's.
- Regressions, each failing on 29b19e9 and passing after:
  `test_a_late_fork_does_not_move_the_parents_random_stream` (the parent's next round
  recommends what an unforked control does) and
  `test_siblings_draw_alike_whatever_order_they_run_in` [aabb, bbaa, abba, ab|ab] (siblings
  draw identical recommendations in any order, under one gather too; the global RNG is not
  drawn). `test_parent_unchanged` no longer excludes the RNG.
- `uv run pytest -q tests/simulation tests/execution`: 366 passed, 1 skipped. ruff clean,
  `checks/no_secrets.py` and `checks/attribution.py` ok. The full gate is the landing train's.

## Follow-ups / known gaps
- Draws outside a world's platform task and steps stay on the global RNG: camel's retry jitter
  (wall-clock delays only) and interviews, which run on their own backend by design.
- Worlds built with the same seed now draw the same stream; a caller wanting different feeds
  passes different seeds.
- The review's F2-F4 (replay of concurrent posts, replay memory graph collision, supplied-ledger
  cleanup) are separate cards.

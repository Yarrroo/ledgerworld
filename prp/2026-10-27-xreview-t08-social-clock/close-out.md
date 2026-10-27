# A round's social writes on that round's clock — Close-out
> Close-out (/dev-close). Source: cross-family review of l_9f97cfd532, finding F3 (correction card, board item 73).
> Date: 2026-10-27

## What shipped
- OASIS stamps every post and action trace with `sandbox_clock.time_step`, and `env.step`
  advances that clock only after all of the step's actions have run. Step 1 used to advance the
  round clock alone, so the round's scheduled posts (step 3) and the agents' posts in step 5 were
  written under round r-1, while the clock check after the step still passed.
- `Clock.advance(sandbox_clock)` (step 1) checks the two clocks agree, then moves OASIS's with
  the round clock, before any social write of the round.
- `Clock.settle_step(sandbox_clock)` (after step 5) takes back `env.step`'s own advance, and
  fails the round if the step did not advance it exactly once. The platform's clock still moves
  once a round and reads r after the step.
- The capture is unchanged: it pins both clocks before step 1, so an aborted round restores
  both. Module docstrings (clock, coordinator) and the agent-world HANDOFF's `Clock` row and
  drift risk row now say step 1 moves OASIS's clock.

## Verification
- Reproduced at 29b19e9: `test_a_rounds_posts_and_traces_are_stamped_with_that_round` failed
  (the round-1 scheduled post read `created_at` 0). It passes after the fix. It checks scheduled
  and agent-made posts and their `create_post` traces across an aborted and retried round, and
  each post's world item against the round its row is stamped with.
- `test_one_clock_four_hour_rounds_and_a_drift_fails` covers `advance`/`settle_step` drift.
- `uv run pytest -q tests/simulation tests/test_skeleton.py checks/tests/test_kpi.py`: 252
  passed. ruff is clean on the changed files, and `checks/attribution.py` and
  `checks/no_secrets.py` pass. The full gate is the landing train's.
- The new test is registered under `public_shock_traceable_response` in `checks/required.json`.

## Follow-ups / known gaps
- No backfill: platform databases written before this fix carry posts stamped one round early.
  They are per-run simulation files, not kept state.
- `update_rec_table` at the start of `env.step` now sees round r. With the `random` recommender
  the world uses, nothing changes. A recency-weighted recommender would need its own check.

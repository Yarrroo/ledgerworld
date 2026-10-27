# Concurrent posts replay with the ids they were recorded with — Close-out
> Close-out (/dev-close). Source: review of T09 (branches), finding F2 (`branches.py:322-331`).
> Date: 2026-10-27

## What shipped
- Root cause: in step 5 each agent ran its social calls as soon as its own model answered, so
  OASIS numbered a round's posts in answer order. The next round's observations name posts by
  that id (`post-<id>` and its owner), and a replay answers at once in agent order, so two
  concurrent posters swapped ids and an unchanged transcript failed with `ReplayMiss`.
- `oasis_finance.agent.SocialOrder`: an agent with social calls waits, after its model turn and
  before posting, until every earlier agent of the step has finished its turn (posted or not,
  failed or not). The feed read and the model calls stay concurrent; a turn without social calls
  does not wait. `end()` lets go of any turn still waiting.
- `World` gives its agents one shared order; `Coordinator._steps` begins it from step 5's actions
  and ends it in a `finally`, so a failed step leaves no order behind.
- Docs: `agent.py` (S5), `world.py` and `coordinator.py` (step 5) docstrings.

## Verification
- Reproduced on ff94de2: two posters whose models answer in reverse order; the replay failed
  with `ReplayMiss: treasury round 2`.
- Regressions, each failing before its fix and passing after:
  `test_concurrent_posts_replay_through_the_following_round` (same posts, calls and journals
  through round 2; asserts the barrier did reverse the answers; fails again with the coordinator's
  `begin` removed), `test_a_step_that_fails_before_any_turn_holds_no_later_turn` (timed out
  before vet round 1) and `test_ending_a_step_releases_a_turn_still_waiting` (timed out before
  vet round 2). The three ran 20 times: 20 of 20 green.
- `uv run pytest -q tests/simulation`: 206 passed (includes T09's own accept, `test_branches`).
  ruff clean, `checks/no_secrets.py` and `checks/attribution.py` ok. The full gate is the
  landing train's.
- Vet: T3, 2 rounds, 23 findings, 10 applied (2 proven), 13 recorded, 0 open.

## Follow-ups / known gaps
- Only step 5's model turns are ordered; a future caller of `env.step` with data actions, or a
  second model action per agent, gets no order. Step 3's scheduled posts are already sequential.
- Waiting turns hold upstream's step semaphore (128 slots): past 128 agents, a slow early model
  delays later agents' model calls. Worlds here have under ten model actors.
- The shipped `scenarios/world.json` has one poster (`feed`), so it never met this; any scenario
  with two posters did. No recorded transcripts are checked in, so nothing needs re-recording.

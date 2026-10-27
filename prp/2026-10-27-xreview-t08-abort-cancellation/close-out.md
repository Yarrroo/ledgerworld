# Round abort under cancellation — Close-out
> Close-out (/dev-close). Source: cross-family review of l_9f97cfd532 (correction card, board item 71).
> Date: 2026-10-27

## What shipped
- `Coordinator.run_round` runs the round's abort in its own task (`round-<n>-abort`) and waits
  it out: a cancellation that arrives while the abort is still stopping writers no longer tears
  out of it. The cancellation propagates once the abort has ended, chained from the round's error.
- Admission closes and the failed round is recorded in `world.failures` before that task
  starts, so both hold even if the abort is cancelled before its first step.
- `Coordinator._abort` rolls the ledger transaction back and closes its connection in a
  `finally`; if the abort task itself is cancelled (loop shutdown), `run_round` cancels the
  round's remaining tasks and closes the connection, which rolls back what the abort never
  reached.
- An abort that raises or is cancelled sets `world.unusable` to
  `round <n>: the abort did not finish (<why>)` (lifecycle `abort_failed`) instead of the stale
  `round <n> is aborting`. Its exception reaches the caller in place of a round fault (as before
  this item); a cancellation is never replaced and carries it as a note instead.
- Module docstring states the abort's cancellation and failure guarantees.

## Verification
- Reproduced on 0019a0a: `test_a_cancellation_during_abort_cleanup_waits_for_it_to_finish`
  [fault] and [cancel] failed (`run_round` finished cancelled while the writer was still in its
  cancellation cleanup); both pass after.
- Vet regressions, each failing before its fix: `test_an_abort_that_raises_leaves_the_world_
  unusable_and_reaches_the_caller` [fault] [cancel], `test_an_abort_cancelled_itself_still_
  closes_the_ledger_and_refuses_a_retry`, `test_an_abort_cancelled_before_its_first_step_still_
  closes_the_round`.
- `uv run pytest -q tests/simulation/test_coupled.py`: 37 passed. The 9 abort tests ran 20
  times: 20 of 20 green. ruff clean on both files. The full gate is the landing train's.
- Vet: T3, 2 rounds, converged; 17 findings, 12 applied (5 proven, 2 unproven, 5 quality),
  5 dismissed, 0 open.

## Docs updated
- `coordinator.py` module docstring. The system brief (§7.2) and T08's brief already require
  this behaviour; neither changes.

## Follow-ups / known gaps
- A cancellation during the abort replaces the round's own fault as what the caller sees (the
  fault is its `__cause__` and stays in `world.failures`): standard asyncio semantics, kept.
- If the abort task itself is cancelled while a writer is still alive, the connection is closed
  under that writer; the world is unusable by then, so nothing reuses it.
- Unproven: the note an abort failure leaves on a second cancellation (no test drives a
  cancellation and a failing restore together).

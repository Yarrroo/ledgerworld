# T08 · close-out

> Close-out. Source: design.md.

## What landed

- `backend/app/simulation/clock.py`: one 4-hour round clock, 18 rounds to the horizon; `check()` fails a round whose
  OASIS `time_step` is not the round.
- `backend/app/simulation/world.py`: a branch's ledger, OASIS platform, queue, agents, model transcript and
  `WorldState`; `capture`/`restore`/`fingerprint` of every round-start component; `trace(journal_id)`.
- `backend/app/simulation/coordinator.py`: the ten steps of §7.2 in one ledger transaction, the clearing rules,
  and the abort path (close admission → cancel/join tagged round tasks → fence the platform → restore → verify).
- `tests/simulation/test_coupled.py` (18 tests): the three fixtures' expect blocks, overdue marking, offered
  facility / release, clock agreement, a model-chosen bad reference as a rejection.
- `checks/required.json`: g2 `public_shock_traceable_response` and `failed_round_rolls_back`.

## Decisions made here (the HANDOFF left them open)

- An actor's ledger entity is its `actor_id` and it acts from `<actor>/operating` (T10 builds the demo world to it).
- An advance is disbursed into `<borrower>/in-transit` and lands at the next boundary in step 2; an inflow due by
  now lands in step 2 too, so an observation shows `arrived` with the cash (matches `nonanticipativity`).
- A scripted model's answered entries are captured as round state; a live model holds none.
- `repay`, `defer`, `convert` are rejected with a named reason in the round world (no observed-revenue period, no
  deferrable contract, no FX quote yet).

## Follow-ups (not this task's files)

- `tests/simulation/test_actions.py` still clears with its own step-7 stand-in; it could call `clear_intents`.
- No caller reaches `World.run` yet: the runs job/API (T16) and the demo world (T10) are its consumers.
- T11 needs a policy driver for the treasury in a policy branch (the treasury model not called).

# T08 · Coupled round coordinator on one clock — close-out

> Close-out. Source: design.md ← briefs/T08.md. Date: 2026-10-27

## What shipped

- `backend/app/simulation/clock.py`: one 4-hour round clock, 18 rounds to the ledger's 72 h horizon; `check()` fails
  a round whose OASIS `time_step` is not the round.
- `backend/app/simulation/world.py`: a branch's ledger, OASIS platform (own SQLite, random recommender), queue,
  agents, model transcript and `WorldState`; `capture`/`restore` of every round-start component, with a fingerprint
  computed from the capture's copies when a round aborts; `trace(journal_id)` back to the post.
- `backend/app/simulation/coordinator.py`: the ten steps of §7.2 in one ledger transaction; step 6 holds each intent
  to C1, its tool's argument schema, its mandate and one use of its id; step 7 checks every reference before the
  ledger and clears in sorted order; the abort path closes admission, cancels and joins tagged round tasks, fences
  the platform, restores and verifies, or marks the world unusable.
- `tests/simulation/test_coupled.py` (31 tests): the three fixtures' expect blocks, overdue marking, offered
  facility and release, clock agreement, and one regression test per vet finding.
- `checks/required.json`: g2 `public_shock_traceable_response` and `failed_round_rolls_back`.

## Verification

- Accept: `uv run pytest -q tests/simulation/test_coupled.py` → 31 passed.
- Touched suites: `tests/simulation tests/execution/test_import_fence.py checks/tests tests/test_skeleton.py` →
  237 passed. The full merge gate is the landing train's and was not run in this tree.
- Lint: `ruff check` over the merge gate's new-code paths → clean; `checks/no_secrets.py`, `checks/attribution.py`
  → ok.
- The barrier and rollback tests (7) ran 20 times in a row under the heavy queue: 20 of 20 green.
- Review: T3, two rounds (code review high, security review, four-angle cleanup; then code review medium on the
  fixes): 46 findings, 28 applied (15 with a test that failed first), 18 recorded with reasons, 0 open.

## Decisions made here (the HANDOFF left them open)

- An actor's ledger entity is its `actor_id` and it acts from `<actor>/operating` (T10 builds the demo world to it).
- An advance is disbursed into `<borrower>/in-transit` and lands at the next boundary in step 2; an inflow due by
  now lands in step 2 too, so an observation shows `arrived` with the cash (matches `nonanticipativity`).
- An inflow's promised hour rounds up, an outflow's down: each errs on the cautious side.
- A scripted model's answered entries are captured as round state; a live model holds none.
- `repay`, `defer`, `convert` are rejected with a named reason in the round world (no observed-revenue period, no
  deferrable contract, no FX quote yet); `pay(obligation_id=…)` is refused, since an obligation settles when due.

## Follow-ups / known gaps

- No caller reaches `World.run` yet: the runs job/API (T16) and the demo world (T10) are its consumers.
- T11 needs a policy driver for the treasury in a policy branch (the treasury model not called).
- `tests/simulation/test_actions.py` still clears with its own step-7 stand-in; it could call `clear_intents`.
- Rollback reaches private state of other modules (`ScriptedModel._used`, the agent's memory storage); a public
  checkpoint API on `FinanceAgent` and the model doubles would replace it (outside this task's files).

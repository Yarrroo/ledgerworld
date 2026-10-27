# An obligation outstanding at the checkpoint is carried into feasibility — Close-out
> Close-out (/dev-close). Source: cross-family review of T11 (policy comparison), finding on
> `feasibility.py:135-138` (assessment filters obligations solely by due round).
> Date: 2026-10-27

## What shipped
- Root cause: `assess` kept an obligation only when `from_round < due_round <= to_round`, so
  one due at or before the checkpoint and still unpaid there vanished; the branch read feasible.
- `assess` (`backend/app/decisions/feasibility.py`) now carries such an obligation in, unmet,
  with its original `due_h` and `overdue_h` = the first assessed round end. One paid by the
  checkpoint (its `settle:` journal at or before it, or state `met` when no journal names it)
  is history and stays out.
- One shortfall rule for every unmet obligation: the free cash at its first chance in the
  branch (its due round, or the first round for an overdue one), read before its own payment
  when the branch paid it in that round; an unknown round end still counts none of it.
- `ObligationResult.checked_h` names the hour its shortfall was read. The escalation
  (`objective._binding`) says "overdue since t=<deadline>"; a zero-short unmet obligation reads
  "not paid by its deadline, though free cash covered it", never a false "<" comparison.
  The demo's failure line (`demo/run.py`) adds "overdue at the checkpoint (read at
  t=<overdue_h> h)".
- The rules-replay world (`reverse_stress.replay_world`) counts unmet obligations as `assess`
  does: every one it holds is outstanding at the start, so one already overdue there is unmet.
- HANDOFF's `assess` row states the rule and the new field.

## Verification
- Reproduced on e0db754: 1,500,000 due at t=4, checkpoint round 2: `obligations == ()`,
  `feasible == True`.
- New tests fail before and pass after: `tests/decisions/test_feasibility.py` (carried with
  its deadline: unpaid, paid at its first chance, paid a round later, paid by the checkpoint;
  escalation wording, incl. in-branch zero-short), `tests/decisions/test_reverse_stress.py`
  (replay counts an overdue snapshot obligation), `tests/demo/test_demo_fake.py`.
- `uv run pytest -q tests/decisions tests/api tests/contracts tests/hunt tests/demo`: 320
  passed, 1 xfailed. ruff clean; `checks/no_secrets.py`, `checks/attribution.py` ok. The full
  gate is the landing train's.

- Vet: T2 (money flag cleared to an assessment read; 3 areas), 2 rounds, converged; 24
  findings, 11 applied (5 proven by a fails-before test, 6 quality), 13 recorded, 0 open.
  Round 1 unified the shortfall rule and the zero-short wording; round 2 moved the add-back
  of the obligation's own payment ahead of the unknown clamp.
- The API contract (`c6_api.schema.json`) carries only `obligations_unmet`; no change needed.

## Recorded, not changed
- An overdue obligation the branch settles under a caller-named journal (`j-<leg>`) has no
  `settle:` journal to date it; its state reads `met`, so it is taken as paid by the checkpoint.
  Journals carry no flow link (item 83's follow-up); that schema change removes this too.
- `later` still subtracts reservations already settled or released (item 83's follow-up).
- The replay world never sees an obligation whose reservation is committed at the snapshot
  (`snapshot_observation` leaves it out); pre-existing, in-branch ones too.
- `assess` now dates every historic obligation of the account (one or two reads each); branch
  obligation counts are small. A batched lookup is the fix if they grow.
- The add-back takes the obligation's amount as what its payment journal moved; a reservation
  and its obligation are held at one amount, so they agree. Other payments made in the same
  round still reduce its "free then" (round-end granularity, as for in-branch obligations).
- The escalation binds the earliest unmet obligation, so an overdue zero-short one names the
  binding ahead of a later real shortfall: the documented rule, unchanged here.

## Follow-ups
- `candidates.py` plan-for-now emits payout legs only for obligations due after the
  observation (`t_h < due_h`), though the projection counts an overdue one now: an overdue
  obligation the plan funds gets no payout leg. That changes the execution plan, so it is a
  separate item.

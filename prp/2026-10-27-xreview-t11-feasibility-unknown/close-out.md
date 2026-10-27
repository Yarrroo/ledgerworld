# Realised feasibility counts no cash from unknown rounds — Close-out
> Close-out (/dev-close). Source: cross-family review of T11 (policy comparison), finding on
> `feasibility.py:87-100` (realised floor counts an unknown balance as usable cash).
> Date: 2026-10-27

## What shipped
- `assess(..., observability=)` takes the assessed account's observability at the end of every
  round after the checkpoint; it refuses a round with none recorded, and a value other than
  `known`/`unknown`. A round that ended unknown counts only what it owes (`min(settled, 0)`)
  toward the floor (`min_cash`, `breach_h`) and an unmet obligation's `short_minor`; `settled`
  still reports the ledger unchanged, and `Feasibility.unknown_h` names the unknown round ends.
- `evaluate` (`candidates.py`) records the treasury account's observability after each round.
- The all-infeasible binding text (`objective.py`) marks `(balance unknown)` when the hour it
  cites fell in an unknown round, so a freeze does not read as a cash shortfall.
- Root cause: `account_observations` holds only the current observability, and `assess` read
  settled cash straight from postings, so HANDOFF's "unknown adds nothing" was never applied.
- Docs: `feasibility.py` docstrings; HANDOFF's `assess` row names the input and `unknown_h`.

## Verification
- Reproduced on ae51393: a 1,000,000 balance on a 500,000 floor, unknown through the horizon,
  assessed `min_cash 1000000, breach_h None, feasible True`.
- `tests/decisions/test_feasibility.py` (14 cases), each failing before its fix: a sustained
  unknown balance breaches t=8 to the horizon; a freeze then recovery breaches t=8..16; an
  obligation due in an unknown round is short its whole amount; a debt posted while unknown is
  still counted (min cash -200,000); the escalation names the unknown balance; a missing round
  and a `stale`/`Known`/None value are refused.
- `uv run pytest -q tests/decisions`: 68 passed, 1 xfailed (the T11 comparison fixtures are
  unchanged: no fixture scenario makes the treasury account unknown).
  `tests/reports/test_provenance.py`: 37 passed. ruff clean; `checks/attribution.py`,
  `checks/no_secrets.py` ok. The full gate is the landing train's.
- Vet: T2, 2 rounds, converged; 17 findings, 9 applied (3 proven by tests), 8 recorded.

## Recorded, not changed
- A policy's own view still shows an unknown balance as 0 (`candidates.py:344, 552`): a policy
  acts only on what it observes; the assessment judges the realised outcome.
- `as_dict()["settled"]` is the ledger, beside a floor computed on usable cash; `unknown_h`
  reconciles the two, and no consumer plots `settled` against the floor today.
- The obligation text's free cash is clamped at 0, as `short_minor` always was.

## Follow-ups / known gaps
- No history of observability is kept in the ledger; a caller outside `evaluate` (T21's reverse
  stress) must record the map itself. A history table would be a schema change.
- The review report named on the card was not in this checkout; the finding was taken from the
  card's text.

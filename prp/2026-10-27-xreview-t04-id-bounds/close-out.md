# Ledger id widths — Close-out
> Close-out (/dev-close). Source: cross-family review of l_3cd47f46f6 (correction card, board item 70).
> Date: 2026-10-27

## What shipped
- `models.bounded_id(column, text, room=0)`: an id that fits its column is kept as written; a
  longer one keeps its head plus `~` and 16 hex of its sha256, so the same source gives the same
  id and two sources do not share one. A column with under 32 characters to spare is refused.
- Every generated ledger id goes through it: settlement and commit ids (`ledger.settle_due`,
  `store.commit`, `store.settle_flow`), snapshot openings, rest holds and pledges
  (`ledger._load_account`), `_next_id` prefixes, line draws and undrawn holds, disbursal and
  repayment journals, receivable and payable accounts (`contracts`, `lending`), and the
  gateway's `j-…` journal ids.
- T05's load-time refusal of contract ids whose derived ids overflowed (`contracts._ids_fit`) is
  removed: those ids are valid and now load.
- `ledger._source_ids_fit`: a C5 source id wider than the column it is stored in as written
  (C5 allows 128, several columns hold 64) is refused by name at `from_snapshot`, on SQLite as
  on PostgreSQL, leaving the store untouched.
- No schema change, no migration. Ids that already fit are byte-identical, so no stored state
  changes meaning.

## Verification
- `uv run pytest -q backend/tests/finance/test_id_bounds.py`: 9 passed, 1 deselected (`pg`).
  The column scan found 65 overflowing values with bounding disabled; the 5 round-1 cases fail
  on 4b76b1c and pass after.
- Touched suites (`tests/finance tests/execution tests/contracts tests/simulation
  tests/decisions tests/demo tests/reports tests/fixtures backend/tests/finance`): 558 passed,
  1 skipped. ruff clean on the lint paths. The full gate is the landing train's.
- The `pg` test was not run here: no PostgreSQL server on this machine.

## Docs updated
- `contracts` module docstring and `from_snapshot` docstring name the bounded form and the
  source-id refusal.

## Follow-ups / known gaps
- Execution ids are not covered: `leg_id` is VARCHAR(96) yet is used as a ledger `flow_id`
  (64) and in `{leg_id}:out` (gateway `_flows`, `release_failed` SQL); approval ids are `Id`
  (128) in VARCHAR(64). These need their own decision (widen, or bound both halves together).
- A CLAUDE.md gotcha ("a generated ledger id goes through `models.bounded_id`") is worth
  recording; this order leaves CLAUDE.md alone.
- Non-id widths: C5 `Kind` is 64 but `expected_flows.kind`, `obligations.kind` and
  `reservations.purpose` are VARCHAR(32), the same SQLite-passes/PostgreSQL-refuses gap for
  kinds. Not ids, so outside this item.
- The root of the source-id gap is C5's `Id` (128) against 64-wide columns. Narrowing the
  per-field types in `schemas.py`, or widening the columns with a migration, would retire
  `_source_ids_fit`; both change a contract other modules read, so they are a separate decision.

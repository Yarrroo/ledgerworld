# T04 · typed ledger — Close-out
> Close-out. Source: design.md ← briefs/T04.md ← design/modules/ledger/HANDOFF.md.
> Date: 2026-10-27

## What shipped
- `backend/app/finance/models.py`: tables mirroring `schema.sql`, `Journal`/`Posting`,
  `LedgerRefusal` with the closed code set, `STALE_AFTER`, `HORIZON`.
- `backend/app/finance/migrations/`: `upgrade(engine)`, one idempotent step.
- `backend/app/finance/store.py`: `LedgerStore`. Each write is one transaction, or a savepoint
  inside the caller's transaction. Covers journals, hold/commit/release/expire/settle, pledges,
  expected flows, obligations and `view`.
- `backend/app/finance/spendability.py`: S, P, `min_projected`, `headroom`, `floor_check` as
  pure functions of an `AccountView`.
- `backend/app/finance/ledger.py`: `check_outflow`, `pay`, `settle_due` (the mandatory
  settlements of a round), `from_snapshot` (C5 → store).
- Tests: `tests/finance/test_ledger.py` (every `invariants.json` and
  `reservation-lifecycle.json` case, schema parity, hypothesis properties, 15 regression tests
  from review), `test_fixtures.py` (LF-1's expected block), `test_ledger_pg.py` (the same on
  PostgreSQL, marked `pg`).
- `checks/required.json`: g1 ids for LF-1 and the five ledger invariants.
- Dependencies: `sqlalchemy>=2.0.30`, `psycopg[binary]>=3.1` (the CI postgres job's driver).

## Verification
- `uv run pytest -q tests/finance/test_ledger.py tests/finance/test_fixtures.py`: 44 passed.
- `tests/fixtures` (the pencil re-derivation of LF-1/LF-2): green beside the engine.
- ruff on new code, `checks/no_secrets.py`, `checks/attribution.py`: green.
- `python3 checks/kpi.py g1`: 50 (8 of 16 g1 checks). Before this change, 2 of 16 passed.
- PostgreSQL: DDL compiled for the PG dialect, including the partial unique index. The `pg`
  tests are skipped here (no server on this machine) and run in CI.

## Docs updated
- Module docstrings carry the rules: two measures, savepoints, an unknown balance taken as
  observed.
- `design.md` lists the consumers of the ledger. No README or CLAUDE.md change is needed, since
  no command or workflow changed.

## Follow-ups / known gaps
- Nothing calls the ledger yet. The coordinator (round steps 7–8), decisions, the gateway and
  the overview API are later tasks. `check_outflow`, `settle_due` and `AccountView` are their
  entry points.
- Concurrent writers on PostgreSQL: fixed after review (finding F3). Every free-funds check
  locks the cash account's row (`FOR NO KEY UPDATE`, id order) under a pinned READ COMMITTED;
  `pay` and the lending payments lock their accounts, and lending its facility row, before the
  checks they rely on; commit, release and settlement are guarded UPDATEs. The `pg` tests named
  `test_two_connections_*` are the two-connection regressions. Still open: K_p is a pool-wide
  total, so two disbursals from different cash accounts of one pool (or a pay from another pool
  account) are not serialized against it; `max(seq)+1` makes two concurrent journals collide on
  the unique `seq` (one fails, nothing moves); and a transaction that locks in several steps
  (`settle_due`) can deadlock with another, which PostgreSQL aborts.
- A negative hold, pledge or outflow amount is refused as `zero_amount`. The closed code set has
  no separate code for it.
- Kinds and purposes are cut to the 32-character columns of the design schema; `schemas.Kind`
  allows 64. Widening the columns is a schema change for the ledger design's owner.
- On an unknown cash account, `apply` and `expect` are not bounded by a balance (none is
  observable); `hold`, `pledge` and `check_outflow` refuse `unknown_balance`.

## Correction — concurrent writers (review finding F3, board item 68)
> Close-out (/dev-close), 2026-10-27. Source: the cross-family review of this task, finding F3.

- **What broke:** on PostgreSQL two transactions could each read the same free units and each
  commit a hold, pledge or payment against them (1,400 spoken for out of 1,000). The vet of the
  fix found the same read-then-write shape one level up: a flow settled twice, a hold expired
  under a concurrent commit, an advance disbursed twice, a line drawn past its limit, two
  periods repaid past what was owed, and a settle/pay deadlock.
- **The guard:** cash account rows are locked (`FOR NO KEY UPDATE`, id order) before any
  free-funds check under a pinned READ COMMITTED; lending locks its facility row first; every
  move out of `held` or `pending` is a guarded UPDATE. Files: `store.py`, `ledger.py`,
  `lending.py`, `contracts.py`.
- **Proof:** the eleven `pg` tests named `test_two_connections_*` and
  `test_settling_against_a_cash_account_never_deadlocks_a_payment` run two connections in a
  fixed order (A's transaction held open, B on a second connection). Every one fails on the
  pre-fix code and passes after it, 20 of 20 runs. Run with `pytest -m pg` and
  `LEDGER_DATABASE_URL` naming a PostgreSQL database (CI's postgres job). The default gate
  deselects them; `tests/finance` (79) stays green on SQLite.
- **Backfill:** none needed. Nothing calls the ledger on PostgreSQL yet, so no stored state was
  written under the race.

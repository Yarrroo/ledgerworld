# T04 · typed ledger — build design

> Design output (build stage 2). Source: `briefs/T04.md` and `design/modules/ledger/HANDOFF.md`
> (the approved module design; this note only fixes the shape of the code). Next: implement → close-out.

## Accept (from the brief, unchanged)

- `uv run pytest -q tests/finance/test_ledger.py tests/finance/test_fixtures.py` exits 0
- `bash checks/merge.sh` exits 0; LF-1 balances to the cent; every invariant has a named test.

## Consumers — who reads or writes this ledger

| Consumer | Task | What it calls | What it must be able to rely on |
|---|---|---|---|
| lending (K_p, disburse, repay) | T05 | `LedgerStore.apply`, `hold`, `pledge`, `view` | journals balance per currency; pledged/reserved buckets are exact |
| coordinator, round step 7–8 | T08 | `check_outflow`, `pay`, `settle_due`, `LedgerRefusal.code` → C2 `reason` | a refusal changes nothing; a due obligation settles without any actor acting |
| branches (fork at checkpoint) | T09 | one store per branch (`LedgerStore(url)`), `migrations.upgrade` | the whole branch state is in the tables; nothing in process memory |
| decisions (feasibility, headroom) | T11 | `AccountView`, `projected_cash`, `floor_check`, `headroom` | P and S are pure functions of a view, so a policy reads no live store |
| gateway (before a leg), reconcile | T13/T16 | `check_outflow` (`stale_balance`, `unknown_balance`), `apply` with `source_leg_id`, `mode` | authority `full` only on a known, fresh balance |
| overview / treasury API | T17 | `view`, `spendability`, `projected_cash` | `None` for unknown, never 0 |
| money-safety hunts | T29 | all of the above | the closed refusal-code set |

Invariants that cannot be added later (they shape stored data): settled is Σ postings, never a
column; a journal's `seq` is the branch's commit order; one active pledge per `collateral_ref` is a
partial unique index; minor units are BIGINT integers.

## Shape

- `models.py` — SQLAlchemy Core tables mirroring `schema.sql` column for column (a test loads both
  and compares); `Posting`, `Journal` dataclasses; `LedgerRefusal(code, **detail)` with the closed
  code set.
- `migrations/` — `upgrade(engine)`, idempotent; one step today (`v0001_initial`).
- `store.py` — `LedgerStore(url)`: every write is one transaction; validation happens before the
  first insert and the transaction rolls back on any refusal. Reads return an `AccountView`.
- `spendability.py` — pure functions on an `AccountView`: `spendability` (S + state + authority),
  `projected_cash` (P), `min_projected`, `headroom`, `floor_check`. P is a step function, so its
  minimum is taken over `now` and every flow/obligation time in the horizon.
- `ledger.py` — `check_outflow`, `pay` (check and post in one transaction), `settle_due`
  (mandatory settlements: arrivals, committed outflows, due obligations from their reservation),
  `from_snapshot` (C5 → store: opening journals against `<account>:opening`).

Obligation and pending_out are never subtracted twice in P: an obligation whose reservation is
committed is counted through its pending_out flow only.

## Run footer

Architect run, tier Sketch: the module design (`design/modules/ledger/HANDOFF.md`) was already
written and approved; this note records consumers and code shape only. No reviewer pack on this
machine; no publish step (unattended order, nothing outward).

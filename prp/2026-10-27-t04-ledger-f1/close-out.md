# One reservation backs one obligation — Close-out
> Close-out (/dev-close). Source: cross-family review of T04, finding F1 (board item 66).
> Date: 2026-10-27

## What broke, and why
`add_obligation` and `attach_reservation` checked only that a reservation sat on the
obligation's account for its amount. Two obligations could name one reservation. `view` then
dropped both in favour of the single committed flow, so projected cash rose by one obligation,
and `settle_flow` marked every obligation on the reservation `met` after one payment. Repro:
fund 1,000, hold 500, attach two 500 obligations, commit, settle. One payment of 500 was made,
both obligations were met, and 500 of debt disappeared.

## What shipped
- `backend/app/finance/models.py`, `design/modules/ledger/schema.sql`: unique index
  `obligations_one_per_reservation` on `obligations.reservation_id`. It covers every state
  (a met obligation keeps its payment), and NULL repeats freely.
- `backend/app/finance/store.py`: the index is the one enforcement point. Its refusal is
  turned into `ValueError("reservation r already backs obligation o")` after the refused
  savepoint rolls back, so a caller's transaction stays usable and a concurrent writer gets the
  same named refusal.
- `backend/app/finance/migrations/v0002_one_obligation_per_reservation.py`: frozen DDL that adds
  the index to an existing database. A database whose obligations already share a reservation is
  refused by name, not mended.
- `tests/finance/test_ledger.py`: 13 regression tests. They cover both methods against held,
  committed and settled reservations, the reviewer's one-payment repro, the raw database
  refusal, the upgrade, the upgrade on shared rows, refusal inside a caller's transaction, a
  duplicate obligation id that must not be reported as a shared reservation, and a C5 snapshot
  naming one committed reservation from two obligations.

## Verification
- Before the fix, all 10 first-round regression tests failed. After it, they pass.
- `uv run pytest -q tests/finance tests/contracts tests/fixtures`: 140 passed, 20 `pg`
  deselected. The T04 accept (`tests/finance/test_ledger.py tests/finance/test_fixtures.py`)
  passes.
- `uv run ruff check backend/app/finance tests/finance`: clean. `checks/attribution.py` and
  `checks/no_secrets.py`: ok.
- vet: T3 (money path, schema and migration), 2 rounds. 18 findings: 5 applied (1 proven,
  2 unproven, 2 quality) and 13 recorded with reasons. 0 open. The instruments were
  `/code-review high`, then `medium` on the fixes, plus `/simplify` and a security review on the
  explicit range.
- PostgreSQL was not run (no database here). The index name match on a PostgreSQL unique
  violation, and the concurrent-writer path, are unproven. That makes 2 of the applied fixes
  unproven.

## Follow-ups / known gaps
- **Adopting a spent reservation (owner decision).** An obligation may still name a reservation
  that was committed and settled by a plain outflow with no obligation. `settle_due` then marks
  it met without a payment of its own. T04 asks for exactly this
  (`test_an_obligation_whose_reservation_settled_is_met`), so it was left alone rather than
  weakening the original accept. Since this fix, a payment meets at most one obligation. Whether
  an unowned settled reservation may be adopted at all is a policy call.
- `attach_reservation` replaces an obligation's reservation without releasing the old one, and
  accepts a released or expired one. This predates the fix and is outside this item.
- F2–F5 of the same review (unknown-balance settlement, PostgreSQL serialisation, due-now
  arrival, identifier widths) are separate items.

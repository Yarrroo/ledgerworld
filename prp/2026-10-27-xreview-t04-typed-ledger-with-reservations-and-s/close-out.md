# T04 correction — settle_due on an unknown balance — Close-out
> Close-out (/dev-close). Source: cross-family review of l_3cd47f46f6 (`report.md` beside this file).
> Date: 2026-10-27

## What shipped
- `backend/app/finance/ledger.py` `settle_due`: before any automatic outgoing settlement it reads
  the account's state (`state_of`); on an unknown balance a due pending_out flow stays pending, a
  held reservation is not committed or paid, and the obligation keeps its state (owed, in P).
  Arrivals still land. Before, only the "no reservation yet" path refused (through `store.hold`);
  a held or committed reservation was paid and its obligation marked met with no observed funds.
- `tests/finance/test_ledger.py`: `test_an_unknown_balance_never_pays_a_held_reservation`,
  `test_an_unknown_balance_never_pays_a_committed_flow`. Both fail on the parent, pass after, and
  each also checks the payment goes through once the balance is known again.

## Verification
- Reproduced before the fix: held and committed paths both left settled 6,999,500 and the
  obligation `met` on an unknown account.
- `uv run pytest -q tests/finance`: 80 passed (holds the T04 accept, `test_ledger.py` +
  `test_fixtures.py`). Every other suite reaching the ledger (connectors, contracts, decisions,
  execution, fixtures, reports, simulation): 490 passed, 6 skipped.
- ruff on the changed files, `checks/no_secrets.py`, `checks/attribution.py`: green.
- Vet: T3 (money path), `/code-review high` + `/simplify` + `/security-review`, converged in 2
  rounds. Round 1 applied the single-check and `state_of` cleanups and corrected the docstring;
  round 2 (`/code-review medium` on that commit) found the refactor behaviour-equivalent.
  Recorded, not applied: the stale rule and the store-level guard (below); `known()` building a
  full view (cached once per account per round); a bare `except LedgerRefusal` (as on the parent;
  `add_obligation` already refuses zero and out-of-range amounts).

## Docs updated
- `settle_due` docstring states the unknown-balance rule.

## Follow-ups / known gaps
- A **stale** balance still settles mandatory payments from its last observed figure; `check_outflow`
  and `lending._payable_from` refuse stale. Blocking it here halts every settlement once a round
  passes six hours, because nothing in the round calls `store.observe()` to refresh `as_of`. It
  needs a decision on who refreshes observations, so it is left as a follow-up.
- `store.settle`/`settle_flow` do not refuse an unknown account themselves. Their only automatic
  caller is `settle_due`; an explicit settle follows an observed provider receipt.
- `expire_due` still expires a lapsed hold on an unknown account (a time rule, not a payment).
- No test yet pins an obligation already missed, or whose hold expired, while its balance is
  unknown (it keeps its state, as on the parent).

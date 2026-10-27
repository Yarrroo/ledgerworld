# T04 correction — clearing and posting agree on arrivals due now — Close-out
> Close-out (/dev-close). Source: cross-family review of l_3cd47f46f6 (correction card).
> Date: 2026-10-27

## What shipped
- `backend/app/finance/ledger.py`: `land_arrivals(store, account, now)` settles an account's
  pending arrivals due by `now` inside the caller's transaction. `pay` calls it after
  `check_outflow` passes and before posting. Before, S(now) counted a due arrival but the
  posting's `reserved ≤ settled` guard did not, so a cleared payment was refused
  `reserved_exceeds_settled`.
- `backend/app/finance/lending.py`: the same check-then-post shape in `disburse`
  (`check_outflow`), `draw_line` and `repay` (`_payable_from`) calls `land_arrivals` after its
  check. `disburse` checks K_p before landing, so K_p still counts settled cash only.
- `backend/app/finance/store.py`: `settle_flow(if_pending=True)` returns None for a flow another
  writer already landed; `due_flows(account_id=)` filters in SQL. `settle_due` uses `if_pending`
  for arrivals, so a step 8 that read a flow before a concurrent outflow landed it skips it
  instead of rolling back every mandatory settlement.
- `backend/tests/finance/test_ledger_round_order.py` (the board check): 7 tests. Due-now and
  past-due arrivals fund a payment; a future arrival funds nothing (refused, store unchanged);
  a refused payment lands nothing; advance disbursal and repayment funded by a due arrival post;
  step 8 skips an arrival landed after its read. 5 fail on the parent commits.

## Verification
- Reproduced before the fix: `pay` raised `reserved_exceeds_settled {settled: -50000}` on a
  payment `check_outflow` had cleared.
- `uv run pytest -q backend/tests/finance/test_ledger_round_order.py`: 7 passed.
- Suites reaching the ledger (backend/tests/finance, checks, tests/connectors, contracts,
  decisions, execution, finance, fixtures, reports, simulation): 648 passed, 6 skipped.
- ruff on `backend/app/finance` and `backend/tests/finance`, `checks/no_secrets.py`,
  `checks/attribution.py`: green.
- Vet: T3 (money path). `/code-review high`, a security review on the explicit range,
  `/simplify` angles. 2 rounds, 0 open.

## Docs updated
- Docstrings: `pay`, `land_arrivals`, `_payable_from`, `settle_flow`, `due_flows`.

## Follow-ups / known gaps
- `store.hold` still measures free units without due arrivals, so a hold taken for an intent
  cleared against one is refused. No caller does that today.
- `checks/merge.sh` does not lint `backend/tests/finance`, where the board's check put this
  test. Ruff is green on it locally; add the path in a change that owns `merge.sh`.
- Brief §7.2 lists pending arrivals under step 8. An arrival on an account whose outflow clears
  at step 7 now lands with that outflow, in the same round and transaction; step 8 lands the rest.

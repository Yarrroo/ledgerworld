# T29 · Hunt: money-safety edge cases — Close-out
> Close-out. Source: briefs/T29.md ← design/modules/ledger/HANDOFF.md ← 00-system.md §5, §6.
> Date: 2026-10-27

## What shipped
- `tests/hunt/test_money_safety.py`: the eight cases of `design/modules/ledger/fixtures/
  money-safety.json` (loaded unchanged), each attacked in its owning module and asserted against
  its `expect` block: spend beyond cash (ledger and gateway), double pledge, obligation removed
  by inaction (hourly and in one jump), withdrawal after the deadline, delayed receivable,
  stale balance at execution (incl. the 6 h boundary), floor never relaxed when infeasible
  (K_p = 0 from a 42,000.00 redemption, full branch comparison), provider timeout after accept.
- Five real bugs, all at the execution gateway, each pinned by a test that fails before its fix:
  1. `gateway.preflight` counted an arrival due by now and not landed (overdue) in S(now) and
     P: at t=12 with the receivable late, a 10,000.00 discretionary payout went to the provider
     while P(40) without it is 20,000.00 < floor. Preflight now reads `observed_view`.
  2. `lending.disburse` / `repay` landed every due arrival on the source when a gateway leg
     settled, booking cash that had not arrived. New `land` flag; the gateway passes False.
  3. Two legs funded by one held reservation passed preflight; `execute` then raised
     `LedgerRefusal`. Now refused `reservation_mismatch`.
  4. One offered advance could be sent twice (two legs, or a second approval while the first
     was in flight or unknown). Now refused like an in-flight repayment.
  5. A pool's advance legs were checked against K_p one at a time; they now share it.
- `checks/required.json`: 15 ids under g1 `money_safety_hunts` (was empty).
- `design/modules/execution/HANDOFF.md`: the preflight row names the new rules.

## Verification
- `uv run pytest -q tests/hunt/test_money_safety.py` (the item's check): 15 passed, exit 0.
- Every suite importing the changed modules (`backend/tests/finance tests/connectors
  tests/execution tests/finance tests/hunt tests/reports tests/simulation/test_coupled.py
  tests/simulation/test_scenarios.py checks/tests`): 607 passed, 1 skipped at d86a004; after the
  vet round, `tests/hunt tests/execution tests/finance/test_lending.py backend/tests/finance`:
  232 passed, 1 skipped. The full `checks/merge.sh` is the landing train's, not run here.
- ruff on the changed code, `checks/no_secrets.py`, `checks/attribution.py`: green.
- Vet: T3 (money surface), 2 rounds, 0 open: `/code-review high` 8 findings, `/simplify` (one
  agent, four angles) 7, `/security-review` none; 7 applied (1 with a fails-before test),
  8 recorded below.

## Docs updated
- Docstrings: `observed_view`, `_Claims`, `preflight`, `disburse`/`repay` (`land`),
  `_payable_from`. HANDOFF row as above. No README or CLAUDE.md change.

## Follow-ups / known gaps
- Preflight runs before the transaction that queues the legs, so two approvals executed
  concurrently can both pass the once-only guards (advance in flight, K_p sum). The same
  window predates this change for the repayment guard and the facility-state check; closing
  it means running preflight inside the queue transaction (a dev-fix of its own).
- Recorded, not applied: "overdue is not cash" as a property of the store view instead of
  `observed_view` + `land` (the ledger view also serves the simulation, where due arrivals
  land at step 2); `_in_flight` re-reads approval terms per in-flight leg (pre-existing
  pattern); the hunt imports helpers from other test modules (repo precedent); merging the two
  settle tests and the `advancing`/`repaying` sets, and checking K_p once per pool at the end
  of preflight (changes which refusal is reported first).
- Not confirmed: a settled fx conversion whose buy side is missing or malformed may escape
  `_post_journal` as an exception instead of a `ledger_refused` incident (low, unproven).
- The money-safety fixture says `result: infeasible`; the decisions result calls it
  `all_infeasible`. The test asserts every policy infeasible and the decisions vocabulary.

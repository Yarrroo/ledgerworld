# Vet report: execution gateway (board item 14)

`vet: T3, round 2, 16 applied (11 proven, 1 unproven), 7 recorded, 0 open`

**Tier: T3.** The change moves provider money and posts ledger journals. It spans 8 files and
about 1,740 lines, with tests in the diff.

**Instruments:**
- `/code-review high` on be5ed25..slot/ledgerworld-6 (round 1), then `/code-review medium` on
  192d8ea..slot/ledgerworld-6 (round 2: the fixes only).
- `/simplify`, run inline because the engine is solo.
- `/security-review`: 0 findings.

**Coverage:** every changed code file was read in full, and the docs were not reviewed.

## Applied, each with a test that fails before the fix

| # | Finding | Test |
|---|---|---|
| R1-F1 | A journal the ledger refused escaped drive, execute and sweep | `test_a_journal_the_ledger_refuses_is_an_incident_not_a_crash` |
| R1-F2 | A queued advance did not speak for the pool's cash | `test_a_queued_advance_speaks_for_the_pools_cash` |
| R1-F3 | A reservation-funded repayment left its flow and reservation open | `test_a_reservation_funded_repayment_settles_its_reservation` |
| R1-F4 | A reservation-funded advance skipped the facility and K_p checks | `test_a_reservation_funded_advance_still_needs_an_offered_facility` |
| R1-F5 | An unreadable create answer escaped `send` | `test_an_unreadable_create_answer_is_an_unknown_outcome_never_an_error` |
| R1-F6 | An fx target was missing in a gateway started before the approval was recorded | `test_an_fx_leg_recorded_by_another_process_runs` |
| R1-F7 | A hint for our leg whose GET failed was still marked handled | `test_a_hint_for_our_leg_whose_get_errors_stays_retryable` |
| R1-F9 | A repayment was not pooled with the other legs on S, and its amount was not checked | `test_a_repayment_shares_spendable_cash_with_the_other_legs`, `test_a_repayment_pays_exactly_what_the_observed_period_owes` |
| R2-2 | An oldest period with zero revenue blocked every later repayment | `test_a_period_with_no_revenue_does_not_block_the_next` |
| R2-3 | Two legs could repay one period | `test_one_period_is_never_repaid_by_two_legs` |
| R2-5 | Any exception from posting a journal was filed as a ledger refusal | `test_a_fault_in_posting_a_journal_is_raised_not_filed_as_a_refusal` |

**Quality fixes (the gate is their proof):**
- `/simplify` found that preflight read each account view up to four times, and that
  `release_failed` rescanned every failed leg. Both fixed.
- Round 2 review: `period()` read every repayment journal in the ledger (R2-7) and did its own
  naive-UTC conversion (R2-10). Both fixed.

**Applied without a test (unproven):** R2-8, the guard against a repayment journal of the wrong
amount, restored in `_repay`. No path through the code can make `period()` and `lending.repay`
disagree, so no test can reach it.

## Recorded, not applied

- **R1-F8, `list_all` ignores pagination.** The sandbox's list paging parameters are unverified,
  and T15 confirms the list API. The fake does not page.
- **R1-F10, the edit to `test_approval_binding.py`.** The edit is deliberate: the work order says
  to align old paths, and that file's skip said "lands with T13". The efficiency notes in the
  same finding are also recorded: the sweep re-reads reconciled legs because a PAID payout can
  still fail, and the used-approval read is small.
- **R2-1, old stores lack the `ledger_refused` kind.** No observed store with execution tables
  is deployed yet, so the first install creates the new CHECK.
- **R2-4, settle recomputes the repayment period.** C3 carries no period. The R2-3 guard covers
  races the gateway itself starts.
- **R2-6, the extra GET per hint.** `drive` deliberately swallows lookup errors for the sweep, so
  the hint path needs its own GET that raises. Deposit legs never receive transfer or conversion
  hints.
- **R2-9, `bound()` parses the stored terms on every call.** Every leg is written in the same
  transaction as its terms, so the row is always there. The cost is one row read.
- **Simplify, the hard-coded collection path in `on_hint`.** Cosmetic.

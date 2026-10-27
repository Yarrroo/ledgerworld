# World reference model — findings

`refmodel/world_ref.py` (stdlib only) runs the coupled round of system brief §7.2 against the three
agent-world fixtures, loaded unchanged from `prp/…/agent-world/fixtures/`. Check:
`python -m unittest discover -s refmodel -p test_world_ref.py` — 31 tests, green on 2026-10-27
(Python 3.12). Mutating out the queue sort, the restore, the writer-epoch bump or the task cancel
each turns tests red. Fixture paths below are relative to that directory; money is USD minor units.

## Reproduced

| Fixture | Values reproduced |
|---|---|
| `clearing-order.json` | `spendable_now` 2,000,000. All three arrival orders clear `treasury-1, treasury-2, borrower-b, borrower-c`. Results: accepted with seq 1 · rejected `insufficient_spendable` with `spendable_minor` 1,000,000 · accepted with seq 2 · accepted with seq 3. `ledger_after` 6,000,000/5,000,000 · 800,000 · 300,000. The ledger hash is the same for every order. |
| `coupled-chain.json` | K_p 4,200,000 before. Shock: `i-r4-borrower-c-1` `request_advance` has evidence `[p-r3-1]`, C2 accepted, no journal. `i-r5-lender-1/2` have evidence `[req:borrower-c:r4]`, both accepted, 1 journal. Lender operating ends at 3,300,000, venue at 1,500,000, borrower-c gains 1,200,000, K_p ends at 3,000,000. The five-link trace matches exactly. Control: no_action in r4/r5 and K_p stays 4,200,000. Trap: a committed-line draw leaves K_p at 4,200,000. Reversing the actor answer order leaves the transcript unchanged. |
| `round-rollback.json` | Faults in events, settlement and commit, plus actor failure → `failed`; coordinator cancel → `cancelled`. In all five: the ledger hash equals round start, the transcript ends at r9, no r10 C2 is delivered, and the full capture equals round start. The retry equals a clean control on obs hashes, intent ids, C2, journals, ledger hash and transcript. Event, settlement, post, memory and C2 each happen once. Actor cases: the sibling's cleanup write and child finish before `restore_begin`. 0 tasks are live at restore, the late write by the stale writer is refused, and the cleanup writes are gone. Unproved quiescence → world unusable and retry refused. `invalid-intent`: round committed, C2 rejected `amount_not_integer_minor`, payroll settled. |

## Mismatches and gaps (fixtures not edited)

| # | Where | Finding | Severity · confidence |
|---|---|---|---|
| W1 | `clearing-order.json:36` (`expect.note`) | The note is true only with the §5 reserve-floor check off. With the floor on, an unsorted coordinator rejects the 15,000.00 on `reserve_floor` (headroom 1,000,000) and accepts the 10,000.00. It still fails the fixture, but on the reason, not on which payment wins. | low · high |
| W2 | `clearing-order.json:5`, `00-system.md:118` | `ledger_before` omits the LF-1 floor (30,000.00) and the payroll obligation due t=40, but the result depends on them. After the 10,000.00, P(40) equals the floor exactly. The fixture also needs S checked before the floor: both bind on `treasury-2` (S 1,000,000 and headroom 0), and §5 does not order the two checks. | medium · high |
| W3 | `coupled-chain.json:27-28` | Here `evidence_ids` is the matched plan entry's `when_seen`, not everything the actor saw: the lender also sees public `p-r3-1` in r5. HANDOFF never defines where `evidence_ids` comes from. Also, borrower-c already sees `p-r3-1` in r3, since step 3 publishes before step 4 observes. The r4 response is the plan's choice, not a visibility limit. | medium · high |
| W4 | HANDOFF `IntentQueue` / Data "Intent ids" (line 42) | A string tiebreak on `intent_id` sorts tool call 10 before tool call 2 of the same response. Resolved: HANDOFF now sorts on the call number as an integer, and `sort_key` and its test follow. | low · high |
| W5 | HANDOFF line 44 vs `00-system.md:165` | HANDOFF says arrivals are "delivered in step 2". §7.2 runs pending arrivals in step 8. The model marks `overdue` in step 2 and posts arrival journals in step 8. | low · medium |
| W6 | `coupled-chain.json` `borrower_c_after` vs HANDOFF line 44 | For a request with no facility, the fixture's settled increase means disburse settles at once. An offered facility arrives as `pending_in` at the next boundary. The model settles at once on the request path; T08 must state this. | low · medium |
| W7 | `round-rollback.json:29` | The injected intent has no `intent_id`, `priority_class`, `sim_minute` or `to`. The model assigns them, and the amount check runs first. | low · high |
| W9 | HANDOFF `Coordinator.run_round` ("`env.step`… `asyncio.gather`") | A coordinator that awaits `asyncio.gather` cannot be cancelled past a stubborn actor. Cancelling a gather waits on its children, so the abort never starts and quiescence detection never runs. The model waits with `asyncio.wait(FIRST_EXCEPTION)` and lets the abort cancel and join (test `test_second_cancel_during_abort_marks_world_unusable`). T08 wraps upstream `env.step`, which gathers internally, so it must keep the actor step in its own task and cancel that task. | medium · high |
| W8 | `round-rollback.json` `quiescence` | Proving that a task which won't stop is unusable needs a detection bound (a timeout). The model uses one only for detection. All ordering uses barriers, as the fixture requires. | info · high |

Not modelled (out of this oracle's scope): OASIS/camel APIs, SQLite file copy, branches/fork (T09),
observation scope beyond the three fixtures, LF-2 venue freeze, process-crash recovery.

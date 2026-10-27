# decisions — three plans, the same shocks, no peeking

Tasks: T11 (policy comparison with nonanticipativity) · T21 (reverse stress and the collateral facility; the cut line, system brief §15).
Read with `00-system.md` §6, §7.2, §9 and §15, the agent-world module (branches, `ScriptedModel`, the coupled chain) and the ledger module (P(t), `capacity`, reservations). The fixtures in `fixtures/` are the test truth.

Four rules this module exists to keep:
- **Same shocks for every plan.** Each policy runs in its own fresh branch per scenario, forked from one checkpoint with one seed and one exogenous schedule; the other actors re-react on their own in each branch.
- **Judge outcomes, not intentions.** Feasibility and cost are read from each branch's realised ledger, never from the policy's own projection.
- **No clairvoyance.** A decision at round r reads only what is observable at t = 4r h. A guarded view names any field read early, and a paired-history check catches a policy that reaches the future some other way.
- **No silent relaxing.** When no plan is feasible, nothing is offered for approval. The result names the earliest unmet constraint, the binding constraint and the role to escalate to. The floor and the reservations stay as they are.

## Interfaces

| Unit | File | Shape | Notes |
|---|---|---|---|
| `Policy` | `backend/app/decisions/candidates.py` | `id`, `decide(view: PolicyView) → list[PlanAction]` | `PlanAction` uses the treasury's tools only: `request_advance{facility, amount_minor}`, `defer{flow, to_h}`, `convert{buy, sell_currency, for_obligation}`, `pay`. An empty list is `no_action`. |
| `NoAction`, `FixedReserve`, `Integrated` | `candidates.py` | the three of §9, declared in that order | `FixedReserve` defers discretionary outflows that carry `defer_to_h` and never borrows. `Integrated` closes a projected shortfall with the cheapest remedy first: a free deferral, then a paid deferral, then an eligible advance (all or nothing). It converts a foreign-currency obligation one round before it is due. (`candidate-rules.json`) |
| projection inside a policy | `candidates.py` | settled + pending_in expected and not overdue − pending_out − obligations, all due within the horizon | Overdue, unknown and stale add nothing. A policy never reads the lender's K_p; a draw beyond it comes back as a C2 rejection the next round and is never resubmitted in that branch. |
| `PolicyView` | `backend/app/decisions/nonanticipativity.py` | read-only view over the branch's world at t: `get(path)` | Every leaf carries `available_at`. A read with `available_at > t`, or of a leaf marked never (scenario parameters, scheduled future events, the rng, another branch), raises `AnticipationViolation(path, read_at_h, available_at_h)`. Every read is recorded; the paths become the C1 intent's `evidence_ids`. (`nonanticipativity.json`) |
| `paired_history_check(policy, tree)` | `nonanticipativity.py` | `→ ok \| AnticipationViolation(node={round, scenarios})` | For every pair of scenarios whose observable histories (hash of the full view each round) are equal through round r, the canonical JSON of the decisions at r must be equal. |
| `evaluate(run_id, checkpoint, scenarios, policies=ALL)` | `candidates.py` | → `Evaluation` per (scenario, policy) | `fork(checkpoint, branch_id="<run_id>-<scenario>-<policy>")` from the agent-world module. In a policy branch the policy drives the treasury: its intents are C1 with `actor_id=treasury`, `params.source="policy:<id>"`, `obs_hash` = hash of the view. The treasury's model is not called there; every other actor's is. The schedule hash must be equal across policies, or the evaluation fails. |
| `assess(branch, observability)` | `backend/app/decisions/feasibility.py` | `→ Feasibility{obligations[{id, due_h, met, short_minor?, overdue_h?}], floor{min_cash, at_h, short_minor, breach_h}, funding_cost_minor, feasible, unknown_h}` | From the realised ledger: settled at each round end, unknown adds nothing positive. The store keeps only the current observability, so the caller passes the account's at each round end; a round that ended unknown counts `min(settled, 0)` toward the floor and a shortfall, and its hour is in `unknown_h`. An obligation due by the checkpoint and still outstanding there is carried in unmet with its original `due_h`, its shortfall read at the first assessed round end (`overdue_h`; none when the branch paid it, late); one paid by the checkpoint is left out. Funding cost = advance fees + deferral fees + conversion spread, integer minor units. `feasible` = no unmet obligation and no floor breach. |
| `rank(evaluations)` | `backend/app/decisions/objective.py` | → `DecisionResult` | Key per policy, summed over scenarios and never averaged: `(obligations_unmet, branches_breached, max_short_minor, funding_cost_minor)`, smaller first. Equal keys keep the declared order and are reported as ties. Selected = the first policy that is feasible on every scenario, else `status = all_infeasible`. (`policy-comparison.json`, `all-infeasible.json`) |
| `plan_for_now(policy, observed_snapshot)` | `candidates.py` | → legs for the execution module's `bind` | The selected policy decides again on the **current observed** snapshot, never on a branch. It adds the obligations its funding protects as payout legs, `after` the funding legs. The demo compresses time: a payout runs once its `after` legs settle. A `DecisionResult` is never an approval (`not_an_approval` in the execution module). |
| `reverse_stress(selected, baseline, families, confirm=True)` | `backend/app/decisions/reverse_stress.py` | → `{label, cohort: "reverse_stress", results{family: …}, smallest, sensitivity_table, failure_path}` | One family at a time, in two steps. First an 8-point monotonicity grid, then an exact integer binary search over the size. It runs on a rules-replay world: the other actors' recorded reactions are replayed, and an observation that no longer matches falls back to `no_action` and sets `reactions_frozen`. One fresh branch confirms the found point. `size_bps = floor(size × 10000 / scale)`. No probability field. (`reverse-stress.json`) |
| `borrowing_base(lots, limits, now)` | `backend/app/finance/collateral.py` | → `{after_haircut, excluded, pre_limit, obligor_cut, type_cut, borrowing_base, authority}` | `floor(value × (10000 − haircut_bps) / 10000)` per eligible lot. One pass of limits on the pre-limit total: obligor first, then asset type. Unknown, stale and pledged lots add nothing. Simulation only. (`collateral.json`) |
| route | API module wiring (T16) | `GET /api/v1/decisions/{run_id}` → `DecisionResult` + `as_of`, `mode` | Each branch row carries `replay: bool`; a precomputed cohort is labelled replay on screen. |

`DecisionResult`: `{run_id, checkpoint{branch, round, snapshot_id}, scenarios[], policies[{id, branches[{scenario, branch_id, replay, actions, feasibility}], key, feasible}], ranking, ties, selected | null, status: selected | all_infeasible, escalation?{earliest_unmet, binding, escalate_to}, plan_for_now | null, label}`.

## Data

- **Scenarios of the comparison** (checkpoint round 3, t = 12 h): s1, the receipt delayed 240 h; s2, the receipt delayed 4 h, which looks exactly like s1 at t = 12; s3, s1 plus the venue rumour and a venue freeze at round 4. Integrated is feasible on all three for 2,400.00 of fees. No-action and fixed reserve each breach the floor by 10,000.00 on s1 and s3. Fixed reserve has nothing discretionary to defer in LF-1.
- **The coupling shows in s3.** The lender's K_p ends at 5,000.00 in the integrated branch, against 15,000.00 under no-action: its advance, the venue freeze and borrower-c's draw all hit the same pool.
- **The demo runs s3 live**: three fresh policy branches of 15 rounds each, with five model calls per round (the treasury is driven by the policy). That is ≤ 225 calls, inside the agent-world budget of 432. s1 and s2 run in tests on `ScriptedModel`, and on screen only as a labelled replay.
- **Observability rules** this module needs from the round coordinator (T08):
  - a `pending_in` expected at t whose arrival is not delivered in step 2 of that round is marked `overdue` before step 4;
  - a request against a facility in state `offered` clears at step 7 through `lending.disburse`, and the units arrive as `pending_in` at the next round boundary;
  - a lender `release` on an offered facility withdraws the offer.

  Without the first rule the advance would arrive after LF-1's t ≤ 18 deadline.
- **Usable capacity counts pool obligations.** K_p subtracts the pool's obligations due within the horizon. Without that, a redemption spike leaves K_p unchanged and the lender-side shock cannot bind. LF-2 has none, so 42,000.00 stands.
- **Escalation contact** is a role on the snapshot: C5 `entities[].escalation`, "treasury operator" for borrower-a.
- **Reverse stress on LF-1.** With no shock, the smallest break is payroll growing by 20,000.01 (4,000 bps). On the demo shock the selected plan keeps the floor with zero margin at t = 40: a 0.01 growth breaks it. A lender redemption above 32,000.00 breaks it too, through capacity. The Break beat shows both, labelled a search.

## Fixtures

| File | Drives | What it pins |
|---|---|---|
| `fixtures/policy-comparison.json` | T11 | 3 scenarios × 3 policies: realised cash at key hours, breaches, fees, the lender's K_p by round in s3, the keys, the ranking with its tie, the selection, and `plan_for_now` equal to the execution module's approval legs |
| `fixtures/candidate-rules.json` | T11 | 11 single-node decisions: draw, offer withdrawn, too late, rejected not retried, defer then draw, a paid deferral that beats the advance, fixed reserve defers only and never defers an obligation, convert just in time (two nodes), no-action |
| `fixtures/all-infeasible.json` | T11 | the lender cannot fund (K_p 7,000.00 after a redemption) and an obligation unmet at t = 20 without touching the payroll reservation: `all_infeasible`, no plan, escalation fields |
| `fixtures/nonanticipativity.json` | T11 | a three-scenario tree with shared histories; 3 honest policies accepted; 4 clairvoyant ones rejected, each with the path (or the round and scenario pair for a side channel) |
| `fixtures/reverse-stress.json` | T21 | 7 families on two baselines: breaking sizes, `size_bps`, the not-applicable and live-only families, failure paths by hour, the search label, cohort apart |
| `fixtures/collateral.json` | T21 | haircuts, obligor and type limits in one pass, unknown and stale lots excluded, rounding down, draws within and beyond the base, the double pledge, no wiring to execution |

## Failure modes

| Failure | Where it bites | Guard |
|---|---|---|
| A policy reads the schedule, the scenario parameters or a future post | a plan that looks good only because it knew | `PolicyView` raises with the path; `peek-arrival`, `peek-params`, `peek-post` |
| A policy reaches the future through a closure or a global | the view never sees the read | paired-history check; `side-channel` |
| Policies compared on different seeds or schedules | the winner is luck | one checkpoint, one seed, schedule hash equal across policies or the evaluation fails |
| The treasury's model also acts in a policy branch | two decision makers; the policy is not what was measured | treasury model calls in policy branches = 0 |
| One policy's branch leaks into another | agents react to a plan they never saw | fresh fork per (scenario, policy); sibling isolation from the agent-world module |
| Feasibility read from the policy's own projection | an optimistic plan scores as feasible | `assess` reads the realised ledger |
| The overdue receipt seen only at step 8 | the advance lands at t = 20, after the deadline; integrated looks infeasible | overdue marked before step 4 (T08) |
| A redemption spike leaves K_p unchanged | the lender-side break is invisible | K_p subtracts pool obligations due within the horizon (ledger) |
| Averages or floats in the key | unstable ranking, a fractional cent decides | integer key, sums only, declared tie order |
| All infeasible, and the floor or a reservation is quietly relaxed | an "approved" plan that breaks a rule | `status = all_infeasible`, `plan_for_now = null`, `floor_relaxed = false`, `reservation_raided = false` |
| A branch's plan executed as is | money moved on a hypothetical state | `plan_for_now` decides on the observed snapshot; C3 binds its `snapshot_id` |
| A rejected draw resubmitted every round | spam intents, misleading transcripts | rejection remembered for the branch; `integrated-rejected-not-retried` |
| Reverse stress shown as a forecast or mixed into the comparison | a made-up probability on screen | label on every result, no probability field, cohort `reverse_stress` stored apart |
| A non-monotone response hides a smaller break | the binary search misses it | 8-point grid first; `non_monotone` flag |
| Replay silently reuses a reaction to a different observation | a search result built on reactions that never happened | unmatched → `no_action` + `reactions_frozen`; one confirming fresh branch |
| Collateral wired to execution | a simulation-only facility moves money | import check and no leg kind; `not-wired-to-execution` |
| Unknown or stale collateral counted | the borrowing base is overstated | excluded, authority reduced; `venue-freeze`, `stale-lot` |

## Done-whens

- accept: uv run pytest -q tests/decisions/test_policies.py — fixture: fixtures/policy-comparison.json
- accept: uv run pytest -q tests/decisions/test_policies.py — fixture: fixtures/candidate-rules.json
- accept: uv run pytest -q tests/decisions/test_policies.py — fixture: fixtures/all-infeasible.json
- accept: uv run pytest -q tests/decisions/test_nonanticipativity.py — fixture: fixtures/nonanticipativity.json
- accept: uv run pytest -q tests/decisions/test_reverse_stress.py — fixture: fixtures/reverse-stress.json
- accept: uv run pytest -q tests/finance/test_collateral.py — fixture: fixtures/collateral.json

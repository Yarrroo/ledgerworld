# T11 · policy comparison — build design

> Design output (dev-build stage 2). Source: briefs/T11.md and design/modules/decisions/HANDOFF.md
> (the approved module design; this note only records the build's choices). Next: implement.

## Consumers (who reads what this builds)

| Consumer | Reads | Invariant it relies on |
|---|---|---|
| API route `GET /api/v1/decisions/{run_id}` (T16) | `DecisionResult` as a dict | integer key, `replay` per branch row, `label`, no approval field |
| execution `bind` (T13) | `plan_for_now(...)` → `{entity, account, legs}` | decided on an **observed** snapshot id; legs equal approval-binding base legs |
| reverse stress (T21) | `Policy`, `assess`, the selected policy id | `assess` reads only the realised ledger |
| UI decisions screen / demo s3 | `Evaluation` rows, K_p by round | same schedule hash per scenario; treasury model calls = 0 |

## Choices the HANDOFF leaves open

- **Checkpoint boundary.** "Checkpoint round 3 (t = 12 h)" is the committed boundary *before*
  round 3: the scenario's round-3 events must come after the checkpoint (`fork` refuses earlier
  ones) and the advance drawn at t = 12 must land at t = 16. The base world is checkpointed at
  committed round 2; every branch runs rounds 3‥18 (t = 72 h, the horizon).
- **Treasury off in a policy branch.** After `fork`, the treasury's agent leaves the branch's
  acting set, so `env.step` never calls its model; its model is an empty `ScriptedPlan` whose
  call count is reported (must be 0). The policy decides at the coordinator's `observed` hook
  (step 4, the same moment the agents observe) and its intents join the round at `intents`.
- **`params.source = "policy:<id>"`.** The coordinator held every intent to its tool's schema
  (`extra="forbid"`), which refused `source`; `_fits_its_tool` now drops that one provenance key
  before the tool check (one-line wiring in `coordinator.py`, the contract named it).
- **The policy's view** is a `PolicyView` over a flat world built from the treasury's own
  observation at t (its account, pending flows with the coordinator's promised hour and status,
  open obligations, the advances offered to it, every C2 it has been shown, public prices), plus
  `scenario.*` leaves that are never observable. Paths are `pending_in[rcv-1]`,
  `facilities[adv-a]` …; they become the intent's `evidence_ids`.
- **A facility's deadline** (`arrive_by_h`) is a term of the offer the ledger does not hold;
  `evaluate` and `plan_for_now` take it as `terms={facility: {"arrive_by_h": h}}`.
- **Feasibility** from the branch ledger: settled at each round end from the checkpoint to the
  horizon; an obligation is unmet when it was not paid in its due round, short by its amount
  minus the free cash then; funding cost = the treasury's fee-expense booked in the branch.
- **Key** `(Σ unmet, Σ branches breached, max short, Σ funding cost)`: the fixture's
  `max_short_minor` is the largest single-branch short (1,000,000 over two breached scenarios),
  so that one component is a max; the others are sums. Never an average.
- **Payout legs** in `plan_for_now` need a beneficiary the snapshot does not carry:
  `beneficiaries={obligation_id: beneficiary}`; a protected obligation without one is refused.

---
Run footer: ARCHITECT · tier=Sketch — the module's design is the approved
`design/modules/decisions/HANDOFF.md`; this run records only the build's choices and its consumers.
No reviewer pack, nothing published (unattended pane).

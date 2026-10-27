# T11 · policy comparison — Close-out
> Source: design.md ← briefs/T11.md ← design/modules/decisions/HANDOFF.md.
> Date: 2026-10-27

## What shipped
- `backend/app/decisions/candidates.py`: `NoAction`, `FixedReserve`, `Integrated`; the flat
  policy world (`view_world`, `read`, `project`); `branch_observation`; `evaluate`, which forks
  one fresh branch per (scenario, policy), takes the treasury agent out of the acting set and
  queues the policy's C1 intents (`params.source = policy:<id>`); `plan_for_now`; `decide`.
- `backend/app/decisions/feasibility.py`: `assess` from the branch ledger (settled per round,
  unmet obligations with their short, fee expense).
- `backend/app/decisions/objective.py`: `Evaluation`, `DecisionResult`, `rank` (integer key,
  declared-order ties, `all_infeasible` with earliest unmet, binding and escalation role).
- `backend/app/simulation/coordinator.py`: one line. The tool-schema check drops the
  `source` provenance key.
- `tests/decisions/test_policies.py`: candidate-rules, policy-comparison and all-infeasible,
  read unchanged, plus regressions from review. `checks/required.json` registers them under
  g1 (`lf1_reproduction`, `clairvoyant_policy_rejected`).

## Verification
- `uv run pytest -q tests/decisions`: 54 passed, 1 xfailed (strict).
- Touched suites: `tests/simulation`, `tests/execution`, `tests/test_skeleton.py`,
  `tests/testing` all green. Ruff, `checks/no_secrets.py` and `checks/attribution.py` pass.
  The full suite is the landing train's, so it was not run here.

## Docs updated
- Module docstrings carry the rules. `design.md` records the build's choices and consumers.

## Follow-ups / known gaps
- **Fixture gap (strict xfail).** In all-infeasible `obligation-unmet`, the fixture holds the
  integrated branch at 30,000.00. On the realised ledger, wd-1 lands at t=48 and
  `ledger.settle_due` retries the missed inv-9, which takes cash to 5,000.00. So that case's
  floor, keys, ranking and escalation differ from the fixture. Either the fixture or the
  retry rule needs a decision.
- **No route yet.** `decide()` is the entry point; the `GET /api/v1/decisions/{run_id}` route
  belongs to T16.
- `decide()` passes no prices or absolute horizon to `plan_for_now`. A committed obligation
  that settles under its flow's journal is judged by its final state. Unmet free cash
  subtracts later reservations as an approximation. All three are recorded in the vet.

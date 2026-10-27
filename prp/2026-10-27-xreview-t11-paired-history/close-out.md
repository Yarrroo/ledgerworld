# Policy evaluation enforces the paired-history guard — Close-out
> Close-out (/dev-close). Source: cross-family review of T11 (policy comparison), finding on
> `backend/app/decisions/candidates.py` `evaluate`. Landed at 4df019a.
> Date: 2026-10-27

## What shipped
- Root cause: `evaluate` ran only the view guard (`guarded_decide`) each round and recorded each
  decision's `obs_hash`, but never compared one policy's decisions across scenarios. The
  paired-history check existed only in `paired_history_check` over a `ScenarioTree`, which no
  comparison path calls. A policy that told branches apart by a side channel (call order,
  private state) acted differently on identical observable histories and was still ranked.
- `nonanticipativity.check_pairs(decisions, policy=None)`: the comparison, over each scenario's
  `{round, obs_hash, actions}` records; `paired_history_check` now calls it.
- `candidates.evaluate` runs `check_pairs` once per policy over its branches, before it returns,
  so `decide` never ranks a policy that fails it. The violation's node is
  `{round, scenarios, policy}` (the handoff's `{round, scenarios}` plus the policy id).
- Docs: module docstrings of both files and `evaluate`'s docstring.

## Verification
- Reproduced on ae51393: `test_a_side_channel_policy_is_caught_by_evaluate_before_any_ranking`
  failed with `DID NOT RAISE AnticipationViolation`; it passes after. The honest control,
  `test_an_honest_policy_on_the_same_pair_passes_evaluate`, reads the nine-branch comparison
  (s1 and s2 share the t = 12 history and the integrated draw). Both are registered under
  `clairvoyant_policy_rejected` in `checks/required.json`.
- `uv run pytest -q tests/decisions tests/test_skeleton.py`: 76 passed, 1 xfailed (the strict
  fixture-gap xfail recorded in T11's close-out). T11's accept, every test under
  `lf1_reproduction` and `clairvoyant_policy_rejected`: 36 passed. ruff clean,
  `checks/no_secrets.py` and `checks/attribution.py` ok. The full gate is the landing train's.
- Vet: T1, 2 rounds, converged; 3 quality fixes applied, 3 recorded, 0 open.

## Follow-ups / known gaps
- One policy instance serves every branch and then `plan_for_now`, which calls `propose`
  outside both guards. A stateful policy whose scenarios never share a history is not caught,
  and its branch state reaches the live plan. Giving each branch and the plan its own copy
  closes that; it changes behaviour, so it is not in this correction.

# T15 · Sandbox arrives: live contract pass and fake corrections — Close-out
> Close-out (/dev-close). Source: board item 16, briefs/T15.md (Medium; criteria from the board's `check:`).
> Date: 2026-10-27

## What shipped
- `backend/app/connectors/airwallex/fake.py`: the conversion replay refusal carries no `trace_id`;
  the deposit create answers `id, amount, currency, reference, status` only (no `request_id`,
  `created_at`, `global_account_id`; the list keeps the last two). These were the two key
  differences sandbox run 4 (api_version 2024-09-27, Mode B, 14/14 both sides) left.
- `checks/airwallex_canon.json` (new): HTTP status, key set and status value of every diffed
  canonical check on the fake, each verified on the sandbox in run 4.
- `backend/tests/finance/test_airwallex_fake_keys.py` (new, 16 tests): holds the fake to the canon.
- `docs/airwallex-contract.md` (new): what was verified, when, which §10 assumptions changed,
  and the run-2 and run-4 differences with the items that fixed them.

## Verification
- `uv run pytest -q backend/tests/finance/test_airwallex_fake_keys.py`: 4 red before the fake
  fix, 16 green after.
- Touched suites `backend/tests/finance tests/connectors tests/execution tests/demo tests/api
  checks/tests`: 746 passed, 1 skipped. `tests/hunt/test_money_safety.py`: 15 passed.
- `uv run python checks/airwallex_live.py --fake`: 14/14 PASS. ruff, no_secrets, attribution: ok.
- Not run: `--require-key` (no sandbox credential in this checkout). The fake corrections rest on
  run 4's recorded diff. The full `checks/merge.sh` belongs to the landing train.

## Vet
vet: T1 (money keywords in a fake's answer keys, no arithmetic changed), round 1, 1 applied
(0 proven, 0 unproven, 1 quality), 2 recorded, 0 open.

## Follow-ups / known gaps
- `00-system.md` §10 still says "(T15 confirms)" for the deposit `amount` as a number; the
  contract doc records it as confirmed. Not in this item's files.
- The fake's deposit list keys and the Mode A legs are not verified against the sandbox.

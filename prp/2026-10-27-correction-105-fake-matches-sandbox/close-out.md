# Correction 105: the fake Airwallex answers as the sandbox did on run 2 (Close-out)
> Close-out (/dev-close). Source: board item 105 (no design; a fix).
> Date: 2026-10-27

## What shipped
- `backend/app/connectors/airwallex/fake.py`: a quote answers 200 with `valid_to_at`; a conversion
  settles at create (`SETTLED`, both sides moved) and carries `conversion_id` with no `id`; a
  replayed transfer is `400 request_id_duplicate` with no `trace_id`, a replayed conversion
  `400 invalid_argument` "has been used in the past", the rest per `REPLAY_REFUSALS`; a payout
  create answers `SCHEDULED` and reads back `PROCESSING`; Global Accounts carry no `currency`
  key, and a deposit takes the currency the client's `account_currencies` reads. The
  settle/cancel-conversion test controls are gone (nothing left to settle).
- `backend/tests/finance/test_airwallex_fake_matches_sandbox.py` (new, 8 tests);
  `test_airwallex_sandbox_shapes.py` reads `valid_to_at`.
- Callers unchanged; the outbox docstring names the sandbox's spellings.

## Verification
- `uv run pytest -q backend/tests/finance/test_airwallex_fake_matches_sandbox.py`: 5 red before
  the fix, 8 green after; `backend/tests/finance/`: 62 passed.
- `uv run python checks/airwallex_live.py --fake`: 14/14 PASS.
- `bash scripts/demo.sh --mode fake` then `checks/demo_receipt.py`: ok, payout PAID, advance
  SETTLED, 0 incidents.
- ruff, `checks/no_secrets.py`, `checks/attribution.py`: green. The full `checks/merge.sh` is
  the landing train's.

## Docs updated
- `00-system.md` §10 duplicate-id fact; airwallex `HANDOFF.md`; fixtures `canonical-requests`,
  `errors`, `idempotency`, `fake-lifecycles` state the sandbox shapes.

## Follow-ups / known gaps
- The fake can no longer produce a SCHEDULED/OVERDUE/CANCELLED conversion or a SCHEDULED/OVERDUE
  payout, because the sandbox does not either; reconcile's handling of those states has no
  fake-backed test. If it needs one, add an arm-able scenario to the fake.
- `demo/run.py` `pay()` still sends a `PROCESSING` transition the sandbox already made; the
  client reads it back as made (one refused call per payout).
- The conversion replay's `trace_id` and the charge/connected-account replay codes were not
  observed on run 2; they keep their previous shapes.

## Red return (landing train, 12 tests)
- The first landing missed `tests/` at the repo root: 12 tests there still pinned the old fake
  (a payout reading `SCHEDULED`, an unsettled conversion and the settle/cancel controls, the
  renamed `errors.json` scenarios, the diff tests' status and key mutations).
- Fixed in the tests and fixtures, not in callers: a payout create step asserts the answer
  `SCHEDULED` and the read `PROCESSING`; an fx leg is settled by the run that submits it; the
  connected-account conversion settles on that account; `errors.json` keeps its scenario names.
- Re-run: `tests/connectors tests/execution tests/demo tests/api tests/hunt backend/tests
  checks/tests`: 728 passed, 1 skipped.

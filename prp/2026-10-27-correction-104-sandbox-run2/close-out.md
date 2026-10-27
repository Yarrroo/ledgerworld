# Correction 104: the second sandbox run's three failing checks — Close-out
> Close-out (/dev-close). Source: board item 104 (dev-fix).
> Date: 2026-10-27

## What broke, and why
The second contract run on the real sandbox (api_version 2024-09-27) passed 10 of 14 checks.
- **global-accounts** — "no USD global account among 1". From 2024-09-27 a Global Account has no
  `currency` key; its currencies are in `required_features[]` / `supported_features[]` (the run's
  diff listed both keys). The check, the gateway, `gateway_from_env` and the demo's wallet
  funding all read `currency`.
- **fx-conversion-replay** — the conversions endpoint refuses a replay as `400 invalid_argument`
  "request_id '…' has been used in the past" (transfers answer `request_id_duplicate`). The
  client knew only the duplicate codes, so the gateway would have marked a conversion that had
  in fact moved as `Rejected` instead of adopting it by lookup.
- **payout-to-paid** — "outcome unknown for request_id None: http 500". The sandbox moved the
  payout to `PROCESSING` by itself (the lookup read `PROCESSING` right after the create), and
  the first transition asked for `PROCESSING`. Inferred from the run, not confirmed live.

## What shipped
- `client.py`: `account_currencies` and `global_accounts_by_currency`, where an account whose own
  currency it is wins over one that only supports it. The contract check takes the same
  account. `global_account_in` serves the gateway and the API services,
  `global_accounts_by_currency` the demo.
- `_replayed`: the conversions' "has been used" refusal becomes a `DuplicateRequest`, and so does
  a duplicate code.
- `simulate_transition` reads a refused or unknown transition back. A transfer at or past the
  target on `PAYOUT_PATH` is the answer. Only a `PAYOUT_PATH` step left unknown is sent again,
  and only while the transfer is on the step before it, at most 3 times. A `FAILED` transition
  is sent once.
  `OutcomeUnknown` names the transfer (`provider_id`) and the status it holds.
- `checks/airwallex_live.py` walks `PAYOUT_PATH` from the client. A failure reports the
  transfer id and the step.

## Verification
- `uv run pytest -q backend/tests/finance/test_airwallex_sandbox_run2.py`: 18 passed. Each answer
  is replayed through an `httpx.MockTransport` sandbox. Run against the code from before the fix,
  the file does not import. Run against each vet round's starting commit, that round's new
  tests fail (6 in round 1, 2 in round 2).
- Touched suites (`tests/connectors tests/execution tests/api tests/demo checks/tests
  backend/tests/finance`): 576 passed, 1 skipped. `checks/airwallex_live.py --fake`: 14/14.
  ruff, attribution and no_secrets: ok.
- Not run: `--require-key`. This pane holds no Airwallex credential, and `research` refused
  (no `PPLX_API_KEY`), so the feature shape rests on the run's own key listing.

## Vet
vet: T3 (money path: duplicate classification feeds the gateway's conversion legs; a resent
POST on payouts), round 2, 14 applied (7 proven, 0 unproven, 7 quality), 13 recorded, 0 open.
Recorded with reasons:
- The check's race after a made step: already covered by the read-back (the test passed before
  the fix).
- `demo.pay` working from a stale status: its status is read fresh at the call.
- The gateway's single Global Account cache: older than this change; listed below.
- The fake's old shapes: listed below.
- Three efficiency notes: error path only, a few calls per run.
- A shared retry helper or an idempotent-POST flag in `_request`: one endpoint does not earn a
  general mechanism.
- The check's pre-read of the status: removed on purpose. The read-back covers what it covered
  and also the races it missed.
- The demo's own `PAYOUT_PATH` copy: older than this change.
- `required_features` counted as the account's own currencies: by design.
- Two passes over a handful of accounts: kept for clarity.
`/security-review`: no findings.

## Follow-ups / known gaps
- The run's diff still fails where the fake differs from the sandbox. The fake's Global Account
  still carries `currency`. Its replay codes are `duplicate_request_id`, where the sandbox
  answers `request_id_duplicate` and `invalid_argument`. Its quote answers 201, not 200, and
  carries `valid_to`. Its conversions stay `SCHEDULED` with an `id`, its payouts `SCHEDULED`,
  and its error envelope has a `trace_id`. These belong to a fake/fixture alignment item.
- The gateway caches one Global Account id for every currency (older than this change).
- If the sandbox answers 500 to every transition, the check now says so by transfer and step;
  only a live run can tell.

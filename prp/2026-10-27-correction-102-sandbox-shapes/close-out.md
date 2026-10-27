# Correction 102: sandbox request shapes — Close-out
> Close-out (/dev-close). Source: board item 102 (dev-fix).
> Date: 2026-10-27

## What shipped
- `x-api-version` default and floor raised to 2024-09-27 (`transport.py`). The cause: before
  that version `/api/v1/transfers` is the connected-account transfer. That is why the sandbox
  asked a payout for `currency` and answered the list with `incorrect_version` (provider
  changelog, 2024-09-27).
- FX quote sends `validity` (`MIN_15`); payout sends the required `reason` (`business_expenses`)
  and `reference` (the `request_id` when none or empty is given) (`client.py`).
- Conversions are created, read and listed under `/api/v1/fx/conversions` (client, gateway,
  reconcile, fake).
- Mode A only on an `ACTIVE` account in the connected-accounts list; a 200 with no status, no
  active account or no items list selects Mode B (`on` fails at start). The contract pass takes
  the active account's id.
- The fake enforces the same: `validity` required (and `valid_to` follows it), `reason` and
  `reference` required, the transfers paths refused before 2024-09-27 as the sandbox did.
- Design fixtures, `00-system.md`, `DESIGN.md`, `HANDOFF.md`, `README.md` say 2024-09-27 and
  the fx path.

## Verification
- `uv run pytest -q backend/tests/finance/test_airwallex_sandbox_shapes.py`: 14 passed. The
  file failed at import before the fix, and 4 of the vet-round tests failed before their fixes.
- Touched suites (`tests/connectors tests/execution tests/api tests/demo tests/hunt checks/tests
  deploy/tests` plus the new file): 596 passed, 1 skipped.
- `uv run python checks/airwallex_live.py --fake`: 14/14 PASS.
- ruff, `checks/attribution.py` and `checks/no_secrets.py`: ok. The full `checks/merge.sh` is
  left to the landing train, as the order says.
- Not run: `--require-key` on the real sandbox. The pane holds no Airwallex credential, so the
  fix rests on the provider's published reference and changelog, not on a live answer.

## Follow-ups / known gaps
- `gateway_from_env` (api/v1/services.py) can choose Mode A with no connected account id, and
  nothing checks that a configured id is the active one. This is older than this change.
- The probe reads only the first page of the connected-accounts list.
- The gateway sends the receipt label as the payout reference. Its length and format on LOCAL
  rails have not been checked on the sandbox.

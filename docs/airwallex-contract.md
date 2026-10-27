# Airwallex contract

What the connector (`backend/app/connectors/airwallex/client.py`) and its fake (`fake.py`) are
held to, as verified on the Airwallex sandbox. The pass is `checks/airwallex_live.py`: the
canonical requests (`design/modules/airwallex/fixtures/canonical-requests.json`) run on the
sandbox, then on the fake, and every answer's HTTP status, key set and status value is diffed.

**Last verified:** 2026-10-27, sandbox run 4 · `x-api-version: 2024-09-27` · Mode B (connected
accounts not enabled) · sandbox 14/14, fake 14/14. The fake's key sets are pinned in
`checks/airwallex_canon.json` and enforced offline by
`backend/tests/finance/test_airwallex_fake_keys.py`.

**Live demo run:** 2026-10-27, run `demo-20261027T190757Z-9674` · Mode B · scripted agents
(`scripts/demo.sh --mode sandbox`, `LLM_BASE_URL=scripted://family`) · fresh branch
`…-shock-integrated` (16 rounds) · advance `e7c4579c-9388-4191-93ac-67d80bc435ae` `SETTLED` ·
payout `3e8e7a6d-620c-466b-98f9-e76c101ce8a5` `PAID` · reconciled, no incidents ·
`checks/demo_receipt.py --require-live`: live checkpoints 3/3. The receipt stays in `var/demo/`.

## Verified behaviour

| Step | Sandbox answer the fake reproduces |
|---|---|
| Login | `201 {token, expires_at}` |
| Balances | `200`, items `currency, available_amount, pending_amount, reserved_amount, total_amount` (JSON numbers) |
| Global Accounts | no `currency` key; currencies are in `required_features` / `supported_features` |
| FX quote | `200` (not 201), `quote_id`, `client_rate`, end named `valid_to_at`; `validity` required |
| Conversion | `201`, `SETTLED` at create, named `conversion_id` (no `id`) |
| Conversion replay | `400 invalid_argument` "request_id '…' has been used in the past", no `trace_id` |
| Payout | `201 SCHEDULED`; reads back `PROCESSING` straight after (the sandbox moves it on) |
| Payout replay | `400 request_id_duplicate`, no `trace_id`; the original found by `GET /api/v1/transfers?request_id=…` (one) |
| To `PAID` | `simulation/transfers/{id}/transition` from `PROCESSING` → `SENT` → `PAID`; USD moves −10000 minor once |
| Mode B advance | `simulation/deposit/create` answers `201 PENDING` with `id, amount, currency, reference, status` only; `SETTLED` observed on `GET /api/v1/deposits?page_num&page_size`; USD moves +1000000 minor once |
| One movement | exactly one transfer and one conversion per `request_id` |

## Assumptions of §10 that changed

- **Connected-accounts probe** (the one `assumed` row): `GET /api/v1/accounts`. The sandbox
  account has no active connected account, so the pass runs Mode B; the Mode A legs
  (`connected_account_transfers`, `charges`) are not verified and keep their documented shapes.
- **Deposit simulation `amount`**: sent as a JSON number and accepted. Request amounts on
  transfers, quotes and conversions stay decimal strings.
- **Deposit settlement** is asynchronous: the create answers `PENDING`, never `SETTLED`.
- **Duplicate `request_id`**: rejected per collection as above, never answered with the original.
- **API version**: before `2024-09-27`, `/api/v1/transfers` is the connected-account transfer.

## Differences found and fixed in the fake

| Run | Difference | Fixed by |
|---|---|---|
| 2 | quote 201/`valid_to`; conversion unsettled with `id`; replay code `duplicate_request_id` with `trace_id`; payout read `SCHEDULED`; Global Account `currency` key | board items 104, 105 |
| 4 | `trace_id` on the conversion replay | board item 16 |
| 4 | `created_at`, `global_account_id`, `request_id` on the deposit create | board item 16 |

The deposit list still carries `global_account_id` and `created_at` in the fake; the pass does
not diff the list, so those two are unverified there.

## Re-running

`uv run python checks/airwallex_live.py --require-key` with `AIRWALLEX_CLIENT_ID`,
`AIRWALLEX_API_KEY` and `AIRWALLEX_BENEFICIARY_ID` set (sandbox only; production is refused).
A key only the fake returns fails the pass. When the sandbox shows a new key, add it to the fake
and to `checks/airwallex_canon.json` together, and update this page's date.

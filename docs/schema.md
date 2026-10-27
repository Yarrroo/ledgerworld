# Schema

The contracts are JSON Schema files in `contracts/`, generated from the pydantic v2 models in
`backend/app/finance/schemas.py`. Valid and invalid examples sit in `contracts/examples/<contract>/`.
`tests/contracts/test_contracts.py` proves that the models, the schemas and the examples agree. The
schema files are the source of truth, and this page is a map of them.

## Money

`Money = {minor: int, currency}`. `minor` is an integer count of minor units. `currency` is an
ISO-4217 code from USD, EUR, GBP, JPY, AUD, HKD, SGD or CNY. `Amount` is the same shape with
`minor > 0`, and is what an intent, a leg or an obligation moves. No contract carries a float or a
decimal string. The connector converts minor units to the provider's decimal string at the
boundary, and nowhere else.

## Contracts

| Contract | File | Required fields | Rule |
|---|---|---|---|
| C1 ActionIntent | `c1_action_intent.schema.json` | `intent_id, branch_id, round, actor_id, type, params, evidence_ids[], obs_hash` (optional `priority_class` 0–3, `sim_minute`) | `type` ∈ request_advance · offer · accept · disburse · repay · convert · pay · pledge · release · defer · no_action. A rejected or malformed intent becomes `no_action`. |
| C2 ClearedAction | `c2_cleared_action.schema.json` | `intent_id, status, round` (optional `reason, binding, journal_id`) | `status` ∈ accepted · rejected · pending. A rejection carries a reason. The actor sees it the next round. |
| C3 BoundApproval | `c3_bound_approval.schema.json` | `approval_id, entity, account, legs[], plan_hash, snapshot_id, expires_at, mode, approver` | A leg has `kind` (advance · repayment · fx · payout), an `amount` and its terms. `mode` ∈ fake · sandbox. Any term outside the bound invalidates the whole approval. |
| C4 ProviderOp | `c4_provider_op.schema.json` | `leg_id, request_id, kind, state, receipt, reconciled` (optional `provider_id, journal_id`) | `state` ∈ pending · submitted · settled · failed · unknown. `settled` requires a `journal_id`. `unknown` opens an incident and is looked up by stored ids before any retry. |
| C5 Snapshot | `c5_snapshot.schema.json` | `snapshot_id, as_of, entities[], accounts[], obligations[], contracts[], exposures[], pools[]` | Details are in the next section. |
| C6 API | `c6_api.schema.json` | one `$defs` entry per request and response | Validate a body against `#/$defs/<Name>`, for example `HealthResponse` or `OverviewResponse`. |

## C5 Snapshot in detail

- **Entity** `{entity_id, name, kind, synthetic, escalation?}`. `escalation` names a role to contact
  when every plan is infeasible.
- **Account** `{id, entity, currency, kind, venue?, floor?, observability, buckets}`.
  `observability` ∈ known · unknown.
  - `buckets = {settled, reserved, pledged, pending_in[], pending_out[]}`.
  - `settled` is null exactly when the account is unknown. Unknown is never zero.
- **Flow** `{flow_id, kind, amount, expected_at, reservation_id?}`, a pending inflow or outflow.
- **Obligation** `{obligation_id, entity, account, kind, amount, due_at, mandatory, state, reservation_id?}`.
- **Contracts** are discriminated by `kind`:
  - `revenue_advance`: `principal, fee_bps, repay_share_bps`.
  - `committed_line`: `limit, drawn`.
  - `collateral_facility`: `limit, advance_rate_bps`, simulation only.
- **Exposure** `{exposure_id, account, venue, flow_id?, shared_with[]}` links two entities to one
  venue.
- **Pool** `{entity, floor}`, a lender pool and its reserve floor.

## C6 API routes

All routes are under `/api/v1`. Every response carries `as_of` and `mode`.

| Route | Request → response `$defs` |
|---|---|
| `GET /health` | `HealthResponse` |
| `GET /overview` · `/treasury` · `/lending` | `OverviewResponse` · `TreasuryResponse` · `LendingResponse` |
| `POST /runs` · `GET /runs/{id}` · `POST /runs/{id}/fork` | `RunRequest → JobAccepted` · `RunResponse` · `ForkRequest → JobAccepted` |
| `GET /decisions/{run_id}` | `DecisionsResponse` |
| `POST /approvals` · `POST /executions` · `GET /executions/{id}` | `ApprovalRequest → ApprovalResponse` · `ExecutionRequest → ExecutionAccepted` · `ExecutionResponse` |
| `POST /webhooks/airwallex` | `WebhookAck`; the signature is verified and no token is needed |
| `POST /interview` · `GET /reports/{run_id}` | `InterviewRequest → InterviewResponse` · `ReportResponse` |

Every user `POST` needs `Authorization: Bearer $LEDGERWORLD_DEMO_TOKEN`. Errors are an
`ErrorResponse`.

## Storage

- **Ledger:** SQLAlchemy Core in `backend/app/finance/models.py`, which mirrors
  `prp/2026-10-20-ledgerworld/design/modules/ledger/schema.sql`. Migrations are in
  `backend/app/finance/migrations/`. The tables are `branch_meta`, `entities`, `accounts`,
  `account_observations`, `journals`, `postings`, `expected_flows`, `obligations`,
  `reservations`, `pledges`, `lending_pools`, `facilities` and `revenue_observations`. A
  settled balance is never a column: it is the sum of an account's postings. Each journal
  balances per currency.
- **Execution:** `backend/app/execution/` uses the tables of
  `design/modules/execution/schema.sql` in the observed ledger store: `approvals`,
  `execution_legs` (the outbox), `leg_events`, `incidents` and `webhook_events`, plus the
  gateway's own `approval_terms`.
- **Jobs:** `backend/app/jobs/store.py` holds `jobs` and `records` (runs, decisions, transcripts).

# Execution gateway (T13) — close-out

> Close-out (dev-build stage 5). Source: design.md. Board item 14.

## What landed

- `backend/app/execution/gateway.py` stores the approval's C3 terms, then runs `verify` and the
  ledger-backed preflight. An accepted approval is queued together with its ledger effects in
  one transaction. Each leg kind and mode has an adapter over the Airwallex client, and each leg
  kind has its settle journal.
- `backend/app/execution/reconcile.py` runs the sweep: it drives open legs, re-reads reconciled
  payouts, flags orphan provider objects and releases failed legs. A `paid_then_failed` incident
  reopens the obligation. The module also turns a webhook hint into a `GET`, and records webhook
  events in `webhook_events`.
- `backend/app/execution/outbox.py` takes a pluggable `transaction`, so a leg's settle, its
  `leg_events` row and its journal commit together.
- Tests: `tests/execution/test_gateway.py` and `tests/execution/test_reconcile.py` load all five
  T13 fixtures unchanged. The g1 ids are registered in `checks/required.json`, and the
  ledger-backed placeholder skip in `test_approval_binding.py` is removed.

## Verification

- `uv run pytest -q tests/execution`: 153 passed, 1 skipped (the token route).
- ruff, `no_secrets` and `attribution`: ok. The full suite is run by the landing train
  (`bash checks/merge.sh`), not in this slot.

## Not wired here (named follow-ups)

- **Routes.** `POST /api/v1/approvals` and `/executions`, `GET /executions/{id}`, and
  `POST /webhooks/airwallex` do not exist yet. When the API module lands, each route is one call:
  `Gateway.record`, `Gateway.execute`, `Gateway.legs`, or
  `reconcile.webhook_verifier(...).verify_and_ingest`.
- **Sweep job.** The 60 s sweep needs a scheduled job in `backend/app/jobs`. It calls
  `reconcile.sweep` while `reconcile.open_legs` is not empty.
- **PostgreSQL.** The gateway uses the ledger's SQLite DBAPI connection, because the outbox is
  written in raw sqlite3. Deploying on PostgreSQL needs an outbox on SQLAlchemy Core.
- **Client API.** The client has no public get/find for connected-account transfers and
  charges, and no list-all. The gateway uses `AirwallexClient._request`/`_find` for these.
  `client.py` should expose them.
- **Mode B deposits.** A deposit has no lookup, so an unknown deposit is left for the operator.
  T15 confirms whether the provider can list deposits by reference.

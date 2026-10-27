# Execution gateway (T13) — build design

> Design output (dev-build stage 2). Source: briefs/T13.md and design/modules/execution/HANDOFF.md
> (the approved module design; this note records only what the build had to decide beside it).
> Next: implement → close-out.

## Consumers (who reads or writes this)

| Consumer | What it uses | Status |
|---|---|---|
| `POST /api/v1/approvals`, `POST /api/v1/executions`, `GET /api/v1/executions/{id}` | `Gateway.record`, `Gateway.execute`, `Gateway.legs` | route module not built yet (API task) |
| `POST /api/v1/webhooks/airwallex` | `reconcile.webhook_verifier(gateway, secret).verify_and_ingest` | one line of wiring when the route lands |
| `scripts/demo.sh` / `backend/app/demo` (T23), live run (T31) | `Gateway`, `reconcile.sweep` | later tasks |
| the 60 s sweep job (`backend/app/jobs`) | `reconcile.sweep(gateway)` while `open_legs()` | later task |
| T14 boundary, T29 money-safety hunts | `app.execution.gateway` is the import the sim role is refused | later tasks |

## Decisions the HANDOFF left to the build

1. **One store, one transaction.** The execution tables live in the observed ledger store
   (`LedgerStore`, SQLite). The gateway opens the outbox on the store's own DBAPI connection and
   gives it the ledger's transaction (`Outbox(transaction=…)`), so a leg turning `settled`, its
   `leg_events` row and its ledger journal commit together or not at all.
2. **The approval's terms are stored** (`approval_terms`, beside `approvals`): verification
   compares what is presented with what was bound, and a restarted gateway needs a leg's
   facility and target currency, which `execution_legs` does not carry.
3. **Ledger effects.** At queue (same transaction as the legs and `used_at`) every leg's money
   is spoken for on its source: a reservation-funded leg commits its reservation into a pending_out
   flow, any other leg adds one (named by the leg id, `<leg>:out` for an advance), and an advance
   is also a pending_in to the borrower. At settle: payout → `settle_flow` (reservation settled,
   obligation met); the others close their flows and post their own journal: advance →
   `lending.disburse` (`j-<facility>-disburse`), fx → one journal balanced per currency from the
   provider's buy amount, repayment → `lending.repay` for the oldest observed, unrepaid period,
   which preflight already required to owe exactly the leg's amount. A failed leg's flows are
   cancelled (a committed reservation returns to held). A journal the ledger refuses after the
   provider moved the money is incident `ledger_refused` (added to `schema.sql`); the leg waits,
   and the next pass that posts it closes the incident.
4. **Connector adapter.** Connector errors map onto the outbox's: refusal → `Rejected`;
   duplicate id / 409 → `DuplicateRequest` (adopted by lookup); `OutcomeUnknown` → may have sent
   unless the transport says it never left; a retryable refusal (429) → never left. Lookups that
   error → `LookupFailed`, the leg stays as it is.
5. **Mode B deposit.** The deposit simulation takes no `request_id` and the client has no deposit
   list, so its reference carries the leg id and an unknown deposit stays unknown with its
   incident open for the operator (HANDOFF failure-modes row; T15 confirms the list).
6. **FX amounts.** A C3 fx leg binds the sell side (`amount` in the source currency, `to_currency`
   the target), the side the connector and the outbox compare; the reconciliation fixture's
   EUR 10,000.00 buy is reached by selling USD 11,100.00 at the fake's 1.1100.

---
Run footer: architect ran at tier Sketch. The module design was already approved in
design/modules/execution/HANDOFF.md, and this note only records the build-level decisions and
names the consumers. No reviewer pack on this node, and no publish step (the run is unattended).

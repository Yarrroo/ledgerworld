# execution — the only door from a plan to money

Tasks: T13 (gateway: approval binding, outbox, idempotent legs, reconciliation) · T14 (hunt: credential and network isolation) · T23 (`scripts/demo.sh`) · T31 (live sandbox demo run).
Read with `00-system.md` §4, §8 (C3, C4), §10 and §13, the airwallex module (the connector this gateway drives) and the ledger module (`check_outflow`, reservations, `advance-journals.json`). The fixtures in `fixtures/` are the test truth, and the tables are in `schema.sql` (DDL only; it loads clean in SQLite next to the ledger's schema).

Four rules this module exists to keep:
- **A plan moves money only as a bound approval (C3), once.** Any term outside the bound — amount, counterparty, an extra leg, the mode, the snapshot, the expiry — refuses the whole approval before anything is written.
- **The outbox row comes before the call.** A leg is written with its fixed `request_id`, then marked `submitted` (provider id still empty) before the connector is called. A restart that finds `submitted` without a provider id looks the leg up by `request_id`; it never sends blind.
- **The provider's `GET` is the truth.** A leg settles, and its journal posts, in one transaction, only when a `GET` shows the terminal status. A webhook is a verified hint that triggers that `GET`. A later contradiction (`PAID → FAILED`) opens an incident and never auto-corrects.
- **The simulation cannot reach any of this.** A sim worker has no provider variable in its environment, cannot import the live connector or the gateway, and its tools only queue C1 intents in a branch store.

## Interfaces

| Unit | File | Shape | Notes |
|---|---|---|---|
| `bind(plan, snapshot, approver, mode, ttl=15 min)` | `backend/app/execution/approval.py` | `→ BoundApproval (C3)` | `plan_hash` = sha256 of the canonical JSON (sorted keys, no spaces) of `{entity, account, legs, snapshot_id, mode}`. Legs carry `index, kind, amount, currency, source, counterparty, funded_by?, after?` and are hashed in their C3 shape (`amount: {minor, currency}`, defaulted fields left out); the contract examples carry that hash. |
| `verify(approval, presented, now, current_snapshot_id, gateway_mode)` | `approval.py` | `→ ok \| Refusal` | Refusal codes: `approval_altered, approval_expired (at expires_at exactly), approval_used, mode_mismatch, not_observed_snapshot, snapshot_moved, unowned_funds, beneficiary_not_allowed, reservation_mismatch, stale_balance, unknown_balance, breaks_floor, insufficient_spendable, not_an_approval`. (`approval-binding.json`) |
| preflight per leg | `gateway.py` | ledger `check_outflow` for `funded_by: spendable`; the held amount equals the leg amount for `funded_by: reservation:<id>`; source owned by the entity; payout beneficiary allowlisted; in sandbox mode, `balances/current` available ≥ amount; an arrival due by now and not landed is overdue and adds nothing (the observed ledger lands nothing unobserved, and a settling leg lands no other arrival); one reservation funds one leg; a facility disburses or repays through one leg at a time; a pool's advance legs share its K_p | All legs pass, or none is queued. |
| `Gateway.record(approval)` · `Gateway.execute(presented, current_snapshot_id=)` | `gateway.py` | `record` stores the bound terms; `execute` verifies the presented approval against them, runs the preflight, queues the legs with their ledger effects (one transaction), then runs each leg whose `after` legs are settled | Claim = conditional update `pending → submitted`; only one worker wins. Returns `Execution(execution_id = approval_id, legs)` or the `Refusal`. |
| `Outbox` / `LegState` | `outbox.py`, `state.py` | the `execution_legs` and `leg_events` tables; transitions from `leg-state-machine.json` only | `request_id = <plan_hash[:12]>-<index>-<kind>`; it never changes. Every transition writes one `leg_events` row in the same transaction. |
| `ConnectorProvider.find(leg)` (the outbox resolves `unknown` with it) | `gateway.py` | connector `find_transfer` / `find_conversion` (list by `request_id` for connected-account transfers and charges); a Mode B deposit has no list in the client yet, so it stays `unknown` for the operator until T15 confirms one | 1 found → adopt; 0 found and the last attempt could not have been sent → `pending`, same id; error or more than 1 → stays `unknown`, incident open. |
| `reconcile_leg(gateway, leg_id)` · `sweep(gateway)` | `backend/app/execution/reconcile.py` | `GET` by provider id → state, journal, incidents | Journals: the advance posts `j-adv-…-disburse` (ledger module); a payout settles its reservation and meets the obligation; FX posts balanced per currency; a Mode B repayment is ledger-only. Sweep every 60 s while any leg is open (`open_legs`), and once after each run. A journal the ledger refuses after the provider moved money is incident `ledger_refused`. (`reconciliation.json`) |
| `verify_and_ingest(headers, raw_body, now)` | `backend/app/connectors/airwallex/webhooks.py` | `→ 200 \| 401` | Hex HMAC-SHA256 over `x-timestamp` + the raw bytes, keyed by `AIRWALLEX_WEBHOOK_SECRET`; older than 5 min → 401; deduped by event id; the only action is `reconcile.on_hint` (a `GET`). `reconcile.webhook_verifier(gateway, secret)` builds it. The route `POST /api/v1/webhooks/airwallex` is one line of wiring. (`webhooks.json`) |
| `spawn_sim(env)` / import guard | `backend/app/execution/boundary.py` | scrubbed env with `LEDGERWORLD_ROLE=sim`; `app.connectors.airwallex.live` and `app.execution.gateway` raise `BoundaryViolation` on import under role sim | (`isolation.json`, T14) |
| routes | API module wiring | `POST /api/v1/approvals` (token) → C3 · `POST /api/v1/executions` (token) → `{execution_id}` · `GET /api/v1/executions/{id}` → legs with state, label, provider id, journal id, incidents | Every response carries `as_of` and `mode`. |
| demo | `scripts/demo.sh`, `backend/app/demo/run.py`, `checks/demo_receipt.py` | `--mode fake\|sandbox --out FILE`; the seven beats of §13; receipt per `demo-receipt.json` | `--require-live`: three checkpoints in mode sandbox with provider ids → `demo_checkpoints_live = 3`. Setup funding of the sandbox wallet is listed apart and labelled. |

## Data

- Tables: `schema.sql` defines `approvals, execution_legs, leg_events, incidents, webhook_events`. They live in the **observed** ledger store only; a branch store never has them.
- What the database refuses on its own (checked once in SQLite):
  - a second leg with the same `request_id`;
  - a settled leg without a journal;
  - a settled provider leg without a provider id;
  - a second open incident of the same kind on one leg;
  - one journal claimed by two legs.
- Leg ↔ ledger:
  - At queue time, a reservation-funded payout commits its reservation (the units move to `pending_out`, so S already excludes them).
  - An advance is a `pending_in` to borrower-a until it settles.
  - The journal posts only at `settled`.
- Labels come from the connector's `leg_plan`. A Mode B advance always reads "advance inflow (sandbox simulation)"; a Mode B repayment reads "repayment (simulated)".
- The demo's approval is LF-1's integrated plan as executed: an advance of 10,000.00 into borrower-a (LF-2's `adv-a`, fee 800.00 booked in the ledger only), then the 50,000.00 payroll payout from `res-payroll-1`, which runs after the advance settles.
- The sandbox wallet is not the synthetic ledger. In sandbox mode the gateway checks both, and T31 funds the wallet with one labelled setup deposit that the receipt lists apart.

## Fixtures

| File | Drives | What it pins |
|---|---|---|
| `fixtures/approval-binding.json` | T13 | the base C3 approval (advance + payroll payout) and 15 cases: ok, 3 alterations, expiry at the boundary, mode, a branch snapshot, a moved snapshot, unowned funds, a beneficiary off the allowlist, stale balance, breaks floor, reservation mismatch, no token, approval reused |
| `fixtures/leg-state-machine.json` | T13 | 5 states, 9 allowed and 5 forbidden transitions, the ledger-only path, dependencies |
| `fixtures/crash-and-retry.json` | T13, T29 | 6 crash points and 11 cases (timeouts, the lookup race, lookup errors, two workers); property: at most one provider object per id and one journal per leg |
| `fixtures/reconciliation.json` | T13 | the advance closed in Mode A and B, payout PAID, PAID → FAILED, amount and currency mismatch, an orphan provider object, the Mode B repayment, FX balanced per currency; the sweep |
| `fixtures/webhooks.json` | T13 | real HMAC values over a fixed body: valid, wrong secret, altered body, a correctly signed FAILED that is still only a hint, a re-serialised body, stale, missing headers, a replay, unknown events |
| `fixtures/isolation.json` | T14 | the scrubbed env, the import refusals (live connector, gateway), no execution tool on any actor, an intent never reaching the outbox, the secret sentinel across a whole fake demo |
| `fixtures/demo-receipt.json` | T23, T31 | the receipt shape, one valid fake receipt, 8 invalid ones (cached branch, payout only SENT, a mislabelled Mode B, setup counted as a checkpoint, live without a provider id) |

## Failure modes

| Failure | Where it bites | Guard |
|---|---|---|
| The provider is called before the outbox row exists | a crash leaves money moved with no record | queue, then `submitted`, then call; `crash-before-send` / `crash-after-send` |
| Retry after a timeout under a fresh id | double payroll | the id is fixed at queue time; `unknown` → lookup; money-safety hunt `timeout-retried-blindly` |
| A webhook settles a leg | a forged or premature PAID posts a journal | the event only triggers a `GET`; `altered-body-own-signature` |
| The signature is checked on re-serialised JSON | every real webhook fails, or a forged one passes | raw bytes; `reserialised-body` |
| `PAID` read as final | payroll counted as paid, then the transfer fails | incident `paid_then_failed`, the obligation reopens, the reversal waits for the operator |
| An approval re-checked only on its hash | a moved snapshot or an expired approval still executes | `snapshot_moved`, `approval_expired`, `approval_used` |
| A branch's plan executed directly | money moved on a hypothetical state | `not_observed_snapshot`, `not_an_approval`; branches have no execution tables |
| Payout from an account the entity does not own | moving another party's money | `unowned_funds` |
| The ledger says yes but the sandbox wallet is short | `balance_insufficient` mid-demo after the advance moved | sandbox preflight reads `balances/current` for every leg before queueing; T31 setup funding |
| A Mode B deposit cannot be looked up by `request_id` | an unknown advance stays unknown | the reference carries the leg id; T15 confirms the deposit list filters, or the incident closes by the operator |
| A failed advance still lets the payout run | payroll paid from money that never arrived | `after` dependencies; a failed dependency fails the leg without a call |
| Two workers claim one leg | two POSTs, one rejected as duplicate, confusing state | conditional claim; `two-workers` |
| Mismatch auto-corrected | the ledger is silently rewritten to match the provider | incidents only; a posted journal is never edited |
| Sim worker inherits the parent env | an agent process holds the provider key | `spawn_sim` scrubs every `AIRWALLEX_*` and the demo token; `sim-env-scrubbed` |
| A demo receipt counts the setup deposit | g3 measured on a funding move, not the plan | setup listed apart; `setup-counted` |

## Done-whens

- accept: uv run pytest -q tests/execution/test_gateway.py — fixture: fixtures/approval-binding.json
- accept: uv run pytest -q tests/execution/test_gateway.py — fixture: fixtures/leg-state-machine.json
- accept: uv run pytest -q tests/execution/test_gateway.py — fixture: fixtures/crash-and-retry.json
- accept: uv run pytest -q tests/execution/test_reconcile.py — fixture: fixtures/reconciliation.json
- accept: uv run pytest -q tests/execution/test_reconcile.py — fixture: fixtures/webhooks.json
- accept: uv run pytest -q tests/execution/test_isolation.py — fixture: fixtures/isolation.json
- accept: uv run pytest -q tests/demo/test_demo_fake.py — fixture: fixtures/demo-receipt.json
- accept: uv run python checks/demo_receipt.py var/demo/live.json --require-live — fixture: fixtures/demo-receipt.json

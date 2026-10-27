# T16 · API /api/v1 and the job runner — workflow

> Workflow output (build stage 3, design folded in: Medium). Source: briefs/T16.md, system brief §11,
> design/modules/ui/HANDOFF.md. Next: implement → close-out.

## Requirements (from the brief's accept)

- Every C6 route of `C6_ROUTES` answers its schema on LF-1/LF-2; every response carries `as_of`, `mode`.
- Metric states known/unknown/stale/unassessed, run status queued/running, completeness partial: representable.
- Writes need `Authorization: Bearer $LEDGERWORLD_DEMO_TOKEN` (the interview POST too); the signed webhook is
  the only unauthenticated POST; approval without a token is refused; reads take no token and write nothing.
- Runs are durable jobs: Redis queue with leases, retries, cancellation; job state in the ledger store's database;
  submit answers < 1 s.
- Overview names the prepared demo run and the execution associated with it, or null — never the latest execution.

## Shape

| Unit | Holds |
|---|---|
| `app/jobs/store.py` | `api_jobs` (state, attempts, cancel flag) and `api_records` (run, decisions, transcript, approval→run, demo) tables on the ledger store's engine |
| `app/jobs/queue.py` | `JobQueue` (submit, claim with a lease, heartbeat, complete, fail→retry, cancel, reap expired leases, re-push queued rows Redis lost) and `Worker` |
| `app/jobs/runner.py` | the two handlers: `run` (a family world, round by round, each committed round written) and `fork` (rebuild the run to the checkpoint, check replay identity, `decisions.evaluate` + `rank`); imports no connector |
| `app/api/v1/services.py` | one `Services`: observed snapshot + its ledger store, gateway, queue, clock, mode, token, models |
| `app/api/v1/views.py` | Overview / Treasury / Lending projections from the observed store (S, P, K_p via finance) |
| `app/api/v1/routes.py` | the fourteen C6 routes, token check, error bodies |
| wiring | `backend/app/__init__.py` registers the blueprint (upstream file, listed in ATTRIBUTION.md) |

Contract gap fixed in `contracts/`: `RunResponse.status` gains `cancelled` (a cancelled job is not a failure).

## Phases and gates

1. Jobs store + queue + worker → unit tests on fakeredis (lease expiry, retry, cancel).
2. Runner handlers → a real 3-round family run and a fork through the worker.
3. Services, views, routes, wiring → every route validated against `contracts/c6_api.schema.json`.
4. Gate: `uv run pytest -q tests/api/test_api_v1.py`, ruff on new paths, contracts/attribution tests.

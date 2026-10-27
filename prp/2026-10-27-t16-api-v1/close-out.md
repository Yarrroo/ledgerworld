# T16 · API /api/v1 and the job runner — close-out

> Close-out (build stage 5). Source: workflow.md, briefs/T16.md.

## What landed

- `backend/app/api/v1/`: the fourteen C6 routes on the upstream Flask app (`create_app` registers
  them; the two-line wiring is listed in `ATTRIBUTION.md`). Every body is validated against its C6
  model before it leaves. Reads are public and write nothing; every user POST (the read-only
  interview too) needs `Authorization: Bearer $LEDGERWORLD_DEMO_TOKEN`; the signed webhook is the
  one POST without it and is verified before anything is locked or started.
- Overview / Treasury / Lending are read from the observed ledger store through finance (S, P,
  K_p). Metrics carry known / unknown / stale / unassessed; completeness is partial on an unknown
  or stale cash account; coverage is the minimum of the accounts' combined projection.
- Overview's `demo` names the run `Services.prepare_demo` set and only an execution approved from
  that run; otherwise null.
- `backend/app/jobs/`: a Redis queue (leases renewed by a heartbeat, retries, cancellation, reaping
  of expired leases and of jobs Redis lost) with the job state and the API's records in the ledger
  store's database. `python -m app.jobs` is the worker; it needs `REDIS_URL` and
  `LEDGER_DATABASE_URL` and imports no connector or gateway.
- A run job runs a scenario family on the demo world round by round, each committed round readable
  at once. A fork job rebuilds a scripted run to its checkpoint, refuses a replay whose journals
  differ, and ranks the policies (`decisions.evaluate` + `rank`).
- Approvals re-decide the selected policy on the observed snapshot (`plan_for_now`) and bind C3;
  executions go through the gateway, then a reconciliation sweep.

## Contract and dependency

- `RunResponse.status` gains `cancelled` (model in `finance/schemas.py`, regenerated
  `contracts/c6_api.schema.json`).
- `redis>=5.0` is a runtime dependency (it was already locked through `fakeredis`).

## Known limits

- Policy branches keep no transcript, so only a run's base branch can be interviewed (404
  `no_transcript` otherwise): `decisions.evaluate` returns no worlds.
- The gateway is SQLite-bound; one process lock serialises the observed store, so a slow provider
  call during an execution holds the reads until it returns.
- No model writes the report sections; the template does, and the report says `scripted`.
- Measured: delayed-receipt (seed 101, 5 rounds) forked at round 2 decides `all_infeasible` — all
  three policies keep cash at 20,000.00 at t=40 against the 30,000.00 floor, escalated to the
  treasury operator. The demo world's snapshot holds no revenue advance for the treasury, so
  `integrated` has nothing to draw; an approval therefore comes only from a selected decision
  (the tests seed one on LF-1/LF-2, where `adv-a` exists).

- An expired approval cannot be replaced by the same plan on the same snapshot: the execution
  schema keeps `UNIQUE (plan_hash, snapshot_id)` (execution module's to change).
- A gateway that failed to start at boot leaves recorded executions reading 404 until a POST
  starts it (logged at boot).
- The lease heartbeat is GET then PEXPIRE, not one atomic step (a Lua compare would close it).

## Vet

T3 (auth, money, concurrency, a consumed contract; 18 files, +2111). Round 1: `/code-review high`,
a security reviewer on the explicit range, `/simplify` (reuse, simplification, efficiency,
altitude). Round 2: `/code-review high` on the round-1 range. 44 findings after dedupe: 28 applied
(16 correctness fixes proven by a test that failed before, 1 applied without its own test — the
webhook reads its body outside the lock, part of the verify-first change — and 11 quality), 16
recorded with a reason (above, plus: fork-branch transcripts, the lock held over provider I/O on
one SQLite connection, the contract edit being in the model it is generated from, the execute
route presenting the stored approval as C6 defines, metric/test-helper/leg-event duplication in
files this task does not own, and demo-scale efficiency notes). 0 open; capped at 2 rounds.

## Reflect

- Probed: `python -m app.jobs` refuses without `REDIS_URL` or `LEDGER_DATABASE_URL` (tested);
  `.env.example` already names both; `create_app` mounts exactly `C6_ROUTES` (tested).
- Follow-up: README does not yet say how to start the worker (`python -m app.jobs`).
- Follow-up: the demo world needs an advance the integrated policy can draw (or the demo uses an
  LF-1/LF-2 observed snapshot) before the judge path can reach an execution.

## Evidence

`uv run pytest -q tests/api/test_api_v1.py` — 55 passed. Touched gate (contracts, import fence,
skeleton, backend tests): 335 passed before the last test-seed change, API file re-run green
after it; ruff, `no_secrets`, `attribution` green. The ten clock/thread/subprocess tests ran 20
of 20 green.

# LedgerWorld — system brief

Every task reads this file first, then its own brief in `briefs/`. It is the build's single
specification: when code and this file disagree, fix one of them in the same commit and say which.
Tags: **[REQ]** an event rule, read on the event pages on 2026-10-20 · **[FACT]** read in public
docs or source on 2026-10-20 · **[DEFAULT]** a value this brief chooses; the builder may not change
it silently · **[ASSUMPTION]** believed, checked by a named task.

Event: Airwallex Agentic Banking Hackathon (airwallex.hackerearth.com). Build window
**2026-10-25 04:30 UTC → 2026-11-13 18:29 UTC** [REQ]. Build freeze **2026-11-12**. Submission: a
working demo, a video walkthrough under five minutes, and a repository link with setup
instructions [REQ]. Entrants keep ownership of their project [REQ].

## 1. The product in one paragraph

LedgerWorld is an agentic treasury that rehearses a crisis before it spends a dollar. It loads a
company's cash, obligations, borrowers and counterparties into a coupled agent world, lets a shock
play out round by round, compares protective plans on the same shocks, finds the plan that still
meets every obligation, and then executes only that plan through the Airwallex sandbox and
reconciles the result against its own ledger. Every figure on screen traces to a structured result.
Nothing simulated ever touches a credential; nothing executed is ever decided inside a hypothetical
branch.

- The model proposes; the ledger and the rules decide. Agents submit typed intents; a deterministic
  coordinator clears them. A plan becomes money only by crossing the execution gateway with a bound
  approval.
- Missing data stays missing: zero, unknown and stale are three states; a stale balance blocks an
  execution instead of guessing.
- Simulated speech is not a commitment: an agent modelling an organisation never represents it.

Glossary (one name per thing): *snapshot* (frozen observed state, C5) · *world* (actors + snapshot
+ clock) · *actor* (one agent with a mandate and an information scope) · *round* (one transactional
step of the clock) · *intent* (C1) · *cleared action* (C2) · *branch* (a fork of the world at a
checkpoint) · *scenario family* (a parameterised shock) · *policy* (a candidate protective plan) ·
*plan* (the selected policy's concrete actions) · *bound approval* (C3) · *leg* (one provider
operation) · *receipt* (provider state of a leg, C4) · *spendability* S[a,c,t] (what can reach
account a in currency c by time t) · *K_p* (a lender pool's usable capacity) · *replay* (a branch
re-run from transcripts, always labelled).

## 2. The core journey

1. **Freeze.** The operator opens a frozen synthetic snapshot: cash by account and bucket,
   obligations with deadlines, the lending pool, shared exposures.
2. **Shock.** A delayed receipt and a public confidence shock are applied; the world advances round
   by round on one clock.
3. **Watch.** Borrower actors read the shock and change their draw and repay plans; spendability
   moves; a shared exposure pulls the lender into a constraint.
4. **Fork.** At a checkpoint the three policies run on the same shocks, each in a fresh branch
   where agents re-react independently.
5. **Break.** Reverse stress returns the smallest shock that breaches the reserve floor under the
   selected plan.
6. **Execute.** The operator approves the bounded plan; the gateway runs the sandbox legs and the
   reconciliation closes them against the loan ledger.

## 3. The upstream base and what may change

- [FACT] The agent world is the open-source engine at github.com/666ghj/MiroFish, licence
  **AGPL-3.0**, pinned at commit `7657031ac01184afe2cb220f5ee3545573b5e843` (2026-10-01). It is a
  Flask backend (`backend/app`, Python ≥3.11,<3.13, uv) and a Vue 3 / Vite frontend (`frontend/`).
  Its dependencies include `camel-oasis==0.2.5` and `camel-ai==0.2.78` (Apache-2.0) and
  `zep-cloud==3.25.0` (hosted graph memory).
- [FACT] Its configuration names: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `ZEP_API_KEY`,
  optional `LLM_BOOST_API_KEY`, `LLM_BOOST_BASE_URL`, `LLM_BOOST_MODEL_NAME`.
- The repo's first commit is that tree, unmodified, tagged `upstream-7657031` (T01). All our work
  comes after it, so `git diff upstream-7657031` is the exact original-vs-modified record.
- New code goes into new modules (§16). An upstream file is modified only to wire a new module in
  (a registration, a route, a menu entry) and every such file is listed in `ATTRIBUTION.md` in the
  same commit; `checks/attribution.py` enforces it.
- The licence of the whole repo is AGPL-3.0 (the combined work). The deployed demo links its source
  from every page footer (AGPL §13).
- `camel-oasis` is extended by subclassing and registration in `packages/oasis-finance`, never by
  editing site-packages or vendoring it.

## 4. System shape

```
observed evidence + contracts
        │
        ▼
versioned financial world (snapshot C5, ledger)  ◄──────────── new observations
        │
        ▼
agent world (upstream graph, personas, memory)
        │
        ▼
coupled scenario simulation  ◄── resimulate ──┐
        │                                      │
        ▼                                      │
outcomes + failure paths ──► candidate policies┘
        │
        ▼
bound approval (C3) ──► EXECUTION GATEWAY ──► Airwallex sandbox ──► receipts (C4) ──► reconciliation
```

The one hard rule of the shape: external execution never happens inside a hypothetical branch. A
plan is selected against the current observed snapshot, then crosses the gateway. Agents never call
a provider; the simulation role's process has no Airwallex credential in its environment (T14).

## 5. The ledger (`backend/app/finance/`)

- Money: `{minor: int, currency: "USD"}`; all arithmetic in integers; one converter turns minor
  units into the provider's decimal string at the connector boundary [FACT: Airwallex request
  amounts are decimal strings].
- Accounts belong to an entity and hold one currency. Buckets per account: `settled`,
  `pending_in` (with expected time), `pending_out`, `reserved`, `pledged`, `unknown` (value not
  observable), each with `as_of`. A balance older than `STALE_AFTER` (default 6 h simulated) is
  `stale`.
- Journals are double-entry: Σ debits = Σ credits per currency per journal; a journal commits whole
  or not at all.
- Reservations: `hold` (moves settled → reserved) → `commit` (reserved → pending_out → settled
  out) | `release` | `expire`. A pledge moves units to `pledged`; the same units are never pledged
  twice.
- Spendability S[a,c,t] = settled − reserved − pledged − Σ all pending_out (a committed outflow is spoken
  for from the moment of commit) + Σ pending_in with expected arrival ≤ t. `unknown` and `stale` add
  nothing and set `authority = reduced`; an execution needs `authority = full`.
- Projected cash P[a,t] = settled + Σ pending_in expected ≤ t − Σ pending_out due ≤ t − Σ obligations
  due ≤ t (reserved or not). **The reserve floor is checked on P over the horizon**, not on S. A
  discretionary outflow clears only if amount ≤ S(now) and amount ≤ min over t of (P(t) − floor).
- Store: SQLAlchemy 2 Core; SQLite in tests, PostgreSQL in deploy (`LEDGER_DATABASE_URL`). Tests
  marked `pg` run only in CI. The build box has no PostgreSQL, Redis or Docker.

## 6. Fixtures [DEFAULT]

The brief this project grew from cites external fixtures that are not available to the build. Until
they are supplied, these two are the money truth. Numbers in USD.

**LF-1 · treasury (borrower-a), horizon 72 h, t in hours**
- Operating account: settled 70,000.00 at t=0. Reserve floor 30,000.00.
- Receivable 20,000.00, `pending_in`, expected t=12.
- Exchange withdrawal 15,000.00, `pending_in`, expected t=48.
- Payroll obligation 50,000.00 due t=40, reserved at t=0 (hold).
- Expected, no shock: before payroll 70,000 + 20,000 = 90,000 (the withdrawal lands after the deadline
  and is not counted); P(t=40) after payroll = 40,000 ≥ floor → feasible. S(0) = 70,000 − 50,000 = 20,000.
- Shock "receipt delayed 240 h": before payroll 70,000; P(t=40) = 20,000 < floor → breach of 10,000.
- Integrated plan: draw an eligible advance of 10,000.00 at t≤18; after payroll 30,000 = floor →
  feasible (the floor is kept when ≥).
- Rejections: a payment of 80,000.00 at t=0 (beyond cash); pledging the same 5,000.00 twice;
  dropping the payroll obligation by taking no action (an obligation is never removed by inaction).

**LF-2 · lender pool, same clock**
- Pool settled cash 60,000.00, of which 15,000.00 held at the exchange venue shared with LF-1.
- Committed undrawn line to borrower-b 10,000.00 (held, not discretionary). Pool reserve floor
  8,000.00.
- K_p = settled − committed undrawn − pledged − pool obligations due within the horizon − pool floor = 60,000 − 10,000 − 0 − 0 − 8,000 = **42,000.00** (LF-2 has no pool obligation; a redemption spike lowers K_p by its increase).
- Stress "venue freeze": the 15,000.00 at the venue becomes `unknown` → K_p = 45,000 − 10,000 −
  8,000 = **27,000.00**.
- Advance to borrower-a: 10,000.00, flat fee 8 % → 10,800.00 owed; repayment 15 % of observed
  weekly revenue; week-1 revenue 24,000.00 → repayment 3,600.00 → 7,200.00 outstanding. Repayment
  is computed from observed revenue only, never from forecast revenue.
- A draw of 30,000.00 under stress is rejected with the binding constraint `K_p = 27,000.00`.

## 7. The agent world (`backend/app/simulation/`, `packages/oasis-finance/`)

### 7.1 Actors (eight, all synthetic)
treasury (borrower-a, the operator's company) · lender pool · borrower-b · borrower-c · payroll
counterparty · exchange / settlement venue · market-maker of public prices · public feed account.
Each has objectives, a contract set and an information scope: it sees its own cash, its contracts,
messages addressed to it, public posts and public prices, its memory, and nothing scheduled after
the current simulated time.

### 7.2 Round order (transactional)
1. Advance the clock. 2. Deliver scheduled external events due now (scenario). 3. Publish public
posts. 4. Build each actor's observation (scope-filtered, hashed). 5. Agents propose intents (C1).
6. Validate intents (schema, mandate, authority). 7. Clear intents in deterministic order
(priority class → simulated time → actor id) against the ledger. 8. Run mandatory settlements
(due obligations, pending arrivals). 9. Return C2 results to actors. 10. Commit the round and append
the transcript. Capture state before step 1. Any unhandled exception or cancellation in steps 1–10
before durable completion aborts the round. Close admission and cancel/join all round-owned actor
work and children before restoring state; no failed-round writer may survive restoration. If
quiescence cannot be established, mark the world unusable and refuse retry on that instance.
Restore all round-start state: ledger, OASIS SQLite, actor memory, both clocks, RNG, scheduled-event
cursor, pending C2, intent queue and transcript cursor. Barrier-controlled actor-failure and
coordinator-cancellation fixtures must prove cleanup writes are removed and no late write survives.
Injected failures must allow a scripted retry equal to a clean control; this does not establish
process-crash recovery, identical fresh model responses or reversal of external model charges.
A rejected intent or malformed output handled by repair/no_action is not an unhandled round failure.

### 7.3 Scenario families (six)
delayed receipt · confidence rumour · stablecoin depeg (a USDC-denominated pending_in loses value
and settles late) · borrower silence (a borrower stops repaying and stops answering) · redemption
spike (an outflow obligation grows) · FX gap (an obligation in another currency moves against us).
Each has size and timing parameters and a seed.

### 7.4 Models and memory
The upstream OpenAI-compatible client is used for agents and reports. Tests use `ScriptedModel`
and `FakeGraphMemory` (T06). Memory namespaces are `world/<id>/branch/<id>`.

## 8. Contracts (JSON Schema in `contracts/`, pydantic v2 in `backend/app/finance/schemas.py`)

- **C1 ActionIntent** `{intent_id, branch_id, round, actor_id, type, params, evidence_ids[], obs_hash}`
  · on error: rejected and recorded; the actor's safe fallback is `no_action`.
- **C2 ClearedAction** `{intent_id, status: accepted|rejected|pending, reason?, journal_id?, round}`
  · the actor sees a rejection next round.
- **C3 BoundApproval** `{approval_id, entity, account, legs[{kind, amount, currency, counterparty}],
  plan_hash, snapshot_id, expires_at, mode: fake|sandbox, approver}` · any term outside the bound
  invalidates it.
- **C4 ProviderOp** `{leg_id, request_id, kind, provider_id?, state: pending|submitted|settled|failed|unknown,
  receipt, reconciled: bool, journal_id?}` · unknown opens an incident and is queried by stored ids
  before any retry.
- **C5 Snapshot** `{snapshot_id, as_of, entities[{entity_id, name, kind, escalation?}], accounts[{id, entity, currency, buckets}],
  obligations[], contracts[], exposures[]}`.
- **C6 API** the shapes of §11.

## 9. Decisions (`backend/app/decisions/`)

Three policies: **no-action**; **fixed reserve** (keep the floor by deferring discretionary
outflows, no borrowing); **integrated** (draw an eligible advance, defer what the contract allows,
convert just in time). Objective, lexicographic: (1) obligations met, (2) reserve floor kept,
(3) funding cost. Paired evaluation: same seeds, fresh branch per policy. Nonanticipativity: a
decision at t reads only what is observable at t. All infeasible → return the earliest unmet
obligation, the binding constraint and the escalation contact (C5 `entities[].escalation`, a role); never relax the floor silently.
In a policy branch the policy drives the treasury and the treasury model is not called; every other actor re-reacts. Feasibility is read from the branch's realised ledger. The selected policy decides again on the current observed snapshot to produce the plan; a decisions result is never an approval.

## 10. Airwallex (`backend/app/connectors/airwallex/`)

- [FACT] Sandbox base `https://api.sandbox.airwallex.com`; production `https://api.airwallex.com` is
  refused by code. Auth `POST /api/v1/authentication/login` with headers `x-client-id`,
  `x-api-key`; the token lasts 30 minutes; renew at expiry minus 60 s.
- [FACT] Read cash: `GET /api/v1/balances/current`.
- [FACT] FX: `POST /api/v1/fx/quotes/create` (`validity` required), `POST /api/v1/fx/conversions/create`.
- [FACT] Payout: `POST /api/v1/beneficiaries/create`, `POST /api/v1/transfers/create` (`reason`
  and `reference` required).
- [FACT] Connected accounts: `POST /api/v1/connected_account_transfers/create` (`amount`,
  `currency`, `destination`, `request_id`) funds a connected account from the platform balance;
  `POST /api/v1/charges/create` (`amount`, `currency`, `source`, `request_id`) charges a connected
  account; `x-on-behalf-of` acts for a connected account. **Connected-account APIs are not enabled
  in the sandbox by default**; Airwallex enables them on request.
- [FACT] Deposit simulation (sandbox only): `POST /api/v1/simulation/deposit/create` with
  `{amount, global_account_id, reference?, status?}`; `status` defaults to `SETTLED` and a settled
  deposit adds to `balances/current`. It needs a Global Account in the advance currency
  (`GET /api/v1/global_accounts`). The `deposits/{id}/settle|reverse` endpoints are for direct
  debits and are not used.
- [FACT] Transfer status simulation: `POST /api/v1/simulation/transfers/{id}/transition`
  `{next_status: "PAID"}`, or `"FAILED"` with a `failure_type`; this is how T15 settles one transfer.
- [FACT] The API version is sent on every call in `x-api-version`. Amounts on transfers and conversions are decimal strings; the deposit simulation documents
  `amount` as a number (T15 confirms). Pin the API version to 2024-09-27 or later: before it
  `/api/v1/transfers` is the connected-account transfer and the sandbox refuses a payout there.
- [FACT] Airwallex's lending API is a partner API for lender apps; it is not used.
- Every request carries a deterministic `request_id` (leg id); a replay with the same id must not
  move money twice. [FACT] The provider **rejects** a duplicate id (`duplicate_request_id`, or
  `409` while the first is in flight); it does not return the original. The gateway resolves both
  by `GET /api/v1/transfers?request_id=…` (or `conversions?request_id=…`) and adopts what it
  finds; it never resubmits under a new id, and the fake reproduces the rejection.
- [FACT] Webhooks carry `x-timestamp` (Unix ms) and `x-signature` = hex HMAC-SHA256 keyed by the
  notification URL's secret over timestamp + raw body. `payout.transfer.paid` is not final (a
  transfer may still fail). Reconciliation's truth is `GET` by provider id; a webhook is a verified
  hint (stale beyond 5 minutes → rejected) that triggers that `GET`.

Leg mapping, chosen at start by probing `GET` on connected accounts (`AIRWALLEX_CONNECTED=auto`):

| Leg | Mode A · connected accounts enabled | Mode B · fallback |
|---|---|---|
| Advance (lender → borrower-a) | connected-account transfer to borrower-a | simulated deposit into the operator's account, labelled "advance inflow (sandbox simulation)" |
| Repayment (borrower-a → lender) | charge on borrower-a | ledger-only, labelled "simulated" |
| FX | quote + conversion | quote + conversion |
| Payout (payroll) | transfer on behalf of borrower-a | transfer from the operator's account |

The demo and the video say which mode ran. A mode-B receipt is never described as a lender
disbursement through Airwallex.

## 11. API (`/api/v1`, Flask, behind the upstream app)

`GET /api/v1/health` → `{ok, mode, airwallex: fake|sandbox, connected: bool, model: scripted|live, version}` ·
`GET /api/v1/overview` → cash, upcoming outflows, min projected coverage, lender capacity,
completeness · `GET /api/v1/treasury` · `GET /api/v1/lending` · `POST /api/v1/runs` → `202 {job_id}` ·
`GET /api/v1/runs/{id}` (rounds, feed, cash paths, branches) · `POST /api/v1/runs/{id}/fork` ·
`GET /api/v1/decisions/{run_id}` · `POST /api/v1/approvals` (token) · `POST /api/v1/executions`
(token) · `GET /api/v1/executions/{id}` · `POST /api/v1/webhooks/airwallex` (signature-verified, no token; a hint that triggers a `GET`) · `POST /api/v1/interview` (read-only) ·
`GET /api/v1/reports/{run_id}`. Write routes need `Authorization: Bearer $LEDGERWORLD_DEMO_TOKEN`;
reads are public. Every response carries `as_of` and `mode`. C6 also preserves relevant snapshot/run/branch/committed-round identity and per-metric status/currency. Overview names the prepared demonstration run and its associated execution when available; an absent association is unavailable, never a guess from the latest execution. All user POSTs, including the read-only interview, require the demo token (the signed provider webhook is the sole exception).

## 12. Look and feel

Traditional finance, not "AI product". Paper-and-ink surfaces for reading state, a dark instrument
panel for the live simulation (dark in both themes). Tokens: light surface `#F5F3ED`, ink
`#0E1411`, brand `#2D69D6`, ok `#0F8A4F`, warn `#A86A00`, bad `#CC3328`; dark surface `#0E1520`,
ink `#E6EEF6`, brand `#79A6FF`, ok `#3BE58F`, warn `#FFB43A`, bad `#FF5E54`. Status always icon +
label, never colour alone. WCAG AA, keyboard-complete approval, reduced motion honoured, UTC and
local time labelled. Balances never animate decoratively. A persistent banner names the mode
("Simulated provider" in fake mode, "Airwallex sandbox" otherwise).

## 13. The demo and the video

`scripts/demo.sh` and the video follow the same seven beats: **State** (snapshot) → **World**
(actors, one actor's objectives and scope) → **Shock** (delayed receipt + rumour; borrowers react;
spendability moves) → **Fork** (three policies; the shared exposure constrains the lender) →
**Break** (reverse-stress path) → **Execute** (approve the bounded plan; sandbox legs; settled
balances; loan reconciliation) → **Explain** (interview an actor; grounded report). The honesty
moment: at least one genuinely new branch runs live; any precomputed cohort is labelled replay. No
fabricated comparison, receipt or probability. Freshness, model provenance, replay status and
provider mode are distinct labels. A scripted shock/control test establishes wiring, not independent
live-model choice; the shot list links the post, request, intent and journal to their run and branch.
The judge's first 60 seconds: Overview → Live
Simulation → Decisions → Execution, four clicks. The coupled world is shown before the treasury
decision, because plain treasury and lending decisions alone are common in this event.

## 14. Environment variables (names only; values live in the host's and the build box's secrets)

`AIRWALLEX_CLIENT_ID` · `AIRWALLEX_API_KEY` · `AIRWALLEX_BASE_URL` (default sandbox) ·
`AIRWALLEX_MODE` (fake|sandbox) · `AIRWALLEX_CONNECTED` (auto|on|off) · `AIRWALLEX_WEBHOOK_SECRET` ·
`AIRWALLEX_API_VERSION` (pinned, ≥ 2024-09-27) · `AIRWALLEX_GLOBAL_ACCOUNT_ID` (Mode B advance leg; probed if unset) ·
`LLM_API_KEY` · `LLM_BASE_URL` · `LLM_MODEL_NAME` · `LLM_BOOST_API_KEY` · `LLM_BOOST_BASE_URL` ·
`LLM_BOOST_MODEL_NAME` · `ZEP_API_KEY` · `LEDGER_DATABASE_URL` · `REDIS_URL` ·
`LEDGERWORLD_ROLE` (api|worker|sim) · `LEDGERWORLD_DEMO_TOKEN` · `LEDGERWORLD_URL` ·
`LEDGERWORLD_LLM_DAILY_USD` (default 5) · `LEDGERWORLD_FREEZE`. `.env.example` lists them with no
values.

## 15. Decided · free · unknown

- **Decided**: the upstream engine is included in full (not a report attachment, not a numerical
  replacement); the action → ledger → observation loop is the acceptance test; scope = 8 actors,
  ≥3 borrowers, 1 lender pool, 1 treasury, 6 scenario families, 3 policies; revenue advances run end
  to end through the sandbox, collateral facilities are simulation and tests only; PostgreSQL is the
  ledger of record, graph memory is never the ledger; sandbox credentials only; AGPL-3.0; English.
- **Free** (the builder decides): model within budget; NumPy parameterisation of market factors;
  worker pool size; component details inside the Vue app; synthetic names within the fixtures.
- **Unknown, each with the default the build proceeds on**:
  U1 connected accounts enabled on our sandbox? default Mode B until T15 proves Mode A. ·
  U2 external fixtures supplied? default §6. ·
  U3 host? default one small always-on machine running `deploy/compose.yml`. ·
  U4 model and budget? default a small OpenAI-compatible model, `LEDGERWORLD_LLM_DAILY_USD=5`. ·
  U5 graph memory quota enough for the demo? default the free tier; T15/T31 record usage.
- **The cut line**: if time is short, T21 (reverse stress, collateral) is cut first; the video's
  Break beat then shows the policy table's failure conditions instead.

## 16. Repository layout (additions to the upstream tree)

```
backend/app/finance/        schemas, models, ledger, spendability, store, contracts, lending, collateral
backend/app/simulation/     world, clock, coordinator, actions, observations, branches, memory, transcripts, scenarios, interview
backend/app/decisions/      candidates, feasibility, objective, nonanticipativity, reverse_stress
backend/app/execution/      approval, gateway, outbox, state, reconcile, boundary
backend/app/connectors/airwallex/  client, transport, fake, live, errors, webhooks
backend/app/api/v1/  backend/app/jobs/  backend/app/reports/  backend/app/demo/  backend/app/testing/
packages/oasis-finance/     action, platform, observation, clock extensions of camel-oasis
frontend/src/views/         Overview, Treasury, Lending, Simulation, Decisions, Execution
contracts/  fixtures/  scenarios/  scripts/ (demo.sh, judge-path.sh)  checks/  deploy/  e2e/  docs/
tests/{contracts,fixtures,finance,simulation,decisions,connectors,execution,api,reports,demo,hunt,testing}/
UPSTREAM.md  ATTRIBUTION.md  NOTICE  LICENSE (AGPL-3.0)  README.md  CLAUDE.md  .env.example
```

One uv workspace at the root (members `backend`, `packages/oasis-finance`), Python 3.12. The merge
gate is `bash checks/merge.sh` (T01): ruff on new code → `checks/no_secrets.py` →
`checks/attribution.py` → `uv run pytest -q` (offline: fake transport, ScriptedModel,
FakeGraphMemory, SQLite, fakeredis; `live` and `pg` markers skipped) → frontend build when its
dependencies are installed.

## 17. Goals and how they are measured

`python3 checks/kpi.py gN --print` prints one number (T22). Before its inputs exist it prints the
baseline.

| Goal | KPI | Target | Measure |
|---|---|---|---|
| g1 Money is correct | `money_checks_pct` | 100 | passing share of `checks/required.json` group g1 |
| g2 The world is coupled | `coupling_checks_pct` | 100 | passing share of group g2 |
| g3 It executes for real (sandbox) | `demo_checkpoints_live` | 3 | sandbox checkpoints in `var/demo/live.json`: fresh branch, advance reconciled, payout reconciled |
| g4 A judge can follow it | `judge_path_s` | ≤ 60 | seconds of `scripts/judge-path.sh $LEDGERWORLD_URL` (999 on failure) |
| g5 The entry is complete and honest | `submission_items` | 8 | items `checks/submission.py` verifies |

Required check ids (each task adds its own, in the same commit as the test):
g1 — LF-1 reproduction, ledger invariants (balance, no orphan posting, reserved ≤ settled, no double
pledge, unknown ≠ zero), LF-2 reproduction, draw beyond K_p rejected, no duplicate movement, no
movement from unowned funds, altered approval refused, timeout resolved by query, reconciliation
closes the advance, clairvoyant policy rejected, credential isolation, the eight money-safety hunts.
g2 — actions only through tools, public shock traceable response, failed round rolls back, sibling
isolation, replay identity, six families run, report numbers grounded, interview read-only.

## 18. Fences for every task

- Never put a secret in the repo, a log, a fixture, a trace or a test; `.env.example` names only.
- Never call the real Airwallex API, a real model or hosted graph memory from a merge-gate test.
- Money is integer minor units; a model's float never reaches a posting or a provider request.
- A simulation process never holds an Airwallex credential.
- Never call an Airwallex production host; never vendor Airwallex's CLI (its licence forbids
  redistribution).
- Upstream files change only per §3 and are listed in `ATTRIBUTION.md`.
- Edit only the files your brief owns, plus the one-line wiring it names.
- Repo files never name a person, a team or the system that builds the repo.
- Never push, merge or deploy; the engine publishes your branch.

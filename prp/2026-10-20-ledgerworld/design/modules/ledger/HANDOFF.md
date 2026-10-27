# ledger — money truth

Tasks: T02 (contracts and schemas) · T03 (fixtures LF-1, LF-2) · T04 (typed ledger, reservations, spendability) · T05 (advances and lender capacity) · T29 (money-safety hunt).
Read with `00-system.md` §5, §6 and §8. The fixtures in `fixtures/` are the test truth: T03 turns `lf1-treasury.json` and `lf2-lender.json` into `fixtures/lf1_treasury.json` and `fixtures/lf2_lender.json` in the repo (C5 snapshot + `expected`), and every other test loads its fixture unchanged and asserts its `expect` block. The store's tables are in `schema.sql` (DDL only, loads clean in SQLite).

Two measures, kept apart (this corrects a conflation between §5 and §6 of the system brief):
- **S(t), spendability**: what is free to commit. `settled − reserved − pledged − Σ all pending_out + Σ pending_in expected ≤ t`. A committed outflow is spoken for from the moment of commit, whatever its due time.
- **P(t), projected cash**: what the account will hold at t. `settled + Σ pending_in expected ≤ t − Σ pending_out due ≤ t − Σ obligations due ≤ t` (reserved or not). **The reserve floor is checked on P over the horizon**, not on S. With S alone, LF-1 would read as a breach at t=0 (S(0) = 20,000 < 30,000) and §6's "S(t=40) = 90,000" contradicts §5's formula.
- A discretionary outflow clears only if `amount ≤ S(now)` **and** `amount ≤ headroom(now) = min over t in [now, horizon] of (P(t) − floor)`. LF-1: S(0) = 20,000 but headroom(0) = 10,000, so a 20,000 payment at t=0 is refused (`breaks_floor`) and a 10,000 one clears.

## Interfaces

| Unit | File | Shape | Notes |
|---|---|---|---|
| `Money` | `backend/app/finance/schemas.py` | pydantic v2 `{minor: StrictInt, currency: Literal[supported ISO-4217]}` | Rejects floats, strings, lower-case codes, a decimal `amount` field (`money-cases.json`). |
| `to_provider_decimal(money)` | `backend/app/finance/schemas.py` | `Money → str` | The only converter to a decimal string, by currency exponent (USD/EUR 2, JPY 0); refuses negatives at the provider boundary. Used by the Airwallex connector only. |
| contracts C1–C6 | `contracts/*.schema.json`, `contracts/examples/` | JSON Schema; pydantic models generate or match them | One valid + two invalid examples each; amounts are `Money`. |
| `LedgerStore` | `backend/app/finance/store.py` | SQLAlchemy 2 Core over `LEDGER_DATABASE_URL`; `apply(journal)`, `hold`, `commit`, `release`, `settle`, `expire_due(now)`, `pledge`, `release_pledge`, `observe(account, known|unknown, as_of)` | One transaction per call; a refusal raises `LedgerRefusal(code, detail)` and leaves the store byte-identical. Checks per-currency balance before commit (no triggers). |
| `Journal` | `backend/app/finance/models.py` | `{journal_id, kind, round, sim_time, seq, source_intent_id?, source_leg_id?, mode, postings: [{account_id, currency, amount_minor≠0}]}` | Signed postings, debit positive. Σ amount = 0 per currency. `seq` is the global commit order of the branch. |
| `spendability(account, t, now)` | `backend/app/finance/spendability.py` | `→ {value: int|None, state: known|stale|unknown, authority: full|reduced}` | `unknown` → value `None`; stale = `as_of` strictly older than `STALE_AFTER` (6 h simulated) → value kept, authority reduced. |
| `projected_cash(account, t)` and `headroom(account, now, horizon)` | `backend/app/finance/spendability.py` | `→ int` / `{value, binding_t}` | Used by clearing, decisions (T11) and the overview screen. |
| `check_outflow(account, amount, now)` | `backend/app/finance/ledger.py` | `→ ok | LedgerRefusal(insufficient_spendable | breaks_floor | stale_balance | unknown_balance)` | Called by the coordinator at step 7 and the gateway before a leg. |
| `capacity(store, pool, now, horizon)` | `backend/app/finance/lending.py` | `→ PoolCapacity{K_p: int, authority, parts: {settled_known, committed_undrawn, pledged, obligations_due, floor}}` | `K_p = Σ settled of known, non-stale pool accounts − committed undrawn − pledged − Σ pool obligations due within the horizon − pool floor` (LF-2 has no pool obligation; a redemption spike lowers K_p by its increase, which the decisions module's lender-side stress needs). Every committed outflow of the pool (pending_out) counts in `obligations_due`, as it does in S. Committed undrawn = limit − outstanding of each active line. |
| `check_draw` / `disburse(store, facility_id, now)` / `draw_line(store, facility_id, amount, now)` / `observe_revenue` / `repay(store, facility_id, period_end, now)` | `backend/app/finance/lending.py` | → refusal or `Journal` / `Repayment` | An advance disburses its whole principal. A draw beyond K_p → `LedgerRefusal(beyond_capacity, binding="K_p = 27,000.00")`; a committed-line draw is bounded by the line's undrawn part, not K_p, and leaves K_p unchanged. Repayment = `floor(revenue × share_bps / 10000)` of the revenue observed for the period (`revenue_observations`; an observation before the period ends is a forecast and is refused), capped at outstanding; no observation → 0; a period is repaid once (its journal id). |
| contract terms | `backend/app/finance/contracts.py` | committed line, revenue advance, collateral facility → `facilities` row + receivable `<pool>/loan:<id>` | Fee in bps on principal, recognised at disbursal. Outstanding = the receivable's balance (Σ postings). `ledger.from_snapshot` registers every contract; an active advance is refused (C5 carries no outstanding for it). |

Refusal codes are a closed set: `journal_unbalanced, no_journal, zero_amount, amount_not_integer_minor, reserved_exceeds_settled, pledge_exceeds_free, already_pledged, reservation_not_held, insufficient_spendable, breaks_floor, stale_balance, unknown_balance, beyond_capacity`.

## Data

- Tables: `schema.sql` — `branch_meta, entities, accounts, account_observations, journals, postings, expected_flows, obligations, reservations, pledges, lending_pools, facilities, revenue_observations`. One schema (PostgreSQL) or one file (SQLite) per branch; a fork copies it at the checkpoint (agent-world module).
- Settled balance = Σ postings of the account; never stored as a column, so it can never drift from the journals.
- Buckets map to tables: settled ← postings · reserved ← `reservations` held · pending_in/out ← `expected_flows` pending · pledged ← `pledges` active · unknown ← `account_observations.observability`.
- Reservation states: `held → committed → settled`, or `held → released | expired`. Commit creates a pending_out flow and moves the units out of reserved in the same transaction, so they are never counted twice.
- Double pledge is refused by the database itself: a partial unique index, one active pledge per `collateral_ref` (checked once in SQLite).
- Rounding: only in repayment and fee; down, in the borrower's favour; amounts stay integer minor units throughout.
- Seed numbers: LF-1 and LF-2 in `fixtures/`; synthetic entity names, marked synthetic.

## Fixtures

| File | Drives | What it pins |
|---|---|---|
| `fixtures/money-cases.json` | T02 | valid and invalid Money shapes; the decimal converter for USD and JPY |
| `fixtures/lf1-treasury.json` | T03, T04 | S and P at t = 0, 12, 40, 48, 72; no shock feasible (min P 40,000); shock breach 10,000 at t=40; advance of 10,000 at t=16 keeps P(40) = 30,000 = floor; five rejections incl. `breaks_floor` |
| `fixtures/lf2-lender.json` | T03, T05 | K_p 42,000 → 27,000 under venue freeze; 30,000 draw refused with the binding constraint; advance 10,800 owed; weeks 1–4 of repayment incl. forecast-only (0), rounding down, cap at outstanding; a committed-line draw leaves K_p unchanged |
| `fixtures/invariants.json` | T04 | 15 cases: balance per currency, orphan, zero, float, reserved vs settled, double pledge, pledge over free, committed outflow not re-spendable, unknown ≠ zero, stale boundary at 6 h |
| `fixtures/reservation-lifecycle.json` | T04 | hold → commit → settle, release, expire, no double commit, with buckets after each step |
| `fixtures/advance-journals.json` | T05 | the disbursal and week-1 repayment journals posting by posting, each summing to zero |
| `fixtures/money-safety.json` | T29 | the eight hunts, each with the owning module and the naive behaviour it catches |

## Failure modes

| Failure | Where it bites | Guard |
|---|---|---|
| Floor checked on S instead of P | LF-1 reads as a breach at t=0; every plan looks infeasible | P(t) and headroom; `lf1-treasury.json` pins both |
| A committed outflow still counts as spendable until due | money spent twice before payroll leaves | S subtracts all pending_out; `committed-outflow-not-respendable` |
| Settled stored as a column | balance drifts from journals after a partial failure | settled = Σ postings |
| Journal balanced in total but not per currency | silent FX money creation | per-currency check; `balanced-total-unbalanced-per-currency` |
| Unknown treated as zero or as the last value | K_p overstated or a breach invented | `None` + authority reduced; `unknown-is-not-zero`, LF-2 stress |
| Stale boundary off by one | flaky execution refusals | stale = strictly older than 6 h; `fresh-at-6h` |
| Repayment from forecast revenue | the brief's explicit rule broken | `revenue_observations` only; week-2 case |
| Float from a model reaches a posting | rounding money | `StrictInt`; `float-amount`, `money-cases.json` |
| Double pledge through a race | collateral counted twice | partial unique index in the database |
| A delayed receivable keeps its old time | credited early | delay rewrites `expected_at`; hunt `delayed-receivable-credited-early` |
| Fee rounding up | borrower overcharged by a cent | round down; week-3 case |
| A test that hard-codes 42,000 | g1 measures a constant | T05 accept asserts the parts of K_p, not only the total |

## Done-whens

- accept: uv run pytest -q tests/contracts/test_contracts.py — fixture: fixtures/money-cases.json
- accept: uv run pytest -q tests/fixtures/test_fixture_data.py — fixture: fixtures/lf1-treasury.json
- accept: uv run pytest -q tests/fixtures/test_fixture_data.py — fixture: fixtures/lf2-lender.json
- accept: uv run pytest -q tests/finance/test_ledger.py — fixture: fixtures/invariants.json
- accept: uv run pytest -q tests/finance/test_ledger.py — fixture: fixtures/reservation-lifecycle.json
- accept: uv run pytest -q tests/finance/test_fixtures.py — fixture: fixtures/lf1-treasury.json
- accept: uv run pytest -q tests/finance/test_lending.py — fixture: fixtures/lf2-lender.json
- accept: uv run pytest -q tests/finance/test_lending.py — fixture: fixtures/advance-journals.json
- accept: uv run pytest -q tests/hunt/test_money_safety.py — fixture: fixtures/money-safety.json

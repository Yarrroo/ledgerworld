# LedgerWorld

An agentic treasury that rehearses a crisis before it spends a dollar. It loads a company's cash,
obligations, borrowers and counterparties into a coupled agent world, lets a shock play out round
by round, compares protective plans on the same shocks, and executes only the plan that still
meets every obligation through the Airwallex sandbox, then reconciles the result against its own
ledger.

Built on [MiroFish](https://github.com/666ghj/MiroFish) (AGPL-3.0); see `UPSTREAM.md` and
`ATTRIBUTION.md` for exactly what changed.

## Setup

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/); Node 20+ for the frontend.

```bash
uv sync                      # backend, packages/oasis-finance and dev tools
cp .env.example .env         # fill in values; never commit .env
bash checks/merge.sh         # lint, secrets, attribution, offline tests, frontend build
```

The merge gate runs fully offline: no real provider, model or hosted graph memory is called.
Tests marked `live` or `pg` are skipped by default; `uv run pytest -m pg` runs the PostgreSQL
tests against `LEDGER_DATABASE_URL`.

Frontend: `npm --prefix frontend install && npm --prefix frontend run dev`; the observed-state
screens are `/overview`, `/treasury` and `/lending`; `/simulation?run_id=<run>` replays a run's
committed rounds on one scrubber; the policy comparison is `/decisions` and the approval, provider
state and receipts are `/execution`. Unit tests: `npm --prefix frontend run test:unit`.
Backend: `cd backend && uv run python run.py`.

## Licence

AGPL-3.0, the licence of the upstream engine and of the combined work. See `LICENSE` and `NOTICE`.

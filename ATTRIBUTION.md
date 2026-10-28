# Attribution

LedgerWorld is a modified version of [MiroFish](https://github.com/666ghj/MiroFish) at commit
`7657031ac01184afe2cb220f5ee3545573b5e843`, under AGPL-3.0 (see `UPSTREAM.md`, `NOTICE`).
`git diff upstream-7657031` is the exact record. `checks/attribution.py` fails the merge gate when
an upstream path is modified or deleted and not listed in the second table.

## Files added by this project

| Path | Why |
|---|---|
| `ATTRIBUTION.md` | this record |
| `UPSTREAM.md` | upstream source, commit and how to diff |
| `NOTICE` | upstream and Apache-2.0 dependency notices |
| `CLAUDE.md` | rules for coding agents working on this repo |
| `pyproject.toml`, `uv.lock` | the root uv workspace (`backend`, `packages/oasis-finance`) and its lock |
| `packages/oasis-finance/` | finance extensions of camel-oasis: the finance tool boundary (typed tools that queue C1 intents, scoped observations, one-repair guardrail) |
| `backend/app/finance/` | money and contract schemas, the double-entry ledger store and its migrations, spendability, lending, collateral |
| `backend/app/simulation/` | the coupled agent world: clock, coordinator, observations, branches, memory, transcripts, scenario families, interview |
| `backend/app/decisions/` | the three policies, feasibility, objective, nonanticipativity, reverse stress |
| `backend/app/execution/` | approval binding, the execution gateway, outbox, leg states, reconciliation |
| `backend/app/connectors/` | the Airwallex connector: client, fake and live sandbox transports, webhooks |
| `backend/app/api/v1/` | the `/api/v1` routes (contract C6) |
| `backend/app/jobs/` | the run queue, its worker and its records |
| `backend/app/reports/` | grounded reports |
| `backend/app/demo/` | the seven-beat demo |
| `backend/app/testing/` | `ScriptedModel`, `FakeGraphMemory` and their scripted plans |
| `backend/app/utils/llm_budget.py` | the `LEDGERWORLD_LLM_DAILY_USD` cap: meters every live model call per UTC day in the shared store and refuses calls once it is reached |
| `backend/tests/finance/` | ledger tests placed beside the upstream backend tests |
| `contracts/` | JSON Schemas C1–C6 and their valid and invalid examples |
| `fixtures/`, `scenarios/` | the synthetic money fixtures LF-1 and LF-2, the demo world and the six scenario families |
| `frontend/src/views/Overview.vue`, `Treasury.vue`, `Lending.vue`, `Simulation.vue` | the new screens |
| `frontend/src/api/v1.js`, `frontend/src/components/ActionFeed.vue`, `CashPaths.vue`, `Scrubber.vue`, `frontend/src/styles/tokens.css` | their API client, components and design tokens |
| `frontend/tests/unit/`, `frontend/vitest.config.js` | frontend unit tests |
| `deploy/` | one-machine deployment: compose file, image, role entrypoint, host settings, their tests |
| `scripts/demo.sh` | the one-command demo |
| `refmodel/` | reference models and findings used to check the simulation design |
| `tests/` (except the upstream `test_local_star_*` files) | the offline test suite by area, and the tests of the merge gate (`tests/test_skeleton.py`) |
| `docs/` | architecture, schema and screenshots |
| `checks/` | the merge gate and its checks |
| `.github/workflows/ci.yml` | CI: merge gate, PostgreSQL tests |
| `prp/` | system brief, design and task briefs |

## Upstream files modified

| Path | Why |
|---|---|
| `README.md` | replaced by this project's README, linking the stable demo origin; the upstream text stays in the import commit and `README-ZH.md` |
| `.env.example` | lists every variable this project reads, names only, no values |
| `.gitignore` | adds `var/` and `frontend/dist/` to the upstream rules |
| `backend/app/__init__.py` | registers the `/api/v1` blueprint (`app.api.v1.register`) in `create_app`; wires the simulation boundary around config loading |
| `backend/app/services/simulation_runner.py` | wires the shared scrubbed environment into all upstream simulation subprocess launches |
| `frontend/src/router/index.js` | adds the `/overview`, `/treasury`, `/lending`, `/simulation`, `/decisions` and `/execution` routes; `/` redirects to `/overview` and the upstream home page moves to `/home`; other upstream routes unchanged |
| `frontend/src/components/GraphPanel.vue` | exposes its own `closeDetailPanel` so the `/simulation` screen closes a selection when the round or run changes |
| `frontend/package.json` | adds the `test:unit` script and its dev dependencies (vitest, happy-dom, @vue/test-utils) |
| `frontend/package-lock.json` | the lock for those dev dependencies |
| `backend/app/utils/openai_chat_compat.py` | `create_chat_completion` sends its request through the daily model budget (`app.utils.llm_budget.metered`) |
| `backend/app/services/oasis_profile_generator.py` | its persona retry loop takes a daily model budget refusal (`LLMBudgetExceeded`) straight to the rule-based profile instead of retrying it |
| `backend/app/services/simulation_config_generator.py` | its config retry loop re-raises a daily model budget refusal (`LLMBudgetExceeded`) instead of retrying it |
| `backend/scripts/run_twitter_simulation.py` | its live camel model is wrapped in the daily model budget (`app.utils.llm_budget.budgeted`) |
| `backend/scripts/run_reddit_simulation.py` | its live camel model is wrapped in the daily model budget (`app.utils.llm_budget.budgeted`) |
| `backend/scripts/run_parallel_simulation.py` | its live camel model is wrapped in the daily model budget (`app.utils.llm_budget.budgeted`) |

# LedgerWorld

Rules for coding agents working on this repository.

## Read first

`prp/2026-10-20-ledgerworld/00-system.md` (the system brief) before any change, then your task's
brief in `prp/2026-10-20-ledgerworld/briefs/`. When code and the brief disagree, fix one of them in
the same commit and say which.

## The merge gate

`bash checks/merge.sh` — ruff on new code, `checks/no_secrets.py`, `checks/attribution.py`,
`uv run pytest -q` (offline), frontend build when `frontend/node_modules` exists. It must be green
before a change lands. Call tools through `uv run`, never `.venv/bin/…`.

## Fences

- Never put a secret in the repo, a log, a fixture, a trace or a test; `.env.example` names only.
- Never call the real Airwallex API, a real model or hosted graph memory from a merge-gate test;
  use the fake transport, `ScriptedModel`, `FakeGraphMemory`, SQLite and fakeredis. Mark anything
  else `live` or `pg`.
- Money is integer minor units with an ISO currency; a model's float never reaches a posting or a
  provider request.
- A simulation process never holds an Airwallex credential and never imports
  `app.connectors.airwallex.live`.
- Never call an Airwallex production host; never vendor Airwallex's CLI.
- Upstream files change only to wire a new module in, and every changed upstream file is listed in
  `ATTRIBUTION.md` in the same commit (`checks/attribution.py` enforces it). New code goes in new
  modules; camel-oasis is extended in `packages/oasis-finance`, never edited in site-packages.
- Edit only the files your brief owns, plus the one-line wiring it names.
- Repo files never name a person, a team or the system that builds the repo.
- Never push, merge or deploy.

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
| `packages/oasis-finance/` | finance extensions of camel-oasis (empty package for now) |
| `checks/` | the merge gate and its checks |
| `tests/test_skeleton.py` | tests of the merge gate and its checks |
| `.github/workflows/ci.yml` | CI: merge gate, PostgreSQL tests |
| `prp/` | system brief, design and task briefs |

## Upstream files modified

| Path | Why |
|---|---|
| `README.md` | replaced by this project's README; the upstream text stays in the import commit and `README-ZH.md` |
| `.env.example` | lists every variable this project reads, names only, no values |
| `.gitignore` | adds `var/` and `frontend/dist/` to the upstream rules |

# HANDOFF · T08 → dev-build

Build `backend/app/simulation/{clock,world,coordinator}.py` and `tests/simulation/test_coupled.py` to `design.md`.
Accept: `uv run pytest -q tests/simulation/test_coupled.py`; gate `bash checks/merge.sh`.
Fixtures (unchanged, read from `design/modules/agent-world/fixtures/`): clearing-order, coupled-chain, round-rollback.
One-line wiring: `checks/required.json` g2 `public_shock_traceable_response`, `failed_round_rolls_back`.

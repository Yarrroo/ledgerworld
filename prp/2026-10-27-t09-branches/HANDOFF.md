# T09 · build hand-off

Build `backend/app/simulation/branches.py` and `tests/simulation/test_branches.py` to `design.md`;
`memory.py` / `transcripts.py` (board item 62) are reused unchanged.
Accept: `uv run pytest -q tests/simulation/test_branches.py`; gate `bash checks/merge.sh`.
Fixture (unchanged, read from `design/modules/agent-world/fixtures/`): branch-isolation (with coupled-chain for the plan).
One-line wiring: `checks/required.json` g2 `sibling_isolation`, `replay_identity`.

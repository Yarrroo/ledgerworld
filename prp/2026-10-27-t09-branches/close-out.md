# T09 · close-out

> Close-out (build stage 5). Source: design.md, HANDOFF.md.

## What landed
- `backend/app/simulation/branches.py`: `checkpoint(world, memory)`, `fork(cp, branch_id, model=…)`,
  `replay(cp, transcript)`, `Branch.label()`, `ledger_hash(store)`.
- `tests/simulation/test_branches.py`: 11 tests that play `branch-isolation.json` once on real OASIS
  platforms (ScriptedModel, FakeGraphMemory, SQLite) and assert each `expect` line.
- `checks/required.json` g2: `sibling_isolation` (7 ids) and `replay_identity` (4 ids).

## Measured
- `uv run pytest -q tests/simulation/test_branches.py`: 11 passed (about 11 s).
- Touched neighbours (`test_branch_memory`, `test_coupled`, `test_skeleton`, `checks/tests/test_kpi`) plus
  the new file: 116 passed. ruff, `no_secrets` and `attribution` are ok. The full gate is the landing
  train's.
- Fixture numbers reproduced: K_p at round 5 is 4,200,000 on no-action and 3,000,000 on integrated. The
  replayed `integrated` gives byte-identical journals and postings, the same ledger hash and the same
  transcript bytes.

## Brief vs code
- HANDOFF names `fork() → World`. The code returns a `Branch`, which wraps the `World` with its
  `BranchMemory` and lineage, because graph memory is not part of `World`. The design records this
  deviation.
- `memory.py` and `transcripts.py` were not changed: commit b14e2cd already supplied namespaces,
  snapshots and `ReplayModel`.

## Open, by name
- The OASIS RNG is module-global (inherited from T08). After a fork has run, a parent that continues
  draws from where the fork left the RNG. Only the random recommender reads it; it is a checkpoint
  component, but it is not isolated per world.
- No caller exists yet: the runs API (`POST /runs/{id}/fork`), decisions (a fresh branch per policy)
  and the T18 replay label are the consumers named in design.md.
- Copying a PostgreSQL ledger is written (it moves the posting-id sequence) but is not exercised
  offline.

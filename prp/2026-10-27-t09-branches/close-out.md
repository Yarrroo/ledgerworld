# T09 · Branches with isolated memory and exact replay — Close-out
> Close-out. Source: design.md, HANDOFF.md ← briefs/T09.md.
> Date: 2026-10-27

## What shipped
- `backend/app/simulation/branches.py`:
  - `checkpoint(world, memory)`, `fork(cp, branch_id, model=…, scenario=…)`,
    `replay(cp, transcript, …)`, `Branch.label()`, `ledger_hash(store)`.
  - Lineage is recorded in the child ledger's `branch_meta`, and a replay sets `replay=true` there.
- `tests/simulation/test_branches.py`: 25 tests.
  - 11 play `branch-isolation.json` once on real OASIS platforms (ScriptedModel, FakeGraphMemory,
    SQLite) and assert each `expect` line.
  - 14 pin the review findings; each failed before its fix.
- `checks/required.json` g2: `sibling_isolation` (16 ids), `replay_identity` (9 ids).

## Verification
- Accept: `uv run pytest -q tests/simulation/test_branches.py` gives 25 passed in about 25 s.
  It ran 20 times in a row with 0 red.
- Touched suites (`test_branches`, `test_branch_memory`, `test_coupled`, `test_actions`,
  `test_tool_boundary`, `test_skeleton`, `checks/tests`): 206 passed.
- ruff, `checks/no_secrets.py` and `checks/attribution.py` are ok. The full `checks/merge.sh` is run
  by the landing train.
- Fixture numbers reproduced:
  - K_p at round 5: no-action 4,200,000, integrated 3,000,000.
  - The replayed `integrated` gives byte-identical journals and postings, the same ledger hash and
    the same transcript bytes.
  - After both forks reach round 6, the parent's ledger hash, SQLite file hash and memory digest
    equal the checkpoint's.

## Brief vs code
- HANDOFF names `fork() → World`. The code returns a `Branch`, which wraps the `World` with its
  `BranchMemory` and lineage, because graph memory is not part of `World`. design.md records the
  deviation.
- `memory.py` and `transcripts.py` were not changed: commit b14e2cd already supplied namespaces,
  snapshots and `ReplayModel`.

## Follow-ups / known gaps
- ~~The RNG is per process, not per world.~~ Fixed (`prp/2026-10-27-xreview-t09-rng/`): each `World` owns its RNG,
  and OASIS's and camel's draws are routed to the running world's (`oasis_finance.draws`).
- **A checkpoint shares one SQLite connection** across the forks made from it. Forking one
  checkpoint from several threads at once needs a lock or per-fork bytes. `World.capture` copies
  the platform once more than needed. Both belong to `world.py`.
- **A replay from the wrong ancestor checkpoint is not detected** when the transcripts agree up to
  it: the lineage row then names that checkpoint's branch.
- **No caller yet.** The consumers named in design.md are the runs API, decisions (a fresh branch
  per policy) and the T18 replay label.
- **Copying a PostgreSQL ledger** is written (it moves the posting-id sequence) but is not run
  offline.

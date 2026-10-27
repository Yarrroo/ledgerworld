# A replay on the original's memory backend gets a graph of its own — Close-out
> Close-out (/dev-close). Source: cross-family review of l_b14b1d00ea, replay graph-id finding (correction card, board item 78).
> Date: 2026-10-27

## What shipped
- A replay keeps its branch's id and so its memory namespace, and `BranchMemory` derived the
  graph id from the namespace alone. A replay given a client on the original's memory backend
  therefore re-created the original's graph id and failed with `ConflictError`. Had it got
  past that, its failure cleanup would have deleted the graph under that id.
- `graph_id_for(namespace, instance=None)` and `BranchMemory(..., instance=...)` separate storage
  identity from logical identity: the namespace (reads, ownership, labels) is unchanged, while a
  named instance gets its own graph. `_fork` gives every replay a fresh `replay-<uuid>` instance,
  so any number of replays sit beside the original. A failed replay deletes only its own graph.
  Forks are unchanged: a second fork under one branch id is still refused by the backend.
- Files: `backend/app/simulation/memory.py`, `backend/app/simulation/branches.py`,
  `tests/simulation/test_branches.py`, `checks/required.json`.

## Verification
- Reproduced at 7803a87: both new tests failed with `ConflictError: graph lw-mem-18e9… exists`.
  Both pass after the fix. One runs two replays on the original's backend and checks the
  original's graph and records are intact. The other runs a replay that fails in its run
  (`ReplayMiss`) on that backend, checks that only its own graph and files are gone, then
  retries it.
- `uv run pytest -q tests/simulation/test_branches.py tests/simulation/test_branch_memory.py
  tests/simulation/test_interview.py` (60 passed) and `tests/decisions/test_policies.py`
  (39 passed, 1 xfailed; it calls `fork`) are green. Ruff is clean on the changed files, and
  `checks/no_secrets.py` and `checks/attribution.py` pass. The full gate is the landing train's.
- The new tests are registered under `replay_identity` in `checks/required.json`.

## Follow-ups / known gaps
- No backfill: nothing persisted holds a wrong graph id; a replay that hit the conflict never
  created anything.
- A successful replay's graph stays on the backend, like any branch's; nothing reaps replay
  graphs yet.

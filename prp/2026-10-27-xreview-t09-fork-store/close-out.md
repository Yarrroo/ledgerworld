# A failed fork or replay puts a given ledger store back as it was — Close-out
> Close-out (/dev-close). Source: cross-family review of T09 (branches), finding at
> `branches.py:284-292` (landed at 421be49): a failed fork leaves a supplied persistent ledger
> populated, so a retry with the same store fails on duplicate entity ids.
> Date: 2026-10-27

## What shipped
- Root cause: `World.__init__` loads the checkpoint's snapshot into a caller-supplied
  `LedgerStore` (`world.py:214-215`). `_fork`'s failure path closed the platform and removed the
  file and graph but never touched the store, and the `World` was built outside its `try`, so a
  failure while building it (a model backend refusing) undid nothing. `replay` carried its own
  copy of that failure path with the same gap.
- `branches._fork`: reads the store's rows first, builds the world inside the `try`, and on any
  failure closes the platform, removes the file and graph it created and copies those rows back
  (`_copy_ledger`), each undo running whichever fails (`AsyncExitStack`). The fork's own
  exception is raised; an undo that fails too is added to it as a note.
- `replay` runs its rounds inside `_fork` (`rounds=`), so both share one failure path.
- Docs: `fork`, `_fork` and `replay` docstrings; `prp/2026-10-27-t09-branches/design.md`.

## Verification
- Reproduced on 7a40cd1: a retry on the same store failed with
  `UNIQUE constraint failed: entities.entity_id`.
- Regressions, each failing on the pre-fix `branches.py` and passing after:
  `test_a_failed_fork_can_be_retried_on_the_same_store[model|lineage]`,
  `test_a_failed_replay_can_be_retried_in_the_same_workdir` (now also on the same store, and
  asserting no platform file is left), `test_a_failed_undo_does_not_hide_why_the_fork_failed`
  (failed with `ConnectionError: graph backend unreachable`).
- `uv run pytest -q tests/simulation tests/decisions/test_policies.py`: 258 passed, 1 xfailed
  (the xfail is in test_policies and predates this change). ruff clean,
  `checks/no_secrets.py` and `checks/attribution.py` ok. The full gate is the landing train's.
- Vet: T3, 2 rounds, 15 findings, 5 applied (1 proven), 10 recorded, 0 open.

## Follow-ups / known gaps
- `World.__init__` writes into a store it does not own before its fallible work (models,
  agents). Loading the snapshot later, or only into a store it created, would spare `_fork`
  both the wasted load and the construction-time undo. Out of this item's files.
- On PostgreSQL, restoring an empty store leaves the `postings` id sequence advanced; the next
  fork resets it from the checkpoint, a `World` built directly on that store does not. No `pg`
  test covers it.
- A failed replay of the checkpoint's own branch deletes the graph of that shared namespace on
  the replay's client (unchanged from before; the design gives a replay its own client).
- A store shared by concurrent runs would lose the others' writes on a failed fork's restore;
  the contract is an isolated, empty store and no caller shares one.

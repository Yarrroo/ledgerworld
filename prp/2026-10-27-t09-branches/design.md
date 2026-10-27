# T09 · Branches with isolated memory and exact replay — design

> Design output (build stage 2). Source: `briefs/T09.md`, `design/modules/agent-world/HANDOFF.md`,
> fixture `branch-isolation.json`. Next: implement → close-out. Depth: Large; the
> brief's accept and the fixture's `expect` block are the approval criteria.

## Who reads and writes a branch (consumers)

| Consumer | Task | Uses |
|---|---|---|
| Decisions: three policies on the same shocks, a fresh branch each | T11/T13 | `checkpoint(world)` once, `fork(cp, policy_id, model=…)` per policy, reads each fork's ledger |
| Runs API `POST /runs/{id}/fork`, `GET /runs/{id}` | API task | `Branch.label()` (`world_id, branch_id, parent, checkpoint_round, replay`) on every response |
| Simulation screen: replay label, scrubber | T18 | `replay` from `Branch.label()` / ledger `branch_meta.replay` |
| Demo: precomputed cohort labelled replay | T26/T28 | `replay(cp, Transcript.load(path))` |

None of them exists yet; this task ships the library they call. The unbackfillable invariants are
fixed here: a fork never writes its parent, a branch never reads a sibling's memory, and a
replay is labelled in the ledger itself (`branch_meta.replay`), not only in memory.

## Shape

```
parent World ──checkpoint()──► Checkpoint (frozen)
  committed boundary            capture: SQLite copy, actor memory records, clocks, RNG,
                                event cursor, pending C2, empty queue, transcript calls
                                ledger rows · BranchMemory snapshot (namespace + records)
                                    │
             ┌──────────────────────┼─────────────────────────┐
     fork(cp,"no-action")    fork(cp,"integrated")    replay(cp, transcript)
     new World, new agents   new World, new agents    fork with ReplayModel per actor,
     (build_finance_agent,   own queue, own .db,      same branch id, replay=true,
      never clone())         own ledger, own ns       runs the recorded rounds
```

- **`checkpoint(world, memory=None) → Checkpoint`** — only at a committed boundary
  (`committed_round == clock.round`, usable, empty queue). Wraps `World.capture()` (deep copies),
  the ledger's rows, `memory.snapshot()`, the parent's construction inputs (snapshot, actors,
  events already selected for the parent, seed, epoch). Nothing in it is shared with the parent.
- **`fork(cp, branch_id, *, model, workdir, memory_client=None, store=None, replay=False) →
  Branch`** — builds a new `World` (agents rebuilt from their personas, tools bound to the new
  queue), starts its platform on a new SQLite file, then `World.restore` from the checkpoint's
  capture (scripted-model bookkeeping reset for the new plan), replaces the ledger's rows with
  the checkpoint's, writes the child's `branch_meta` row, restores memory into the child's own
  namespace, and checks every component's digest against the checkpoint (ledger by
  `ledger_hash`, which leaves out `branch_meta`). A fork may not reuse the parent's id unless it
  is a replay, nor take the id of any ancestor its ledger records. `scenario` adds the fork's own
  events after the checkpoint (an event naming a `branch` runs only there). A fork that fails
  removes the platform file and memory graph it created, so it can be retried; a
  scenario event naming another branch is that branch's and is not checked. A replay of a branch the
  checkpoint already records keeps that row's parent and round and only sets `replay`;
  only the checkpoint's own branch or a new one may replay, never an ancestor (a cycle).
- **`replay(cp, transcript, *, workdir) → Branch`** — the transcript must hold the checkpoint's
  calls as its prefix; each model actor gets `transcript.replay_model(...)` (no live model, obs
  hash checked per call); runs the recorded rounds; same branch id, so journals compare byte for
  byte; labelled `replay=true`. It takes the branch's own `coordinator`, `memory_client` and
  `scenario`, as the branch was forked.
- Memory: `BranchMemory` (graph memory, `world/<w>/branch/<b>`) rides beside the world; it is
  not in the round loop (HANDOFF). Actor chat memory is restored by `World.restore`.

## Limits stated

- Ledger copy is a row copy in foreign-key order; on PostgreSQL the posting id sequence is moved
  past the copied rows. Only SQLite is exercised offline.
- The OASIS module RNG is process-global; worlds interleaved in one process share it (as T08).
- No `memory.py` / `transcripts.py` change was needed: commit b14e2cd already built namespaces,
  snapshots, transcripts and `ReplayModel`; this task composes them.

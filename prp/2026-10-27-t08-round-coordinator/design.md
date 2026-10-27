# T08 · Coupled round coordinator on one clock

> Design (workflow folded in). Source: `briefs/T08.md`, `00-system.md` §7.2,
> `design/modules/agent-world/HANDOFF.md` and its fixtures. Next: implement → vet → close.

## Requirements (from the brief; the accept is the criterion)

- `uv run pytest -q tests/simulation/test_coupled.py` and `bash checks/merge.sh` exit 0.
- Fixtures read unchanged: `clearing-order.json` (three arrival orders, one journal), `coupled-chain.json`
  (rumour r3 → request r4 → disbursal r5 → K_p 4,200,000 → 3,000,000, control unchanged, five-link trace),
  `round-rollback.json` (five faults restore everything, retry equals a clean control, rejected intent commits).
- Test ids registered in `checks/required.json` g2 `public_shock_traceable_response` and `failed_round_rolls_back`.

## Consumers (who reads or calls this)

| consumer | uses |
|---|---|
| branches / fork (T09) | `World.capture()` components (ledger, OASIS SQLite, memory, clocks, RNG, cursors, pending C2, empty queue, transcript cursor) |
| demo world, scenarios (T10) | `World(world_id, branch_id, snapshot, actors, scenario, …)`; scheduled events `public_post`, `delay_receipt`, `message` |
| policies, decisions (T11) | `overdue`/`arrived` status of each pending_in in the round's observation; offered facility → `lending.disburse` at step 7 |
| runs API, simulation screen (T16/T18) | `RoundResult{round, cleared, journals, transcript_entry}`, `World.trace(journal_id)` |
| replay (T09) | the model `Transcript`: one call per actor per round, `obs_hash` + tool calls |

Invariants that cannot be added later: one clock (`Clock.round` = OASIS `time_step` after every step, else the round
fails); a round commits whole or not at all; clearing order is `(priority, minute, actor, call)` only; every journal
names its intent and every intent its evidence, so a trace never needs a guess.

## Shape

- **`clock.Clock`**: `round`, `t_hours = 4·round`, `now`, `advance()`, `check(oasis_time_step)`. 18 rounds = 72 h.
- **`world.World`**: owns the ledger store, the OASIS env (one SQLite per branch, `recsys_type="random"`, TWITTER
  type so `env.step` advances its clock), one `IntentQueue`, one `FinanceAgent` per model actor, the model
  `Transcript` and `WorldState` (items, requests, flow statuses, pending C2, event cursor, intent log, round
  records). Convention: an actor's ledger entity is its `actor_id`; it acts from `<actor>/operating`.
- **`coordinator.Coordinator.run_round(world)`**: the ten steps inside one ledger connection-level transaction;
  step 10 records the transcript, then commits the ledger (the durable point).
  Step 6 also holds every intent to its tool's argument schema and to one use of its id. Every reference an
  intent names is checked before the ledger is asked, so a wrong one is a rejection, never a failed round.
  Clearing: `pay` → `ledger.pay` to an operating or cash account, or out of the world (never into a loan,
  payable or in-transit account, never of an obligation); `request_advance` → an addressed message `req:<actor>:r<round>` to the lender,
  or, against an `offered` facility, `lending.disburse` into the borrower's `in-transit` account plus a pending_in
  that lands at the next round boundary (step 2); `offer`/`accept` → a revenue-advance facility in state
  `offered` (LF-2 terms: 8 % fee, 15 % share); `disburse` → as above; `release` → closes an offer; `pledge` →
  `store.pledge`; `repay`, `defer`, `convert` → rejected with a named reason (repayment follows observed revenue,
  no deferrable contract, no FX quote in the round world).
- **Abort** (any exception or cancellation before the commit): close admission (every actor's turn ends) → cancel
  and join every task created inside the round (tagged by a context variable, so `env.step`'s gather children and
  their children are found) → fence the OASIS platform (one FIFO round trip, so a write a cancelled agent queued
  lands before restoration) → roll back the ledger and restore every captured component → verify the fingerprint
  equals the capture. A task that outlives its cancellation, a dead platform or a fingerprint mismatch marks the
  world unusable; `run_round` then refuses.

Out of this task: process-crash recovery, graph memory in the loop (off, HANDOFF), a policy driver for the treasury
(T11), and moving `tests/simulation/test_actions.py`'s step-7 stand-in onto `clear_intents` (not a file T08 owns).

# agent-world — the coupled agent world

Tasks: T06 (test doubles) · T07 (financial actions) · T08 (round coordinator) · T09 (branches and replay) · T10 (demo world).
Read with `00-system.md` §7–§8. The upstream facts below were read in the pinned sources on 2026-10-22.
Fixtures in `fixtures/` are the test truth: each test loads its fixture unchanged (copied to `tests/simulation/fixtures/` or read from this directory) and asserts its `expect` block.

How it sits on the upstream engine (read at camel-oasis 0.2.5, camel-ai 0.2.78, MiroFish `7657031`):
- Our runner drives `oasis.make(...)` and `env.step(...)` itself. The upstream simulation scripts (`backend/scripts/run_*_simulation.py`, started by `simulation_runner.py` as a subprocess) are not edited and not used for LedgerWorld runs.
- `env.step` runs every agent at once (`asyncio.gather`). Nothing in a round may depend on which agent answers first.
- OASIS's `ActionType` is closed; financial actions are extra tools given to `SocialAgent(tools=[…])`.
- `SocialAgent.perform_action_by_llm` builds its prompt from the social feed only; we override it.
- camel's `ChatAgent.clone()` returns a plain `ChatAgent` and loses the subclass; branches never use it.
- Graph memory is off in the round loop (upstream default `enable_graph_memory_update=False`).

## Interfaces

Signatures are prose; names are what the build uses.

| Unit | File | Shape | Notes |
|---|---|---|---|
| `ScriptedModel` | `backend/app/testing/scripted_model.py` | subclass of camel `BaseModelBackend`; implements `token_counter`, `_run`, `_arun`; built from a plan (list of entries `{actor_id, round, when_seen?, tool_calls[]}` plus one `default`) | Returns OpenAI-shaped completions whose `tool_calls` come from the plan entry matching **(actor, round, what the actor saw)**, never from call order. Records every prompt. A call that matches no entry and has no default raises. Selected by `LLM_BASE_URL=scripted://<plan>` or injection. |
| `FakeGraphMemory` | `backend/app/testing/fake_graph_memory.py` | the subset of the graph-memory client upstream calls (`graph_builder.py`, `zep_tools.py`, `zep_entity_reader.py`), in memory | Every key lives under a namespace; a read or write outside the caller's namespace raises `NamespaceViolation`. |
| `FinanceAgent` | `packages/oasis-finance/` | subclass of `SocialAgent(agent_id, user_info, …, tools=finance_tools(queue, actor), available_actions=[social subset])` (non-empty and without `purchase_product`: research/oasis-seam.md S3/S4) | Overrides `perform_action_by_llm`: observation = financial block first, then `env.to_text_prompt()`. Stores `obs_hash` and `evidence_ids` on the agent for the round. |
| finance tools | `packages/oasis-finance/` | `request_advance, offer, accept, disburse, repay, convert, pay, pledge, release, defer, no_action`; each takes typed args with `amount_minor: int`, `currency` | A tool call validates its args, builds a C1 `ActionIntent` and appends it to **its branch's** `IntentQueue`; it returns `"queued <intent_id>"`. It never reads or writes the ledger. Bound per branch by closure over that branch's queue. |
| `build_observation(actor, world, t)` | `packages/oasis-finance/` (`oasis_finance.observation`, over the world's items); `backend/app/simulation/observations.py` adapts the world to it | → `Observation{body, text, obs_hash, evidence_ids}` | Includes only the actor's own accounts and contracts, messages addressed to it, public posts and prices with time ≤ t, and its memory. `obs_hash` = sha256 of canonical JSON (sorted keys, no whitespace, integer minor units, ISO-8601 UTC). |
| `IntentQueue` | `packages/oasis-finance/` (`oasis_finance.actions`) | `put(*intents)` (all or none), `drain() → list[ActionIntent]` | Thread- and task-safe; `drain` returns intents **sorted** by `(priority_class, sim_minute, actor_id, call order)`: an actor's `i-r4-x-2` before its `i-r4-x-10`. |
| `Clock` | `backend/app/simulation/clock.py` | `round: int`, `t_hours = round × ROUND_HOURS`; `ROUND_HOURS = 4`, horizon 72 h = 18 rounds | One clock for social and financial events. OASIS's own `sandbox_clock.time_step` is advanced by `env.step` (only for a TWITTER-type platform, so never `recsys_type="reddit"`: research/oasis-seam.md S10/S11) and must equal `round` after each step; a mismatch fails the round. |
| `World` | `backend/app/simulation/world.py` | `World(world_id, snapshot: C5, actors, scenario, ledger, env)`; `World.run(rounds)` | Owns the OASIS env (one SQLite file per branch), the ledger handle, the queue and the clock. |
| `Coordinator.run_round(world)` | `backend/app/simulation/coordinator.py` | → `RoundResult{round, cleared: [C2], journals, transcript_entry}` | The ten steps of §7.2 inside one ledger transaction: advance clock · deliver scheduled events · publish posts · build observations · `env.step({agent: LLMAction()})` (agents queue intents) · validate · clear in sorted order · mandatory settlements · deliver C2 next round · commit and append transcript. Any exception or cancellation in steps 1–10 before durable completion aborts the round. Stop admission and cancel/join all round-owned actor work before restoring the complete round-start capture specified under Data; retry must equal a clean scripted control. |
| `Branch` / `checkpoint()` / `fork()` | `backend/app/simulation/branches.py` | `checkpoint(world) → Checkpoint{ledger_state, sqlite_copy, immutable_memory_records, memory_ns, clocks, rng_state, event_cursor, pending_c2, empty_queue, transcript_cursor}`; `fork(checkpoint, branch_id, plan?) → World` | A fork **rebuilds** every `FinanceAgent` from its persona (no `clone()`), copies each agent's memory records (`memory.retrieve()` → `write_record`), copies the SQLite file and the ledger state, and binds new tools to the new queue. Copy-on-write for the ledger: the parent is never written. |
| memory namespace | `backend/app/simulation/memory.py` | `world/<world_id>/branch/<branch_id>` | The live adapter prefixes ids; the fake enforces. |
| `Transcript` | `backend/app/simulation/transcripts.py` | append-only JSONL per branch: `{round, observations: {actor: obs_hash}, tool_calls: {actor: [...]}, intents, c2, journal_ids}` | `replay(branch)` builds a `ScriptedModel` from the recorded tool calls and re-runs the branch with no live model; output is labelled `replay=true`. |
| scenario loader | `backend/app/simulation/scenarios.py` | `load_world("scenarios/world.json") → DemoWorld{snapshot: C5, actors, epoch}`; `load_family(id, seed, params) → Family{events, market, overlay, script, cleared}`; `build_world(family, model, workdir) → World` | Six families, each seeded. `events` are the World's scheduled events; `market` (public prices, a grown obligation) is applied by the family's `delivered` coordinator hook; `overlay` adds the family's accounts, flows and obligations to the snapshot so the base world stays LF-1 + LF-2. `convert`/`defer` are refused in the round world, so the depeg and FX-gap families record that refusal and clear an advance request. |

Priority classes: 0 mandatory settlements and venue operations · 1 treasury and lender · 2 borrowers · 3 public information.

## Data

- **Round length 4 h**, horizon 72 h = 18 rounds. LF-1's events (receipt t=12, payroll t=40, withdrawal t=48) fall on round boundaries; the advance deadline t≤18 falls in round 4 (t=16).
- **Model calls**: six actors call the model (treasury, lender, borrower-b, borrower-c, venue, feed); payroll and the market-maker are rules. ≤ 6 calls per round, ≤ 108 per branch, ≤ 432 for the four branches of a demo run (live base + three policies).
- **Money** is `{minor: int, currency}` everywhere; tool args carry `amount_minor`. A non-integer amount is a validation error, never rounded.
- **Intent ids** are `i-r<round>-<actor_id>-<n>`, with `n` the order of tool calls inside that actor's single model response; deterministic for a given plan.
- **Per-branch state**: one OASIS SQLite file, one ledger schema/namespace, one memory namespace, one transcript, one `IntentQueue`.
- **Overdue and offered facilities** (the decisions module relies on these): a `pending_in` expected at t whose arrival is not delivered in step 2 of the round at t is marked `overdue` before step 4, so every actor and policy sees it that round. A `request_advance` against a facility in state `offered` clears at step 7 through `lending.disburse` (the lender committed when it offered) and arrives as `pending_in` at the next round boundary. A request with no facility waits for the lender's `accept` + `disburse` (`coupled-chain.json`). A lender `release` on an offered facility withdraws the offer.
- **Whole-round restoration**: capture actor memory records, both clocks, RNG state, scheduled-event cursor, pending C2 deliveries, queue and transcript cursor as well as ledger and OASIS SQLite. On the injected pre-completion exceptions in `round-rollback.json`, restore every captured component before retrying the same round. Failed-round diagnostics stay outside committed actor history. A scripted retry must equal a clean control from that capture, with no repeated event, settlement, post, memory entry or C2 delivery. This is exception rollback, not a claim of process-crash recovery.
- **Abort before restoration**: the capture precedes step 1, and rollback also covers event delivery, observation construction and the concurrent actor step. An unhandled actor exception or coordinator cancellation closes admission for that round; cancel and join every round-owned task, including children, before restoring state or allowing a retry. No failed-round writer may survive into the restored world. If quiescence cannot be established, mark the world unusable and refuse retry on that instance. Ordinary malformed output handled by the existing repair/no_action rule is not an unhandled round failure. Test the sibling-write race with explicit barriers, not timing sleeps; `round-rollback.json` names the interleaving. Scripted retries do not imply identical fresh model responses or refunded external model charges.
- **Checkpoint completeness**: a committed-boundary checkpoint pins immutable actor memory records, not just a mutable namespace name, plus both clocks, RNG, event cursor, pending C2 deliveries and an empty queue. A fork restores these alongside ledger and SQLite. Parent memories changing later cannot alter the checkpoint.
- **Evidence limits**: the scripted shock/control pair proves the response wiring and traceability under a declared plan. It does not establish that a live model independently chose the response. A fresh branch, a live-model branch, a replay and a scripted run are separate labels; sandbox provider mode does not select the model provenance. See `JUDGE.md` for the demonstration pre-mortem.
- Actor roster and scopes: `fixtures/actors.json`. Scenario families and seeds: `fixtures/scenario-families.json`.

## Fixtures

| File | Drives | What it pins |
|---|---|---|
| `fixtures/actors.json` | T10 | the eight actors, tools per mandate, what each may see, priority classes, call budget |
| `fixtures/clearing-order.json` | T08 | three arrival orders of four intents give one cleared order, one set of C2 results and one ledger |
| `fixtures/coupled-chain.json` | T06, T08 | ScriptedModel plan keyed on what the actor saw; rumour r3 → advance request r4 → disbursal r5 → K_p 4,200,000 → 3,000,000; control branch stays at 4,200,000; trace of five links |
| `fixtures/observation-scope.json` | T07 | six items borrower-c must not see at t=16 h and five it must |
| `fixtures/malformed-output.json` | T07 | one repair, then `no_action` + alert; a float never reaches a posting |
| `fixtures/round-rollback.json` | T08 | event/actor/settlement/commit faults and cancellation restore complete state after all round writers stop; scripted retry equals control; rejected intent still commits |
| `fixtures/branch-isolation.json` | T09 | sibling read raises, parent unchanged, replay byte-identical |
| `fixtures/scenario-families.json` | T10 | six families with seeds and the cleared action each must produce |

## Failure modes

| Failure | Where it bites | Guard |
|---|---|---|
| Clearing depends on which agent answered first | T08; branches stop being comparable | sort in `drain`; `clearing-order.json` runs three permutations |
| A tool writes the ledger directly | T07; money moves outside a round transaction | tools only queue; ledger handle is not in the tool closure; test asserts the ledger is unchanged until step 7 |
| Branch tools share one queue | T09; a sibling's intent clears in the wrong world | tools bound per branch; `branch-isolation.json` |
| `clone()` used for a fork | T09; agents lose the finance tools and persona silently and only post | fork rebuilds agents; test asserts each forked agent is a `FinanceAgent` with the full tool list |
| ScriptedModel keyed on call order | T06; concurrent `env.step` makes tests flaky | plan keyed on (actor, round, when_seen) |
| Observation leaks the future or another actor's cash | T07; nonanticipativity broken, judges' "fabricated" risk | `observation-scope.json`; scheduled events filtered by `visible_from_h ≤ t` |
| OASIS clock and ours drift | T08; posts timestamped in the wrong round | assert `sandbox_clock.time_step == round` after each step |
| The coupled test uses a committed-line draw | T08; K_p cannot move, the test is weakened to pass | `coupled-chain.json` `trap`: use an uncommitted advance |
| Rollback restores the ledger but not the OASIS SQLite | T08; posts from a failed round stay visible | copy the SQLite file at round start; restore on failure |
| An early step fails outside the rollback boundary | T08; delivered events or actor memories leak into retry | capture before step 1; abort unhandled failures in steps 1–10 |
| A sibling actor writes after state restoration | T08; the restored world is contaminated by the failed attempt | cancel/join all round-owned work before restoration; barrier-driven failure and cancellation cases; refuse reuse if quiescence is unproved |
| Model returns a float or an unknown tool | T07 | one repair, then `no_action` + alert (`malformed-output.json`) |
| Replay calls a live model | T09; non-identical replays, cost | replay builds a `ScriptedModel` from the transcript; network off in the test |
| Live demo too slow | T18/T31 | ≤ 108 calls per branch; upstream semaphore keeps concurrency |

## Done-whens

- accept: uv run pytest -q tests/testing/test_doubles.py — fixture: fixtures/coupled-chain.json
- accept: uv run pytest -q tests/simulation/test_actions.py — fixture: fixtures/observation-scope.json
- accept: uv run pytest -q tests/simulation/test_actions.py -k malformed — fixture: fixtures/malformed-output.json
- accept: uv run pytest -q tests/simulation/test_coupled.py — fixture: fixtures/coupled-chain.json
- accept: uv run pytest -q tests/simulation/test_coupled.py -k clearing — fixture: fixtures/clearing-order.json
- accept: uv run pytest -q tests/simulation/test_coupled.py -k rollback — fixture: fixtures/round-rollback.json
- accept: uv run pytest -q tests/simulation/test_branches.py — fixture: fixtures/branch-isolation.json
- accept: uv run pytest -q tests/simulation/test_scenarios.py — fixture: fixtures/scenario-families.json
- accept: uv run pytest -q tests/simulation/test_scenarios.py -k world — fixture: fixtures/actors.json

The `-k` lines narrow a run for debugging only; the task's own accept is the whole file, and every case above lives in it.

# T07 · FinanceAgent — the finance seam on the OASIS agent

> Design output (build stage 2, workflow folded in). Source: `briefs/T07.md`, `design/modules/agent-world/HANDOFF.md`,
> `research/oasis-seam.md`. Next: implement → vet → close.

## Requirements (from the brief; the accept is the criterion)

- `uv run pytest -q tests/simulation/test_actions.py` and `bash checks/merge.sh` exit 0.
- Two scripted actors change ledger state only through tools; malformed output → one repair → `no_action` + alert
  (`malformed-output.json`, unchanged); an observation never holds a future item or another actor's cash
  (`observation-scope.json`, unchanged). Test ids registered under g2 `actions_only_through_tools`.

Already landed (items 54, 61): `FinancialActionType`, typed args, `make_finance_tools`, `submit`, `IntentQueue`,
the guardrail turn and `build_observation`. Missing: the agent the platform actually drives.

## Consumers (who reads or calls this)

| consumer | uses |
|---|---|
| round coordinator (T08) | builds observations (step 4), `agent.observe(obs)`, `env.step({agent: LLMAction()})`, drains the queue (step 7), reads `agent.last_turn.alert` |
| branches / fork (T09) | rebuilds each agent with `build_finance_agent(spec, branch queue, …)`; `clone()` is refused |
| transcripts / replay (T09) | `last_turn.calls`, `observation.obs_hash`, intent ids |
| demo world (T10) | `actors.json` spec → agent via `app.simulation.actions.build_finance_agent` |
| interview (read-only) | upstream `perform_interview`, unchanged |

Invariant that cannot be added later: an intent's `obs_hash` is the hash of the exact financial block the model was
shown that turn — replay and the judge's trace rely on it.

## Shape

`oasis_finance.agent.FinanceAgent(SocialAgent)`:

- **Construction** (S3/S4/S8): finance tools from `make_finance_tools(queue, actor)` wrapped as `FunctionTool` with
  their schema; `available_actions` = the actor's social subset (an empty subset gives no social tool — upstream
  reads empty as "all", so it is built on `do_nothing` and that tool removed), and `purchase_product` is refused. After `__init__` the tool set
  is sealed: `add_tool(s)`, `add_external_tool`, `remove_tool(s)` and `clone()` raise.
- **`perform_action_by_llm`** (S5): needs `observe(obs)` first. Prompt = `obs.to_prompt()` then
  `env.to_text_prompt()`; system = the persona plus the tool rule. One model response offers finance + social tools;
  the guardrail checks the whole response (finance args typed, social args are an object with the schema's required
  keys and no others), repairs once, else queues `no_action` + alert. Only the accepted response's social calls run
  through the platform channel; finance calls only queue intents. The turn is written to memory. Returns the
  `TurnResult` (also `last_turn`) and never swallows a model or platform error (a round failure, §7.2).
- **`perform_action_by_data`** (S6): only the actor's social subset; a finance name or an unoffered social act
  (`purchase_product`) is refused. **`perform_action_by_hci`** is refused.

Guardrail change: `arun_turn/run_turn` take `social` (name → schema) and `system`; `TurnResult.social` holds the
accepted social calls. Defaults keep every existing caller's behaviour.

Wiring: `app.simulation.actions` exports `FinanceAgent` and `build_finance_agent(spec, …)`;
`app.simulation.observations` adapts world items as before.

## Dependency

camel's agent stack does not import with `mcp` 2.x (`FastMCP` left `mcp.server`), which the lock resolves today, so no
`SocialAgent` can be built. `oasis-finance` now depends on `camel-oasis==0.2.5` and `mcp<2` (lock: mcp 2.3.0 → 1.x).
This also un-skips the agent-stack test in `tests/testing/test_doubles.py`.

## Phases (each gated by its tests)

1. dependency + lock; `import oasis` works under `uv run` (tests chdir to a temp dir: importing oasis writes `./log`).
2. guardrail `social`/`system`; existing `test_tool_boundary.py` stays green.
3. `FinanceAgent` + `build_finance_agent`; `test_actions.py`; g2 ids in `checks/required.json`.

## Rejected alternative

Let camel's `astep` run every tool natively (finance closures return "rejected …" strings). Rejected: camel executes
each call as it comes, so half of a malformed response would already be queued before the repair — the guardrail must
see the whole response before any tool runs (S5, S7).

## Brief pass (feasibility · failure modes · simplicity)

- Feasible: `import oasis` with `mcp<2` measured OK (`uv run --with "mcp<2" python -c "import oasis"`, 2026-10-27).
- Failure modes: a social call that raises propagates (round abort, §7.2), after the finance intents are queued — the
  coordinator's rollback restores the queue, so no partial state survives. A finance call outside a turn is refused
  by `FinanceActor.stamp`.
- Simplicity: no new model client; the guardrail stays the single place a response is judged.

Run footer: Architect at Brief tier, unattended; no reviewer pack on this node; no publish (needs the owner's tap).

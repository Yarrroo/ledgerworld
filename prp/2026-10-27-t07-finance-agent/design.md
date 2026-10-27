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
  reads empty as "all", so it is built on `do_nothing` and that tool removed), and `purchase_product` is refused.
  After `__init__` the tool set is sealed: `add_tool(s)`, `add_external_tool`, `remove_tool(s)`,
  `remove_external_tool` and `clone()` raise, and the social offer is frozen at construction (upstream's
  `action_tools` list is not read again). A model is required: upstream would fall back to a default live one.
- **`perform_action_by_llm`** (S5): needs a fresh `observe(obs)` (one observation, one turn; `observation` stays
  readable after the turn). Prompt = `obs.to_prompt()` then the feed; system = the persona plus the tool rule. One
  model response offers finance + social tools; the guardrail checks the whole response (finance args typed, social
  args valid against the tool's JSON schema with no other keys), repairs once, else queues `no_action` + alert. A
  response with no financial call queues `no_action`, so every turn leaves one intent carrying `obs_hash`. Only the
  accepted response's social calls run on the platform; their results are `last_social_results` (a platform refusal
  is a `success: false` result, not an exception). The turn's observation and actions are written to memory. A
  model or platform exception is raised, never returned (a round failure, §7.2).
- **`perform_action_by_data`** (S6): only the actor's social subset; a finance name or an unoffered social act
  (`purchase_product`) is refused. **`perform_action_by_hci`** is refused.

Guardrail change: `arun_turn/run_turn` take `social` (name → schema) and `system`; `TurnResult.social` holds the
accepted social calls; a call outside the offer is refused naming every offered tool. `decode_args` is shared by the
finance and social parsers. Without `social`, every existing caller's behaviour is unchanged.

Wiring: `app.simulation.actions` exports `build_finance_agent(spec, …)` (the class itself is
`oasis_finance.agent.FinanceAgent`, imported lazily: importing `oasis` is slow and writes `./log`);
`app.simulation.observations` adapts world items as before.

## Dependency

camel's agent stack does not import with `mcp` 2.x (`FastMCP` left `mcp.server`), which the lock resolves today, so no
`SocialAgent` can be built. `oasis-finance` now depends on `camel-oasis==0.2.5`, `mcp<2` (lock: mcp 2.3.0 → 1.30.0) and `jsonschema>=4,<5`
(already locked through camel-ai; now declared, as the guardrail validates social arguments with it).
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

Review depth: a brief pass (feasibility, failure modes, simplicity); no separate design panel.

# T07 · FinanceAgent — close-out

> Close-out (build stage 5). Source: design.md. Brief: `briefs/T07.md`.

## What landed

- `oasis_finance.agent.FinanceAgent` — the OASIS `SocialAgent` each actor runs as. Finance tools on the branch's
  `IntentQueue`; explicit social subset (never `purchase_product`, never "all"); sealed tool set; `clone()` refused;
  `perform_action_by_llm` shows the scoped financial observation first, then the feed, and judges the whole response
  through the guardrail; `perform_action_by_data` limited to the social subset; `perform_action_by_hci` refused;
  a model is required (no silent default live model).
- Guardrail: `social` schemas and a persona `system` prompt; accepted social calls returned in `TurnResult.social`.
- `app.simulation.actions.build_finance_agent(spec, agent_id, queue, model=…)` — the entry the world (T08), forks
  (T09) and the demo world (T10) build agents through.
- `tests/simulation/test_actions.py`, registered under g2 `actions_only_through_tools`.

## Dependency

`oasis-finance` declares `camel-oasis==0.2.5`, `mcp<2` and `jsonschema>=4,<5`; lock moves mcp 2.3.0 → 1.30.0.
Without the mcp pin `camel.agents` does not import and no agent can be built. jsonschema was already locked (camel-ai).

## Verification (2026-10-27, this checkout)

- Accept: `uv run pytest -q tests/simulation/test_actions.py` — 23 passed; 20 consecutive runs, 0 red (the tests run
  an OASIS platform task that reads the wall clock).
- Touched suites: `tests/simulation`, `tests/testing`, `tests/execution/test_import_fence.py`, `checks/tests` —
  180 passed. The agent-stack case in `tests/testing/test_doubles.py`, skipped before for want of `mcp<2`, now runs.
- Lint and fences: `ruff check` on the new-code paths, `checks/no_secrets.py`, `checks/attribution.py` — green.
  The full `uv run pytest -q` is the landing train's run, not this checkout's.
- KPI: `checks/kpi.py g2 --print` → 25 (`actions_only_through_tools` and `report_numbers_grounded` pass).
- Reached: `app.simulation.actions.build_finance_agent` builds every LLM actor of `actors.json`, and
  `OasisEnv.step` drives it on a real OASIS platform in the tests. Importing `app.simulation.actions` does not load
  `oasis`.

## Reflect

- Fixed in the vet: every gap the two review rounds proved (vet-report.md).
- Follow-ups: camel warns that several finance-tool parameters carry no description (better tool calling, changes
  the offered schemas); `ATTRIBUTION.md` could name the agent beside the tool boundary (left alone: shared file,
  sibling changes land beside this one); the fixture loading and ledger opening helpers repeated across
  `tests/simulation` belong in a shared conftest.
- Not a gap: no coordinator calls the agent yet — the round coordinator is T08, and this task's consumer table names
  what it reads.

## Vet

T3, two rounds, 26 findings: 17 applied (10 proven by a failing-first test, 2 prose, 5 quality), 9 recorded with
reasons, 0 open. Details: vet-report.md.

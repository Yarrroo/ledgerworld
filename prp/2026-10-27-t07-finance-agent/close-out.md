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

## Not done here (named follow-ups)

- The round coordinator that drains and clears intents is T08; the tests clear `pay` intents with a stand-in.
- camel warns that several finance-tool parameters carry no description; adding them changes the offered schemas.

## Vet

(filled after the vet round)

# T07 · FinanceAgent — vet report

> Vet of `09592d1..HEAD`. Source: design.md, close-out.md.

**Tier T3**: the change decides which model calls become money intents (`guardrail.py` `_check` / `submit`);
8 files, 787+/99−, four subsystems, tests present. Instruments: code review (high), quality pass (four angles),
security review (separate reviewer over the explicit range).

## Round 1 — findings and what happened to each

| # | finding | source | conf. | outcome |
|---|---|---|---|---|
| 1 | `parse_social_call` raised `TypeError` on a list-typed schema property | review + own read | high | applied, proven (`test_a_social_schema_with_a_list_type_refuses_instead_of_raising`); now validated with jsonschema |
| 2 | a social-only response queued no intent, so no `obs_hash` record | review | medium | applied, proven (`test_a_response_of_social_calls_only_still_queues_no_action`) |
| 3 | the agent dropped its observation at turn start | review | medium | applied, proven (observation test asserts `agent.observation.obs_hash`) |
| 4 | camel memory is written but not read when acting | review | low | recorded: the observation's `memory` scope is the actor's history by design; prompts stay bounded and replayable |
| 5 | platform results (`success: false`) were invisible | review | medium | applied, proven (`last_social_results` asserted in the platform post test) |
| 6 | `remove_external_tool` not sealed | review | high | applied, proven (seal test) |
| 7 | argument decoding duplicated | review + quality | low | applied (quality): `decode_args` |
| 8 | a stale observation could survive an aborted round | review | low | recorded: the coordinator observes every actor at step 4 each round and restores actor state on rollback (T08) |
| 9 | design said `FinanceAgent` is exported from `app.simulation.actions` | review | high | applied (prose, cited contradiction with `__all__`) |
| 10 | design footer named the build tooling | review | high | applied (prose, repo naming rule) |
| 11 | social offer read from upstream's mutable `action_tools` | quality (altitude) | medium | applied, proven (seal test appends to `action_tools`) |
| 12 | a call outside the offer was refused listing finance tools only; money hint on social errors | quality (altitude) | medium | applied, proven (`test_a_tool_outside_the_offer_is_refused_naming_every_offered_tool`) |
| 13 | follower/follow lookups the feed never renders | quality (efficiency) | low | applied (quality) |
| 14 | `update_memory` re-counts the whole history each turn; feed stored in memory | quality (efficiency) | low | applied (quality): records of observation + actions |
| 15 | `TurnResult.calls` comment stale | quality | low | applied (quality) |
| 16 | `_sealed` via `getattr`; name normalisation repeated; idle plan repeated | quality | low | applied (quality) |
| 17 | per-turn schema rebuild of finance tools | quality (efficiency) | low | recorded: sub-millisecond, ≤6 calls per round |
| 18 | finance/social split of a spec in three places | quality | low | recorded: the agent's own check guards direct construction |
| 19 | `ListModel` reaches `ScriptedModel._finish`; ledger opening helper and fixture loading repeated across tests | quality | low | recorded: test-only, and a shared conftest would edit test files this task does not own |

Security review: no finding at confidence ≥ 8 (eleven candidates refuted: name collision, extra kwargs, actor
impersonation, SQL, purchase, other dispatch paths, fallback social calls, cross-branch intents, scope leaks,
by-data acts, untyped properties).

## Round 2 — re-vet of the round-1 delta (code review, medium: it changed which intents are queued)

| # | finding | conf. | outcome |
|---|---|---|---|
| 20 | jsonschema counts `1.0` as an integer, so a model float could reach a platform id | high | applied, proven (`test_an_integral_float_is_not_an_integer_argument`): strict integer type checker |
| 21 | a schema that is not valid JSON Schema raises inside the turn | low | recorded: social schemas are upstream's fixed code, every actor's are built and exercised by the seal test; a broken one is a code defect that should fail loudly, not a model error to repair |
| 22 | memory records lost `agent_id` | medium | applied, proven (`test_a_turn_is_remembered_under_the_agents_id_…`) |
| 23 | the seal is shallow: `FunctionTool.func` can be swapped | low | recorded: the seal closes camel's registration APIs (S8); attribute mutation is in-process, not a path a model reaches |
| 24 | `last_turn` stale when a social call raises | medium | applied, proven (same test): recorded before the posts run |
| 25 | `_check` and `parse_tool_call` both check the mandate | low | recorded: `parse_tool_call` is also the tool closures' entry, where the mandate is the whole offer |
| 26 | a validator is built per social call | low | recorded: sub-millisecond, ≤ 6 calls per round |

Round cap reached at 2; nothing left open. Gate after round 2: ruff, no_secrets, attribution green; the touched
suites (`tests/simulation`, `tests/testing`, the import fence, `checks/tests`) 180 passed.

**vet: T3, round 2, 17 applied (10 proven, 0 unproven, 2 prose, 5 quality), 9 recorded, 0 open** (26 findings after dedupe: 5 high · 7 medium · 14 low by the grades above).

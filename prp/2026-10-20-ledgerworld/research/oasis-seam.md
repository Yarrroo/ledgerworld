# camel-oasis 0.2.5 dispatch seams that T07 extends

> Research for T07 (financial actions in the agent platform). Read at camel-oasis 0.2.5
> (wheel sha256 `9ebd6ba8…606d`) and camel-ai 0.2.78 (`356624da…78d5`). Every row is
> machine-checked by `oasis_seam_probe.py` (ast over the downloaded wheels). Design it serves:
> `design/modules/agent-world/HANDOFF.md` (finance tools go in `SocialAgent(tools=…)`).

"Bypass" = a way for a model or a caller to act outside our typed finance tools, one that a
prompt-only extension would not close.

| id | seam | what T07 must do there | bypass? |
|---|---|---|---|
| S1 | `oasis/social_platform/typing.py:ActionType` | Closed `Enum` with members: cannot be subclassed or extended. Define a separate `FinancialActionType`; never coerce it through `ActionType`. | no |
| S2 | `oasis/social_platform/platform.py:Platform.running` | Do **not** send finance actions through the `Channel`: `ActionType(action)` raises `ValueError` on an unknown value with no `try`, which kills the platform task and hangs every waiting agent. Handlers are found by `getattr` and `__code__.co_argcount` ≤ 3, so a decorated handler breaks too. | no (crash, not bypass) |
| S3 | `oasis/social_agent/agent_action.py:SocialAction.get_openai_function_list` | Fixed list of 29 social tools including `purchase_product` and `interview`. The social subset T07 passes must exclude `purchase_product` (a money-like act that never touches the ledger). | **yes** |
| S4 | `oasis/social_agent/agent.py:SocialAgent.__init__` | `FinanceAgent` passes `tools=finance_tools(...)` and an explicit non-empty `available_actions`: an empty list means *all* S3 tools. `self.env` is built inline (no injection). `max_iteration=1` is set after `ChatAgent.__init__`, so one response per step, all its tool calls run; keep it 1 or intent numbering breaks. | **yes** (empty list) |
| S5 | `oasis/social_agent/agent.py:SocialAgent.perform_action_by_llm` | Override (HANDOFF): prompt = finance block + `env.to_text_prompt()`. Upstream catches every exception and *returns* it, so the repair→`no_action` guardrail must inspect the return value, not rely on raising. | no |
| S6 | `oasis/social_agent/agent.py:SocialAgent.perform_action_by_data` | `ManualAction` dispatch searches only S3's list and raises `ValueError` for a finance name: scripted finance acts go through the tool functions, not `ManualAction`. | no |
| S7 | `camel/agents/chat_agent.py:ChatAgent._aexecute_tool` | An unknown tool name hits `_internal_tools[name]` outside the `try` → `KeyError` → returned by S5. A tool that raises becomes the string `"Tool execution failed: …"` fed back to the model. Finance tools must return structured rejections and record the alert themselves. | no |
| S8 | `camel/agents/chat_agent.py:ChatAgent.add_tool` | Anyone holding the agent can add an executable tool at runtime (also `tools=`, `add_external_tool`). Test asserts each agent's tool set equals the mandate after construction and fork. | **yes** |
| S9 | `oasis/social_agent/agent_environment.py:SocialEnvironment.to_text_prompt` | Feed, groups and follower counts with no time or scope filter. Our observation builder adds the scoped finance block; the social part is public by design. | no |
| S10 | `oasis/environment/env.py:OasisEnv.step` | Advances `sandbox_clock.time_step` **only when the platform type is TWITTER**. `asyncio.gather` has no `return_exceptions`: one raising task does not cancel its siblings (§7.2 quiescence must cancel them). | no |
| S11 | `oasis/environment/env.py:OasisEnv.__init__` | Pass a `Platform` instance (one SQLite per branch). Its type is TWITTER unless `recsys_type="reddit"`; with reddit the S10 clock never advances and HANDOFF's `time_step == round` assert fails every round. | no |
| S12 | `oasis/clock/clock.py:Clock.time_transfer` | Wall-clock (`datetime.now()` at construction, scaled by `k`): non-deterministic. Reddit mode stamps posts with it; another reason for the TWITTER type plus our round clock. | no |
| S13 | `oasis/social_agent/agents_generator.py:generate_twitter_agent_graph` | All `generate_*` builders hard-code `SocialAgent(...)`; build `FinanceAgent`s ourselves. Importing `oasis` creates `./log` in the cwd and opens a log file (env.py, agent.py), and imports torch via recsys: tests must chdir to a temp dir. | no |

So the only bypasses are tool-set bypasses (S3, S4, S8). One test closes all three: assert each
agent's executable tool names equal its mandate, with no `purchase_product`.

## Python 3.12

- The wheel claims `requires_python <3.12,>=3.10.0`. T01 (`a9df13c`) locks the workspace at
  `==3.12.*`. uv ignores a dependency's upper bound, so the lock resolves.
- The sources are clean on 3.12.3: they compile with `SyntaxWarning` as error, and nothing
  imports `distutils`, `imp`, `asyncore`, `asynchat` or `smtpd` or calls `get_event_loop`.
  camel-ai 0.2.78 claims `<3.13`. The locked torch 2.14.1 and pandas 2.2.2 ship cp312 wheels, and
  igraph 0.11.6 ships abi3 wheels. `unstructured==0.13.7` also claims `<3.12`, but oasis never
  imports it.
- Gap: no test on T01's branch imports `oasis` (only `backend/scripts/*` do, and the gate does not
  run them). So T07's first `import oasis` is the first real 3.12 run. Probe verdict: a
  low-risk metadata mismatch, not a code break. Fallback if the import fails: pin the workspace to
  3.11. Upstream allows `>=3.11,<3.13`.

## Accept run

```
$ python3 -I prp/2026-10-20-ledgerworld/research/oasis_seam_probe.py && grep -q '^## Python 3.12' prp/2026-10-20-ledgerworld/research/oasis-seam.md; echo rc=$?
ok S1 oasis/social_platform/typing.py:ActionType
ok S2 oasis/social_platform/platform.py:Platform.running
ok S3 oasis/social_agent/agent_action.py:SocialAction.get_openai_function_list
ok S4 oasis/social_agent/agent.py:SocialAgent.__init__
ok S5 oasis/social_agent/agent.py:SocialAgent.perform_action_by_llm
ok S6 oasis/social_agent/agent.py:SocialAgent.perform_action_by_data
ok S7 camel/agents/chat_agent.py:ChatAgent._aexecute_tool
ok S8 camel/agents/chat_agent.py:ChatAgent.add_tool
ok S9 oasis/social_agent/agent_environment.py:SocialEnvironment.to_text_prompt
ok S10 oasis/environment/env.py:OasisEnv.step
ok S11 oasis/environment/env.py:OasisEnv.__init__
ok S12 oasis/clock/clock.py:Clock.time_transfer
ok S13 oasis/social_agent/agents_generator.py:generate_twitter_agent_graph
ok note table matches 13 seams
ok requires_python: camel-oasis '<3.12,>=3.10.0', camel-ai '<3.13,>=3.10'
ok oasis sources compile clean on Python 3.12.3 (SyntaxWarning=error); no distutils/imp/asyncore/asynchat/smtpd, no get_event_loop, no unstructured import
PASS
rc=0
```

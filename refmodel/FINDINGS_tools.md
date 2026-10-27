# Tool boundary reference model — findings

Oracle for the g2 check *actions only through tools* (`refmodel/tools_ref.py`), run against the
agent-world fixtures `observation-scope.json`, `malformed-output.json` and `actors.json`, loaded
unchanged from `prp/`. Accept: `python -m unittest discover -s refmodel -p test_tools_ref.py` → 32 tests, OK.

## Reproduced

| Fixture | Value reproduced |
|---|---|
| observation-scope | borrower-c at t=16 h sees exactly the 5 `included` ids; each of the 6 `excluded` ids is out for its stated reason |
| observation-scope | `obs_hash` = `c8430aaeae01473fc5aacc9915b72fa40af720189ebcb8db5dd3236b4bcbb1f0` (epoch 2026-01-01T00:00:00Z, item time points rewritten as ISO, UTF-8 JSON), pinned by `test_obs_hash_pinned`; same for reversed input and with every excluded item removed |
| malformed-output `repaired` | `request_advance`, 1 repair, no alert |
| malformed-output `still-malformed` | `no_action`, 1 repair, alert `malformed_tool_args` |
| malformed-output `unknown-tool` | `no_action`, 1 repair, alert `tool_not_in_mandate` |
| malformed-output `float-never-reaches-ledger` | `1200000.4` refused (not rounded); repaired intent carries int `1200000` |
| malformed-output `expect_all` | repair asked at most once; the prompt names the schema error; the guard never raises, so a malformed answer cannot abort a round |
| actors | 8 actors, 6 LLM / 2 rule, 6 calls per round, 18 rounds, 108 calls per branch; every tool outside an actor's list refused with `tool_not_in_mandate` |

## Mismatches and gaps in the fixtures (no fixture edited)

1. **`kind` is relative to the observer.** `observation-scope.json` labels borrower-c's account
   `own_account` and treasury's `account`. A kind cannot depend on who looks; the model ignores the
   `own_` prefix and decides by `owner == actor_id`. T07 should do the same.
2. **No epoch for ISO-8601 times.** The brief asks for ISO-8601 UTC in the hash input but the clock
   has only hours. The model takes the epoch as an input (default 2026-01-01Z); the hash above is
   pinned to it. T07 needs the world's start time in C5 or the scenario.
3. **Scheduled events have no scope.** `sees` has no entry for them; the HANDOFF only says they are
   filtered by `visible_from_h ≤ t`. The model: a due event addressed to an actor (`to`) is private
   to it; an unaddressed one is public, so the feed and the treasury see a scheduled rumour or
   receipt delay. No fixture covers a due event.
4. **Only `request_advance` args are pinned** (`amount_minor`, `currency`, `from`). Schemas for the
   other tools in `TOOL_SCHEMAS` are this model's assumption, not spec: currency codes are 3–6
   upper-case characters (USD, USDC), string targets non-empty, `accept`/`release` must name a
   target, `defer` takes `{flow, to_h}` as the decisions fixtures write it. `create_post` (feed) is
   a social action listed beside finance tools. `to_h` after the current time is left to step 6
   validation, which holds the clock. The decisions fixtures carry money as `{minor, currency}`
   while the HANDOFF's tool args carry `amount_minor`; T07 must map one onto the other.
5. **`alert_reason` when the two attempts fail differently** is unpinned; the model reports the
   repair attempt's reason, `repair_call_failed` when the repair call itself raises, and
   `tool_schema_missing` for a mandated tool with no schema.
6. **The hash input's encoding is unpinned.** The model hashes UTF-8 JSON (no `\u` escapes, as
   RFC 8785 does), orders items by id and refuses duplicate ids. Only time points (`visible_from_h`,
   `due_h`, `expected_h`, `to_h`, `until_h`) become ISO; durations such as `delay_h` stay hours.
7. **`mandatory_settlements_run`** needs a ledger and a round coordinator; out of scope for a
   stdlib oracle. Covered here only as "the guard never raises".

No `checks/required.json` id is added until T07 imports this model.

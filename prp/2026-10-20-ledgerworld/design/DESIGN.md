# LedgerWorld — design

## What it is
LedgerWorld is an agentic treasury that rehearses a cash crisis in a coupled agent world before it spends a dollar: it lets a shock play out round by round, compares three protective plans on the same shocks, and executes only the plan that still meets every obligation through the Airwallex sandbox, then reconciles the result against its own ledger.

The model proposes; the ledger and the rules decide. Nothing simulated holds a credential, and nothing executed is decided inside a hypothetical branch. Entry for the Airwallex Agentic Banking Hackathon, build window 25 Oct 04:30 UTC → 13 Nov 18:29 UTC.

## Architecture

Ten modules. Money flows one way: observed snapshot → simulated world → chosen plan → bound approval → gateway → sandbox → receipts → reconciliation back into the ledger.

| Module | Owns | Tasks | Critical |
|---|---|---|---|
| ledger | money truth: accounts, buckets, double-entry journals, reservations, pledges, spendability S[a,c,t], advances, lender capacity K_p | T02 T03 T04 T05 T29 | yes |
| agent-world | eight actors on the upstream engine, one clock, transactional rounds, branches, replay, six scenario families | T06 T07 T08 T09 T10 | yes |
| decisions | three policies on paired seeds, nonanticipativity, reverse stress | T11 T21 | yes |
| airwallex | fake and live transports behind one key switch; Mode A / Mode B leg mapping | T12 T15 | yes |
| execution | bound approval, outbox, idempotent legs, receipts, reconciliation, credential isolation, `demo.sh` | T13 T14 T23 T31 | yes |
| ui | six screens; the four-click judge path under 60 s | T17 T18 T19 T26 | yes |
| api-reports | `/api/v1`, job runner, grounded reports, read-only interview | T16 T20 | no |
| submission | README, attribution, submission pack, video script | T27 T28 | no |
| base | upstream import (unmodified, tagged), workspace, merge gate, KPI runner | T01 T22 | no |
| deploy | container, host, freeze switch, uptime monitor | T24 T25 T30 | no |

Seams (contracts in `contracts/`, system brief §8):

| Seam | From → to | Shape |
|---|---|---|
| C1 ActionIntent | agent tool call → round coordinator | `{intent_id, branch_id, round, actor_id, type, params, evidence_ids[], obs_hash}` |
| C2 ClearedAction | coordinator → actor (next round) | `{intent_id, status, reason?, journal_id?, round}` |
| C3 BoundApproval | operator → execution gateway | legs, `plan_hash`, `snapshot_id`, `expires_at`, `mode` |
| C4 ProviderOp | gateway ↔ Airwallex transport | `{leg_id, request_id, kind, state, receipt, reconciled}` |
| C5 Snapshot | ledger → world, decisions | entities, accounts with buckets, obligations, contracts, exposures |
| C6 API | backend → six screens | system brief §11 |

How the world plugs into the upstream engine (read at the pinned commits, 22 Oct):
- The round coordinator is **our own runner** calling `oasis.make` and `env.step`; the upstream simulation scripts stay untouched.
- Financial actions are **extra tools** on a `SocialAgent` subclass (`tools=[…]`). A tool call only queues a C1 intent in its branch's queue; the coordinator clears the queue after `env.step` returns, in a fixed order (priority class → simulated time → actor id), because `env.step` runs agents concurrently.
- The subclass overrides `perform_action_by_llm` so the scope-filtered financial observation comes before the social feed, and hashes it into `obs_hash`.
- A fork rebuilds each agent (camel's `clone()` returns a plain `ChatAgent`), copies its memory records, the platform's SQLite file and the ledger at the checkpoint, and binds tools to that branch's own queue.

## Decisions
- Build on the upstream engine MiroFish at `7657031`, imported unmodified as the first commit and tagged `upstream-7657031`; new code goes into new modules. — system brief §3
- Licence AGPL-3.0, repo public from day one, demo footer links the source; `camel-oasis` is Apache-2.0. — event pages + upstream LICENSE, 20 Oct
- Money is integer minor units; one converter at the provider boundary; zero, unknown and stale are three states, and stale blocks execution. — system brief §5
- Fixtures LF-1 (treasury) and LF-2 (lender pool) are the money truth until an external spec is supplied. — system brief §6
- Scope: 8 actors, 6 scenario families, 3 policies; revenue advances run end to end, collateral is simulation-only; cut line is T21. — system brief §15
- No product code before the build window opens; until then only plans, designs and DDL. — owner, 21 Oct
- Mockups from the brief author are the canonical design input for the UI; where they contradict the brief, the mockup wins for UI. — owner, 21 Oct
- Tests run offline on SQLite, fakeredis, a scripted model and a fake graph memory; `pg` and `live` markers run outside the merge gate. — system brief §16, build box probe 20 Oct
- The reserve floor is checked on projected cash P(t) over the horizon, not on spendability S; S subtracts every committed outflow. This corrects §5/§6 of the system brief, where LF-1 would otherwise breach at t=0. — design, ledger module, 22 Oct
- Settled balance is the sum of postings, never a stored column; a double pledge is refused by a partial unique index in the database. — design, ledger module, 22 Oct
- One clock with 4 h rounds, 18 per 72 h horizon: LF-1's events at 12, 40 and 48 h land on round boundaries; six actors call the model, so a branch costs ≤ 108 calls and a four-branch demo run ≤ 432. — design, agent-world module, 22 Oct
- Graph memory is off in the round loop (upstream default); it is spent once per world build and on report queries. — upstream source at the pin, 22 Oct
- A replayed `request_id` is rejected by the provider, not answered with the original: the gateway resolves a duplicate or `409` by looking the leg up by `request_id` and never resubmits under a new id; the fake rejects the same way. Receipts come from `GET` by provider id; a webhook (HMAC-SHA256 over timestamp + raw body) is only a verified hint. — provider API docs, research note 22 Oct
- Mode B's advance leg is a settled `simulation/deposit/create` into a Global Account in the advance currency; the API version is pinned at 2024-06-30 or later. — provider API docs, research note 22 Oct
- The connector never repeats a POST after a timeout or a 5xx (outcome unknown, the gateway looks up by `request_id`); it retries a 429 and one 401 itself with the same id. The live mode needs `AIRWALLEX_MODE=sandbox`; a key appearing never flips it, and an unclear connected-accounts probe selects Mode B. API version pinned at `2024-06-30` in `x-api-version`. — design, airwallex module, 23 Oct
- The gateway writes the leg and marks it `submitted` before calling the provider; a leg settles and its journal posts in one transaction only on a `GET`; a later contradiction is an incident the operator closes. Execution tables live in the observed store only, never in a branch. — design, execution module, 23 Oct
- Each policy is judged on its own fresh branch per scenario from one checkpoint, seed and schedule. The policy drives the treasury there (its model is not called), and feasibility comes from the realised ledger. The key `(unmet, breached, max short, cost)` is integer, summed over scenarios and never averaged. The selected policy re-decides on the observed snapshot to produce the legs. — design, decisions module, 23 Oct
- Nonanticipativity has two guards: a view whose fields carry `available_at` (an early read names the path) and a paired-history check (identical history → identical decision) for side channels. When nothing is feasible, no plan is offered and the result escalates to a role. — design, decisions module, 23 Oct
- K_p also subtracts the pool's obligations due within the horizon; LF-2 has none, so 42,000.00 stands. A receipt that misses its round is marked overdue before the actors observe, so LF-1's advance can land by t = 18. — design, decisions module, 23 Oct
- Reverse stress searches one family at a time (an 8-point grid, then an exact integer search) on replayed reactions, with one confirming branch. It is labelled a search, has no probability field, and its cohort stays out of the comparison. On LF-1 the selected plan keeps the floor with zero margin at t = 40. — design, decisions module, 23 Oct

- The six screens extend the existing frontend. Every number retains source/context, currency, status and as_of; graph/feed/cash share one committed-round cursor. Old responses, including older polls for the same execution, cannot overwrite newer state. Layout is provisional until canonical mockups arrive. — design, UI module, 23 Oct
- Operator review shows current-plan terms and lifetime before approval; returned C3 hash/expiry and terms are verified before a separate explicit Execute action. Credentials stay in tab memory only; financial POSTs are not retried automatically. Scenario-set fees are distinct from current-plan fees. — design, UI module, 23 Oct
- The judge path is anonymous and read-only: initial Overview, then Open simulation, Compare policies, View execution, Open receipt. A backend-supplied demonstration run/execution association is required; no invented receipt or unrelated latest execution. Cold-navigation elapsed includes loads, excludes tool installation, and takes the maximum viewport/theme run. No g4 duration is measured before build. — design, UI module, 23 Oct

- Whole-round rollback and checkpoints preserve actor memories, both clocks, RNG, event/delivery cursors and queue as well as ledger/SQLite/transcript. Injected pre-completion exceptions must retry identically to a clean scripted control; these checks do not prove process-crash recovery. — judge pre-mortem, agent-world module, 23 Oct
- Capture precedes step 1; an unhandled exception or cancellation before durable completion aborts the entire round, including event delivery and concurrent actor work. Cancel/join all round-owned writers before restoring; if quiescence is unproved, refuse reuse of that world. Handled invalid output remains an ordinary result. — judge pre-mortem, agent-world module, 24 Oct
- Scripted coupled-chain evidence proves declared wiring, not independent live-model choice. The recording retains run/branch/checkpoint/seed and distinguishes freshness, model provenance, replay and provider mode. — judge pre-mortem, agent-world module, 23 Oct

## Open decisions
- **Are connected accounts enabled on our sandbox (Mode A)?** · owner: the brief author · default: Mode B, the advance as a labelled sandbox deposit simulation · by: 2026-10-28
- **Is an external build spec with its own fixtures coming?** · owner: the brief author · default: LF-1 / LF-2 from the system brief · by: 2026-10-24
- **Host, model and graph-memory keys with spend caps** · owner: the owner · default: build on fakes; fake-mode banner on the demo · by: 2026-10-30
- **Screen layout of the six screens** · owner: the brief author · default: system brief §12 tokens and the four-click judge path · by: 2026-10-27

## Changes
- 2026-10-24 · first-window sequence rechecked against the unchanged board: accepts, prerequisites and nominal window retained. Operational preflight reports acceptance and credential gates still unresolved; no start, publication or deployment authorisation inferred. Freeze remains the next scheduled sequence refresh.
- 2026-10-24 · coupled-round pre-mortem extends rollback to early steps and cancellation: all round-owned writers must stop before restoration; otherwise the world is unusable. Barrier-driven sibling-cleanup cases added to the fixture; T08, HANDOFF and system brief §7.2 aligned. Runtime behaviour remains untested.
- 2026-10-23 · first-window sequence prepared in modules/agent-world/SEQUENCE.md: authorised start, offline ledger/doubles prerequisites, fixed checkpoints, proof commands and delay responses. Application/participation blocker closed from the owner's reported confirmation relayed on 22 Oct; event acceptance remains unconfirmed.
- 2026-10-23 · coupled-world judge pre-mortem: complete rollback/checkpoint capture and retry-control assertions; scripted proof distinguished from live-model evidence. T08/T09/T28 and system brief §7/§13 aligned; criteria-source blocker remains open.
- 2026-10-23 · UI designed (six fixtures, seven done-whens, six-screen layout/state/approval contracts). Briefs T17/T18/T19/T26 linked; T16 and system brief §11 preserve C6 context and prepared demo association. All critical modules now have fixture-backed design; product UI and timing remain untested.
- 2026-10-23 · decisions designed (interfaces, 6 fixtures, 17 failure modes, 6 done-whens). K_p counts pool obligations (system brief §6, ledger, T05). The coordinator marks overdue receipts before observation and clears offered facilities (T08). C5 entities carry an escalation role. Briefs T11 and T21 sharpened.
- 2026-10-23 · execution designed (interfaces, schema.sql with 5 tables, 7 fixtures, 15 failure modes, 8 done-whens); system brief §11 names the webhook route; briefs T13, T23, T31 sharpened.
- 2026-10-23 · airwallex designed (interfaces, 6 fixtures, 12 failure modes, 6 done-whens); brief T12 scenarios widened (timeout before send, 5xx, malformed body) and the no-repeat-POST rule.
- 2026-10-22 · Provider semantics read from the docs: duplicate request ids are rejected (T12 fake rule corrected), deposit and transfer simulations named, webhook signing; system brief §10 and briefs T12, T13, T15 updated.
- 2026-10-22 · ledger designed (interfaces, schema.sql, 7 fixtures, 9 done-whens); system brief §5/§6 corrected: floor on P(t), S subtracts committed outflows.
- 2026-10-22 · agent-world designed (interfaces, data, 8 fixtures, failure modes, 9 done-whens); round length settled at 4 h.
- 2026-10-22 · Design written: module map, seams C1–C6, the upstream plug-in points, decisions and open decisions.
- 2026-10-22 · Upstream seam read at the pins; T06–T09 plans carry it.

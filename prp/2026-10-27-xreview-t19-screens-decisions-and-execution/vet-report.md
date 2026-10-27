# Vet: board item 94
> Tier T3: the outcome of a payment-executing POST, `Execution.vue`; 2 code files, test delta
> present. Range 96f5bfc..24b9adf. Instruments: `/code-review high` (twice, level unconfirmed),
> `/simplify`, `/security-review` (clean). Rounds: 2, converged with 0 open.

| Round | Finding | Grade | Outcome |
|---|---|---|---|
| 1 | Bound approval not checked for entity, account, leg index/kind/source/counterparty/after | medium | applied, proven |
| 1 | An approval with no legs was taken as bound, so Close re-enabled Confirm | high | applied, proven |
| 1 | A status read with no legs stopped the poll on a TypeError | high | applied, proven |
| 1 | An unparseable first read reported "the server has no record" | medium | applied, proven |
| 1 | `Date.parse` took "1" as a valid expiry | medium | applied, proven |
| 1 | The unreadable error borrowed status 0; the fake answered 201 to `/executions` | low | applied (quality) |
| 1 | Simplify: one refusal rule, dead no-legs guard, inline check, `optional(promise)`, `accepted()` | low | applied (quality) |
| 1 | Parse failure belongs in `request()`; shared outcome rule for Simulation | medium, low | recorded: changes other screens; follow-up |
| 1 | A non-ApiError thrown after the answer is applied reads as unknown | medium | recorded: only by sabotaging browser globals; fails closed |
| 1 | `flow.blocked` survives navigation | medium | recorded: existing guard; follow-up |
| 1 | Second `Date.parse`; typed v1 wrappers; status null | low | recorded: no gain |
| 2 | A read for another execution id was shown as this one's | medium | applied, proven |
| 2 | Missing mode/as_of/ids or leg/incident fields passed the read check | medium | applied, proven |
| 2 | An unreadable linked execution failed the whole load and blocked review | medium | applied, proven |
| 2 | "Not recorded" and "could not be read" could stand together | low | applied, proven |
| 2 | `funded_by`/`facility_id`/`after` element types unchecked | low | applied, proven |
| 2 | RFC 3339 space/lowercase forms rejected | medium | applied, proven |
| 2 | Hoist the timer helpers in the spec | low | applied (quality) |
| 2 | fx `to_currency` not shown in the dialog | medium | recorded: missing column; follow-up |
| 2 | Validate against the contract schemas | low | recorded: no validator in the frontend; follow-up |

Coverage: read the whole of `Execution.vue`, `api/v1.js`, the C3/C6 schemas and the API routes the
screen calls. Simulation was read for the outcome rule only. Totals: 31 found (2 high, 12 medium,
17 low), 22 applied (12 proven, 0 unproven), 9 recorded, 0 open.

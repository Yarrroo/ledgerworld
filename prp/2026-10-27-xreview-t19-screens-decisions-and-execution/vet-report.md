# Review record: unreadable successful POSTs on the Execution screen
> Risk: the outcome of a payment-executing POST, `Execution.vue`. Range 96f5bfc..HEAD, plus the
> merge with main. Instruments: a correctness review at high effort (three passes: two rounds,
> then one after merging main), a quality pass and a security pass (clean). Nothing left open.

| Pass | Finding | Grade | Outcome |
|---|---|---|---|
| 1 | Bound approval not checked for entity, account, leg index/kind/source/counterparty/after | medium | applied, proven |
| 1 | An approval with no legs was taken as bound, so Close re-enabled Confirm | high | applied, proven |
| 1 | A status read with no legs stopped the poll on a TypeError | high | applied, proven |
| 1 | An unparseable first read reported "the server has no record" | medium | applied, proven |
| 1 | `Date.parse` took "1" as a valid expiry | medium | applied, proven |
| 1 | The unreadable error borrowed status 0; the fake answered 201 to `/executions` | low | applied (quality) |
| 1 | Quality: one refusal rule, dead no-legs guard, inline check, `optional(promise)`, `accepted()` | low | applied (quality) |
| 1 | Parse failure belongs in `request()`; shared outcome rule for Simulation | medium, low | recorded: changes other screens; follow-up |
| 1 | A non-ApiError thrown after the answer is applied reads as unknown | medium | recorded: only by sabotaging browser globals; fails closed |
| 1 | A held block survived navigation | medium | closed by main's per-run hold |
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
| merge | A linked execution whose read failed was never read again | medium | applied, proven |
| merge | "No execution to show" stood beside a read error, for a payment just sent | medium | applied, proven |
| merge | An unparseable decision read as "no decision is available" | medium | applied, proven |
| merge | The read error said "last loaded" when nothing was loaded | low | applied (wording) |
| merge | Records named the tooling that produced them | low | applied (wording) |
| merge | An unknown execution stays blocked after a read shows it | medium | recorded: a quarantine decision; follow-up |
| merge | Space-form times parse differently in Safari | low | recorded: the server emits `T`; Safari fails closed |
| merge | fx `to_currency`; `request()` altitude; schema reuse | — | duplicates of recorded rows |

Coverage: read the whole of `Execution.vue`, `api/v1.js`, the C3/C6 schemas and the API routes the
screen calls. Simulation was read for the outcome rule only.

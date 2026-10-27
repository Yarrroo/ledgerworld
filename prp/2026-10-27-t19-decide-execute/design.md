# T19 · Decisions and Execution — build design

> Build design (Large). Source: `briefs/T19.md` and
> `design/modules/ui/HANDOFF.md` (the module design; this file records only the build decisions it
> leaves open). Next: implement → vet → close. No design page was pushed: the module design is the
> visual reference and this run has no reviewer to show one to.

## Requirements (accept, pre-registered)

- `npm --prefix frontend ci && npm --prefix frontend run build && npm --prefix frontend run test:unit -- tests/unit/decide-execute.spec.js` exits 0.
- `bash checks/merge.sh` exits 0.
- The spec loads `decide-execute.json` and `accessibility.json` unchanged: approval disabled outside
  authority, unknown renders the incident view, a fake-mode receipt reads `Simulated provider`.

## Readers and writers

| Party | Reads / writes | What it needs from T19 |
|---|---|---|
| Judge (anonymous) | `/decisions` → `View execution` → `Open receipt` | read-only, no token prompt in the way, stable CTA text |
| Operator | token, `Review plan` → `Confirm approval` → `Execute approved plan` | bound terms before each act, one POST per click |
| API (T16, C6) | producer of `DecisionsResponse`, `ApprovalResponse`, `ExecutionAccepted`, `ExecutionResponse` | the browser formats, never recomputes the plan, hash or reconciliation; the server rechecks every term |
| T26 judge path | `/decisions?run_id=`, `/execution?run_id=&execution_id=` | route paths and link text |
| T17 shell (`api/v1.js`) | shared | `request`, `ScreenShell`, `useReading`, `latestOnly`, formatters, `LABELS` — reused, not edited |

## Invariants that cannot be added later

- The token lives in one module-scoped `ref` of `Execution.vue`: tab memory, gone on reload, sent
  only as the `Authorization` header of the two POSTs. It is bound to the input as a DOM property,
  never an attribute, a URL, storage or a log.
- A financial POST is sent once per explicit click: a `submitting` flag set before the `await`
  disables the button; an approval is executed at most once from this tab, whatever the outcome.
- A timed-out execution POST is resolved by `GET /executions/{approval_id}`; 404 there is "not yet
  recorded", never "failed". A timed-out approval POST has no id, so the review blocks with
  "operator resolution required"; no lookup endpoint is invented.
- Expiry is read on the server's clock: `as_of` of the approval response plus elapsed tab time.

## Decisions

1. **Routes**: `/decisions?run_id=` and `/execution?run_id=&execution_id=`; without a query both
   take the Overview's `demo` context and say "unavailable" when it names nothing. Two lines in
   `router/index.js`, the wiring T17 left for this task.
2. **Requests** use `request()` from `api/v1.js` inside the views; no API helper is added to the
   shared module (owned by T17).
3. **Scenario-set cost** is the integer sum of one policy's `funding_cost` over its results in one
   currency, labelled "across N scenarios; not the current execution fee". Per-branch funding cost
   is listed beside it.
4. **Review** is a modal dialog on Execution (Escape closes with no POST, focus returns to the
   opener). Stage one shows what the API supplies before binding: policy, run, comparison
   snapshot, mode, the approval lifetime default (15 minutes, server-set), the per-branch funding
   cost of the selected policy and the note that the server binds the plan on the current observed
   snapshot. Stage two shows the returned C3 — entity, account, snapshot, mode, every leg, the hash
   and the absolute expiry — and `Execute approved plan`. Execute is disabled when the returned
   mode differs from the screen's, the snapshot is one of the comparison's branches, the approval
   expired, or a refusal invalidated it.
5. **Search cohort** (`reverse_stress`) renders under "Search result, not a forecast" and offers no
   review: a search is not a decision.
6. **Receipt row text**: reconciled → `<STATUS> · reconciled as of <as_of UTC>`; otherwise
   `<State> · <STATUS or no provider status> · not reconciled`. An open incident on a leg removes
   its success text and the incident view lists it; `unknown` shows "Outcome unknown; checking
   provider status. Do not send again." There is no reverse or resend control.
7. **Polling**: every 5 s while a leg is pending, submitted or unknown, through `latestOnly`; it
   updates text in place and never moves focus. The screen's own read (initial and Refresh) draws
   its generation from the same guard, so an older poll never overwrites it and it never
   overwrites a newer poll. A 404 is an answer; any other failure is not, so it discards no
   earlier-issued read, and its error clears only on an answer issued after it.

## Contract gaps (recorded, not hard-coded)

- **No current-plan preview**: C6 has no route returning the plan before `POST /approvals`
  (`no_approval_preview_endpoint` in the fixture), so the legs and amounts are first visible as
  the server's bound C3, before the separate Execute.
- **No fee in C3**: `ApprovalLeg` carries `facility_id` but no fee, so the current-plan fee
  ("USD 800.00 for adv-a" in the fixture) is shown only as the selected policy's per-branch funding
  cost and labelled as such.
- **No setup movements in `ExecutionResponse`**: setup funding (Mode B) is not on this screen.

## Design run

Size: one module, no named reviewer, nothing irreversible. The consumers, invariants and
rejected shapes are the module design's (`design/modules/ui/HANDOFF.md`); this note adds only
build decisions. No design page was published. The review pass is the vet round
(`vet-report.md`).

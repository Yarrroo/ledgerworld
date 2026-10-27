# ui — see the crisis, compare the plans, review the receipt

Tasks: T17 (Overview, Treasury, Lending) · T18 (Live Simulation) · T19 (Decisions, Execution) · T26 (browser judge path).
Purpose [REQ, system brief §12–13]: make the money, its provenance and the approval boundary legible on a phone and desktop. This is a reversible design default, not a delivered UI or an approved mockup. Canonical mockups from the brief author supersede layout defaults when supplied; safety and source labels remain mandatory.

## Readers and writers

The operator reviews and authorises; a judge reads without a token; the brief author supplies canonical mockups; the builder implements; assistive technology reads the same state as the sighted user. C6 from the API module is the only financial data source. C3 is produced by the execution module after operator confirmation, not by the browser. C4 receipts are read-only projections from reconciliation. The existing frontend is extended; upstream views stay reachable [BOUND, T17].

## Invariants to preserve before the layout

C6 must carry snapshot, run, branch and round identity plus `as_of` and mode wherever relevant. Never erase unknown/stale states, replay provenance, the original receipt timestamp or the currency. These are existing data invariants, not new stores; a UI cannot reconstruct missing provenance later. Current-plan terms and approval lifetime must be visible before confirmation; the returned C3 hash and absolute expiry are displayed after confirmation and before the separate Execute action. UI disabling helps the user, but the backend rechecks authority and is the security boundary.

## Target and measured load

Target [BOUND]: six screens, eight actors, eighteen rounds over a 72 h horizon, three policies. At 390 px, navigation and essential actions remain visible without hover. The existing world budget bounds the graph and timeline; full historical transcripts load on demand. Measured [ABSENT]: no product UI, latency, contrast or g4 duration has been tested in this cycle. The g4 target is 60 seconds, not a measured result.

## Drift surfaces and detection

| Two copies | Detection |
|---|---|
| API data and browser cache | Context key `(mode, snapshot_id, run_id, branch_id)` plus per-resource request generation; discard old-context responses and generations older than the last applied response, including status polls on the same execution |
| Graph, feed and cash at different times | One committed-round cursor; absent round data is labelled unloaded, never replaced by latest |
| Selected policy and executable plan | Re-decide on current observed state, review bound terms; server snapshot/hash/mode checks |
| Displayed receipt and changing provider outcome | Read execution status again; preserve as_of; PAID is not irreversible finality; show later incidents |
| Design and future mockups | Mockup input preempts the next design cycle; record UI conflicts and any task/goal changes separately |

## Problems removed and alternatives

[BOUND, system brief §15] No production-money UI, collateral execution or second frontend. [ASSUMED, strikeable until canonical mockups] No realtime socket transport is required: existing job/status reads suffice, and polling must not steal focus. Keep detailed calculations collapsed until asked.

| Shape | Requirement fit / implementation simplicity (design judgement) | Decision |
|---|---|---|
| Extend existing app with six focused views and shared context | High / high | Chosen: matches T17, reuses graph, readable on phone |
| Put all six views on one dashboard | Partial / medium | Rejected: mixes observed and hypothetical state, hides the approval boundary |
| Separate financial frontend | Low / low | Rejected: violates reuse requirement and duplicates navigation/auth |

## Architecture and contract registry

Screen order: observed-state reading → hypothetical simulation and comparison → explicit operator review → receipt inspection. Each screen starts with its answer and source label, followed by one main action; calculations and raw evidence are secondary. The design page's UI flow figure draws the permission split.

| Seam | Producer → consumer | Owner / rule |
|---|---|---|
| C5 through C6 | observed ledger → Overview, Treasury, Lending | API module produces projections; UI formats, never recomputes finance |
| C1/C2 through C6 | coordinator/transcript → Simulation | agent-world supplies committed rounds and evidence ids |
| C6 decisions | decisions module → Decisions | preserve cohort, weight kind, replay/search labels and all-infeasible status |
| C3 | execution approval service → operator review → gateway | explicit authorised POST, visible bound terms, server verification |
| C4 through C6 | reconciliation → Execution | provider state, journal, incident and as_of retained |

## Interfaces

| Screen / unit | Route or source | Contract and action |
|---|---|---|
| Shared shell (T17) | app navigation and C6 context | Mode banner always visible: `Simulated provider` or `Airwallex sandbox`; also distinguish synthetic snapshot, hypothetical branch and replay. Token is explicitly supplied for the tab, kept only in memory, never in storage/URL/log/export. Reload forgets it. Public read works without it. |
| Overview (T17) | `/overview`, GET `/api/v1/overview` | First block: settled cash, next payroll with absolute deadline, min projected cash and reserve floor. `Open simulation` carries the selected demonstration run. Each metric opens API-supplied inputs and calculation. |
| Treasury (T17) | `/treasury`, GET `/api/v1/treasury` | Accounts/buckets, obligation deadlines and reservations. Show S and P as separate measures; `unknown` is not 0. Timeline marks the floor and the shortfall. |
| Lending (T17) | `/lending`, GET `/api/v1/lending` | K_p plus known cash, commitments, pledges, due pool obligations and floor. Show facility principal, fee, observed revenue and outstanding. Reduced authority disables funding and names why. |
| Simulation (T18) | `/simulation`, GET runs, POST fork and interview from system brief §11 | One committed round cursor drives existing graph, feed, cash path and actor inspector. Desktop: graph and feed alongside cash path; phone: controls, cash, feed, graph/inspector. Pause means local playback pause, not server job cancellation. Fork/interview preserve selected round; writes require token, even read-only interview POST. |
| Decisions (T19) | `/decisions`, GET `/api/v1/decisions/{run_id}` | Three policy summaries stack on phone. Show obligations unmet, floor breach, funding cost, cohort and weight kind. No probability inferred from scenario counts. `Review plan` requires current observed plan; all-infeasible opens escalation, not approval. Search results live in a separate labelled section. |
| Execution (T19) | `/execution`, POST approvals, POST executions, GET execution id | Review modal shows current-plan terms, fee context and approval lifetime. `Confirm approval` creates approval only; then show the returned C3 terms, hash and absolute expiry, and require them to match the reviewed plan. `Execute approved plan` is a separate explicit action. Disable while submitting. Receipt rows show C4 provider status, reconciliation and incidents. `Open receipt` is a read-only expansion. |
| Judge path (T26) | prepared demonstration context on public read endpoints | Initial Overview load, then four clicks: Open simulation → Compare policies → View execution → Open receipt. No authorisation or write required. Missing run/receipt fails the check, never seeds a fake browser success. |

Navigation state uses `(run_id, execution_id)` where applicable and never carries a credential in a URL. A selected simulation branch is displayed as hypothetical; the execution screen identifies the distinct observed plan and execution linked to that demonstration. If the backend supplies no mapping, show unavailable rather than guessing from the latest execution. Automatic GET polling may refresh status; no automatic retry of a financial POST after timeout. An execution timeout is resolved by GET using the known approval id (= execution id). Approval POST timeout without a returned id blocks further action for operator resolution; no lookup endpoint is invented.

## Data

The fixture records define required display projections and assertions, not completed API examples. T16/T02 must put the corresponding shapes and examples in C6 before the frontend consumes them. Missing fields are contract gaps, not reasons to hard-code values.

- Money arrives as integer minor units or null with currency; format exactly at the display boundary. The UI never rebuilds S, P, K_p, the objective or a plan hash.
- State per metric: known, unknown, stale, unassessed; request states add loading, partial and error. Last loaded values survive an error only with a not-current label; all actions depending on current authority stay disabled.
- Round time is simulated (`round × 4 h`); provider and observed timestamps are absolute UTC with separately labelled local display. Do not imply a simulated deadline is the provider's wall clock.
- A PAID receipt reads `PAID · reconciled as of <time>`, not permanently final. Setup funding is listed apart. Mode B's advance keeps its sandbox-simulation label.
- Comparison fees summed across scenarios are not an executable debit: the three-scenario USD 2,400.00 total is separate from adv-a's USD 800.00 current-plan fee. Source: decisions fixture and execution approval fixture.
- The system brief §12 tokens set the visual direction. Contrast, text size, keyboard, touch targets and reduced motion are acceptance requirements, not claimed measurements. Adjust a failing colour pair with evidence; never remove status text.

## Fixtures

| File | Tasks | Pins |
|---|---|---|
| `fixtures/money-views.json` | T17 | LF-1/LF-2 projections, source labels, cash vs spendability, floor vs coverage, calculation drill-down |
| `fixtures/data-states.json` | T17, T19 | zero/unknown/stale/partial/unassessed/loading/error, stale-response discard, mode change |
| `fixtures/scrubber.json` | T18 | committed-round synchronisation, running/invalid/replay, fork/interview context, keyboard and phone order |
| `fixtures/decide-execute.json` | T19 | policy result references, fee context, bound review, auth, separate approve/execute, timeout and incident states |
| `fixtures/judge-path.json` | T26 | four explicit clicks, shared demonstration context, read-only prepared receipt, cold-navigation timing, viewport/theme matrix |
| `fixtures/accessibility.json` | T17–T19, T26 | keyboard focus, contrast, 44 px primary controls, non-colour states, responsive tables, reduced motion |

## Failure modes

| Failure | Guard |
|---|---|
| Unknown displayed as zero or stale displayed as current | Explicit per-metric status and timestamp; data-states fixture |
| Branch cash presented as observed funds | Source and branch label on every relevant view/export |
| Fast navigation accepts an old response | Context-key check; late-response case |
| Feed, graph and cash disagree on round | Single committed cursor; no latest-data substitution |
| Pause implies the backend has stopped | Label local playback pause; show last committed round |
| A policy comparison is treated as a probability | Explicit unweighted scenario cohort; no inferred percentages |
| Aggregate fees mistaken for one debit | Separate scenario-set cost and current-plan terms |
| Two POSTs from double click or transport retry | In-flight disabling; never automatic POST retry; server uniqueness still authoritative |
| A rendered green plan bypasses server approval | Review current observed terms, token and C3 checks; branch is not an approval |
| Expired or changed approval stays actionable | Clear review on context change/refusal; server remains authoritative |
| SENT or webhook hint shown as settled | Render C4 reconciliation, not inferred client state |
| PAID later FAILED still shows success | Refresh status and incident; no client reversal |
| Judge path sends a real write | Anonymous path plus assertion of zero writes; seeded receipt only from backend |
| Demo lacks a receipt and silently uses another run's | Explicit run/execution association or fail |
| Screenshot exposes the token | Memory-only token; never reflected into markup, logs or export |
| A phone user cannot reach approval controls | Stacked actions, visible focus, 44 px controls; full viewport/theme browser matrix |

## Done-whens

- accept: npm --prefix frontend run test:unit -- tests/unit/money-views.spec.js — fixture: fixtures/money-views.json
- accept: npm --prefix frontend run test:unit -- tests/unit/money-views.spec.js — fixture: fixtures/data-states.json
- accept: npm --prefix frontend run test:unit -- tests/unit/simulation-view.spec.js — fixture: fixtures/scrubber.json
- accept: npm --prefix frontend run test:unit -- tests/unit/decide-execute.spec.js — fixture: fixtures/decide-execute.json
- accept: bash scripts/judge-path.sh "$LEDGERWORLD_URL" --max-seconds 60 — fixture: fixtures/judge-path.json
- accept: npm --prefix frontend run test:unit -- tests/unit/decide-execute.spec.js — fixture: fixtures/accessibility.json
- accept: bash scripts/judge-path.sh "$LEDGERWORLD_URL" --max-seconds 60 — fixture: fixtures/accessibility.json

The accessibility fixture's authenticated approval keyboard case runs only in T19's mocked component test. T26 tests anonymous read-only accessibility on its timed four-click path and untimed Treasury/Lending visits; those extra visits do not affect g4 elapsed time. T17–T19 retain their bundle accepts including dependency install and frontend build; the commands above pin which test loads which fixture. Offline unit tests use recorded C6 examples; T26 runs the actual deployed read path. Before the product exists none of those accepts has run.

## Design run and limits

ARCHITECT Brief; thresholds v2; one reversible UI module; no reviewer pack. Binding inputs: system brief §11–13, bundle briefs T17–T19/T26, DESIGN.md mockup precedence; verified by reading those files on 2026-10-23. Empty mockups directory and unchanged brief version are absence evidence only; they do not cut the six-screen requirement. Existing financial module fixtures are reused, no alternate financial truth is created. Scope/requirements and existing provenance invariants are unchanged.

The warm-up format replaces separate ground/frame/map files; this document records their content. Design-tier panel, whole-program adjudication, named-reviewer simulation and reviewer-incorporation stages are skipped: reversible internal Brief, no named reviewer or approval round. Product-browser tests, runtime latency and product accessibility measurements are skipped: pre-build code prohibition. Source-design HTML receives its own render check, not a claim that the future UI has passed. Fresh-eyes feasibility/failure-modes/simplicity review ran; its three seam findings were applied: approval fields appear only when the API supplies them, same-context response ordering preserves later incidents, and authenticated accessibility checks are separate from the public judge path. Independent editorial seam review could not run because of a provider capacity rejection; it is not recorded as passed. Design-page publication requires the owner's approval; readiness does not depend on publishing.

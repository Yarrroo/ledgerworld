# LedgerWorld: Full Product Design Handoff

**Version:** 1.0  
**Date:** October 28, 2026  
**Project:** LedgerWorld

This file is the full design specification. The seven mockup images are not in the repository yet; the written panels below are the contract.

## One complete treasury workflow.

Blue faceted logo from the first concept. Spacious ivory composition from the second. Relationship mapping from the third.

Rehearse a cash crisis.
Choose a plan.
Review the evidence.

Six primary tabs, seven full-screen mockups, every supporting panel and action, approval and execution states, responsive behavior, and implementation boundaries.

**Scope:** a complete design handoff for the six LedgerWorld finance routes. This is a static design specification, not a running prototype or a tested provider workflow. Existing upstream MiroFish research screens are outside this product navigation.

**Reading rule:** images communicate composition and styling. Exact numbers, event times, graph connections and permission behavior are specified in the written panels and integrity appendix. Generated charts and maps must be rebuilt from data rather than traced.

## Navigation & end-to-end journey

One product shell. All six tabs remain visible. Each view preserves provider mode, snapshot, run and execution context.

| Tab / route | Question | Panels | Primary destination |
| --- | --- | --- | --- |
| Overview /overview | Are upcoming obligations covered? | Cash strip; baseline cash path; next obligation; exposure preview; scenario entry | Open prepared Simulation |
| Treasury /treasury | Which funds can we use and when? | Account buckets; spendable calculation; obligations and flows; reserve coverage | Rehearse cash shock |
| Lending /lending | What lending capacity is usable? | Capacity bridge; parts; shared exposure map; facility detail and repayments | Compare funding plans |
| Simulation /simulation | How does the shock propagate? | Run context; world map; actor inspector; feed; timeline; cash paths; fork and interview | Compare policies |
| Decisions /decisions | Which protective plan holds? | Shortfall explanation; timing; policy rows; scenario detail; current-plan handoff | Review current plan |
| Execution /execution | What was authorized and reconciled? | Review; bound approval; execution legs; receipt; ledger reconciliation; incidents | Context-specific review or status read |

**Read-only demo:** Overview > Open simulation > Compare policies > View execution > Open receipt. No operator credential is needed to inspect a prepared run.

**Operator:** inspect observed state > rehearse/fork > compare > create approval on the observed snapshot > inspect bound terms > execute explicitly > read receipt and reconciliation. A hypothetical branch never becomes spending authority.

## Shared visual system & components

| Element | Design contract |
| --- | --- |
| Brand | Preserve the blue faceted symbol and LedgerWorld wordmark from concept 1. The companion PDF text header is a document label, not a replacement logo. Extract/redraw an exact vector asset before implementation; generated images are visual references. |
| Surface & color | Ivory #FAF8F3; ink #17251E; primary forest #174A38; logo blue #2469E8; selected sage #E9EEE7; dividers #D8D7CD; warning terracotta #A8432E. Verify actual rendered contrast before release. |
| Typography | Source Serif 4 for expressive page headings; Inter for navigation, body, tables and tabular financial figures. H1 36/44 desktop, 28/34 mobile; section 22/28; body 16/24; labels 13/18. The companion PDF uses local substitute fonts. |
| Geometry | Desktop sidebar 208px; main padding 32px; 24px section gaps; 16px internal gaps; 8px rhythm. Buttons 44px minimum; radius 6px. Use whitespace and rules before borders. Avoid nested cards. |
| Shared shell | Logo; six labeled navigation items; active highlight; company context; breadcrumb; mode/model source; as-of time; snapshot identity. Run context appears on Simulation, Decisions and Execution. No token in shell URLs. |
| Components | Metric with status and calculation disclosure; currency amount; cash chart with text data; graph node and edge; actor list fallback; evidence drawer; grouped policy rows; keyboard scrubber; modal; leg status row; receipt disclosure; incident banner; empty/error panel. |
| Interaction | One primary action per stage. Disabled actions include a reason. Disclosure retains route and focus. Polling never steals focus. Visible keyboard focus, text status plus icon, reduced motion, touch targets >=44px. |
| Credentials | Use Operator access, with a password-style token field, not an account-password claim. Credential lives in tab memory only; no local storage, URL, analytics or exports. Forget access clears it. |

## Visual mockup: Overview

Observed baseline; scenario entry is visibly hypothetical. The exact hour positions are defined in the integrity appendix.

*(LedgerWorld Overview mockup: image not in the repository yet; build from the written panels)*

## Visual mockup: Treasury

Cash and spendability are separate. Obligations retain reservation and deadline context.

*(LedgerWorld Treasury mockup: image not in the repository yet; build from the written panels)*

## Visual mockup: Lending

Capacity and shared exposure. Use the canonical edge directions in the integrity appendix.

*(LedgerWorld Lending mockup: image not in the repository yet; build from the written panels)*

## Visual mockup: Simulation

One selected committed round drives map, actor inspector, feed and cash cursor. The graph is hypothetical.

*(LedgerWorld Simulation mockup: image not in the repository yet; build from the written panels)*

## Visual mockup: Decisions

The delayed-receipt scenario preserves payroll but breaches the reserve without protection.

*(LedgerWorld Decisions mockup: image not in the repository yet; build from the written panels)*

## Visual mockup: Execution & receipts

Illustrative fake-provider receipt. Review existing terms read-only; do not offer duplicate execution.

*(LedgerWorld Execution & receipts mockup: image not in the repository yet; build from the written panels)*

## Visual mockup: Approval sequence

Two sequential states shown together for documentation. In the product they replace one another in one focused dialog.

*(LedgerWorld Approval sequence mockup: image not in the repository yet; build from the written panels)*

## Overview: every panel & action

Panel identifiers are the handoff contract. All secondary surfaces inherit the same source context and visual system.

### O1 / Context

**Content and data:** Observed snapshot, currency, synthetic company, provider/model and as-of. Use a complete snapshot identity, not only LF-1.

**Interaction and alternate state:** Refresh reads context again. Loading never renders a fabricated zero.

### O2 / Cash strip

**Content and data:** Settled $70k; spendable $20k; next payroll $50k due h40; reserve headroom $10k. Each figure includes currency, source and freshness.

**Interaction and alternate state:** Select a metric to expand API-supplied calculation inputs. Cash and spendable link to Treasury; capacity if shown links to Lending.

### O3 / Cash outlook

**Content and data:** Baseline P: h0 $70k; h12 $90k; h40 $40k; h48 $55k; h72 $55k. Floor $30k. Minimum marker green, not red.

**Interaction and alternate state:** Hover/focus point shows simulated offset, absolute snapshot-relative time, amount and event. View data opens accessible table.

### O4 / Next obligation

**Content and data:** Payroll amount, exact simulated deadline, reservation, state and funding account. No obligation uses a neutral empty state.

**Interaction and alternate state:** Open Treasury deep-links to payroll row and preserves snapshot context.

### O5 / Exposure preview

**Content and data:** Small subset of the canonical world with text relationships. Do not imply a public feed transfers funds.

**Interaction and alternate state:** Explore world opens Simulation at the prepared run. If unavailable, show No demonstration run prepared.

### O6 / Scenario entry

**Content and data:** Clearly hypothetical teaser: What if the $20k receivable arrives late? No change to observed metrics.

**Interaction and alternate state:** Preview scenario opens read-only scenario description; Open simulation follows an existing run. Starting a new run is operator-only and a backend extension if no endpoint exists.

## Treasury: every panel & action

Panel identifiers are the handoff contract. All secondary surfaces inherit the same source context and visual system.

### T1 / Account selector

**Content and data:** Default operating account; show all returned treasury accounts by currency and freshness. Never aggregate mixed currencies into a dollar total.

**Interaction and alternate state:** Select account updates bucket table, calculation and cash path together. Empty accounts has a descriptive empty state. As built to mockup 02 (MATCH.md): the selector shows only when the API serves more than one account.

### T2 / Cash buckets

**Content and data:** Settled $70k, reserved $50k, pledged $0, pending out $0. Pending inflows are expected, not settled.

**Interaction and alternate state:** Bucket disclosure lists ledger/API inputs, account and source timestamp. Unknown has no numeric value; stale retains last value and timestamp.

### T3 / Spendability

**Content and data:** S(now) = $70k - $50k = $20k in the baseline. Full calculation includes pledges and pending flows when supplied.

**Interaction and alternate state:** View calculation expands inline; browser formats API results rather than reconstructing authority.

### T4 / Obligations & arrivals

**Content and data:** Receivable +$20k h12; payroll -$50k h40 reserved; venue arrival +$15k h48. Include identifiers, account and status.

**Interaction and alternate state:** Select row opens flow/obligation details: amount, deadline, reservation, source and current state. Not a payment action.

### T5 / Reserve coverage

**Content and data:** Minimum P $40k h40; floor $30k; headroom $10k; Floor held. Chart and text table share the same API points.

**Interaction and alternate state:** Focus point reveals calculation at that instant. Separate projection from spendable-now. As built to mockup 02: each chart point is a tooltip control naming its hour, P and what moves it, in place of a separate point table; the lowest point's calculation sits in View calculation.

### T6 / Scenario handoff

**Content and data:** Rehearse a cash shock carries account and snapshot to Simulation.

**Interaction and alternate state:** Use existing prepared run when available. Do not invent a live import, account edit or payment feature. Missing run names the prerequisite.

## Lending: every panel & action

Panel identifiers are the handoff contract. All secondary surfaces inherit the same source context and visual system.

### L1 / Pool context

**Content and data:** Harbourline pool, snapshot LF-2, currency, known balance authority and source time.

**Interaction and alternate state:** Refresh updates capacity and its excluded accounts in one coherent context.

### L2 / Capacity bridge

**Content and data:** Known settled $60k - committed undrawn $10k - pledged $0 - obligations $0 - floor $8k = $42k.

**Interaction and alternate state:** Expand calculation displays all parts, not only nonzero terms. View account evidence lists operating $45k and venue $15k.

### L3 / Exposure map

**Content and data:** Pool -> Treasury via adv-a; Pool -> Borrower B via line-b; Pool -> Exchange as a $15k exposure. Treasury also depends on a $15k venue withdrawal.

**Interaction and alternate state:** Select node or edge opens account/contract detail. Arrows and exposure labels follow the integrity appendix. As built to mockup 03: that detail is each node's and link's tooltip; one node per party and one link per pair of parties.

### L4 / Freeze scenario

**Content and data:** If venue balance is unknown, capacity becomes $27k; balance is Unknown, not zero. Label hypothetical until observed.

**Interaction and alternate state:** Rehearse venue freeze opens its prepared scenario. Reduced observed authority disables funding and explains excluded balances.

### L5 / Facility detail

**Content and data:** adv-a principal $10k; fee 8% = $800; total owed $10,800; repayment 15% of observed revenue. Terms are not proof of disbursement.

**Interaction and alternate state:** Open facility shows parties, status, outstanding and revenue evidence from API. View repayments shows observed receipts and actual applied amounts, not a forecast. As built to mockup 03: the facility terms table (no revenue-share column: the API serves no such field) and View repayment schedule, outstanding and observed revenue per facility.

### L6 / Plan handoff

**Content and data:** Compare funding plans opens Decisions for the same prepared run.

**Interaction and alternate state:** Disable on stale/unknown authority, missing run or unresolved context. No standalone direct disbursement control.

## Simulation: every panel & action

Panel identifiers are the handoff contract. All secondary surfaces inherit the same source context and visual system.

### S1 / Run & scenario context

**Content and data:** Run, branch, checkpoint, cohort, seed/provenance and mode. Six families: delayed receipt, FX gap, stablecoin depeg, redemption spike, borrower silence, confidence rumour.

**Interaction and alternate state:** Run/branch selectors use existing records. Scenario settings is a read-only drawer initially; custom parameters/new-run creation require explicit API support.

### S2 / World map

**Content and data:** Eight actors; typed financial and information edges; selected actor highlighted; amber causal path; optional expand/reset view.

**Interaction and alternate state:** Select node synchronizes inspector and feed highlight. Select edge opens relation evidence. Zoom/pan preserves round. Keyboard actor list provides equivalent access.

### S3 / Actor inspector

**Content and data:** Name, role, objective, scoped observations, accepted/rejected actions and evidence IDs at selected round. No unrelated private observations.

**Interaction and alternate state:** Interview submits question with run/branch/round/actor and operator token. Loading/error/result stay in inspector. Read-only answer changes no ledger state.

### S4 / Event & action feed

**Content and data:** Committed public posts, proposed intents, clearing outcomes, rejection reasons and source IDs. Distinguish intention from accepted ledger change.

**Interaction and alternate state:** Event click opens evidence detail and highlights actor. Unloaded round shows Round not loaded rather than latest events.

### S5 / Scrubber & cash

**Content and data:** One committed-round cursor; round 5 corresponds to 20 simulated hours. Cash paths share the cursor. Pause is local playback only.

**Interaction and alternate state:** Arrow keys step loaded rounds; Home/End choose boundaries. Dragging never creates a financial action. Export chosen round preserves IDs and source labels.

### S6 / Fork & comparison

**Content and data:** Fork creates isolated fresh branches for policies at selected committed checkpoint. It creates no approval.

**Interaction and alternate state:** Operator-only confirmation names checkpoint and policies. Pending keeps selection; done reveals branch paths; failure explains retry. Compare policies opens Decisions when linked results exist.

## Decisions: every panel & action

Panel identifiers are the handoff contract. All secondary surfaces inherit the same source context and visual system.

### D1 / Cohort context

**Content and data:** Run, checkpoint, scenario family, weight kind, replay/search labels and same-shock statement.

**Interaction and alternate state:** Open simulation returns to exact branch/round. Cohort counts are never converted into probabilities.

### D2 / Gap explanation

**Content and data:** Without protection: payroll paid, minimum cash $20k at h40, floor $30k, shortfall $10k.

**Interaction and alternate state:** View timing lists h0 cash, h40 payroll, h48 venue arrival, h252 delayed receipt. Show no claim of missed payroll in this fixture.

### D3 / Policy list

**Content and data:** No action, Fixed reserve, Integrated. Each shows obligations unmet, floor-breaching branches, largest short and scenario-set funding cost.

**Interaction and alternate state:** Selected policy highlights and updates explanation without approving anything. The backend determines feasibility/ranking; no arbitrary winning selection.

### D4 / Scenario details

**Content and data:** Per-branch outcomes, floor minima, costs, provenance and replay flag; accessible matrix/table.

**Interaction and alternate state:** Compare scenario details opens drawer with one row per scenario/policy. Distinguish aggregate scenario fee from current-plan fee.

### D5 / Review handoff

**Content and data:** Review current plan goes to Execution review for selected policy on current observed state.

**Interaction and alternate state:** Loading comparison has no selection. All infeasible shows earliest unmet obligation, binding constraint and escalation contact; approval disabled.

### D6 / Reverse stress

**Content and data:** If backend supplies reverse-stress results, display separate Search results section and breaking path, not a selectable plan.

**Interaction and alternate state:** Expand evidence is read-only. Reverse stress remains outside main demo and has no execution CTA.

## Execution: every panel & action

Panel identifiers are the handoff contract. All secondary surfaces inherit the same source context and visual system.

### E1 / Execution context

**Content and data:** Run -> execution association; observed snapshot; mode; status read time. No association means unavailable, never latest unrelated receipt.

**Interaction and alternate state:** Review terms for an existing execution is read-only. New approval is only available for an eligible current plan.

### E2 / Approval review

**Content and data:** Policy/cohort, fee context, default 15-minute lifetime and operator access. Exact legs are not previewed by existing API.

**Interaction and alternate state:** Create approval calls server once; response replaces review with bound terms. Close preserves an existing approval; no automatic execution.

### E3 / Bound terms

**Content and data:** Entity, account, observed snapshot, provider mode, complete plan hash, absolute expiry and each leg source, counterparty, amount, dependencies and facility.

**Interaction and alternate state:** Copy ID/hash announces success. Execute approved plan is a separate explicit action. Expired/mismatched/stale plans disable execution and explain why.

### E4 / Leg tracker

**Content and data:** Ready/submitted/provider-confirmed/reconciled with raw provider status, amount/currency, source and dependencies. Settled only after confirmed read and posted journal.

**Interaction and alternate state:** Expand leg opens receipt. Poll GET for status, retain last-known timestamp on read errors. Already submitted/executed cannot execute again.

### E5 / Receipt & ledger

**Content and data:** Provider/request IDs, raw status, amount/currency, journal, observed time and provider mode. Fake receipts labeled fake; sandbox Mode B deposit labeled simulation.

**Interaction and alternate state:** Open receipt is read-only. Ledger comparison is shown only when backend supplies corresponding amounts; no invented reconciliation figures.

### E6 / Incidents

**Content and data:** Unknown outcome, amount mismatch, later failure, missing journal or stale status shows incident with evidence.

**Interaction and alternate state:** Read status remains available. No resend/reversal control is invented. No execution ID returned after approval timeout requires operator resolution.

## Approval & execution state machine

The flow board shows stages together for explanation. The actual product shows one active stage at a time.

| State | Visible panel / primary action | Transition & guard |
| --- | --- | --- |
| Read-only visitor | Public plan and linked receipt. Operator access prompt only when attempting a write. | No role inference from a green plan. Never expose the credential in rendered content. |
| Review eligible policy | Policy and fee context; operator access field; Create approval. | POST approval once. Buttons disabled while pending. API has no exact-leg preview. |
| Approval submitting | Creating approval; retained context; close disabled during uncertain request. | Success returns approval identity and bound terms. Validation error returns actionable field/general error. |
| Approval unknown | Approval outcome unknown. Further approval actions blocked. | Without returned ID, do not invent lookup or automatically resubmit. Operator resolves. |
| Approved / not executed | Exact bound terms, full hash, absolute expiry, Execute approved plan. | Server rechecks authority; UI checks context, expiry and submitted state. Approval is not a transfer. |
| Expired / invalidated | Approval expired or terms changed; Execute disabled. | Refresh current observed state and review a newly eligible plan; do not silently refresh the approval. |
| Execution submitting / unknown | One in-flight execution; show known approval/execution ID and Reading status. | Poll GET using known ID; never automatically resend a timed-out financial POST. |
| Reconciled | Read-only legs, receipts, journals and as-of. No execute again action. | Later GET can reveal incident. PAID is not a promise of permanent finality. |
| Incident | Prominent explanation, affected leg, IDs, observed status and last-read time. | Preserve evidence; provide read status, not guessed success or an invented recovery payment. |

## Loading, empty & failure states

Every state preserves labels and context. A dash never silently stands for zero.

| State | Visual treatment | Actions / application |
| --- | --- | --- |
| Loading | Skeleton geometry in place of amounts; Loading text announced politely. | Navigation works. Dependent actions disabled with reason. Avoid repeatedly announcing status polls. |
| Empty / no prepared run | Inline explanation with missing prerequisite and no fabricated chart. | All six tabs can explain absence. No auto-seeding run or success receipt in browser. |
| Known zero | Render currency and $0 with Known status. | A real observed zero remains distinct from unavailable and unassessed. |
| Unknown | Unknown text, icon and source; no numeric value. | Exclude from known capacity. Funding/execution disabled when authority depends on it. |
| Stale | Last observed value, Stale label, as-of time and warning band. | Refresh evidence. Do not treat cached data as current authority. |
| Partial | Show known sections and list missing/stale accounts. | Computed metrics carry their own freshness. A fully known unrelated section remains readable. |
| Unassessed | Not assessed text; no green or red reserve verdict. | No inferred headroom, floor result or feasibility. |
| Read error | Could not refresh, plus last-loaded not-current data when present. | Retry GET. Pending financial operations retain their uncertainty and are never retried as writes. |
| Permission required | Inline Operator access required near fork/interview/approval, not a login wall for public reads. | Password-style token field with Forget access. No token retained on reload. |
| Pending / replay / failed run | Running comparison; Replay; or Failed, each with explicit provenance. | Pending has no selected policy. Replay is labeled across feed, paths and export. Failed run retains evidence. |
| All infeasible | No feasible plan, earliest unmet obligation, binding constraint and supplied escalation contact. | Inspect results or return to simulation. No approve or execute action. |
| Submitting / unknown / incident | Single-flight progress, uncertainty message or incident region with affected IDs. | See approval state machine; disable duplicate writes and keep GET status reading available. |

## Responsive layout & accessibility

Desktop visuals define the system. These rules specify tablet and phone reflow; dedicated mobile image mockups have not been rendered.

| Surface | Desktop >=1200px | Tablet 768-1199px | Phone 390-767px |
| --- | --- | --- | --- |
| Shell | 208px labeled sidebar; 32px content gutters. | 72px icon rail with accessible names; 24px gutters. | 48px header, menu drawer with all six labels; 16px gutters. Mode and source remain visible. |
| Overview | Cash strip, 60/40 cash plot and obligation/exposure. | Cash strip 2x2; next obligation below chart. | Metrics 2x2, next obligation, chart/data table, exposure preview, scenario entry. |
| Treasury / Lending | Main data left, calculation/coverage inspector right. | Inspector below primary data, account lists intact. | Financial answer first, calculation disclosure next, obligations/facilities as labeled stacked rows. |
| Simulation | Map left; actor/feed inspector right; scrubber/cash below. | Cash/controls first; map and inspector can stack. | Round control, cash answer, event feed, actor list, map. Tap actor opens full-height sheet; zoom not required to read evidence. |
| Decisions | Gap and policy comparison 50/50. | Gap compressed above full policy list. | Gap summary, timing disclosure, three grouped policy rows, review CTA. No horizontal carousel. |
| Execution | Legs left; bound terms/incidents right. | Terms summary above legs; details in sheet. | Current status, approval summary, legs/receipts, incidents. Review is full-height dialog with fixed action footer. |
| Tables & charts | Sortable only where endpoint/order supports it; numeric columns right-aligned. | Scroll region for truly tabular comparisons. | Never hide amount/status/deadline. Offer equivalent text data and row details; no miniature unreadable chart labels. |
| Inputs & focus | Visible focus ring; labeled icon buttons; disclosure controls. | All touch targets >=44px. | No hover-only information; no action hidden under keyboard or sticky footer. Dialog traps focus and returns it to opener. |

**Keyboard:** six-tab navigation uses links; policy choices use radio-group semantics where selectable; graph actors have a parallel button list; scrubber supports arrows/Home/End. Dialog Escape closes only when safe, and does not imply canceling a server operation. Status always includes words and icons. Honor reduced motion; pause local playback without implying worker cancellation.

## Exact data & relationship integrity

Canonical appendix overrides incidental illustration errors in generated maps, cash plots, status colors and sample labels.

| Event time | Baseline cash P | Delayed receipt / no action | Delayed receipt / integrated |
| --- | --- | --- | --- |
| h0 | $70,000 | $70,000 | $70,000 |
| h12 | $90,000 | $70,000 | $70,000 |
| h16 | $90,000 | $70,000 | $80,000 (advance +$10,000) |
| h40 / payroll -$50,000 | $40,000 | $20,000 | $30,000 |
| h48 / venue +$15,000 | $55,000 | $35,000 | $45,000 |
| h72 | $55,000 | $35,000 | $45,000 |
| Minimum / floor result | $40,000 / held | $20,000 / breached by $10,000 | $30,000 / held |

**Timing:** delayed receivable is h12 + 240h = h252. The reserve floor is $30k; equality holds. The $800 fee is a facility obligation, not an immediate third execution leg. Round n corresponds to 4n simulated hours; round 5 is h20. Plot these exact positions rather than copying generated axes.

**Canonical map:** Lender pool -> Treasury (adv-a); Lender pool -> Borrower B (line-b); Lender pool -> Borrower C (precautionary advance). Treasury -> Payroll bureau (payroll). Treasury and Lender pool each have exposure to Exchange venue. Market-maker provides price/quote information to Treasury. Public feed -> Borrower C is information; Borrower C -> Lender pool is a request. A feed edge is never a cash flow. Borrower B is not a lender to Treasury.

**Illustration corrections:** healthy baseline minimum is green; charts use h40, not a visually shifted h24/h32; Lending maps must connect line-b to Borrower B, not Treasury; Simulation must not show a Treasury-Borrower B credit relationship. Approval expiry is absolute UTC plus separately labeled local time; do not copy an unanchored countdown or simulated h16/h40 as provider wall-clock scheduling.

## API fit, proposed UI & delivery checks

The visual design retains the repository permission boundary. Some richer panels need additional read projections.

| Capability | Implementation requirement |
| --- | --- |
| Existing core routes | Six finance routes and public GET projections exist. Preserve snapshot, run, branch, execution and as-of identity. Existing graph/feed/cash functionality is reused conceptually with the new shell. |
| Approval terms | Current API binds exact legs after approval creation. Design follows that behavior. An exact pre-approval plan preview would require a new read endpoint; not silently assumed. |
| Scenario controls | Family selection and settings can initially inspect prepared scenarios. Custom editor, start-run, seed overrides or batch authoring need backend support. A dropdown is not a claim the endpoint exists. |
| Panel projections | Rich edge detail, repayment schedule, ledger/provider amount comparison and complete evidence drawers need API-supplied fields. If unavailable, show source evidence or unavailable; never reconstruct finance or fake reconciliation. |
| Provider variants | Fake mode uses fake receipt labels. Sandbox has Mode A connected-account transfers and Mode B advance deposit simulation/ledger-only repayment labels. Production-money operation is outside this repo and this design. |
| No invented screens | No additional Home, Reports, Receivables, Payables or Settings route has been added from the earlier concept image. Company and scenario details are panels within the six-tab product. |
| Quality checks before build handoff | Rebuild charts from canonical point table; typed graph edges; one selected-round cursor; data source labels; full hash/expiry and terms; separate approve/execute; correct no-run and all-infeasible states. |
| Quality checks before release | Verify responsive screenshots at 1440, 834 and 390px; keyboard journey; contrast; focus; 44px targets; reduced motion; stale/unknown/zero; no duplicate POST; exact run/receipt association. None of these runtime checks is claimed passed by static mockups. |

**Sources reviewed:** github.com/Yarrroo/ledgerworld: README.md; frontend/src/views/{Overview,Treasury,Lending,Simulation,Decisions,Execution}.vue; fixtures/README.md; docs/architecture.md; docs/evidence/README.md; prp/2026-10-20-ledgerworld/design/modules/ui/HANDOFF.md. Static source inspection; no claim of current deployment availability.

## Source links

- [README.md](https://github.com/Yarrroo/ledgerworld/blob/main/README.md)
- [frontend/src/views/Overview.vue](https://github.com/Yarrroo/ledgerworld/blob/main/frontend/src/views/Overview.vue)
- [frontend/src/views/Treasury.vue](https://github.com/Yarrroo/ledgerworld/blob/main/frontend/src/views/Treasury.vue)
- [frontend/src/views/Lending.vue](https://github.com/Yarrroo/ledgerworld/blob/main/frontend/src/views/Lending.vue)
- [frontend/src/views/Simulation.vue](https://github.com/Yarrroo/ledgerworld/blob/main/frontend/src/views/Simulation.vue)
- [frontend/src/views/Decisions.vue](https://github.com/Yarrroo/ledgerworld/blob/main/frontend/src/views/Decisions.vue)
- [frontend/src/views/Execution.vue](https://github.com/Yarrroo/ledgerworld/blob/main/frontend/src/views/Execution.vue)
- [fixtures/README.md](https://github.com/Yarrroo/ledgerworld/blob/main/fixtures/README.md)
- [docs/architecture.md](https://github.com/Yarrroo/ledgerworld/blob/main/docs/architecture.md)
- [docs/evidence/README.md](https://github.com/Yarrroo/ledgerworld/blob/main/docs/evidence/README.md)
- [prp/2026-10-20-ledgerworld/design/modules/ui/HANDOFF.md](https://github.com/Yarrroo/ledgerworld/blob/main/prp/2026-10-20-ledgerworld/design/modules/ui/HANDOFF.md)

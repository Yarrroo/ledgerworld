# Design match: the live screens against the seven mockups

The mockups in `mockups/` are the design contract for layout, hierarchy, spacing, type and component shapes.
`sidebyside/` shows each mockup (left) next to the live screen at 1487 px (right) on 29.10. Numbers, statuses and
edges still come from the API and HANDOFF.md's appendix, never from the image (the healthy lowest point is green).
If the API lacks a field a mockup element needs, leave that element out and say so in the close-out; never invent it.

## Shared (every screen)

1. **Page hero**, as in every mockup: a one-line serif headline (Source Serif, ~52 px), a one-line grey subtitle,
   and ONE primary button top right. Headlines: Overview "Know your cash. Rehearse the risk." · Treasury "Every
   dollar, accounted for." · Lending "Capacity you can rely on." · Simulation "See the crisis before it spreads." ·
   Decisions "Protect payroll. Preserve your reserve." · Execution "From approved plan to proof." · Approval dialog
   "Review before you execute." The data-built lead sentence (COPY.md) becomes the subtitle or the hero tooltip.
2. **Delete from the visible UI**: the panel-index tab row under the title, the chip rows (Simulated bank
   connection / Scripted agents / What-if repeated per panel), every "How we know" link, "Check again", explanatory
   subtext lines and captions the mockup does not have, run/snapshot/approval/evidence ids, hashes, model talk,
   "Known as of …" lines under figures. That detail moves into tooltips (item 4) or one fold per page.
3. **Header and sidebar** exactly as the mockups: breadcrumb "LedgerWorld / Page" left; "Simulated provider ·
   Scripted agents" and the date right; a second line "Snapshot · USD · Synthetic data"; no Refresh button in the
   header (refresh silently on focus or keep it inside a tooltip menu). Sidebar label "Simulation" (not "Live
   simulation"), the mockup's icons, and the company block "Northwind Parts / Synthetic company" at the bottom.
4. **Tooltips** on every metric, chart point, status dot/chip and action: open on hover, on keyboard focus and on
   tap (phones), close on Escape/blur/second tap, never cover the value they explain. They carry what was subtext:
   source, as-of time, formula, ids.
5. **Figures** in the mockup style: "$70,000" (whole dollars when cents are zero), large serif numbers, small
   label above, separated by thin rules; no boxes around every metric.
6. **Tables** like the mockups: light header row, status as a coloured dot + one word, right-aligned amounts,
   timing as h12/h40 or "in 40h".
7. **Next action obvious**: the hero button is the next step of the journey (Open simulation → Rehearse a cash
   shock → Compare funding plans → Compare policies → Review current plan → Review plan). Empty and error states
   in plain words with the one action that fixes them.
8. **Word budget**: visible words per screen at 1487 px no more than the mockup's plus 15 %.

## Per screen (mockup → what the live screen must change)

- **01 Overview**: hero + "Open simulation"; 4-figure strip (Settled cash, Spendable now, Payroll due · in 40h,
  Reserve headroom); left the 72-hour cash outlook chart with $ axis, point annotations (h0 starting cash, h12
  receivable +$20,000, lowest at h40, h48 venue inflow) and legend; right "Next obligation" card (icon, amount, due
  in, reserved, Open Treasury →) and "World exposure" as a small icon node graph (5 nodes) with "Explore world →";
  bottom full-width HYPOTHETICAL banner "What if your $20,000 receivable arrives late?" + "Preview scenario".
- **02 Treasury**: hero + "Rehearse a cash shock"; 3-figure strip (Settled, Reserved for payroll, Spendable now);
  left "Operating account" bucket table (Cash bucket · Amount · Status dot) and "Obligations & arrivals" table
  (Event with plain name, Timing h12/h40/h48, Amount ±, State dot) + "View calculation" fold; right "Spendable is
  not settled" calculation (Settled − reserved = spendable), "Reserve coverage" list (minimum at h40, floor,
  headroom, status dot "Floor held"), "72-hour projected cash path" chart. No account radio when there is one account.
- **03 Lending**: hero + "Compare funding plans"; big "$42,000" available pool capacity; "Capacity bridge" as
  inline arithmetic ($60,000 − $10,000 − $8,000 = $42,000, red for minus); "Shared exposure map" node diagram
  (pool, Borrower B, Treasury, Exchange venue with labelled arrows); right "Capacity breakdown" table and "Venue
  freeze scenario" amber HYPOTHETICAL card + "Rehearse venue freeze"; bottom "Facility terms" table (facility, from,
  to, principal, fee, total owed, revenue share) + "View repayment schedule".
- **04 Simulation**: hero + "Compare policies"; a selector row (Scenario, Branch, Cohort, Scenario settings);
  left "Market relationships at round N" diagram with icon nodes, labelled edges and the amber causal path; right
  selected-actor panel ("What changed" timeline h12/h16/h20, "Ask this actor" input + Interview, operator access
  note); bottom a round scrubber row (play, "Round 5 of 18", "20h simulated", shock marker, "Fork checkpoint") and
  "Treasury cash path (72-hour outlook)" with the three policies and a red shortfall callout.
- **05 Decisions**: hero + 3-step stepper (Rehearse · Compare · Review); left "The gap we need to close" big red
  "$10,000" + one line, "Cash waterfall (before plan)" bar chart (starting cash, payroll, remaining vs floor), "Key
  timing in this scenario" table (Now / In 40h / In 252h); right "Three ways forward" radio rows (name, one-line
  description, Reserve outcome · Funding cost · Obligations unmet), "Minimum projected cash $30,000 = reserve floor",
  primary "Review current plan →", links "Compare scenario details" and "Open simulation".
- **06 Execution**: hero + "Review plan"; green banner "Reconciled as of … · Illustrative receipt"; horizontal
  4-step tracker (Approved, Submitted, Provider confirmed, Reconciled) with check icons; left "Execution legs" rows
  (number, name, amount, status pill, expand chevron → request/provider/journal ids with copy buttons, Open receipt)
  and "Ledger reconciliation" (provider amount, journal amount, difference) only if the API supplies both amounts;
  right "Bound approval" terms table + "View all terms →", "Incidents" with check icon and plain sentence.
- **07 Approval dialog**: two columns, "1 Create approval" (policy, scenario-set, facility fee, lifetime, amber
  note, Operator access password field with show/hide, Create approval, "This does not execute funds.") and "2
  Check bound terms" (status chip, terms table, bound legs rows, Execute approved plan, Close); one stage active at
  a time on phone.

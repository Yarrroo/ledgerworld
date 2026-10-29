# LedgerWorld copy guide (copy pass)

The reader is the person who owns a company's cash: a finance lead or founder, not an engineer. Every screen answers
their question first, in their words, with real numbers from the API; the agent and ledger mechanics stay available
but folded behind **How we know**.

## Rules

1. **Lead with one sentence the finance lead cares about**, built from API fields (never hard-coded): what is covered,
   until when, by how much. Then the supporting numbers. Then everything else.
2. **Plain words.** Cash, payroll, bills, runway, safety minimum, lender, plan, what-if. No snapshot, branch, cohort,
   checkpoint, intent, provenance, K_p, P, S in visible headings or lead text.
3. **Fold the mechanics.** Snapshot and run ids, round numbers, model and provider mode, evidence ids, formulas and raw
   statuses move into a **How we know** disclosure on each panel (closed by default, keyboard reachable). Nothing is
   deleted: the same facts, one click down.
4. **Keep honesty visible in plain words.** "Simulated bank connection" (fake provider), "Sandbox bank" (sandbox),
   "What-if" (hypothetical branch), "Scripted agents" (scripted model) stay visible as small labels, never hidden.
5. **Every number traceable.** A number in a sentence is the same API value shown in its panel; How we know names its
   source. Unknown stays "unknown", never 0; stale says "last seen <time>".
6. **Short.** Lead sentence <= 25 words; panel intros <= 2 lines; buttons are verbs ("See what happens if…",
   "Compare plans", "Review the plan", "See the receipts").
7. Keep every data-test hook; e2e/judge-path.spec.ts, e2e/walkthrough.spec.ts and checks/recording_ready.py must pass.

## Glossary (visible word -> what it means; the technical term goes into How we know)

| Say | Instead of |
|---|---|
| Cash in the bank | settled cash |
| Free to spend now | spendable now (S) |
| Set aside for payroll | reserved |
| Lowest point ahead | minimum projected cash (P) |
| Safety minimum | reserve floor |
| Room above your minimum | headroom |
| What the lender can still lend | lender capacity K_p |
| What-if | hypothetical branch / scenario |
| Plan | policy |
| Try the plans on this shock | fork at checkpoint |
| Do nothing / Keep a fixed buffer / Borrow just enough | No action / Fixed reserve / Integrated |
| Approve / Send | create approval / execute |
| Receipt | provider receipt + journal |
| Checked against your books | reconciled |

## Lead sentences (templates; fill from the API)

- **Overview:** "You're covered until {next obligation} on {date}: {free now} free now, and your lowest point
  ahead is {lowest} — {room} above your {minimum} safety minimum." If the floor breaks: "Heads up: on {date} you
  dip {short} below your {minimum} safety minimum."
- **Treasury:** "{cash in bank} in the bank; {set aside} is set aside for {obligation}, so {free now} is free to spend."
- **Lending:** "Your lender can still lend you up to {capacity}; here is how that number is worked out."
- **Simulation:** "What if your {amount} {receivable} arrives {delay} late? Watch how it ripples through your
  partners, round by round." (what-if label visible)
- **Decisions:** "Doing nothing leaves you {short} under your safety minimum on {date}. Borrowing {advance} keeps you
  covered for a {fee} fee."
- **Execution:** "The plan you approved moved {advance in} in and paid {payroll} payroll — both checked against your
  books." Before approval: "Nothing moves until you approve and then send."

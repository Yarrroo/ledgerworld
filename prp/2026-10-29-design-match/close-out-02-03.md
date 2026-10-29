# Design match 2 and 3 (Treasury, Lending) — close-out

**What changed.** `/treasury` is built to `mockups/02-Treasury.png`: hero with Rehearse a cash shock; three
figures (Settled cash, Reserved for payroll, Spendable now); the account's bucket table and the obligations
and arrivals table (plain name, h-timing, signed amount, a state dot and one word) with one View calculation
fold; beside them Spendable is not settled, Reserve coverage and the 72-hour projected cash path, drawn by the
shared `CashOutlook` (new `horizon` prop: Treasury's points stop at the last move, the line runs on flat). The
account selector shows only with several accounts; the point table and `CashChart.vue` are gone, each chart
point is a tooltip control. `/lending` is built to `mockups/03-Lending.png`: the big available capacity, the
bridge as arithmetic, the shared exposure map (one node per party, one link per pair), the capacity
breakdown, the amber hypothetical venue freeze card, the facility terms with View repayment schedule.
`HANDOFF.md` T1, T5, L3 and L5 now say how the mockups changed each panel (the brief was fixed, not the code).

**Left out, by MATCH.md's rule (the API has no field):** Lending's frozen-venue capacity figure ("falls to
$27,000"; the card says only known funds count), the facilities' revenue share column, and the mockup's
"Committed $10,000" label on the pool → Treasury link (it reads "Can lend you"). Treasury's chart keeps its
annotations to the tooltips at 1487 px: the side column is narrower than the chart's annotation width (520 px),
and the annotated form collided there.

## Verification (final tree, 4a62f47 + this doc)

- `bash scripts/ux-check.sh` green for `match-treasury`, `match-lending`, `match-overview`, `match-shared`,
  `treasury`, `lending`, `copy-1`, `copy-3`, `states`, `readable-labels`, `shell` (1440/1487, 834, 390 px),
  each followed by a green judge path (slowest 6.1 s of 60). Word budget held by each match spec at every
  width; Lending 183/178/187 words (budget 192).
- `vitest run`: 307 passed. `npm --prefix frontend run build`, `ruff check checks e2e`, `checks/attribution.py`,
  `checks/no_secrets.py`, `checks/tests/test_word_budget.py`: green. The full pytest suite is the landing
  train's and was not run here; no Python changed.
- Vet: T2, two rounds, converged. Seven correctness fixes, each with a unit test that failed first (Treasury:
  "5h ago" not "h-5", one deep-link target, no "−$0" line; Lending map: treasury-as-borrower one node, two
  facilities one link, an expected withdrawal named only when it is the only one, no "Unavailable" cash).

## Follow-ups

- `treasury_account` (backend `views.py`) serves no per-point `events` and no horizon-end point, so Treasury
  rebuilds the point labels and passes `horizon` 72; serving both (as `_outlook` does) would drop the prop
  and the constant.
- The pool → venue link reads the first pool venue account's freshness; with two pool venues it can name the
  wrong one. Needs a world with two venues to test.
- Shared helpers left duplicated: `capital`, the h-hour formatter (Overview, Treasury, Decisions), the metric
  strip CSS (Overview, Treasury), a "held" status tone and Lending's caution colours outside `tokens.css`.

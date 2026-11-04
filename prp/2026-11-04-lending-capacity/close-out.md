# Close-out: Lending, the capacity and what it rests on

> Source: raw.md, workflow.md, ux-sweep.md.

## What changed

- **Lending** — the headline is the API's K_p ("Your lender can still lend you up to $42,000."),
  the subtitle what it is not and why, from the API's parts. One main object,
  `CapacityLoop.vue` (new, Lending only), draws settled known as a column at one scale cut into
  the committed line, the reserve floor and the available capacity, the dependency arrow to You,
  and the venue as a same-scale block reached from the column and from the treasury's expected
  withdrawal. Facility terms are definition lists with the repayment schedule in place; the
  venue freeze is a labelled hypothetical whose disabled reason is visible text; the breakdown,
  "Source and authority" and "When the reading changes" fold below. Compare funding plans sits
  in the hero on a wide screen and under the object on a phone.
- **Fallback** — reduced authority, unobserved accounts, a K_p not Known or not above zero, or
  parts that do not add up to settled known: the earlier capacity block (figure with its status,
  not-counted accounts) and disabled funding, as before.
- **Old paths aligned** — e2e `lending`, `copy-1`, `states`, `match-shared`, `routes.ts`,
  `match-lending`; the unit spec's map hooks moved to the object's parties; Lending's word
  budget is now the accepted design's count (356 at 1487 px).
- **Not changed** — the shared shell (board step 4). Its phone Menu already meets the handoff
  (44 px, Escape closes and returns focus). The design's manual theme toggle is a shell control
  and is not added; dark follows the system. The fold the design calls "How we know" is named
  "Source and authority", because the shared check keeps "How we know" off every screen.

## Verified

| Gate | Result |
|---|---|
| `npm --prefix frontend run test:unit -- tests/unit/money-views.spec.js` | 47 passed (whole suite 383) |
| `bash scripts/ux-check.sh e2e/ux/match-lending.spec.ts` | green: 1440/834/390, first viewport at 1440x900 and 390x900 in both themes, judge path 12/12 |
| aligned e2e specs through `ux-check.sh` | `lending`, `copy-1`, `copy-3`, `states`, `match-shared`, `shell`, `smoke`, `meta` green |
| ruff, `checks/no_secrets.py`, `checks/attribution.py`, `checks/tests/test_word_budget.py` | green |

The full `checks/merge.sh` runs once over the merged batch; it was not run here.

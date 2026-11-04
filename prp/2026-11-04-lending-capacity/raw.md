# Lending: the lending capacity and what it rests on, as one answer

> Requirements. Next: workflow → implement. Depth: Medium (one screen, no API change; the
> design input was accepted before this run, so the design is folded into the workflow).

## Goal

The Lending screen answers one question first: how much can the lender still lend you, and what
does that figure rest on. Design input: the accepted Lending concept of 2026-11-02 (blind
cross-family judge: 83 against 38 for the screen it replaces). It has the answer as the headline,
one main object (the pool's settled cash as a column drawn to scale, cut into the reserve
floor, the committed line and the available capacity; a dependency arrow to You; the shared venue
as a same-scale block reached from the column and from your expected withdrawal), the
venue freeze with its disabled reason as visible text, compact facility terms, and the
breakdown, provenance and state wording folded below.

## Acceptance (pre-registered by the handoff)

1. At 390x900 and 1440x900, light and dark: the answer headline, the whole main object and
   Compare funding plans are visible without scrolling.
2. Every figure comes from `GET /api/v1/lending`, `/overview` and `/treasury`; with reduced
   authority or a non-empty `capacity.unobserved` the headline, the capacity block and Compare
   funding plans fall back to the earlier reduced wording and disabled behaviour.
3. The disabled Rehearse venue freeze shows its reason as visible text; no capacity-under-freeze
   figure appears anywhere.
4. No horizontal scroll at 390; every phone control at least 44 px; the six destinations reachable
   through the phone Menu (Escape closes it and returns focus).
5. The `data-test` hooks `tests/unit/money-views.spec.js` reads for Lending stay on the equivalent
   elements and that spec passes; `map-node`/`relations` move to the main object's parties.
6. The board's check: `npm --prefix frontend run test:unit -- tests/unit/money-views.spec.js`,
   `bash scripts/ux-check.sh e2e/ux/match-lending.spec.ts`, `bash checks/merge.sh`.

## Settled decisions

- The shared shell is not edited (board step 4). The phone Menu with Escape and focus return is
  already the shell's (`ScreenShell`, `data-test="menu"`), so criterion 4 is met by the shell. Dark
  follows the system through the house tokens; the design's manual theme toggle is a shell
  control and is not added here.
- The column is drawn only when the reading is whole: full authority, nothing unobserved, K_p
  and every part Known, K_p above zero, and the API's parts adding up to settled known (a check on
  the API's own figures; nothing shown is computed). Any other reading shows the earlier
  capacity block: the figure with its status, the basis, the not-counted accounts.
- The committed segment names its borrower only when exactly one active committed line exists;
  otherwise it says "promised to borrowers". The venue block is drawn only when the overview
  relates the pool to a venue, and the treasury's withdrawal is named only when the treasury read
  has exactly one expected exchange withdrawal (the earlier rule).
- The design's desktop-only second sentence (the $15,000 on the venue) is left out of the
  headline band: the main object says it, and the band stays one sentence at every width.

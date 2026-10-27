# UX sweep: Lending after the coherent-capacity fix

> Spot-check (dev-ux). Engine: Playwright MCP (Chromium) against `vite` dev on :3106, the API
> answered by the recorded C6 examples. Markup is unchanged; the unobserved tile now reads
> `capacity.unobserved` from Lending instead of the overview's completeness.

Case A pairs a fresh Lending (full authority, nothing unobserved) with an overview of the same
snapshot read past the six-hour boundary that lists `lender/operating` and `lender/venue` as
missing: the pairing that used to show both. Case B is the venue freeze (reduced, `lender/venue`
unobserved) beside an overview that lists nothing missing.

| Check | Phone 390×844 | Tablet 768×1024 | Desktop 1440×900 |
|---|---|---|---|
| A: authority full, no "Not observed" tile | pass | pass | pass |
| B: authority reduced, tile lists `lender/venue · ? Unknown`, funding disabled with why | pass | pass | pass |
| No horizontal page scroll (A and B) | pass | pass | pass |
| Links, buttons and summaries ≥ 44 px (A and B) | pass, 0 below | pass, 0 below | pass, 0 below |

In A, "Fund from the pool" stays disabled only because this build has no decisions route; the
unit test covers the enabled link. Screenshots: `ux/lending-{A,B}-{phone,desktop}.png`.

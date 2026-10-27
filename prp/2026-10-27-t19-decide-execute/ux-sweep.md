# UX sweep: Decisions and Execution

> Evidence (dev-ux, standard depth). Source: design.md. Engine: Playwright MCP (Chromium) against
> `vite` dev on :3193. A local mock answered the API: decisions were built from the T11
> policy-comparison fixture, the approval from the C3 example with a 15-minute expiry from now,
> and the execution from the C6 example plus a PAID payout. Screenshots are in `ux/`.

| Check | Phone 390×844 | Tablet 768×1024 | Desktop 1440×900 | Dark (390) |
|---|---|---|---|---|
| No horizontal page scroll | pass (both screens, review open, receipts open) | pass | pass | pass |
| Primary controls ≥ 44 px (nav, Refresh, Review, Confirm, Execute, Close, token field) | pass, 0 below | pass | pass | pass |
| Money and hash do not clip | pass (hash wraps, figures wrap inside tiles) | pass | pass | pass |
| Flow: Review → token → Confirm approval → bound terms → Execute → receipts | pass, by keyboard (Tab, Enter) | — | review opened | review opened |
| Enter in the token field submits nothing | pass | — | — | — |
| Focus: heading on open, back to Review plan after Execute | pass | — | — | — |
| Console warnings | 0 | 0 | 0 | 0 |

Fixed during the sweep:
- Each policy tile held a five-column table of scenarios. Its columns were cut off even at
  1440 px, so it is now a list that wraps, one scenario per row.
- On phone the review's term list was squeezed into two columns, so below 480 px it stacks.
- The token field sat on the page, behind the review dialog, so the review could open with no
  way to authorise. It moved into the review, inside a form that blocks submission. The page
  never shows a token prompt on the read path.
- Chromium logged "password field not in a form". Wrapping the field in that form removed it.

Not done here: there is no durable viewport test, because this repo has no Playwright harness
(`e2e/` belongs to T26). Contrast was not measured on the rendered page; these views add no new
colour pairs beyond the T17 tokens.

# UX sweep: Decisions and Execution

> UX evidence. Source: design.md. Engine: Playwright MCP (Chromium) against
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

**Re-sweep after vet round 2** (a "no legs yet" note, the wording for an unknown execution, and
Close disabled while a POST is in flight): at 390 px, Execution with receipts and with an
execution the server has no record of. No horizontal scroll, no control under 44 px. The one
console error is the browser's own log of the expected 404.

**Re-sweep for an unreadable successful POST:** the same mock, with the approval
POST answering 201 with an HTML page, then the execution POST answering an empty 202. The approval
shows the operator-resolution block with Confirm disabled, and no refusal text (phone,
`ux/unreadable-approval-phone.png`). The execution shows "outcome unknown … Do not send again",
reads `apr-1` by its approval id, and shows its receipt (`ux/unreadable-execution-{phone,tablet,desktop}.png`).
At all three widths there is no horizontal scroll and no control under 44 px.

**Spot-check after merging main:** a linked execution answering 200 with an HTML page. The receipts
section reads "! Could not read: the answer could not be read. Reading again." and shows no
"no record" or "no execution" note (`ux/unreadable-linked-read-{phone,desktop}.png`). At 390 and
1440 there is no horizontal scroll, and at 390 no control is under 44 px.

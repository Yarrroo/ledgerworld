# Decisions UX proof

**The Decisions mockup check passes in the real offline app.** The scope is `/decisions`: inspect the gap, compare policies, open scenario details, and follow Review current plan to Execution. No provider or model calls were made.

## Browser evidence

| Viewport | Layout, overflow and word budget | Hover/focus or tap tooltips | Light / dark captures |
|---|---|---|---|
| Desktop | Pass | Pass | [Light](ux/1487-light.png) · [Dark](ux/1487-dark.png) |
| Tablet | Pass | Pass | [Light](ux/834-light.png) · [Dark](ux/834-dark.png) |
| Phone | Pass | Pass | [Light](ux/390-light.png) · [Dark](ux/390-dark.png) |

The filenames carry the measured widths. Desktop uses the contract's wider screenshot viewport; tablet and phone use the existing touch-aware Playwright projects. The test checks reading order, API-backed bar values, radio inspection, the details dialog, review routing, the word budget and zero horizontal overflow. Tooltips are exercised by pointer/tap and keyboard focus, then dismissed with Escape. Light and dark screenshots were rendered and inspected; they are evidence, not an automated pixel-diff claim. The existing judge-path accessibility suite also passed.

## Reproduction and regression

Before the fix, `bash scripts/ux-check.sh e2e/ux/match-decisions.spec.ts` exited with the missing-spec error. The previous view had no stepper or waterfall and hid the timing behind a disclosure.

For a behavioral before/after proof, the updated `frontend/tests/unit/ux-panels.spec.js` was copied to a temporary worktree at `e6f268b`. Running its `shows the stepper, three sourced bars` test failed because `decision-steps` did not exist. The same test passes on the updated screen. The temporary worktree was restored and removed.

During the browser pass, the phone timing table overflowed because the shared table style forbade wrapping. The screen now wraps its timing values. The judge-path check also caught an icon-only selected status; the visible Selected label was restored.

## Commands actually executed

All builds and tests ran through the shared heavy-command queue.

- `bash scripts/ux-check.sh e2e/ux/match-decisions.spec.ts` — green, including the judge path and its accessibility checks.
- `npm --prefix frontend run test:unit` — green.
- Existing `decisions`, `copy-2`, `match-shared`, `readable-labels` and `states` Playwright specs — green on the same offline app; desktop/tablet-only cases retain their existing skips.
- `uv run python checks/no_secrets.py` and `uv run python checks/attribution.py` — green.

`bash checks/merge.sh` is reserved for the landing train by this work order and was not run in the slot. This does not prove the separately tracked Simulation combined accept.

## Deliberate differences from the image

The API supplies observed cash and each branch's lowest cash, but no movement attribution at the low point. The middle waterfall bar is therefore **Cash change**, their net difference, rather than a fabricated Payroll movement. Its tooltip and Source evidence say so. Timing retains the API's exchange arrival in addition to the delayed receivable. The plan description does not invent a live funding instruction; current terms are decided at review.

Unknown, stale, mismatched-currency and unrelated-snapshot cash never produce a waterfall. The screen remains read-only; changing its inspection radio does not change the backend-selected policy or create an approval. No data backfill is needed. No dependency was added.

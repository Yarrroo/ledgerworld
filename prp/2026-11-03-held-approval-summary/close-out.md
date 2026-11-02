# Bound approval summarises a held approval alone — Close-out
> Close-out (/dev-close). Source: cross-family review of the Execution and approval mockup match
> (finding on `frontend/src/views/Execution.vue:49`); board item 168.
> Date: 2026-11-03

## What broke
With a run whose linked execution is reconciled, confirming a new approval and closing the review
left the Bound approval panel showing three things at once: the older execution's summary
(Provider, `Status: Reconciled`), the new held approval (`Approved, not executed`), and a
"View all terms" fold carrying the older approval id. The first and third are read from the
execution, not from the held approval, but sat under the same heading, so the new, unexecuted
approval read as reconciled.

## What shipped
- `frontend/src/views/Execution.vue` — `approval-summary` and `summary-plain` render only while no
  approval is held (`execution && !held`). The older execution's own record (banner, tracker,
  legs, "How we know" context) is unchanged and still names its own execution id. When the held
  approval goes (executed, Forget access, dropped on Close), the execution summary returns.
- `frontend/tests/unit/decide-execute.spec.js` — regression: older reconciled `apr-0` plus a new
  held `apr-2`. Red before the fix (`approval-summary` still rendered), green after.
- `e2e/ux/match-execution.spec.ts` — the same case driven in the browser at 1440 (1487), 834 and
  390 px, light and dark; evidence `prp/2026-10-30-match-execution/ux/*-held-*.png`. The run-1
  decisions answer is now one constant shared with the mockup 07 test.

## Verification
- `npm --prefix frontend run test:unit -- tests/unit/decide-execute.spec.js`: 178 passed.
- `bash scripts/ux-check.sh e2e/ux/match-execution.spec.ts`: 12 passed at 1440/834/390, judge
  path 12 passed, `ux-check: green`.
- `checks/no_secrets.py` ok, `checks/attribution.py` ok, frontend build ok. No Python changed, so
  ruff and pytest were left to the landing train.
- The ux check rewrites the committed `*-execution-*.png` evidence on every run (the demo ids are
  random). Those original files were restored from git, not committed.

## Follow-ups / known gaps
- The hero lead ("The plan you approved moved … checked against your books"), the subtitle and the
  four-step tracker still describe the older execution while a new approval is held. They are
  labelled as the execution's record, but the lead's "the plan you approved" can be read as the
  new approval. That is outside this item's scope (the hero is not the Bound approval panel), so
  it is a follow-up for the Execution screen's owner.

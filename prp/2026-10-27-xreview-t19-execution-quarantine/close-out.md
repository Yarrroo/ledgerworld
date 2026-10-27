# Correction to T19: Execution keeps its quarantine across leaving and returning. Close-out
> Close-out (/dev-close). Source: cross-family review of T19 (Execution.vue:236, the
> unresolved-approval block cleared on remount while the operator token stayed).
> Date: 2026-10-27

## What shipped
- `frontend/src/views/Execution.vue`: the operator token lived in module scope (tab memory), while
  the unresolved-outcome block and the followed execution id lived in the component instance.
  Leaving Execution and coming back therefore re-enabled Review plan and Confirm with the token
  still held, after an approval or execution outcome the tab did not know.
  - An unresolved operation is now held in the same tab memory, keyed by the run it was sent for:
    `run_id -> { blocked, followedId, readBy }`.
  - Each load of a run restores that run's block and resumes reading the execution this tab sent
    (by approval id after an unknown POST), unless the address names another execution. In that
    case the block says the lookup is not read on this screen.
  - The block shown is derived only from what is held for the run on screen. A POST answered
    after the operator moved to another run is held for its own run: it neither blocks nor is
    followed on the new one.
  - Forget token does not lift the quarantine; only a reload does. `forgetTab()` clears both, and
    the unit suite calls it as its reload.
- `frontend/tests/unit/decide-execute.spec.js`: 10 cases in two blocks, "leaving and returning to
  Execution (board item 95)" and "vet round 2: an answer belongs to the run it was sent for".
  `gets` is now one shared helper.
- `ux-sweep.md` and `ux/`: browser spot-check at 390, 768 and 1440 px.

## Verification
- Reproduced first: 5 cases failed on the T19 component (block gone, Review enabled, token held,
  lookup not resumed) and pass now. Each applied vet finding has a case that fails on the commit
  before it: 2 on the first commit, 4 on the round-1 commit.
- T19 accept: `npm --prefix frontend run build` green, and `npm --prefix frontend run test:unit`
  114 passed (`decide-execute.spec.js` 48). `checks/attribution.py` and `checks/no_secrets.py`
  ok. Python is untouched, so pytest and ruff were not run in this slot; the full gate runs on the
  landing train.
- Browser (Playwright, Vite plus `page.route` answers, approval POST 504): after the nav link away
  and back, the block shows, Review plan stays disabled and opens nothing, the token is still held,
  and 1 approval POST was sent, at all three tiers.
- Vet: T2 (operator-token and payout-gate surface, 1 subsystem). 2 rounds, 14 findings.
  - 8 applied: 6 proven by tests, 1 quality fix (the shared `gets`), and 1 comment corrected
    without a test (Forget token does not lift the quarantine).
  - 6 dismissed, reasons below. 0 open. Round 2's fixes were read by hand only; the cap is 2.
  - `/security-review`: no findings.

## Dismissed vet findings
- The quarantine never lifts once the lookup shows a final state. This is intended: T19's
  invariant is that an approval is executed at most once from this tab, whatever the outcome, and
  in-mount the block never lifted either. Lifting it on resolution is a design change (follow-up).
- `forgetTab` is exported but only tests call it. It models a reload, and no source calls it.
  Re-importing the module per test would rewrite all 48 cases.
- When there is no `run_id` in the URL, the demo run can change between visits, so the hold stays
  with the old run. A new run is a new approval, which the server binds to the current observed
  snapshot. The old run's hold returns with `?run_id=` of that run.
- A held execution id may differ from the approval id. By contract (C3/C6) the execution id is the
  approval id.
- Restored wording can change between refreshes. This is resolved by the `readBy` change: the
  wording is now a function of the hold alone.
- `follow()` does not clear `pollError`. A stale poll error shows only when two runs each hold a
  lookup within one mount. This predates the change in the POST path (follow-up below).

## Docs updated
- The view's block comments describe the held quarantine and its lifetime. The T19 design and
  brief say the token lives in tab memory and an approval is executed at most once from this tab;
  this correction makes that hold across a remount, so no doc disagrees with the code. `CLAUDE.md`
  was left alone, as the order requires.

## Follow-ups / known gaps
- After an unanswered approval POST, the disabled Confirm button drops focus to `<body>`, so Escape
  no longer closes the review (measured at all three tiers; Cancel works). Predates this change
  (dev-fix).
- `follow()` should clear `pollError` the way the normal load path does (dev-fix, low).
- Whether a resolved lookup (final, reconciled) should lift the quarantine is an owner decision
  about the T19 invariant (dev-build).
- The review report this item cites (`prp/2026-10-27-xreview-t19-screens-decisions-and-execution/report.md`)
  is not in this checkout; the finding was taken from the board item's text.

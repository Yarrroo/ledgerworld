# Approval summary shows the approval this tab holds — Close-out
> Close-out. Source: a review finding on the Execution panels (E1-E6) and the approval dialog,
> landed at 551a146.
> Date: 2026-10-29

## What broke
After Confirm approval and Close without executing, the Approval summary (E3) said "No approval
to summarise" while the tab still held an approval that Review plan would execute. E3 read only
a server-read execution, never the approval held in the dialog's flow.

## What shipped
- `frontend/src/views/Execution.vue`
  - E3 shows a held, unexecuted approval: id (copy), state, snapshot, provider, plan hash and
    expiry. It is shown apart from any execution's receipts, which follow it when present. The
    state says when the approval can no longer execute (expired, or an outcome unknown for the run).
  - One `newScreen()` is the reset for a new run or execution. A query navigation and a refresh
    that names another prepared run under the same address both call it, so the review, its
    approval, the message and the followed execution of the last run all go. A POST in flight
    answers to the screen it was sent from.
  - Forget access drops an unexecuted approval and says it expires unused. Access is only
    entered in a fresh review, so a kept approval could be neither executed nor replaced.
  - Close drops an approval that can no longer execute.
- `frontend/tests/unit/decide-execute.spec.js`: eight tests under "the Approval summary shows the
  approval this tab holds (board item 151)": Close/reopen before and after expiry, executed,
  Forget access, and a refresh naming another run (fresh review, nothing returns with the old run,
  a late approval is not installed, the last run's message goes). Each fix has a test that failed
  before it; the executed and expiry-on-Close tests guard behaviour that already held.
- `e2e/ux/execution.spec.ts`: confirm → Close → summary → expiry → Close drops it, at 1440, 834
  and 390 px.
- `prp/2026-10-29-execution-dialog/design.md`: the E3 line names the held approval (the design
  followed the code).

## Verification
- Unit: `npx vitest run` in `frontend/`, 15 files, 293 tests passed.
- Build: `npm run build` passed.
- UX: `bash scripts/ux-check.sh e2e/ux/execution.spec.ts`, 18/18 at three widths, then the judge
  path 12/12; the summary was screenshotted at each width.
- `checks/no_secrets.py` and `checks/attribution.py` exit 0. No Python changed; `checks/merge.sh`
  runs in full when this lands.
- Vet: T2 (the change gates "Execute approved plan" on a payment path), `/code-review medium`
  twice and `/simplify`. Two rounds, 17 findings: 13 applied (6 with a test that failed before,
  7 comment or structure cleanups), 4 recorded below, 0 open.

## Recorded, not applied
- E3's held-approval list repeats five rows of the dialog's bound terms; sharing them needs a
  new component.
- No run check on Execute itself: the approval is dropped in the same watcher that sees the run
  change, before any click can land.
- A dialog closed by a new screen does not return focus to Review plan. The navigation path
  already behaved this way, and the refresh is behind the open modal.
- A snapshot change under the same run leaves the approval enabled on screen; the server refuses
  it at Execute (`snapshot_moved`, tested). The screen's snapshot id is not comparable to the
  approval's bound one.
- The four `/simplify` angles found nothing beyond the duplication above.

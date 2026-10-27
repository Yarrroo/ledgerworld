# Execution: nothing restarts after unmount — Close-out
> Close-out. Source: a review correction of the T19 decide/execute screen (prp/2026-10-27-t19-decide-execute).
> Date: 2026-10-27

## What shipped
- `frontend/src/views/Execution.vue`: `onUnmounted` marks the view disposed and aborts the polled
  status read. `poll` and `schedule` start nothing once disposed; `executePlan` and
  `confirmApproval` write nothing to the view once their POST answers late; an unknown outcome
  is still held in tab memory first. POSTs are not aborted, because their effect stands either
  way.
- Before this change, a status read answered after unmount re-armed the 5 s timer, and a late
  execution POST started polling from scratch. A late approval POST started the expiry clock,
  and a late answer of any kind wrote its outcome into the dead view's state.
- `frontend/tests/unit/decide-execute.spec.js`: "unmount with a request pending", eight cases:
  six red before the fix, two pinning the merge order below.
- `prp/2026-10-27-t19-decide-execute/design.md` §7: polling ends when the screen is left.
- Merged with the execution quarantine (prp/2026-10-27-xreview-t19-execution-quarantine: an
  unresolved block survives leaving and returning): a late POST answer still records an unknown
  outcome in tab memory before the disposal guard, so returning restores the block and resumes
  the lookup. Two seam tests pin that order; both fail if the guard moves above `hold()`.

## Verification
- `npx vitest run` (frontend): 116 tests passed before the merge with main, 149 after (main
  brought more). The spec ran 20 times with 0 red runs both before and after (fake timers).
  `vite build` green.
- Browser (Playwright, mocked API, 390×844 · 768×1024 · 1440×900): one status read held, the
  user goes to Overview, the read is released and the browser waits 12 s. Status reads stayed
  at 2. With the pre-fix `Execution.vue` swapped in at 390×844 they reached 4. No horizontal
  overflow at any tier.
- Review: two rounds on the fix and two on the merge, nothing left open.

## Follow-ups / known gaps
- `useReading` (src/api/v1.js) has no unmount awareness: its loader reads are not cancelled.
  Harmless today, because Vue stops the view's watchers on unmount and nothing is rescheduled.
  A shared `onUnmounted`-aware signal would serve every screen; it is out of this item's scope.
- `request()` reports an aborted fetch as `unreachable`. Only the disposed path aborts today.
- An approval the server grants after the screen is gone is not kept: returning offers a fresh
  review, and a second confirm creates a second approval for the run. This predates the fix (the
  late answer only ever reached the dead view); keeping a granted approval in tab memory is a
  change to the quarantine's design.

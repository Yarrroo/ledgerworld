# Execution: nothing restarts after unmount — Close-out
> Close-out (/dev-close). Source: board item 98, a correction of the T19 decide/execute screen.
> Date: 2026-10-27

## What shipped
- `frontend/src/views/Execution.vue`: `onUnmounted` marks the view disposed and aborts the polled
  status read. `poll` and `schedule` start nothing once disposed; `executePlan` and
  `confirmApproval` return on disposal right after their POST and at the top of their `catch`.
  POSTs are not aborted, because their effect stands either way.
- Before this change, a status read answered after unmount re-armed the 5 s timer, and a late
  execution POST started polling from scratch. A late approval POST started the expiry clock,
  and a late answer of any kind wrote its outcome into the dead view's state.
- `frontend/tests/unit/decide-execute.spec.js`: "unmount with a request pending", six cases,
  each red before the fix.
- `prp/2026-10-27-t19-decide-execute/design.md` §7: polling ends when the screen is left.

## Verification
- `npx vitest run` (frontend): 4 files, 116 tests passed; the spec ran 20 times with 0 red runs
  (fake timers). `vite build` green.
- Browser (Playwright, mocked API, 390×844 · 768×1024 · 1440×900): one status read held, the
  user goes to Overview, the read is released and the browser waits 12 s. Status reads stayed
  at 2. With the pre-fix `Execution.vue` swapped in at 390×844 they reached 4. No horizontal
  overflow at any tier.
- Vet: T2 (async lifecycle), 2 rounds, converged; see the run report for counts.

## Follow-ups / known gaps
- `useReading` (src/api/v1.js) has no unmount awareness: its loader reads are not cancelled.
  Harmless today, because Vue stops the view's watchers on unmount and nothing is rescheduled.
  A shared `onUnmounted`-aware signal would serve every screen; it is out of this item's scope.
- `request()` reports an aborted fetch as `unreachable`. Only the disposed path aborts today.

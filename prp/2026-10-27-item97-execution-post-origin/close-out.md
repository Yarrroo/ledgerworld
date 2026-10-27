# Execution: a POST answered after a query navigation stays with its own run — Close-out
> Source: a review finding on the Execution screen, `frontend/src/views/Execution.vue:446` (landed at 1388c6b).
> Date: 2026-10-27

## What broke, and why
Executing on run-1 and opening run-2 (a query-only navigation) while the execution POST was in
flight showed run-1's execution under run-2: `Run run-2 · execution apr-1`. The query watcher
skipped its reset while a POST was in flight, and the POST handler then applied its answer to
whatever the screen held when it arrived. An approval answered the same way was installed in the
open review and offered for Execute under the new run.

## What shipped
Built on item 95's tab memory `unresolved` (run id -> block, followed execution), which keeps an
unknown outcome's block on its own run and restores it on every load.
- `frontend/src/views/Execution.vue`
  - Each approval and execution POST records its origin: the run, and a screen counter bumped by
    every run/execution navigation and by leaving the view. A navigation always resets the screen.
  - An answer whose screen is gone is never installed or followed there. An execution is held for
    its run with `unseen`, linked as "Read execution X of run R" until its run's screen shows it
    (`restore(body)`, run on every load and when the answer finds its run already on screen).
    Showing it closes a review opened meanwhile. A refusal or an unknown approval is a message
    naming its run.
  - A view left while a POST was in flight neither follows nor polls the answer; the screen that
    came back links it, and a block held for its run shows at once.
- `frontend/tests/unit/decide-execute.spec.js`: 13 cases under "a POST answered after a query
  navigation stays with its own run", each failing on the code before its fix.

## Verification
- Tests: `npx vitest run` (frontend), 154 passed, item 95's cases included.
- Build: `vite build` ok. `checks/no_secrets.py` ok, `checks/attribution.py` ok. No Python changed.
- Browser: Playwright on the dev server with the API intercepted. Execute, hold the POST, open
  run-2, answer: run-2 shows no execution; the link (293x44 px) works from the keyboard and opens
  run-1 with its execution. No horizontal scroll at 390x844, 768x1024 and 1440x900
  (`ux/elsewhere-*.png`).

## Recorded, not applied
- `review=1` does not auto-open when a waiting outcome is shown on that run's screen: the outcome
  takes the screen.
- An unknown outcome is linked and read by its approval id, as the contract reads it:
  `GET /executions/{approval_id}`, execution id = approval id.
- A run holds one followed execution: if its run is opened at another `execution_id` and executed
  again in place, the newer execution replaces the waiting one's link.
- After a failed reload the screen still shows the last run, and that run's block, as item 95
  decided.

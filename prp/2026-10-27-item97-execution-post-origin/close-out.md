# Execution: a POST answered after a query navigation stays with its own run — Close-out
> Close-out (/dev-close). Source: cross-family review finding on `frontend/src/views/Execution.vue:446` (landed at 1388c6b).
> Date: 2026-10-27

## What broke, and why
Executing on run-1 and opening run-2 (a query-only navigation) while the execution POST was in
flight showed run-1's execution under run-2: `Run run-2 · execution apr-1`. The query watcher
skipped its reset while a POST was in flight, and the POST handler then followed its answer in
whatever context the screen held.

## What shipped
- `frontend/src/views/Execution.vue`
  - Each approval and execution POST records its origin (run id, and a screen counter that is
    bumped by every run/execution navigation). A navigation always resets the screen.
  - An answer whose screen is gone is never installed or followed there. An execution outcome
    waits in `pending` (run id -> execution id, unknown?) and is delivered by `deliver()` the
    next time its run is on screen, by any address naming it. A refusal or approval answer is
    shown as a message naming its run.
  - One link per waiting outcome, "Read execution X of run R", until it is delivered.
    Delivery closes a review opened meanwhile.
  - An unknown outcome still blocks new approvals from this tab with "Do not send again", as
    it did before.
- `frontend/tests/unit/decide-execute.spec.js`: 10 cases under "a POST answered after a query
  navigation stays with its own run", each failing before the commit that fixed it.

## Verification
- Tests: `npx vitest run` (frontend), 119 passed. The new cases were run against the earlier
  code at each step: 3 failed on the original, 5 on the round-1 base, 2 on the round-2 base.
- Build: `vite build` ok. `checks/no_secrets.py` ok, `checks/attribution.py` ok. No Python changed.
- Browser: Playwright on the dev server with the API intercepted. Execute, hold the POST, open
  run-2, answer: run-2 shows no execution; the link reads "Read execution apr-1 of run run-1"
  (293x44 px), works from the keyboard, and opens run-1 with its execution. No horizontal scroll
  at 390x844, 768x1024 and 1440x900 (`ux/elsewhere-*.png`).
- Vet: T3 (concurrency on the execution POST path); code-review high then medium, 2 rounds,
  16 findings: 10 applied (7 proven by test), 6 recorded below, 0 open; security-review clean.

## Recorded, not applied
- An unknown outcome on another run blocks review on every run until reload. This was already
  so before the change (`flow.blocked` was never cleared on navigation). It is the conservative
  stance on a payment path; scoping it per run is a product decision.
- `review=1` does not auto-open when an outcome is delivered to that run's screen: the outcome
  takes the screen.
- An unknown outcome is linked and read by its approval id. That is the contract:
  `GET /executions/{approval_id}`, and execution id = approval id.
- A waiting link stays until its run is shown without another `execution_id`. It describes
  itself, and staying until then is intended.

## Follow-ups / known gaps
- Leaving the Execution screen for another route while a POST is in flight unmounts the view.
  The answer is lost, and `follow()` may poll after unmount. This predates this change; durable
  fix: module-scope `pending`, plus no scheduling after unmount.

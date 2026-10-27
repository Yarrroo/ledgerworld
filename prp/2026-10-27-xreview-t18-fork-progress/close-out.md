# Correction to T18: an accepted fork is followed. Close-out
> Close-out (/dev-close). Source: cross-family review of T18 (Simulation.vue:360, the fork reloaded once).
> Date: 2026-10-27

## What shipped
- `frontend/src/views/Simulation.vue`: an accepted fork is followed on its own timer. It reads
  `GET /decisions/{run_id}` every 4 s until the status leaves `pending`, and 409 `fork_failed`
  shows "Fork failed". It then re-reads the run until every accepted branch is present from this
  fork's checkpoint round, with its cash path. After five reads without them, the screen reports it
  and stops. Any other failed read is shown (`fork-lag`, role=status) and retried. Fork is
  disabled while a fork is followed. Only GETs repeat; the POST is never retried. Following stops
  on another run, on unmount, or when a check already in flight returns after either.
- `frontend/tests/unit/simulation-view.spec.js`: the recorder answers any path and can refuse with
  a C6 ErrorResponse (`Refusal`). Eleven cases cover following an accepted fork. The old "a
  successful fork reloads the run" case is replaced, because accepting no longer re-reads the run.
- `ux-sweep.md` and `ux/`: browser spot-check at 390, 768 and 1440 px.

## Verification
- Reproduced first: 3 cases failed on the original view (the fork showed no progress and no
  failure). Each vet finding has a case that fails on the first commit's view (7 failed there)
  and passes now.
- `npx vitest run`: 110 passed. `npm run build`: green. `checks/no_secrets.py` and
  `checks/attribution.py`: ok. The T18 accept (`simulation-view.spec.js`): 28 passed. Python is
  untouched, so pytest and ruff were not run in this slot; the full gate runs on the landing train.
- Browser (Playwright, Vite plus a local API stub): the forked branches reached the cash paths
  with no Refresh on phone and desktop, and a worker failure showed as an alert on tablet.
- Vet: T2 (async polling surface), 2 rounds, 9 findings: 8 applied and proven, 1 dismissed (a poll
  skipped while a load is in flight only delayed one tick; that skip now leaves the read count
  alone), 0 open.

## Docs updated
- The view's header comment and the new block comment describe the follow loop. The T18 brief and
  the UI HANDOFF row do not describe how the screen learns about a finished fork, so no doc
  disagrees with the code. `CLAUDE.md` was left alone, as the order requires.

## Follow-ups / known gaps
- `frontend/src/views/Decisions.vue` shows `pending` but never re-reads it: same defect class,
  different screen and owner (dev-fix).
- Once a fork's decisions leave `pending`, `GET /decisions` no longer reports the job's state. A
  worker that fails between writing decisions and writing the run is caught only by the screen's
  five-read limit. Exposing the fork job's state on the run would be the backend-level answer
  (dev-build).
- The vet round's copy changes (the Fork-disabled reason, the "branches have not reached the run"
  alert) are covered by unit tests but were not re-swept in a browser.

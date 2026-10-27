# Execution status reads keep their order (board item 96) — Close-out

> Close-out. Source: cross-family review of the T19 screens (finding at
> `frontend/src/views/Execution.vue:427`, landed at 1388c6b). Date: 2026-10-27.

## What shipped

- `frontend/src/views/Execution.vue`: the screen's own execution read (initial and Refresh) takes
  a generation from the same `latestOnly()` guard as the 5 s poll. A poll issued before Refresh
  can no longer overwrite the reconciled receipt or open incident Refresh read, and a Refresh read
  answered after a newer poll no longer replaces it. Only an accepted reading is shown (the
  `state.body.execution` fallback is gone). An accepted 404 clears the shown execution, so "no
  record" never stands beside earlier legs and a context execution is not polled after it.
- `frontend/src/api/v1.js`: `latestOnly().current(ticket, key)`, the accept check without
  recording it. A failed read (not a 404) is not an answer: it discards no earlier-issued read,
  and its error clears only on an answer issued after it.
- `frontend/tests/unit/decide-execute.spec.js`: six regression tests in "correction: a status
  read never overwrites a newer one"; fake-timer helpers shared at module scope.

## Verification

- Tests: `npx vitest run` in `frontend/`: 4 files, 116 passed. Each new test failed on the code
  before its fix (three on 16cdab4, two on ec6d080, two on aea13f4) and passes after.
- Build: `vite build` green. No Python changed, so ruff has nothing new to lint.
- Browser: the built screen with mocked `/api/v1` at 390×844, 768×1024 and 1440×900. A poll held
  in flight across Refresh and released afterwards left the Refresh read's incident on screen at
  every width, with no horizontal overflow.
- Vet: T2, two rounds, converged with 0 open (8 applied, 5 of them proven by tests; 10 recorded).

## Docs updated

- `prp/2026-10-27-t19-decide-execute/design.md` §7: the polling rule now covers the screen's own
  read, 404 versus other failures, and when an error clears.

## Follow-ups / known gaps

- For an execution this tab sent, Refresh fetches it twice: once inside the screen's read, whose
  answer is dropped, and once through `poll()`. This existed before; it wastes one GET and
  shows nothing wrong.
- The shell's "as of" comes from the screen's read even when that read's execution was refused
  as older; the receipts panel prints its own read time from the body it shows.

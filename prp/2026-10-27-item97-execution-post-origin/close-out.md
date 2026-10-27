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
    (`restore(body)`, run on every load and whenever the held entry of the run on screen
    changes). Showing it closes a review opened meanwhile, and the run is not reviewed again until
    it has been read. An unknown approval is linked the same way ("Open run R: approval outcome
    unknown"); a refusal is a message naming its run, shown even while this screen is blocked.
  - A run with a POST still unanswered from an earlier screen (a view since left, or the same view
    before a navigation) is not reviewed again until it answers (`inflight`, tab memory like
    `unresolved`), so two screens never race on one run.
  - While this view's own POST is unanswered, no other screen it moves to offers a review: one
    opened there could be neither confirmed nor cancelled until the old run answered.
  - A view left while a POST was in flight neither follows nor polls the answer (`disposed`, and
    its status reads are aborted); the outcome is still held for its run, so the screen that came
    back shows it at once if it shows that run, and links it otherwise. Forgetting the tab lifts a
    block already on screen.
- `frontend/tests/unit/decide-execute.spec.js`: 23 cases under "a POST answered after a query
  navigation stays with its own run", each failing on the code before its fix.

## Third merge with main (item 94)
Item 94 checks every successful answer before anything is held (`boundApproval`; an execution
answer must name its approval id) and lets a left view apply nothing to itself (`disposed`). Both
rules hold under item 97's origin: the answer is checked first, then routed by `moved(from)`; a
left view still holds the outcome for its run. The two-outcomes case now gives each approval its
own id, as item 94 requires. Run against main's `Execution.vue`, 19 of this suite's cases fail.

## Verification
- Tests: `npx vitest run` (frontend), 215 passed, items 94's, 95's and 96's cases included.
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
- A refusal that answers after the view was left is not carried to the screen that came back:
  nothing was sent, and that screen correctly shows no pending outcome.
- After a failed reload the screen still shows the last run, and that run's block, as item 95
  decided; an outcome answered during that failure is shown on the next successful load.
- `forgetTab()` (the tab reloaded) while an execution is followed leaves the shown execution in
  place, and it empties `inflight` while a request may still answer; a real reload rebuilds the
  view and drops its requests.
- `inflight` is kept beside `unresolved` rather than inside it; folding the two is a refactor.
- An approval created after its screen moved on is named in a message and never held: it binds
  nothing until executed, is never offered for Execute, and expires unused; the run can be
  approved again.
- A message renders beside this screen's block, so an approval answered unknown after moving to
  the same run reads twice (block and message), both true.
- Keying the view per run/execution query would make "moved" the same as "unmounted" and remove
  the screen counter; that is a router change outside this item.
- `restore()` runs once more when it clears `unseen` (a source of its own watcher); it is
  idempotent.

## Vet after the third merge
T3 (concurrency on the execute path), converged in 2 rounds: 4 applied, 11 recorded above or
dismissed, 0 open. Applied: no review opens on another screen while this view's POST is out
(two cases, both failing without the guard); `executePlan` releases in one `finally`; a comment
on where a refusal goes. Dismissed: `forgetTab()` emptying `inflight` (no app code calls it, only
tests); `screen` not reactive (every bump is followed by `refresh()` or unmount, which recompute
`reviewWhy`); `review=1` auto-open behind an old POST (no in-view link carries `review=1`).

## Reflect
- Other POSTs on a reused view: `Simulation.vue` fork and interview already capture their run and
  drop another run's answer (`Simulation.vue:401`, `:488`); neither moves money. Not a gap.
- `approval-unknown-*.png` were not retaken after this merge; that path is covered by the unit
  cases, and the merge did not change its markup.

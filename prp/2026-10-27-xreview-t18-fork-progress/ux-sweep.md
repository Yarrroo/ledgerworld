# Correction to T18 · an accepted fork is followed: UX spot-check

> Finding (cross-family review of T18): the Live Simulation screen reloaded the run once after a
> fork was accepted, so a fork job finishing later, or failing, never appeared without a manual
> refresh. Fix: `frontend/src/views/Simulation.vue` reads `GET /decisions/{run_id}` every 4 s until
> it leaves `pending` (409 `fork_failed` ends it as a failure), then re-reads the run until every
> accepted branch has its branch and cash path. Only reads repeat; the POST is never retried.

Engine: Playwright MCP (Chromium) against the Vite dev server; the API was a local stub whose fork
answers 503 once, `pending` twice, then `selected` with three child branches (`run-ok`), or 409
`fork_failed` (`run-bad`). Screenshots in `ux/`.

| Check | Phone 390×844 | Tablet 768×1024 | Desktop 1440×900 |
|---|---|---|---|
| No horizontal page scroll | pass (0 px) | pass (0 px) | pass (0 px) |
| Running state said while the job runs | pass (`role=status`) | — | pass |
| Unreadable progress said, still checked | pass (503 → `fork-lag`, cleared on the next read) | — | pass |
| Child branches and cash paths appear with no refresh | pass (3 children in cash paths) | — | pass (3 children) |
| Worker failure shown, polling stops | — | pass (`role=alert`, `Fork failed: …`, fork enabled again) | — |
| Fork button keeps a 44 px target | pass (44 px) | pass | pass |
| Token never in DOM or storage | — | — | pass |

Findings: none. The banner overlapping the controls' element screenshot on phone is the shell's
sticky header, unchanged by this fix.

After the sweep, the vet tightened the follow loop. Fork is disabled while a fork is followed
(`fork-why`: "A fork is running: fork again once its branches arrive"). Only `fork_failed` ends a
fork as failed. A branch counts only from this fork's checkpoint round, because a re-fork reuses
branch ids. A failed run read shows as `fork-lag`. Five run reads without the branches end the fork
with an alert. Accepting a fork no longer re-reads the run at once, and a check in flight at unmount
no longer restarts polling. These are text changes inside existing note paragraphs. They are
covered by unit tests and were not re-swept in the browser.

Durable proof: eleven cases in `frontend/tests/unit/simulation-view.spec.js`
(`an accepted fork is followed …`), every one but "leaving the run" failing before its fix. No
Playwright harness exists in the repo.

Deferred, out of this item's scope: `Decisions.vue` shows `pending` but does not re-read it either.

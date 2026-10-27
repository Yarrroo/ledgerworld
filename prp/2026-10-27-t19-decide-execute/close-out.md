# Decisions and Execution (T19) — close-out

> Close-out. Source: design.md ← briefs/T19.md + design/modules/ui/HANDOFF.md.
> Date: 2026-10-27. Board item 20.

## What landed

- `/decisions` (`frontend/src/views/Decisions.vue`) shows the three policies side by side, each
  tile labelled with its cohort and weight kind: obligations unmet, floor kept or breached, the
  scenario-set cost (kept apart from the current-plan fee) and one row per scenario branch. An
  all-infeasible result shows escalation instead of approval. A reverse-stress cohort is
  labelled "Search result, not a forecast". Replays are labelled as replays.
- `/execution` (`frontend/src/views/Execution.vue`) runs Review → Confirm approval → bound C3
  terms (legs, hash, absolute expiry) → Execute approved plan, three explicit acts. Each POST
  is sent once. A timed-out or 5xx execution is read back by its approval id and never resent,
  and an unanswered approval blocks for the operator. Receipts show each leg's C4 state and
  reconciliation as of a time. An unknown outcome or an open incident shows the incident view.
  The token is entered in the review and kept only in the tab's memory. Reads stay anonymous.
- Two routes in `frontend/src/router/index.js` (already listed in `ATTRIBUTION.md`); the shell's
  navigation picks both up from `SCREENS`.
- `frontend/tests/unit/decide-execute.spec.js`: 38 cases built on the decide-execute and
  accessibility fixtures (loaded unchanged), the decisions and execution module fixtures and
  the C3/C4/C6 examples.

## Verification

- The item's check (`npm ci`, then `build`, then `test:unit` on the spec): exit 0, 38 passed.
  The whole frontend suite passed 68 of 68.
- `checks/no_secrets.py` and `checks/attribution.py`: both ok. No Python changed, so ruff and
  pytest have nothing new to cover. The full gate runs on the landing train.
- Vet: T3, 2 rounds, 16 applied (13 proven by tests that fail before the fix, 0 unproven),
  2 recorded, 0 open. Details in `vet-report.md`.
- UX: Playwright sweep at 390, 768 and 1440 px, light and dark, against a local mock API. It
  found no horizontal scroll and no control under 44 px, and the flow passed end to end by
  keyboard. Details in `ux-sweep.md`.

## Docs updated

- `README.md`: the two new screen routes.
- `CLAUDE.md`: not touched; the order keeps it off-limits.

## Follow-ups / known gaps

- C6 has no preview of the plan before `POST /approvals`, and C3 carries no fee. So the
  current-plan fee appears only as the per-branch funding cost, and the legs appear first as
  the server's bound terms. Both are contract gaps for the API owner (T16).
- `ExecutionResponse` lists no setup movements, so this screen cannot show setup funding apart
  from the plan (judge path step 4).
- The scenario-cost helper and the policy names are duplicated in both views, and the rule
  that a 5xx means the outcome is unknown sits in the view, not in `request()`. Both belong in
  `api/v1.js`, which T17 owns.
- No durable viewport test: the Playwright harness is T26's.

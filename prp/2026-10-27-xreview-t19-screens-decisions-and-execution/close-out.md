# Unreadable successful POSTs on the Execution screen — Close-out
> Close-out (/dev-close). Source: the cross-family review finding on T19 (board item 94).
> Date: 2026-10-27

## What shipped
- `frontend/src/views/Execution.vue`: only a 4xx is a refusal now. A 2xx to `POST /approvals` or
  `POST /executions` that does not parse, or lacks a term the screen shows, is an unknown outcome.
  The approval blocks with "operator resolution required" and is never confirmed again. The
  execution is read back by the captured approval id and never resent.
- A bound approval is readable only with every C3 term the dialog shows: id, hash, entity, account,
  snapshot, mode, an RFC 3339 expiry and server time, and at least one leg with an index, kind,
  source, counterparty, integer-minor amount, a text-or-null `funded_by`/`facility_id`, and `after`
  as leg indices.
- `GET /executions/:id` is readable only when it names the execution asked for and carries the C6
  context, legs and incidents the receipts use. An unreadable read is an error that is read again.
  It no longer stops the poll on a TypeError, never reads as "no record", and does not block the
  review of the current plan.
- `prp/2026-10-27-t19-decide-execute/design.md`: the unknown-outcome invariant now says this.

## Verification
- Tests: `npx vitest run` (frontend), 129 passed (104 before this item). Each of the 25 new cases
  failed against the code before the fix that it covers (commits 487fc29, 4b3ef37, 24b9adf).
- Build: `npm --prefix frontend run build` green. `checks/no_secrets.py` and `checks/attribution.py`
  exit 0. No Python changed.
- Real server: answers from the API test fixture (201 approval, 202 accepted, 200 read) pass the
  view's own validators, evaluated from its source.
- UX: Playwright at 390, 768 and 1440 against a mock returning an HTML 201 and an empty 202
  (`../2026-10-27-t19-decide-execute/ux-sweep.md`). No horizontal scroll and no control under
  44 px. The markup did not change after the sweep.

## Docs updated
- The T19 design invariant (above). `CLAUDE.md` was left alone, as the order requires, and the
  dev-workflows block refresh was not run because it commits `CLAUDE.md`.

## Follow-ups / known gaps
- `request()` still returns `null` for an unparseable 2xx. Overview, Treasury, Lending and
  Decisions can show that as a loaded empty state, and Simulation's fork shows it as accepted with
  no branches.
- Simulation's fork reports a timeout or 5xx as "Fork not accepted", which is the same
  misclassification fixed here for money.
- The approved-terms table does not show an fx leg's `to_currency`.
- `flow.blocked` survives a query-only navigation: a deliberate guard, but the execution banner
  then names an id that is no longer read.
- The response checks are written by hand against `contracts/`; nothing in the frontend validates
  against the schema.

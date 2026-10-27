# Unreadable successful POSTs on the Execution screen — Close-out
> Source: the cross-family review of T19, finding "an unreadable successful approval or execution
> POST response is treated as a definitive refusal". Date: 2026-10-27

## What shipped
- `frontend/src/views/Execution.vue`: only a 4xx is a refusal now. A 2xx to `POST /approvals` or
  `POST /executions` that does not parse, or lacks a term the screen shows, is an unknown outcome.
  The approval blocks with "operator resolution required" and is never confirmed again. The
  execution is read back by the captured approval id and never resent.
- A bound approval is readable only with every C3 term the dialog shows: id, hash, entity, account,
  snapshot, mode, an ISO-8601 `T` expiry and server time (the form every browser parses alike), and
  at least one leg with an index, kind,
  source, counterparty, integer-minor amount, a text-or-null `funded_by`/`facility_id`, and `after`
  as leg indices.
- `GET /executions/:id` is readable only when it names the execution asked for and carries the C6
  context, legs (in a C6 state) and incidents the receipts use. A failed read, followed or linked,
  is said as such, discards nothing read before it, and is read again every 5 s unless the server
  refused it outright (a 4xx) or the screen was left. It no longer stops the poll on a TypeError,
  never reads as "no record" or "no execution to show", and does not block the review.
- `GET /decisions/:run` without its status, its results' costs or (when selected) its policy is
  "could not be read", not "no decision is available".
- `prp/2026-10-27-t19-decide-execute/design.md`: the unknown-outcome invariant now says this.

## Verification
- Tests: `npx vitest run` (frontend). The item went from 104 to 129 passing, and each of its 25 new
  cases failed against the code before the fix that it covers. Main was merged twice (an
  unresolved block held against its run; one generation for every execution read), and 10 more
  cases each failed before their fix; 180 pass.
- Build: `npm --prefix frontend run build` green. `checks/no_secrets.py` and `checks/attribution.py`
  exit 0. No Python changed.
- Real server: answers from the API test fixture (201 approval, 202 accepted, 200 read) pass the
  view's own validators, evaluated from its source.
- UX: Playwright at 390, 768 and 1440 against a mock returning an HTML 201 and an empty 202
  (`../2026-10-27-t19-decide-execute/ux-sweep.md`). No horizontal scroll and no control under
  44 px. Later changes kept the markup except the read-error line's wording.

## Docs updated
- The T19 design invariant (above). Nothing else documents this rule.

## Follow-ups / known gaps
- `request()` still returns `null` for an unparseable 2xx. Overview, Treasury, Lending and
  Decisions can show that as a loaded empty state, and Simulation's fork shows it as accepted with
  no branches.
- Simulation's fork reports a timeout or 5xx as "Fork not accepted", which is the same
  misclassification fixed here for money.
- The approved-terms table does not show an fx leg's `to_currency`.
- An unknown execution outcome stays blocked for its run until reload, even once a read shows the
  execution. Lifting it changes the quarantine the screen keeps on purpose; it is a decision.
- The response checks are written by hand against `contracts/`; nothing in the frontend validates
  against the schema.
- A failed read is retried every 5 s with no backoff while it keeps failing with no answer.
- The newest failure's generation never moving back has no test: the three-read out-of-order case
  it guards is not one the suite can stage reliably.

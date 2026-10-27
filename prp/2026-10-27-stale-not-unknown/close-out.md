# A stale account is not unknown (Overview, Lending): Close-out
> Close-out (/dev-close). Source: cross-family review of the T17 screens (finding P2, landed at 5f1ed90).
> Date: 2026-10-27

## What broke
`completeness.missing` names every cash account that is not current, stale and unknown alike.
Overview's partial note called all of them "not observed … read Unknown", and Lending's tile
marked each pool account "? Unknown". 7 h after an observation (stale after 6 h), an account
observed with a value showed as unknown, while Settled cash beside it showed that value as stale.

## What shipped
- API: `completeness.accounts` is a list of `{account_id, status: stale|unknown, as_of}`, one entry
  per id in `missing`, in the same order. `as_of` is the last observation for a stale account
  and null for an unknown one. `NotCurrent` and `Completeness` (backend/app/finance/schemas.py)
  enforce both rules, so the overview route refuses an answer that breaks them.
  `contracts/c6_api.schema.json` is regenerated, and `missing` is kept for existing readers.
- Overview: the partial note names each account with its own state ("◷ Stale, as of …" or
  "? Unknown"). It says that the figures including a stale value say Stale, and that lender
  capacity counts known balances only.
- Lending: the tile reads "Not current, not counted" and marks each pool account Stale (with its
  as-of on a separate line) or Unknown. `freshness()` in `frontend/src/api/v1.js` is the one
  formatter for both screens.
- Examples: `valid-overview-lf-stale` and `valid-lending-lf-stale` are new, recorded from the API
  7 h after the venue-freeze observation, with two stale accounts and the venue unknown. A test
  holds them equal to the API's answer.

## Verification
- Regression tests (they fail on the old code, pass now):
  - money-views.spec.js: "a stale account is not current, and it is not unknown" (3 tests).
  - test_api_v1.py: venue freeze, `test_completeness_is_one_list_of_reasons`,
    `test_the_stale_examples_are_what_the_api_answers`.
- Results: `uv run pytest -q tests/api/test_api_v1.py tests/contracts` 131 passed;
  `npx vitest run` 33 passed; `npm --prefix frontend run build` exit 0; ruff, `checks/no_secrets.py`
  and `checks/attribution.py` ok.
- Browser: Playwright at 390, 768 and 1440, on Overview and Lending served the stale recordings.
  No horizontal overflow at any width, the note fits its box, and funding stays disabled.
- Vet: T3 (an API contract), 2 rounds, 9 applied (5 with a fails-before test), 8 recorded, 0 open.

## Docs updated
- Model and schema docstrings for `NotCurrent` and `Completeness`. README and the system brief do
  not describe this shape, so neither changed.

## Follow-ups / known gaps
- Overview's lender capacity reads `known` when a pool account is unknown, because
  `_pool_capacity` in views.py only considers stale. Lending shows the same K_p as "(known funds
  only)", but Overview does not. This is backend behaviour from before this change and needs its
  own fix.
- Lending still loads the overview to learn which pool accounts are not current, and filters by
  the `pool/` id prefix. The pool's own not-current accounts belong in `LendingResponse`.
- `valid-overview-lf2-venue-freeze` was recorded at a different time from the test harness. Only
  its completeness block was edited here, so it is checked against the schema, not against a
  live answer.

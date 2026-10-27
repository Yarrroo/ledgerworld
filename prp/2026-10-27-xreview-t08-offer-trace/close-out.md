# An offer-backed draw traces to the lender's offer — Close-out
> Close-out (/dev-close). Source: cross-family review of l_9f97cfd532, offer-trace finding (correction card, board item 75).
> Date: 2026-10-27

## What shipped
- `World.trace` found the item an intent acted on by matching a parameter against the intent's
  evidence ids. A `request_advance` names its facility by ledger id (`adv:…`), while the items
  are `offer:adv:…` and `contract:adv:…`. A draw that picks the offer by amount names no facility
  at all. Either way the chain stopped at the borrower's draw and never reached the lender's
  offer intent or the post the lender saw.
- The clearing (`_request_advance`) now records the item a draw used in `WorldState.acted_on`:
  the `offer:` item when one exists, else the facility's `contract:` item (a snapshot's offered
  facility has no offer item). `trace` follows `acted_on` before the parameter match, and the
  `facility_id` match, which could never succeed, is gone.
- `acted_on` is world state, so the round capture pins it and an aborted round restores it.

## Verification
- Reproduced at ff94de2: the five new tests failed with the chain ending at the draw intent.
  All five pass after the fix. They cover a named and an implicit draw, citing either the offer or
  the contract, each tracing to the offer intent and its post, and a draw on an accepted request
  tracing through the accept to the borrower's request and its post.
- `uv run pytest -q tests/simulation checks/tests/test_kpi.py` is green, ruff is clean on the
  changed files, and `checks/attribution.py` and `checks/no_secrets.py` pass. The full gate is the
  landing train's.
- The new tests are registered under `public_shock_traceable_response` in `checks/required.json`.

## Follow-ups / known gaps
- No backfill: the trace is computed on read from world state, and nothing persisted holds a
  wrong chain. A world whose draws cleared before this fix has no `acted_on` entries, so its
  draws still trace only to the draw intent.

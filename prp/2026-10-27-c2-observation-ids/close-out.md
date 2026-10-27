# C2 observation ids — Close-out
> Close-out (/dev-close). Source: T08 cross-review, finding F2 (`world.py:324`).
> Date: 2026-10-27

## What shipped
- `backend/app/simulation/world.py` `World.items_for`: a C2 delivery is now the item
  `c2:r<round>-<n>`, `n` its place among its actor's verdicts that round; the intent id stays in
  the item as data. Before, the item was `c2:<intent_id>`: a schema-valid 128-character intent id
  (rejected `intent_id_too_long`) gave a 131-character evidence id, and an accepted intent plus its
  `duplicate_intent` twin shared one id. Either made the next round's observation builder raise;
  the round aborted and restored the same pending C2, so the world could never advance.
- `tests/simulation/test_coupled.py`
  `test_a_rejected_intent_is_delivered_next_round_without_breaking_it[long_id|duplicate]`: injects
  both cases through the coordinator's `intents` hook in round 1, runs round 2 on a real platform,
  and asserts the round commits and borrower-c sees every verdict once. Failed before the fix
  (`evidence id ... is not a string of 1 to 128 characters`; `item ids repeat in borrower-c's
  observation`), passes after.

## Verification
- `uv run pytest -q tests/simulation/` — 147 passed; `tests/simulation/test_coupled.py` alone
  (the T08 accept) — 33 passed.
- `ruff`, `checks/no_secrets.py`, `checks/attribution.py` — ok. The full merge gate runs on the
  landing batch.

## Docs updated
- Inline comment in `items_for`. No design document names the C2 id scheme; none changed.

## Follow-ups / known gaps
- `refmodel/branch_ref.py:583` still forms `c2:<intent_id>` in the oracle's own evidence set. It is
  a set, never compared with the product's ids, and no fixture or scripted plan names a `c2:` id,
  so nothing breaks; aligning it is optional.
- No backfill: pending C2 lives in world state and round captures only. A world stuck on a bad
  pending C2 recovers on the next run with this code, since the id is recomputed on observation.

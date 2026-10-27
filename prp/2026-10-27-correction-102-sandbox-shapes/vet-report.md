# Vet — board item 102
vet: T3, round 2, 5 applied (4 proven, 0 unproven), 5 recorded

- Tier: T3. The change alters the provider contract on the money path: payout and quote bodies
  and the API version pin. 16 files, test delta present. Instruments: `/code-review high`, then
  `/code-review low` on the round-2 fixes; `/simplify`, done inline because the order runs a
  single agent; `/security-review`, which found nothing.
- Applied with a fails-before test: the fake refuses the transfers paths before 2024-09-27; an
  empty reference falls back; a 200 with no items list is unclear; the fake's `valid_to`
  follows `validity`. Applied as quality: the conversions path comes from the client constant.
- Recorded:
  - The probe does not hand the active id to `gateway_from_env`. Older than this change, and in
    a caller the item does not name.
  - Pagination of the accounts list. One page holds 100 accounts or more; we have one.
  - The length of the gateway's reference. Not measurable without the sandbox.
  - `backend/tests` is not on the ruff path list. The item's check names this path, and the
    file passes ruff.
  - The test's own sandbox model duplicates the fake's. Kept apart on purpose, so the test does
    not trust the fake it checks.
- Coverage: `/code-review` read the whole range in round 1. In round 2 it read the fix diff and
  skipped the test files, which I wrote and ran.

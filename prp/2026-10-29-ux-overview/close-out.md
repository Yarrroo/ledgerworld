# UX 2 — Overview panels O1–O6 — Close-out
> Close-out (/dev-close). Source: prp/2026-10-29-ux-pass/HANDOFF.md (Overview: every panel & action).
> Date: 2026-10-29

## What shipped
- Board item 128: `/overview` rebuilt as panels O1–O6 (`frontend/src/views/Overview.vue`):
  context (complete snapshot id, currency, company, provider, model, as of, Read context again);
  cash strip (settled, spendable, next obligation, reserve headroom; a chosen metric opens the
  inputs the API served for it, and cash and spendable link to their account row on Treasury);
  cash outlook (`frontend/src/components/CashOutlook.vue`: the API's P points as a step path,
  the floor, the API's lowest point marked in its floor state, focusable/hover/tap points,
  View data table); next obligation (amount, exact deadline, reservation, state, funding
  account, deep link to its Treasury row); exposure preview (the snapshot's relationships as
  text, pool capacity, Explore world); hypothetical scenario entry with a read-only preview.
- API (contract C6, additive): `GET /api/v1/overview` gains `company`, `accounts` (Treasury's
  account shape), `outlook` (combined P at now, each flow or deadline in the horizon and its
  end, with what moves it; an overdue item counts at now), `relations`, `scenario`;
  `upcoming_outflows` gain `account` and `reservation_id`. `coverage` is now derived from the
  outlook (one computation). `contracts/c6_api.schema.json` regenerated; the stale overview
  example re-recorded; `valid-overview-demo-baseline.json` recorded (the demo world at its
  epoch) and pinned to the API by `tests/api/test_api_v1.py`.
- Treasury focuses a deep-linked row (`useFocusTarget`, `rowLink` in `frontend/src/api/v1.js`;
  `data-focus` on account sections and obligation rows; `.lw-row--focus` in `tokens.css`) and
  says when the link's snapshot is not the one shown.
- `e2e/judge-path.spec.ts` reads the headroom tile's figure (the old figure was the
  minimum/floor sentence, still checked as text).

## Verification
- `bash scripts/ux-check.sh e2e/ux/overview.spec.ts`: 18/18 at 1440, 834, 390, judge path
  12/12, exit 0 (last run on the final tree). Two earlier runs failed only under a load average of 580+
  (asset fetch stalled 3 min; a navigation past 30 s); one phone tap failure was real (a touch
  pointer leaving cleared the tip) and is fixed.
- `pytest tests/api tests/contracts`: 139 passed. Frontend unit tests: 236 passed. Frontend
  build ok. `ruff`, `checks/no_secrets.py`, `checks/attribution.py` ok. The full
  `checks/merge.sh` is the landing train's.
- Vet: T3 (C6 contract change, money display), two rounds, converged, 0 open; security review
  found nothing.
- Screenshots reviewed at 1440, 834, 390, light and dark: see `ux-sweep.md`.

## Docs updated
- This close-out and `ux-sweep.md`. `docs/schema.md` already names `OverviewResponse` by route; the
  schema itself is generated.

## Follow-ups / known gaps
- `docs/screenshots/overview-fake.png` (README) shows the old Overview; refresh the README
  screenshots once the UX pass has rebuilt the other screens.
- An obligation's payee is the world's entity named by its kind (`payroll`); the snapshot has
  no payee field. A `payee` on obligations would make the exposure preview exact.
- The exposure preview reads lines, exposures and amounts from the observed snapshot, as it
  says; it does not follow later ledger postings.
- The mockup's relationship diagram is a text list here; the handoff asks for text
  relationships, and a drawn map is Simulation's.

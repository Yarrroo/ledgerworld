# T18 · Live Simulation — Close-out
> Close-out (/dev-close). Source: design.md ← briefs/T18.md ← design/modules/ui/HANDOFF.md.
> Date: 2026-10-27

## What shipped
- `frontend/src/views/Simulation.vue` — the `/simulation?run_id=` screen: one committed-round
  cursor drives cash paths, action feed, the reused upstream graph view and an actor inspector;
  running / complete / invalid / cancelled states; replay labels; local playback; fork and
  read-only interview behind the in-memory demo token; round export.
- `frontend/src/components/{Scrubber,ActionFeed,CashPaths}.vue` — the three panels.
- `frontend/tests/unit/simulation-view.spec.js` — every `scrubber.json` case plus one test per
  applied review finding (19 tests).
- Wiring: `/simulation` route in `frontend/src/router/index.js` (row updated in `ATTRIBUTION.md`);
  Overview's existing "Open simulation" link now resolves to it.

## Verification
- Accept: `npm --prefix frontend ci && npm --prefix frontend run build && npm --prefix frontend run
  test:unit -- tests/unit/simulation-view.spec.js` — exit 0 (19 passed); all unit specs 49 passed.
- Merge-gate parts this change touches: frontend build green, `checks/no_secrets.py` ok,
  `checks/attribution.py` ok. Python lint/tests untouched by this diff and left to the landing train.
- Browser: Playwright sweep at 390 / 768 / 1440, light and dark, reduced motion — `ux-sweep.md`.
- Vet: T2, 2 rounds, 10 applied (9 proven, 0 unproven), 5 recorded, 0 open.

## Docs updated
- `README.md` names the `/simulation?run_id=` screen beside the observed-state screens.

## Follow-ups / known gaps
- C6 RunResponse has no per-round lender capacity (K_p); the spec carries the fixture's K_p on a
  cash path. A capacity series is a C6 change for the API owner.
- The reused graph is restyled from outside (inverted for the dark panel, 44 px toolbar); a proper
  dark variant belongs in `GraphPanel.vue`, an upstream file.
- `Compare policies` points at `/decisions`, which T19 adds; until then it is disabled with a reason.

## Vet record
Recorded, not applied: response arrays absent (C6 requires them; the API validates against the
schema), a status outside the five-value enum (same), and three quality notes (cash-point lookup
shared with `api/v1.js`, which this task does not own; the export is one small round; the graph restyle needs the upstream file).

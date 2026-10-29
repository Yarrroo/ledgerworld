# UX 8 states and the h0 demo baseline — Close-out
> Close-out (/dev-close). Source: prp/2026-10-29-ux-pass/HANDOFF.md "Loading, empty & failure states"; board items 134 and 141.
> Date: 2026-10-29

## What shipped
- **134, the states on all six screens**, mostly in the shared shell (`frontend/src/api/v1.js`):
  - Loading: skeleton tiles and one polite "Loading <screen>…".
  - No prepared run (`noDemoRun()`): an inline explanation, also when a refresh finds the demo gone.
  - Read errors: "Could not load" with Retry; "Could not refresh. Last loaded, not current." keeps the last body.
  - Stale: a band naming each stale account and its as of.
  - Treasury S and Lending K_p carry a status line (`metricStatus`), so Known 0, Unknown and Not assessed read apart.
  - Execution says Operator access and Forget access.
  - Live simulation opened from the nav reads the prepared run once and names it in the URL.
- **141, the h0 baseline**: with a prepared demo, `Services.observed()` serves the snapshot the app was built on, at its own as_of (the demo world's h0: settled 70,000, spendable 20,000, payroll at h40). Before, it served the run's h12 observation. Simulation, Decisions and Execution keep the run's own snapshot. The system brief (00-system.md) says so.

## Verification
- `bash scripts/ux-check.sh e2e/ux/states.spec.ts`: 21/21 at 1440, 834 and 390 px, then the judge path at 12/12. The spec forces each state through a mocked API.
- `bash scripts/ux-check.sh` also green on overview.spec.ts (141's check), decisions.spec.ts and simulation.spec.ts.
- `uv run pytest -q backend/tests/test_demo_baseline_h0.py`: it failed before the fix (`obs-demo-r3-demo-h0 != demo-world`); it passes after, together with `test_demo_baseline_after_prepare.py` and `tests/api`, 72 tests in all.
- vitest: 256 passed. That includes two Simulation tests and one Decisions test that each failed before their vet fix. `ruff`, `no_secrets`, `attribution` and the frontend build are green.
- Full `checks/merge.sh` not run here: that is the landing train's.

## Vet
T2, round 2, 8 applied (3 proven), 16 recorded, 0 open. The recorded findings, with reasons:
- After a prepare, the baseline and the live store share one snapshot id. That is the intended h0 world; contextKey cannot tell them apart.
- Execution's header falls back to the overview's snapshot when no execution exists. This was already the case before item 137; a prepared demo always has an execution.
- `self.snapshot` versus `load_world()`: the app is built on `load_world()`.
- Overview shows both the band and its partial note: the band is the handoff's warning band, while the note also lists unknown accounts.

## Follow-ups / known gaps
- Treasury's response has no not-current account list, unlike Overview's (`completeness`) and Lending's (`unobserved`). The shell could read one shared field if the backend sent one (altitude finding, not done here).
- Simulation and Execution read the whole /overview just to learn `demo.run_id`. A small endpoint for that would be cheaper.

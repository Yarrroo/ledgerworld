# UX 0 + UX 1 — Close-out
> Close-out (/dev-close). Source: design.md ← prp/2026-10-29-ux-pass/HANDOFF.md.
> Date: 2026-10-29

## What shipped
- Board item 126: `prp/2026-10-29-ux-pass/HANDOFF.md` verbatim from `design/ux-pass`;
  `scripts/ux-check.sh SPEC` and `scripts/ux_app.py` (offline app: fake provider, SQLite,
  prepared demo run, in-process fakeredis, never an inherited Redis); `e2e/ux.config.ts`
  (1440/834/390, video on); `e2e/ux/smoke.spec.ts`, `e2e/ux/routes.ts`.
- Board item 127: the shared shell in `frontend/src/api/v1.js` (sidebar, icon rail, phone header
  with a modal drawer, breadcrumb, context bar with model from `/health`, panel index with scroll
  highlight), the ivory system in `frontend/src/styles/tokens.css`, self-hosted Source Serif 4 and
  Inter (`@fontsource-variable/*`, new dependencies), no font CDN in `frontend/index.html`,
  `data-panel` marks in the six views, `e2e/ux/shell.spec.ts`; the judge path opens the phone
  drawer before its nav visits.

## Verification
- `bash scripts/ux-check.sh e2e/ux/smoke.spec.ts`: 3/3, then judge path 12/12, slowest 6.1 s, exit 0.
- `bash scripts/ux-check.sh e2e/ux/shell.spec.ts`: 13/13 (one drawer test is phone-only), judge path 12/12, exit 0.
- Frontend unit tests 222/222, offline; frontend build ok; `pytest tests/demo deploy/tests checks/tests` 330 passed;
  ruff, `no_secrets`, `attribution` ok. The full `checks/merge.sh` is the landing train's.
- Vet: T2, two rounds, converged; see the run's report.

## Docs updated
- README: the `ux-check.sh` line under Tests. `ATTRIBUTION.md`: `index.html`, the font dependencies.

## Follow-ups / known gaps
- The logo is a drawn faceted stand-in until the exact vector asset exists.
- The Simulation live panel keeps its dark instrument styling (a later UX pass).
- Upstream research screens fall back to local fonts now that the font CDN is gone.
- `deploy/serve.py` builds its module-level app on import, so `ux_app.py` builds the app twice;
  a `services` parameter on `serve.build` would remove that and the `Services.from_env` patch.

# AGPL source link required at image build — Close-out
> Close-out (/dev-close). Source: cross-family review of the T17 screens (P2, `frontend/src/api/v1.js:362`).
> Date: 2026-10-27

## What broke
`ScreenShell` renders the "Source code (AGPL-3.0)" footer only when the bundle was built with
`VITE_SOURCE_URL`. `deploy/Dockerfile` neither declared nor checked that build argument, so the image
`deploy/compose.yml` builds served every screen without the source link (system brief §3, AGPL §13).

## What shipped
- `deploy/Dockerfile`: the frontend stage takes `ARG VITE_SOURCE_URL` and stops the build, before
  `npm run build`, unless it is an http(s) URL with a host and no space, quote or angle bracket.
  The documented build line passes `--build-arg VITE_SOURCE_URL=<public source URL>`.
- `deploy/compose.yml` passes it as a build argument (`${VITE_SOURCE_URL:-}`); `deploy/host.toml`
  names it under `[build].required`; `.env.example` names it.
- `deploy/tests/test_deploy_config.py`: the stage's check run under `/bin/sh` (13 refused values,
  2 accepted), its place between the ARG and the build, compose wiring, the documented build line.
- `frontend/tests/unit/source-link.spec.js`: Overview, Treasury and Lending, built as the image
  builds them, each loaded and carrying the link in its footer.

## Verification
- `uv run pytest -q deploy/tests` — 45 passed; the new cases failed before the fix (11, then 7 more in vet).
- `npx vitest run` — 110 passed; T17's accept (`ci && build && test:unit money-views.spec.js`) — 33 passed.
- ruff, `checks/no_secrets.py`, `checks/attribution.py` — clean.
- A real `vite build` with the argument embeds the URL; a Playwright sweep of that build at
  390×844, 768×1024 and 1440×900 found the link on all three screens with no horizontal scroll.
- No Docker on the build box: the image itself was not built here.

## Follow-ups / known gaps
- The deploy host's env file must set `VITE_SOURCE_URL` (the public repository URL) before the
  next image build, or that build stops with the variable's name.
- `checks/merge.sh` does not run the frontend unit tests (`npm run test:unit`); the pytest
  regression is the gate-enforced one.
- The footer link carries the browser's default styling and an 18 px line box (unchanged here).

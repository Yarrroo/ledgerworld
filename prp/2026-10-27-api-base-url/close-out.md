# The API base "/" reaches the page's origin — close-out

> Close-out (/dev-close). Source: a review finding on T17 (Overview, Treasury and Lending).
> Date: 2026-10-27. Board item 85.

## What broke, and why

The image builds the frontend with `VITE_API_BASE_URL=/` (deploy/Dockerfile) so every API call
stays on the page's own origin. `request()` in `frontend/src/api/v1.js` joined the base as
`${BASE}/api/v1${path}`, which made `//api/v1/overview`: a protocol-relative URL to a host called
`api`. All three reading screens failed in the deployed image, and a request carrying a bearer
token would have sent it to that host.

## What landed

- `apiUrl(path, base)` in `frontend/src/api/v1.js` trims the base's trailing slashes and the
  path's leading ones and joins them with exactly one; an empty path names `<base>/api/v1`.
  `request()` uses it.
- `frontend/tests/unit/api-url.spec.js`: `"/"`, `""`, `"//"`, absolute origins and path prefixes,
  with and without trailing slashes, resolved against a page URL; and `v1.js` re-imported under
  each `VITE_API_BASE_URL` to check the URL `fetch()` receives for every screen.
- The axios client (`frontend/src/api/index.js`) reads the same variable and already joins with
  one slash (checked: base `/` + `/api/graph/x` gives `/api/graph/x`). It needs no change.

## Verification

- Before the fix, the request test received `//api/v1/overview` (12 of 12 cases failed); after
  it, `npm --prefix frontend run test:unit` passes 44 of 44, `build` exits 0.
- `checks/no_secrets.py` and `checks/attribution.py`: ok. No Python changed.
- Browser: a build with `VITE_API_BASE_URL=/` served beside recorded C6 answers, driven at 390,
  768 and 1440 px. All three screens loaded with no error and no horizontal scroll, and every
  request went to `/api/v1/…` on the serving origin.
- Vet: T2, 2 rounds, 5 applied (1 proven), 4 recorded, 0 open. See `vet-report.md`.

## Follow-ups

- `checks/merge.sh` runs the frontend build but not `test:unit`, so neither this spec nor
  `money-views.spec.js` is part of the merge gate.
- An inline "Its parts on Lending" link on Overview is 18 px tall at 768 px (an inline text link,
  exempt from WCAG 2.5.8). It predates this change.

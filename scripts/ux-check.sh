#!/usr/bin/env bash
# The interaction check: one Playwright spec, in motion, against the app on this machine.
#
#   bash scripts/ux-check.sh SPEC        e.g. bash scripts/ux-check.sh e2e/ux/smoke.spec.ts
#
# Builds the frontend into a fresh mktemp directory, starts the app offline (scripts/ux_app.py:
# fake provider, SQLite, the prepared demonstration run, an in-process job queue), runs SPEC at
# 1440, 834 and 390 px with video on (e2e/ux.config.ts), then the judge path
# (scripts/judge-path.sh) against the same app. Installs the frontend and e2e dependencies
# and chromium when missing. A passing run removes its directory; a failing one keeps it (videos,
# screenshots, the app log) and names it. Exit 0 only when both runs passed.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
e2e="$root/e2e"

usage() { echo "usage: bash scripts/ux-check.sh SPEC   (a spec under e2e/ux/)" >&2; exit 2; }
(($# == 1)) || usage
spec="$(cd "$root" && realpath -m "$1")"
[[ "$spec" == "$e2e/ux/"*.spec.ts && -f "$spec" ]] || { echo "ux-check: no spec $1 under e2e/ux/" >&2; usage; }

out="$(mktemp -d "${TMPDIR:-/tmp}/ux-check.XXXXXX")"
app=""
stop() { [[ -n "$app" ]] && kill "$app" 2>/dev/null && wait "$app" 2>/dev/null; app=""; }
trap stop EXIT
fail() { stop; echo "ux-check: $1; output kept in $out" >&2; exit 1; }

if [[ ! -d "$root/frontend/node_modules" ]]; then
  npm --prefix "$root/frontend" ci --no-audit --no-fund >&2 || fail "frontend npm ci failed"
fi
if [[ ! -d "$e2e/node_modules/@playwright/test" ]]; then
  npm --prefix "$e2e" install --no-audit --no-fund --no-package-lock >&2 || fail "e2e npm install failed"
fi
(cd "$e2e" && npx --no-install playwright install chromium >&2) || fail "chromium install failed"

# the image's build: every API call relative to the page's own origin
(cd "$root/frontend" && VITE_API_BASE_URL=/ npx --no-install vite build --outDir "$out/dist" \
  --emptyOutDir >"$out/build.log" 2>&1) || fail "the frontend build failed (build.log)"

uv run --project "$root" python "$root/scripts/ux_app.py" --dist "$out/dist" --data "$out/data" \
  >"$out/app.log" 2>&1 &
app=$!
url=""
for _ in $(seq 1 600); do
  url="$(sed -n 's/^ux-app: ready //p' "$out/app.log")"
  [[ -n "$url" ]] && break
  kill -0 "$app" 2>/dev/null || fail "the app stopped before it was ready (app.log)"
  sleep 0.5
done
[[ -n "$url" ]] || fail "the app was not ready in 300 s (app.log)"
echo "ux-check: app at $url ($(sed -n 's/^ux-app: //p' "$out/app.log" | head -n 1))" >&2

(cd "$e2e" && UX_URL="$url" UX_OUT="$out" npx --no-install playwright test --config ux.config.ts \
  "${spec#"$e2e/"}" >&2) || fail "$(basename "$spec") failed (videos under artifacts/)"
echo "ux-check: $(basename "$spec") passed at 1440, 834 and 390 px" >&2

bash "$root/scripts/judge-path.sh" "$url" >&2 || fail "the judge path failed against $url"

stop
rm -rf "$out"
echo "ux-check: green"

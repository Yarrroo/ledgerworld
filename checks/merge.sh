#!/usr/bin/env bash
# The merge gate: lint new code, secrets, attribution, offline tests, frontend build.
set -euo pipefail
cd "$(dirname "$0")/.."
# A uv.lock that no longer matches pyproject.toml fails the gate instead of being re-locked.
export UV_LOCKED=1

# New-code paths (system brief §16); upstream code is not linted.
candidates=(
  backend/app/finance backend/app/simulation backend/app/decisions backend/app/execution
  backend/app/connectors/airwallex backend/app/api/v1 backend/app/jobs backend/app/reports
  backend/app/demo backend/app/testing
  packages/oasis-finance checks deploy e2e
  tests/contracts tests/fixtures tests/finance tests/simulation tests/decisions
  tests/connectors tests/execution tests/api tests/reports tests/demo tests/hunt tests/testing
  tests/test_skeleton.py
)
lint_paths=()
for path in "${candidates[@]}"; do
  [[ -e "$path" ]] && lint_paths+=("$path")
done

echo "== ruff (${#lint_paths[@]} paths)"
uv run ruff check "${lint_paths[@]}"

echo "== no_secrets"
uv run python checks/no_secrets.py

echo "== attribution"
uv run python checks/attribution.py

echo "== pytest"
uv run pytest -q

if [[ -d frontend/node_modules ]]; then
  echo "== frontend build"
  npm --prefix frontend run build
else
  echo "== frontend build skipped (frontend/node_modules absent)"
fi

echo "merge gate: green"

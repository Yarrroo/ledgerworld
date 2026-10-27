#!/usr/bin/env bash
# The demo, one command: freeze the snapshot, apply the delayed-receipt + rumour shock, run fresh
# branches, select the plan, execute the advance and the payout, reconcile, write a receipt.
#
#   bash scripts/demo.sh --mode fake|sandbox --out FILE [--seed N]
#                        [--beneficiary ID] [--connected-account ID]   (sandbox only)
#
# Sandbox with scripted agents (no model key): set LLM_BASE_URL=scripted://family.
# The receipt records model: scripted independently of the sandbox provider mode.
# Validate the receipt with: uv run python checks/demo_receipt.py FILE [--require-live]
# The steps and the modes are documented in backend/app/demo/run.py.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
# This tree's own sources first, ahead of any installed copy of the workspace members.
export PYTHONPATH="$root/backend:$root/packages/oasis-finance/src${PYTHONPATH:+:$PYTHONPATH}"
exec uv run --project "$root" python -m app.demo.run "$@"

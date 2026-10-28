#!/usr/bin/env bash
# Start one LedgerWorld process, chosen by LEDGERWORLD_ROLE:
#   api     the Flask app (/api/v1 and the upstream engine's routes) and the built frontend,
#           on port 5001; the only role that holds the Airwallex credentials
#   sim     the simulation job worker (python -m app.jobs)
#   worker  the same job worker: its jobs are simulation, so it runs as sim
# The sim role starts with every AIRWALLEX_* name removed from its environment and with
# LEDGERWORLD_ROLE=sim exported, so code that checks the role sees a simulation process.
# Every role takes its settings from the environment alone: the app loads a .env file with
# override on import, which would put back what the scrub removed, so dotenv is disabled.
# With arguments, the role's environment is prepared and the arguments run in it instead
# (a shell, a one-off script): `entrypoint.sh env` shows exactly what the role would see.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
role="${LEDGERWORLD_ROLE:-}"
export PYTHON_DOTENV_DISABLED=1

case "$role" in
  api) ;;
  sim | worker)
    for name in $(compgen -e); do
      if [[ "${name^^}" == AIRWALLEX_* ]]; then
        unset "$name"
      fi
    done
    role=sim
    export LEDGERWORLD_ROLE=sim
    ;;
  *)
    echo "LEDGERWORLD_ROLE must be api, worker or sim (got '${role}')" >&2
    exit 64
    ;;
esac

if (($# > 0)); then
  exec "$@"
fi

cd "$root/backend"
if [[ "$role" == sim ]]; then
  exec python -m app.jobs
fi

# api: the app and the built frontend from one origin (deploy/serve.py), under gunicorn: one
# worker, because the upstream engine keeps its task and simulation registries in the process,
# with threads for concurrency, as the development server ran it.
exec gunicorn --pythonpath "$root/deploy" --bind 0.0.0.0:5001 --workers 1 --threads 8 \
  --timeout 120 --no-control-socket --access-logfile - serve:application

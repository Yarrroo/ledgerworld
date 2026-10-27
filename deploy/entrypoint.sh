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

# api: the app and the built frontend from one origin. A GET for a frontend route (not an API
# path, no file extension) that is not a file of the build gets index.html, so the frontend's
# own routes survive a reload; anything else the build lacks goes to the app, which 404s it.
# It starts without backend/run.py's key check on purpose: with no model or graph-memory key the
# app still serves the scripted, fake-provider demo.
exec python - "$root/frontend/dist" <<'PY'
import sys
from pathlib import Path

from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.serving import run_simple

from app import create_app

app = create_app()
dist = Path(sys.argv[1])
index = (dist / "index.html").read_bytes() if (dist / "index.html").is_file() else None


def pages(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    route = (environ.get("REQUEST_METHOD") in ("GET", "HEAD") and not path.startswith("/api/")
             and path != "/health" and "." not in path.rsplit("/", 1)[-1])
    if index is None or not route:
        return app(environ, start_response)
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                              ("Content-Length", str(len(index))),
                              ("Cache-Control", "no-cache")])
    return [index]


served = SharedDataMiddleware(pages, {"/": str(dist)}) if dist.is_dir() else app
run_simple("0.0.0.0", 5001, served, threaded=True)
PY

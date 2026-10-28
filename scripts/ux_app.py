"""The app on this machine, offline, for the UX checks: fake provider, SQLite, a prepared demo run.

    uv run python scripts/ux_app.py --dist DIR --data DIR [--port N]

One process holds what the deployed pair (api + sim) holds: the app and the built frontend from
one origin (deploy/serve.py), a simulation worker on a thread, and the job queue on an in-process
fakeredis. The ledger and the job records are a SQLite file in --data. An inherited REDIS_URL is
removed, never used: a worker here would take another deployment's jobs, and a fresh database
here could not answer them. Before it serves, it prepares the demonstration run and its reconciled execution
with the operator command's own code (app.demo.prepare), so Overview names a run and Execution a
receipt, as on a prepared deployment.

It runs with AIRWALLEX_MODE=fake and every AIRWALLEX_*, model and graph-memory setting removed, so
it never reaches a provider or a model; the worker's families are scripted. Serving, it prints
`ux-app: ready <url>` and serves until it is stopped. scripts/ux-check.sh drives it.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRUB = ("AIRWALLEX_", "LLM_", "ZEP_", "LEDGERWORLD_DEMO_TOKEN", "REDIS_URL")


def offline_env(data: Path) -> str:
    """Make this process a fake-provider, scripted-model app on ``data``'s SQLite file, with no
    queue of anyone else's; return that file's URL."""
    for name in list(os.environ):
        if name.upper().startswith(SCRUB):
            del os.environ[name]
    url = f"sqlite:///{data / 'app.sqlite'}"
    os.environ["AIRWALLEX_MODE"] = "fake"
    os.environ["LEDGER_DATABASE_URL"] = url
    # the upstream config loads a .env with override on import; nothing may come back from one
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dist", type=Path, required=True, help="the built frontend")
    parser.add_argument("--data", type=Path, required=True, help="a directory for the SQLite file")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port (default)")
    parser.add_argument("--timeout", type=float, default=300,
                        help="seconds the demo preparation may take (default: 300)")
    args = parser.parse_args(argv)
    dist = args.dist.resolve()
    if not (dist / "index.html").is_file():
        parser.error(f"{dist} holds no index.html: build the frontend first")
    data = args.data.resolve()
    data.mkdir(parents=True, exist_ok=True)
    url = offline_env(data)
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "packages/oasis-finance/src"),
                    str(ROOT / "deploy")]
    os.chdir(data)  # the upstream engine writes ./log beside its working directory

    import fakeredis
    from app.api.v1.services import Services, gateway_from_env
    from app.demo import prepare
    from app.finance.store import LedgerStore
    from app.jobs.queue import JobQueue, Worker
    from app.jobs.runner import Runner
    from app.jobs.store import JobStore
    from app.simulation.scenarios import load_world
    from werkzeug.serving import make_server

    redis = fakeredis.FakeRedis()
    world = load_world()
    services = Services.build(world.snapshot, store=LedgerStore(url), redis=redis,
                              epoch=world.epoch, mode="fake", token=None,
                              make_gateway=gateway_from_env)
    services.gateway()

    # the sim role's worker, on a store handle of its own as the deployed worker has
    worker_store = JobStore(LedgerStore(url).engine)
    worker = Worker(JobQueue(worker_store, redis), Runner(worker_store, data / "jobs").handlers())
    threading.Thread(target=lambda: worker.run_forever(idle_s=0.05), name="sim-worker",
                     daemon=True).start()

    context = prepare.prepare(services, timeout=args.timeout)
    print(f"ux-app: demo run {context['run_id']} execution {context['execution_id']}", flush=True)

    # deploy/serve.py mounts /api/v1 on Services.from_env(): here, the store just prepared
    Services.from_env = classmethod(lambda cls: services)
    import serve

    server = make_server("127.0.0.1", args.port, serve.build(dist), threaded=True)
    print(f"ux-app: ready http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

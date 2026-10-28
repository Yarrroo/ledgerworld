"""The api role's WSGI application: the app and the built frontend from one origin, under gunicorn.

    gunicorn --pythonpath deploy serve:application   (from backend/, as deploy/entrypoint.sh runs it)

A GET for a frontend route (not an API path, no file extension) that is not a file of the build
gets index.html, so the frontend's own routes survive a reload; anything else the build lacks goes
to the app, which 404s it. Every response, the frontend's files included, carries the security
headers (`app.api.v1.hardening`). It starts without backend/run.py's key check on purpose: with no
model or graph-memory key the app still serves the scripted, fake-provider demo.
"""

from __future__ import annotations

from pathlib import Path

from werkzeug.middleware.shared_data import SharedDataMiddleware

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def build(dist: Path):
    from app import create_app
    from app.api.v1 import hardening

    app = create_app()
    index = (dist / "index.html").read_bytes() if (dist / "index.html").is_file() else None

    def pages(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        route = (environ.get("REQUEST_METHOD") in ("GET", "HEAD")
                 and path.lstrip("/").split("/", 1)[0] not in ("api", "health")
                 and "." not in path.rsplit("/", 1)[-1])
        if index is None or not route:
            return app(environ, start_response)
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                  ("Content-Length", str(len(index))),
                                  ("Cache-Control", "no-cache")])
        return [index]

    served = SharedDataMiddleware(pages, {"/": str(dist)}) if dist.is_dir() else app
    return hardening.wrap(served)


application = build(DIST)

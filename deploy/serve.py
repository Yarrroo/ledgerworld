"""The api role's WSGI application: the app and the built frontend from one origin, under gunicorn.

    gunicorn --pythonpath deploy serve:application   (from backend/, as deploy/entrypoint.sh runs it)

A GET for a frontend route (not an API path, no file extension) that is not a file of the build
gets index.html, so the frontend's own routes survive a reload, its link-preview URLs made absolute
on LEDGERWORLD_URL's origin (the request's own when that is unset or not a URL); anything else the
build lacks goes to the app, which 404s it. Every response, the frontend's files included, carries
the security headers (`app.api.v1.hardening`). It starts without backend/run.py's key check on
purpose: with no model or graph-memory key the app still serves the scripted, fake-provider demo.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.wsgi import get_host

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
ORIGIN_MARK = b"__LEDGERWORLD_URL__"  # frontend/index.html's placeholder for the public origin


def build(dist: Path):
    from app import create_app
    from app.api.v1 import hardening

    app = create_app()
    template = (dist / "index.html").read_bytes() if (dist / "index.html").is_file() else None
    url = os.environ.get("LEDGERWORLD_URL", "").strip()
    parts = urlsplit(url)
    public = (hardening.allowed_origins(url)[0]
              if parts.scheme.lower() in ("http", "https") and parts.hostname else None)
    filled = template.replace(ORIGIN_MARK, public.encode()) if template and public else None

    def index(environ) -> bytes:
        if filled is not None:
            return filled
        # no public origin: the request's own; get_host answers "" for a Host that is not one
        host = get_host(environ) or environ.get("SERVER_NAME", "localhost")
        return template.replace(ORIGIN_MARK, f"{environ['wsgi.url_scheme']}://{host}".encode())

    def pages(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        route = (environ.get("REQUEST_METHOD") in ("GET", "HEAD")
                 and path.lstrip("/").split("/", 1)[0] not in ("api", "health")
                 and (path == "/index.html" or "." not in path.rsplit("/", 1)[-1]))
        if template is None or not route:
            return app(environ, start_response)
        body = index(environ)
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                  ("Content-Length", str(len(body))),
                                  ("Cache-Control", "no-cache")])
        return [body]

    if not dist.is_dir():
        return hardening.wrap(app)
    files = SharedDataMiddleware(pages, {"/": str(dist)})

    def served(environ, start_response):
        # /index.html is the page itself, filled, never the build's raw file
        if environ.get("PATH_INFO") == "/index.html":
            return pages(environ, start_response)
        return files(environ, start_response)

    return hardening.wrap(served)


application = build(DIST)

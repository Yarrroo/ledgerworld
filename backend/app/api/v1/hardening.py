"""CORS and security headers (Security 5), installed on the whole app by `create_app`.

Cross-origin calls to `/api/*` are allowed only from LEDGERWORLD_URL's origin (the demo's public
address); with it unset, only from the local frontend dev server, whose bundle calls
http://localhost:5001 from port 3000. The app and the built frontend share one origin, so the demo
itself needs no CORS at all.

Every response carries `SECURITY_HEADERS` unless it already sets one of them. `wrap` applies them
to a whole WSGI app, so the api role's server adds them to the frontend files it serves as well.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

from flask import Flask
from flask_cors import CORS

DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Content-Security-Policy", "frame-ancestors 'none'"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
)


def allowed_origins(url: str | None = None) -> list[str]:
    """LEDGERWORLD_URL's scheme://host[:port], else the local dev server's origins."""
    url = (os.environ.get("LEDGERWORLD_URL", "") if url is None else url).strip()
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and parts.netloc:
        return [f"{parts.scheme}://{parts.netloc}".lower()]
    return list(DEV_ORIGINS)


def wrap(wsgi: Callable[..., Iterable[bytes]]) -> Callable[..., Iterable[bytes]]:
    """``wsgi`` with every missing security header added to each response it starts."""

    def secured(environ: dict[str, Any], start_response: Callable[..., Any]):
        def start(status: str, headers: list[tuple[str, str]], exc_info: Any = None):
            present = {name.lower() for name, _ in headers}
            headers = list(headers) + [
                (name, value) for name, value in SECURITY_HEADERS if name.lower() not in present
            ]
            return start_response(status, headers, exc_info)

        return wsgi(environ, start)

    return secured


def install(app: Flask) -> None:
    CORS(app, resources={r"/api/*": {"origins": allowed_origins()}})
    app.wsgi_app = wrap(app.wsgi_app)  # type: ignore[method-assign]

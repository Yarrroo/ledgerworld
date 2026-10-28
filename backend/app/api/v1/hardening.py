"""CORS and security headers (Security 5), installed on the whole app by `create_app`.

Cross-origin calls to `/api/*` are allowed only from LEDGERWORLD_URL's origin (the demo's public
address); with it unset, only from the local frontend dev server, whose bundle calls
http://localhost:5001 from port 3000. The app and the built frontend share one origin, so the demo
itself needs no CORS at all.

Every response of the app carries `SECURITY_HEADERS` unless it already sets one of them; `wrap`
applies them to a whole WSGI app, which the api role's server uses for the frontend files it serves.
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
    scheme = parts.scheme.lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    if scheme not in ("http", "https") or not parts.hostname:
        return list(DEV_ORIGINS)
    default = 443 if scheme == "https" else 80
    suffix = f":{port}" if port and port != default else ""
    return [f"{scheme}://{parts.hostname}{suffix}"]


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

    @app.after_request
    def security_headers(response):
        for name, value in SECURITY_HEADERS:
            response.headers.setdefault(name, value)
        return response

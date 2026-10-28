"""Security 5: CORS only from the demo origin, no public SECRET_KEY, security headers everywhere.

The api role's production server (gunicorn, not Werkzeug's) is checked with the rest of the
container in deploy/tests/test_deploy_config.py.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from app import create_app
from app.api.v1.hardening import DEV_ORIGINS, allowed_origins

CONFIG = Path(__file__).resolve().parents[1] / "app" / "config.py"
DEMO = "https://ledgerworld.example.net"


def make_client(monkeypatch, url: str | None):
    monkeypatch.delenv("REDIS_URL", raising=False)
    if url is None:
        monkeypatch.delenv("LEDGERWORLD_URL", raising=False)
    else:
        monkeypatch.setenv("LEDGERWORLD_URL", url)
    return create_app().test_client()


def preflight(client, origin: str, path: str = "/api/v1/health"):
    return client.options(path, headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
    })


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/simulation/list", "/api/report/list"])
def test_cors_answers_only_the_demo_origin(monkeypatch, path):
    client = make_client(monkeypatch, DEMO + "/overview?x=1")
    ok = client.get(path, headers={"Origin": DEMO})
    assert ok.headers.get("Access-Control-Allow-Origin") == DEMO
    for other in ("https://evil.example", "http://localhost:3000", "null"):
        resp = client.get(path, headers={"Origin": other})
        assert "Access-Control-Allow-Origin" not in resp.headers
        assert "Access-Control-Allow-Origin" not in preflight(client, other, path).headers
    assert preflight(client, DEMO, path).headers.get("Access-Control-Allow-Origin") == DEMO


def test_without_a_demo_origin_only_the_local_dev_server_is_allowed(monkeypatch):
    client = make_client(monkeypatch, None)
    for origin in DEV_ORIGINS:
        assert client.get("/api/v1/health", headers={"Origin": origin}).headers.get(
            "Access-Control-Allow-Origin") == origin
    resp = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in resp.headers


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://LedgerWorld.example.net/path", ["https://ledgerworld.example.net"]),
        ("http://127.0.0.1:5001", ["http://127.0.0.1:5001"]),
        ("https://demo.example.net:443/", ["https://demo.example.net"]),
        ("http://demo.example.net:80", ["http://demo.example.net"]),
        ("https://user:pw@demo.example.net:8443", ["https://demo.example.net:8443"]),
        ("https://demo.example.net:notaport", ["https://demo.example.net"]),
        ("", list(DEV_ORIGINS)),
        ("  ", list(DEV_ORIGINS)),
        ("ledgerworld.example.net", list(DEV_ORIGINS)),
        ("*", list(DEV_ORIGINS)),
    ],
)
def test_the_allowed_origin_is_the_demo_url_s_origin(url, expected):
    assert allowed_origins(url) == expected


@pytest.mark.parametrize(
    "path", ["/health", "/api/v1/health", "/api/simulation/list", "/api/nope", "/api/report/a.b"]
)
def test_every_response_carries_the_security_headers(monkeypatch, path):
    resp = make_client(monkeypatch, DEMO).get(path)
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def secret_key(monkeypatch, value: str | None) -> str:
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")  # a checkout's .env must not decide
    if value is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", value)
    return runpy.run_path(str(CONFIG))["Config"].SECRET_KEY


def test_the_secret_key_comes_from_the_environment(monkeypatch):
    assert secret_key(monkeypatch, "from-the-environment") == "from-the-environment"


@pytest.mark.parametrize("value", [None, ""])
def test_without_one_the_secret_key_is_random_never_a_public_default(monkeypatch, value):
    first, second = secret_key(monkeypatch, value), secret_key(monkeypatch, value)
    assert first != second
    assert len(first) >= 64
    assert "mirofish" not in first

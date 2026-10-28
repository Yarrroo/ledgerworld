"""The original blueprints must not bypass the demo's write authorization."""

import ipaddress
import uuid

import pytest
from app import create_app

PREFIXES = ("/api/graph", "/api/simulation", "/api/report")


@pytest.fixture
def legacy_app(monkeypatch, offline_legacy_services):
    token = uuid.uuid4().hex
    monkeypatch.setenv("LEDGERWORLD_DEMO_TOKEN", token)
    app = create_app()
    app.config.update(TESTING=True)
    return app, token


def legacy_rules(app):
    return [rule for rule in app.url_map.iter_rules()
            if any(rule.rule.startswith(prefix + "/") for prefix in PREFIXES)]


def rule_path(rule):
    return rule.build({name: 1 if name == "section_index" else "existing_id"
                       for name in rule.arguments})[1]


def test_every_legacy_non_get_requires_token(legacy_app):
    app, token = legacy_app
    client = app.test_client()
    calls = []
    # Each auth case is independent; the write-limit suite covers repeated clients.
    clients = ipaddress.ip_network("198.18.0.0/15").hosts()

    def reached(**kwargs):
        calls.append(kwargs)
        return {"reached": True}

    for rule in legacy_rules(app):
        app.view_functions[rule.endpoint] = reached
        for method in rule.methods - {"GET"}:
            for header in (None, "Bearer wrong", "Basic " + token, "Bearer " + token + "x"):
                headers = {} if header is None else {"Authorization": header}
                response = client.open(rule_path(rule), method=method, headers=headers,
                                       environ_overrides={"REMOTE_ADDR": str(next(clients))})
                assert response.status_code == 401, (rule.rule, method, header)
                assert not calls
            response = client.open(rule_path(rule), method=method,
                                   headers={"Authorization": "Bearer " + token},
                                   environ_overrides={"REMOTE_ADDR": str(next(clients))})
            assert response.status_code == 200, (rule.rule, method)
            calls.clear()


def test_legacy_get_remains_public(legacy_app):
    app, _ = legacy_app
    for rule in legacy_rules(app):
        app.view_functions[rule.endpoint] = lambda **kwargs: {"reached": True}
        if "GET" in rule.methods:
            assert app.test_client().get(rule_path(rule)).status_code == 200


def test_unconfigured_token_admits_nobody(monkeypatch, offline_legacy_services):
    monkeypatch.delenv("LEDGERWORLD_DEMO_TOKEN", raising=False)
    app = create_app()
    response = app.test_client().post("/api/simulation/create", json={})
    assert response.status_code == 401


def test_other_routes_keep_their_own_auth(legacy_app):
    app, _ = legacy_app
    client = app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.post("/api/v1/runs", json={}).status_code == 401


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("path", ["/api/graph", "/api/simulation", "/api/report"])
def test_gate_covers_prefix_roots_and_unknown_routes(legacy_app, method, path):
    app, _ = legacy_app
    client = app.test_client()
    assert client.open(path, method=method).status_code == 401
    assert client.open(path + "/missing", method=method).status_code == 401


def test_auth_precedes_body_validation(legacy_app):
    app, _ = legacy_app
    response = app.test_client().post("/api/simulation/create",
                                      json={"project_id": "../invalid"})
    assert response.status_code == 401


def test_offline_fixture_never_builds_a_redis_client(monkeypatch, request):
    import redis

    def unexpected_redis(*args, **kwargs):
        raise AssertionError("Offline tests must not build a Redis client")

    monkeypatch.setenv("REDIS_URL", "redis://unused.invalid:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", unexpected_redis)
    request.getfixturevalue("offline_legacy_services")
    create_app()


def test_app_fixture_never_builds_a_provider_gateway(monkeypatch, offline_legacy_services):
    from app.api.v1 import services

    calls = []

    def unexpected_gateway(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Offline tests must not build a provider gateway")

    monkeypatch.setattr(services, "gateway_from_env", unexpected_gateway)
    monkeypatch.setenv("AIRWALLEX_MODE", "sandbox")
    monkeypatch.setenv("LEDGER_DATABASE_URL", "sqlite://")
    monkeypatch.delenv("REDIS_URL", raising=False)
    create_app()
    assert calls == []

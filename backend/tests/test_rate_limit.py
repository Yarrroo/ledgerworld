"""Security 6: a per-client limit on writes (429 + Retry-After) and a 5 MB body cap (413)."""

from __future__ import annotations

import fakeredis
import pytest
from app import create_app
from app.api.v1 import rate_limit
from flask import Flask


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("LEDGERWORLD_WRITE_LIMIT", "3")
    monkeypatch.setenv("LEDGERWORLD_WRITE_WINDOW_S", "60")
    monkeypatch.delenv("REDIS_URL", raising=False)
    return create_app()


def test_writes_past_the_limit_answer_429_with_retry_after(app):
    c = app.test_client()
    statuses = [c.post("/api/v1/runs", json={}).status_code for _ in range(4)]
    assert 429 not in statuses[:3]
    assert statuses[3] == 429
    resp = c.delete("/api/v1/runs/x")
    assert resp.status_code == 429
    assert resp.get_json()["error"]["code"] == "rate_limited"
    assert 1 <= int(resp.headers["Retry-After"]) <= 60


def test_reads_are_never_limited(app):
    c = app.test_client()
    for _ in range(4):
        c.post("/api/v1/runs", json={})
    assert all(c.get("/api/v1/health").status_code == 200 for _ in range(20))


def test_the_limit_is_per_client_keyed_on_cf_connecting_ip(app):
    c = app.test_client()
    for _ in range(4):
        c.post("/api/v1/runs", json={}, headers={"CF-Connecting-IP": "203.0.113.1"})
    assert c.post("/api/v1/runs", json={},
                  headers={"CF-Connecting-IP": "203.0.113.1"}).status_code == 429
    assert c.post("/api/v1/runs", json={},
                  headers={"CF-Connecting-IP": "203.0.113.2"}).status_code != 429
    # no header: the socket's address is the client, a third one
    assert c.post("/api/v1/runs", json={}).status_code != 429


def test_cf_connecting_ip_from_a_public_peer_is_not_trusted(app):
    c = app.test_client()
    public = {"REMOTE_ADDR": "8.8.8.8"}
    statuses = [c.post("/api/v1/runs", json={}, environ_base=public,
                       headers={"CF-Connecting-IP": f"203.0.113.{i}"}).status_code
                for i in range(4)]
    assert statuses[3] == 429  # a fresh header per request is not a fresh client


def test_the_signed_webhook_is_not_limited(app):
    c = app.test_client()
    statuses = [c.post("/api/v1/webhooks/airwallex", data=b"{}").status_code for _ in range(6)]
    assert 429 not in statuses


def test_the_redis_counter_times_out_instead_of_hanging(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")
    counter = rate_limit._counter_from_env()
    kwargs = counter.redis.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == kwargs["socket_connect_timeout"] == 0.5


def test_upstream_blueprints_are_limited_too(app):
    c = app.test_client()
    statuses = [c.post("/api/graph/ontology/generate").status_code for _ in range(4)]
    assert statuses[3] == 429


def test_a_body_over_5_mb_answers_413(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 5 * 1024 * 1024
    c = app.test_client()
    resp = c.post("/api/v1/runs", data=b"x" * (5 * 1024 * 1024 + 1),
                  content_type="application/json")
    assert resp.status_code == 413
    assert resp.get_json()["error"]["code"] == "request_too_large"
    assert c.post("/api/v1/runs", data=b"{}", content_type="application/json").status_code != 413


def test_the_window_resets_and_redis_holds_the_counts_for_every_process():
    redis = fakeredis.FakeRedis()
    now = [1_000.0 * 60]

    def make():
        app = Flask(__name__)
        app.add_url_rule("/w", "w", lambda: "ok", methods=["POST"])
        rate_limit.install(app, counter=rate_limit.RedisCounter(redis), limit=2, window_s=60,
                           clock=lambda: now[0])
        return app.test_client()

    one, two = make(), make()  # two processes, one Redis
    assert [one.post("/w").status_code, two.post("/w").status_code] == [200, 200]
    resp = one.post("/w")
    assert resp.status_code == 429 and resp.headers["Retry-After"] == "60"
    now[0] += 45
    assert two.post("/w").headers["Retry-After"] == "15"
    now[0] += 15  # the next window
    assert one.post("/w").status_code == 200


def test_a_failing_counter_lets_the_write_through():
    class Broken:
        def hit(self, *_):
            raise ConnectionError("redis is down")

    app = Flask(__name__)
    app.add_url_rule("/w", "w", lambda: "ok", methods=["POST"])
    rate_limit.install(app, counter=Broken(), limit=1, window_s=60)
    c = app.test_client()
    assert [c.post("/w").status_code for _ in range(3)] == [200, 200, 200]

"""The app's write limit and body cap (Security 6), installed on the whole app by `create_app`.

Every POST/PUT/PATCH/DELETE, on any blueprint, counts against its client in a fixed window; one
over the limit answers 429 with Retry-After. The client is the CF-Connecting-IP header the
Cloudflare tunnel sets, honoured only from a loopback or private peer (the tunnel's own hop), else
the socket's address. Reads are never counted: the judge path is all GETs; nor is the provider's
webhook, which its signature already authenticates and whose events a 429 would only delay. The counters live in Redis (REDIS_URL) so every thread and process shares them, else in
this process; a Redis that fails lets the write through rather than taking the app down.

A body over the app's MAX_CONTENT_LENGTH (5 MB, `Config`) answers 413 before anything reads it.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_LIMIT = 60  # writes per client per window
DEFAULT_WINDOW_S = 60
KEY_PREFIX = "ledgerworld:writes"
EXEMPT_PATHS = frozenset({"/api/v1/webhooks/airwallex"})
REDIS_TIMEOUT_S = 0.5  # a hung Redis fails the hit, which lets the write through

log = logging.getLogger("ledgerworld.rate_limit")


class MemoryCounter:
    """Fixed-window counts in this process, shared by its threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._window = -1

    def hit(self, client: str, window: int, window_s: int) -> int:
        with self._lock:
            if window != self._window:  # an old window's counts can never be read again
                self._counts, self._window = {}, window
            self._counts[client] = self._counts.get(client, 0) + 1
            return self._counts[client]


class RedisCounter:
    """Fixed-window counts in Redis: one key per client and window, expiring with the window."""

    def __init__(self, redis: Any) -> None:
        self.redis = redis

    def hit(self, client: str, window: int, window_s: int) -> int:
        key = f"{KEY_PREFIX}:{window}:{client}"
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_s + 1)
        count, _ = pipe.execute()
        return int(count)


def _trusted_peer(addr: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(addr or "")
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def client_key() -> str:
    peer = request.remote_addr
    forwarded = (request.headers.get("CF-Connecting-IP") or "").strip()
    if forwarded and _trusted_peer(peer):
        return forwarded[:64]
    return peer or "unknown"


def _counter_from_env() -> MemoryCounter | RedisCounter:
    url = os.environ.get("REDIS_URL")
    if not url:
        return MemoryCounter()
    import redis as redis_lib

    return RedisCounter(redis_lib.Redis.from_url(
        url, socket_timeout=REDIS_TIMEOUT_S, socket_connect_timeout=REDIS_TIMEOUT_S))


def _refusal(status: int, code: str, detail: str) -> Response:
    response = jsonify({"error": {"code": code, "detail": detail}})
    response.status_code = status
    return response


def install(app: Flask, *, counter: MemoryCounter | RedisCounter | None = None,
            limit: int | None = None, window_s: int | None = None,
            clock: Callable[[], float] = time.time) -> Flask:
    """Cap request bodies and limit each client's writes on every route of ``app``."""
    counter = counter or _counter_from_env()
    limit = limit or int(os.environ.get("LEDGERWORLD_WRITE_LIMIT") or DEFAULT_LIMIT)
    window_s = window_s or int(os.environ.get("LEDGERWORLD_WRITE_WINDOW_S") or DEFAULT_WINDOW_S)

    @app.before_request
    def _guard() -> Response | None:
        cap = app.config.get("MAX_CONTENT_LENGTH")
        if cap is not None and (request.content_length or 0) > cap:
            raise RequestEntityTooLarge()
        if request.method not in WRITE_METHODS or request.path in EXEMPT_PATHS:
            return None
        now = clock()
        window = int(now // window_s)
        try:
            count = counter.hit(client_key(), window, window_s)
        except Exception:
            log.exception("the write limit's counter failed; the write goes through")
            return None
        if count <= limit:
            return None
        response = _refusal(429, "rate_limited",
                            f"more than {limit} writes in {window_s} s from this client")
        response.headers["Retry-After"] = str(max(1, math.ceil((window + 1) * window_s - now)))
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(_: RequestEntityTooLarge) -> Response:
        return _refusal(413, "request_too_large",
                        f"the request body is over {app.config['MAX_CONTENT_LENGTH']} bytes")

    return app

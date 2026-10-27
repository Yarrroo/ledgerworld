"""The live transport: httpx against the Airwallex sandbox, never production.

Built only by `select_transport` under `AIRWALLEX_MODE=sandbox`. It re-checks the host, never
follows a redirect, and reports a lost answer as `TransportTimeout(after_send=...)`:
`after_send` is false only when the connection was never made, so a caller treats every other
loss, an unreadable reply included, as "may have arrived". A simulation process never imports
this module (system brief §4). Merge-gate tests reach the sandbox never; one drives the error
mapping through an in-process `httpx.MockTransport`.
"""

from __future__ import annotations

from app.execution.boundary import require_execution

require_execution()

from collections.abc import Mapping
from typing import Any

import httpx

from .transport import (
    Credentials,
    Response,
    TransportTimeout,
    check_base_url,
    decode_body,
    encode_body,
)

TIMEOUT_S = 30.0


class LiveTransport:
    mode = "sandbox"

    def __init__(
        self,
        base_url: str,
        credentials: Credentials,
        *,
        timeout_s: float = TIMEOUT_S,
        http_transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = check_base_url(base_url)
        self.credentials = credentials
        self._http = httpx.Client(
            base_url=self.base_url, timeout=timeout_s, follow_redirects=False,
            transport=http_transport,
        )

    def __repr__(self) -> str:
        return f"LiveTransport({self.base_url})"

    def send(
        self,
        method: str,
        path: str,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("a request path is absolute on the sandbox host")
        content = encode_body(json) if json is not None else None
        try:
            answer = self._http.request(method, path, content=content, headers=dict(headers or {}))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise TransportTimeout(after_send=False) from None
        except httpx.RequestError:  # a lost or unreadable reply: it may have arrived
            raise TransportTimeout(after_send=True) from None
        return Response(
            status=answer.status_code,
            json=decode_body(answer.text),
            headers=dict(answer.headers),
            text=answer.text,
        )

    def close(self) -> None:
        self._http.close()

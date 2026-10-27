"""The wire under the Airwallex client, and the one switch between the fake and the sandbox.

`select_transport(env)` reads `AIRWALLEX_MODE` (system brief §10, §14; fixtures/switch-and-hosts):
- unset or `fake` → `FakeTransport`, also when a key is present: a key appearing never flips it;
- `sandbox` → `LiveTransport` against the sandbox host, and only with `AIRWALLEX_CLIENT_ID` and
  `AIRWALLEX_API_KEY` set; without them it raises `ConfigError` naming them — no fallback;
- anything else → `ConfigError`.

The host allowlist is exact: the parsed host of the base URL must be the sandbox host over https.
Bodies are encoded here, once: a `Decimal` is written as a bare JSON number, a float is refused,
and responses are parsed with `Decimal` for every non-integer, so a float never enters or leaves.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

from .errors import ConfigError, HostRefused

SANDBOX_HOST = "api.sandbox.airwallex.com"
SANDBOX_BASE_URL = f"https://{SANDBOX_HOST}"
DEFAULT_API_VERSION = "2024-06-30"
MIN_API_VERSION = "2024-06-30"  # conversion.settled and the PAID transition need it
BANNERS = {"fake": "Simulated provider", "sandbox": "Airwallex sandbox"}
CREDENTIAL_VARS = ("AIRWALLEX_API_KEY", "AIRWALLEX_CLIENT_ID")


@dataclass(frozen=True)
class Response:
    """One HTTP answer: `json` is the parsed body, or None when it is empty or not JSON."""

    status: int
    json: Any
    headers: Mapping[str, str] = field(default_factory=dict)
    text: str = ""


class TransportTimeout(Exception):
    """No answer arrived; `after_send` once the request may have reached the provider."""

    def __init__(self, *, after_send: bool) -> None:
        self.after_send = after_send
        super().__init__("no response after send" if after_send else "no response, not sent")


@dataclass(frozen=True, repr=False)
class Credentials:
    """The login pair; its repr never shows either value."""

    client_id: str
    api_key: str

    def __repr__(self) -> str:
        return "Credentials(<hidden>)"


class Transport(Protocol):
    mode: str  # "fake" | "sandbox"
    credentials: Credentials

    def send(
        self,
        method: str,
        path: str,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


def encode_body(body: Any) -> bytes:
    """JSON bytes for a request body: `Decimal` as a bare number, a float refused."""
    numbers: list[str] = []

    def plain(value: Any) -> Any:
        if value is None or isinstance(value, bool | int):
            return value
        if isinstance(value, str):
            if "\0" in value:
                raise ValueError("a request string carries no NUL")
            return value
        if isinstance(value, float):
            raise TypeError("a float never reaches a provider request")
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("a request number is finite")
            numbers.append(format(value, "f"))
            return f"\0{len(numbers) - 1}\0"
        if isinstance(value, Mapping):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [plain(v) for v in value]
        raise TypeError(f"{type(value).__name__} is not a request body value")

    text = json.dumps(plain(body), separators=(",", ":"))
    text = re.sub(r'"\\u0000(\d+)\\u0000"', lambda m: numbers[int(m.group(1))], text)
    return text.encode()


def decode_body(text: str) -> Any:
    """The parsed body with every non-integer number as `Decimal`; None when not JSON."""
    if not text.strip():
        return None
    try:
        return json.loads(text, parse_float=Decimal)
    except ValueError:
        return None


def check_base_url(base_url: str) -> str:
    """The base URL without a trailing slash, or `HostRefused` unless it is the sandbox."""
    try:
        parts = urlsplit(base_url)
        port = parts.port
    except ValueError:
        raise HostRefused("the base URL does not parse") from None
    if (
        parts.scheme != "https"
        or parts.hostname != SANDBOX_HOST
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise HostRefused(f"only {SANDBOX_BASE_URL} is allowed")
    return SANDBOX_BASE_URL


def api_version_from(env: Mapping[str, str] | None = None) -> str:
    """`AIRWALLEX_API_VERSION`, pinned: a date no earlier than 2024-06-30."""
    env = os.environ if env is None else env
    version = env.get("AIRWALLEX_API_VERSION", "").strip() or DEFAULT_API_VERSION
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", version) or version < MIN_API_VERSION:
        raise ConfigError(f"AIRWALLEX_API_VERSION must be a date no earlier than {MIN_API_VERSION}")
    return version


def mode_from(env: Mapping[str, str] | None = None) -> str:
    """`fake` or `sandbox`; only `AIRWALLEX_MODE=sandbox` selects the sandbox."""
    env = os.environ if env is None else env
    mode = env.get("AIRWALLEX_MODE", "").strip().lower() or "fake"
    if mode not in BANNERS:
        raise ConfigError("AIRWALLEX_MODE must be fake or sandbox")
    return mode


def select_transport(env: Mapping[str, str] | None = None, **fake_options: Any) -> Transport:
    """The transport `AIRWALLEX_MODE` names; `fake_options` go to `FakeTransport`."""
    env = os.environ if env is None else env
    if mode_from(env) == "fake":
        from .fake import FakeTransport

        return FakeTransport(**fake_options)
    missing = [name for name in CREDENTIAL_VARS if not env.get(name, "").strip()]
    if missing:
        raise ConfigError(f"AIRWALLEX_MODE=sandbox needs {', '.join(missing)}; no fallback to fake")
    base_url = check_base_url(env.get("AIRWALLEX_BASE_URL", "").strip() or SANDBOX_BASE_URL)
    from .live import LiveTransport

    credentials = Credentials(env["AIRWALLEX_CLIENT_ID"].strip(), env["AIRWALLEX_API_KEY"].strip())
    return LiveTransport(base_url, credentials)

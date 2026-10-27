"""What the Airwallex connector raises (design/modules/airwallex/HANDOFF.md, fixtures/errors.json).

The class of an error is what the execution gateway acts on:
- `ProviderError` — the provider refused; nothing moved (`outcome="rejected"`). An unknown 4xx
  code is kept verbatim, never mapped to a known one.
- `DuplicateRequest` — the `request_id` was already used (`in_flight` while the first call is
  still open, a 409). Nothing new moved; the original is found by list-by-`request_id`.
- `OutcomeUnknown` — a timeout, a 5xx or an unreadable success on a POST: money may have moved.
  The client never repeats that POST; the gateway queries by the stored ids first.
- `ConfigError`, `HostRefused` — the connector refuses to start or to reach a host.

A message carries codes, statuses and variable names only: never the key, a token or a secret.
"""

from __future__ import annotations


class AirwallexError(Exception):
    """Base of every connector error."""


class ConfigError(AirwallexError):
    """The environment cannot start the connector; the message names variables, never values."""


class HostRefused(AirwallexError):
    """A base URL that is not the sandbox host over https."""


class ProviderError(AirwallexError):
    """The provider refused the request; `retryable` says whether a later attempt may succeed."""

    def __init__(
        self,
        code: str,
        http: int | None,
        *,
        retryable: bool = False,
        message: str = "",
        source: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.code = code
        self.http = http
        self.retryable = retryable
        self.outcome = "rejected"
        self.message = message
        self.source = source
        self.trace_id = trace_id
        detail = f": {message}" if message else ""
        super().__init__(f"provider refused ({http}, {code}){detail}")


class DuplicateRequest(AirwallexError):
    """The provider rejected a replayed `request_id`; look the original up, never re-mint."""

    def __init__(self, request_id: str, *, in_flight: bool, code: str | None = None) -> None:
        self.request_id = request_id
        self.in_flight = in_flight
        self.code = code
        state = "in flight" if in_flight else "already used"
        super().__init__(f"request_id {request_id} {state}")


class OutcomeUnknown(AirwallexError):
    """The request may have moved money; find it by `request_id` before anything else."""

    def __init__(self, request_id: str | None, reason: str) -> None:
        self.request_id = request_id
        self.reason = reason
        super().__init__(f"outcome unknown for request_id {request_id}: {reason}")

"""Verify provider hints without trusting their reported money state.

Bind ``WebhookVerifier`` to the notification URL's secret, an observed-store event
adapter and a GET-triggering reconciliation callback. The HTTP caller must pass
request bytes unchanged and ``now`` as Unix milliseconds. No ledger or live
connector is imported here; route/leg binding belongs to the execution gateway.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

MAX_AGE_MS = 300_000
EVENT_KINDS = {
    "payout.transfer.paid": "transfer",
    "payout.transfer.failed": "transfer",
    "conversion.settled": "conversion",
}


@dataclass(frozen=True)
class ReconciliationHint:
    """Only lookup identifiers cross into reconciliation, never an event status.

    Unknown request ids still trigger GET by provider id. The reconciler, not the
    verifier, decides whether an unknown provider object requires an incident.
    """

    kind: Literal["transfer", "conversion"]
    provider_id: str
    request_id: str | None


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    name: str
    object_id: str | None
    timestamp_ms: int
    received_at_ms: int


class WebhookEventStore(Protocol):
    """Adapter for the observed store's ``webhook_events`` table.

    ``ingest_once`` must serialize callers by event_id, persist the event and run
    the action only for an unhandled event. Mark it handled only after success;
    an action/store exception must propagate and leave it retryable. Completed
    duplicates return without invoking the action. Unknown names are stored with
    a no-op action. The adapter owns durability/concurrency, not the verifier.
    """

    def ingest_once(self, event: WebhookEvent, action: Callable[[], None]) -> None: ...


class WebhookVerifier:
    def __init__(
        self,
        secret: str,
        store: WebhookEventStore,
        reconcile: Callable[[ReconciliationHint], None],
    ) -> None:
        if not isinstance(secret, str) or not secret:
            raise ValueError("webhook secret is required")
        self._secret = secret.encode("utf-8")
        self._store = store
        self._reconcile = reconcile

    def verify_and_ingest(self, headers: Mapping[str, str], raw_body: bytes, now: int) -> int:
        """Return 200 for verified hints/replays, 401 for unauthenticated input.

        Storage/reconciliation failures propagate so the route cannot acknowledge
        lost work. Both stale and far-future signatures are refused; the exact
        five-minute boundary is accepted. Authentication precedes JSON parsing.
        """
        if type(now) is not int or now < 0:
            raise ValueError("now must be Unix milliseconds")
        auth = {}
        for key, value in headers.items():
            name = key.lower()
            if name in {"x-timestamp", "x-signature"}:
                if name in auth:
                    return 401
                auth[name] = value
        timestamp = auth.get("x-timestamp", "")
        signature = auth.get("x-signature", "")
        if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,16}", timestamp):
            return 401
        if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            return 401
        timestamp_ms = int(timestamp)
        if abs(now - timestamp_ms) > MAX_AGE_MS:
            return 401
        expected = hmac.new(
            self._secret, timestamp.encode("ascii") + raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            return 401
        try:
            payload = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return 401
        if not isinstance(payload, dict):
            return 401
        event_id, name = payload.get("id"), payload.get("name")
        if not _identifier(event_id, 96) or not _identifier(name, 64):
            return 401
        data = payload.get("data")
        obj = data.get("object") if isinstance(data, dict) else None
        object_id = obj.get("id") if isinstance(obj, dict) else None
        request_id = obj.get("request_id") if isinstance(obj, dict) else None
        kind = EVENT_KINDS.get(name)
        if kind and (
            not _identifier(object_id, 96)
            or (request_id is not None and not _identifier(request_id, 96))
        ):
            return 401
        event = WebhookEvent(
            event_id=event_id,
            name=name,
            object_id=object_id if _identifier(object_id, 96) else None,
            timestamp_ms=timestamp_ms,
            received_at_ms=now,
        )

        def action() -> None:
            if kind:
                self._reconcile(ReconciliationHint(kind, object_id, request_id))

        self._store.ingest_once(event, action)
        return 200


def _identifier(value: object, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and bool(value.strip())
        and not re.search(r"[\x00\ud800-\udfff]", value)
    )

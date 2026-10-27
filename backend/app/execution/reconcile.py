"""Reconciliation: provider state → ledger journals, and every mismatch an incident.

The truth of a leg is a `GET` by its provider id (design/modules/execution/HANDOFF.md,
`fixtures/reconciliation.json`). What this module adds to the outbox's own settle-and-flag:

- `sweep(gateway)` drives every open leg (submitted, unknown, settled but not reconciled), `GET`s
  every reconciled provider leg again (a `PAID` transfer may still fail: incident
  `paid_then_failed`, the payroll obligation open again, no journal touched), lists the
  provider's objects and opens `unknown_provider_object` for one that moved money and belongs to
  no leg, and releases what a failed leg had spoken for. It runs once after each execution and
  every `SWEEP_EVERY_S` while `open_legs` is not empty.
- `on_hint(gateway, hint)` is what a verified webhook may do: find the leg the hint names and
  run its `GET`, or `GET` an object no leg owns; the event's own status is never read.
- `SqlWebhookEvents` keeps `webhook_events` (one row per event id, handled once), and
  `webhook_verifier(gateway, secret)` builds the verifier the webhook route calls.

A posted journal is never edited and the ledger is never corrected to fit the provider; a
reversal waits for the operator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.connectors.airwallex.client import CONVERSIONS_PATH
from app.connectors.airwallex.errors import AirwallexError
from app.connectors.airwallex.errors import ProviderError as ProviderRefusal
from app.connectors.airwallex.webhooks import ReconciliationHint, WebhookEvent, WebhookVerifier
from app.execution import outbox as ob
from app.execution.gateway import Gateway, collection
from app.finance.models import obligations
from sqlalchemy import update

SWEEP_EVERY_S = 60
OPEN = "state IN ('submitted', 'unknown') OR (state = 'settled' AND NOT reconciled)"
# A provider status that never moved money, or gave it back.
MOVED_NOTHING = frozenset({"FAILED", "CANCELLED", "OVERDUE", "CANCELLATION_REQUESTED"})


@dataclass
class Sweep:
    """What one sweep did: executions driven, legs re-read, incidents it opened."""

    executions: list[str] = field(default_factory=list)
    rechecked: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)


def open_legs(gateway: Gateway) -> list[str]:
    """Legs the sweep still has to look at; while any exists the sweep repeats."""
    return [leg.leg_id for leg in gateway.outbox._legs(OPEN)]


def reconcile_leg(gateway: Gateway, leg_id: str) -> None:
    """`GET` one leg and bring its state, journal and incidents in line with what it shows."""
    leg = gateway.outbox.leg(leg_id)
    if leg.state == "settled" and leg.reconciled:
        gateway.outbox.reconcile(leg_id, gateway.provider)
    gateway.run(leg.approval_id)
    reopen_failed_payouts(gateway)


def sweep(gateway: Gateway) -> Sweep:
    """One reconciliation pass over the whole store."""
    done = Sweep()
    executions = [r[0] for r in gateway.conn.execute(
        f"SELECT DISTINCT approval_id FROM execution_legs WHERE {OPEN} OR state = 'pending'"
        " ORDER BY approval_id")]
    for execution_id in executions:
        gateway.run(execution_id)
        done.executions.append(execution_id)
    for leg in gateway.outbox._legs("state = 'settled' AND reconciled AND NOT ledger_only"):
        gateway.outbox.reconcile(leg.leg_id, gateway.provider)
        done.rechecked.append(leg.leg_id)
    gateway.release_failed()
    reopen_failed_payouts(gateway)
    done.orphans = orphans(gateway)
    return done


def orphans(gateway: Gateway) -> list[str]:
    """Open `unknown_provider_object` for every provider object that moved money and is no
    leg's; it is never adopted into a leg. Returns the provider ids newly flagged."""
    ours = {r[0] for r in gateway.conn.execute("SELECT request_id FROM execution_legs")}
    kinds = {collection(kind, gateway.leg_mode) for kind in ("advance", "repayment", "fx",
                                                              "payout")}
    flagged = []
    for kind, path in sorted(kinds):
        if kind == "deposit":
            continue  # no list to read (see the gateway); the operator owns deposits
        try:
            found = gateway.provider.list_all(kind, path)
        except AirwallexError:
            continue  # the next sweep reads it again
        for obj in found:
            if obj.request_id not in ours and obj.status not in MOVED_NOTHING \
                    and flag_orphan(gateway, obj.provider_id, f"{kind} {obj.request_id} "
                                    f"{obj.status} {obj.amount} {obj.currency}"):
                flagged.append(obj.provider_id)
    return flagged


def flag_orphan(gateway: Gateway, provider_id: str, detail: str) -> bool:
    """One open `unknown_provider_object` per provider id; true when this call opened it."""
    with gateway.transaction():
        if gateway.conn.execute(
                "SELECT 1 FROM incidents WHERE kind = 'unknown_provider_object'"
                " AND provider_id = ? AND closed_at IS NULL", (provider_id,)).fetchone():
            return False
        gateway.conn.execute(
            "INSERT INTO incidents (incident_id, kind, leg_id, provider_id, detail, opened_at)"
            " VALUES (?, 'unknown_provider_object', NULL, ?, ?, ?)",
            (f"unknown_provider_object-{provider_id}-{_count(gateway, provider_id) + 1}",
             provider_id, detail, ob.stamp(gateway.clock())))
    return True


def _count(gateway: Gateway, provider_id: str) -> int:
    return gateway.conn.execute(
        "SELECT count(*) FROM incidents WHERE kind = 'unknown_provider_object'"
        " AND provider_id = ?", (provider_id,)).fetchone()[0]


def reopen_failed_payouts(gateway: Gateway) -> None:
    """A payout that failed after it settled leaves its obligation owed again: the obligation
    met by the leg's reservation opens again while incident `paid_then_failed` is open. The
    settle journal stays; the reversing journal is the operator's to confirm."""
    rows = gateway.conn.execute(
        "SELECT l.funded_by FROM execution_legs l JOIN incidents i ON i.leg_id = l.leg_id"
        " WHERE i.kind = 'paid_then_failed' AND i.closed_at IS NULL"
        " AND l.funded_by LIKE 'reservation:%'").fetchall()
    for (funded_by,) in rows:
        with gateway.transaction():
            gateway.sa.execute(update(obligations).where(
                obligations.c.reservation_id == funded_by.removeprefix("reservation:"),
                obligations.c.state == "met").values(state="open"))


# --------------------------------------------------------------------------------- webhooks


def on_hint(gateway: Gateway, hint: ReconciliationHint) -> None:
    """A verified webhook's only action: the `GET` it points at. A lookup that errors raises,
    so the route does not acknowledge an event whose `GET` never ran."""
    row = gateway.conn.execute(
        "SELECT leg_id FROM execution_legs WHERE provider_id = ? OR request_id = ?"
        " ORDER BY provider_id IS NULL LIMIT 1", (hint.provider_id, hint.request_id)).fetchone()
    if row is not None:
        leg = gateway.outbox.leg(row[0])
        if leg.provider_id is not None:  # the GET first, raising, so a lost one is retried
            gateway.provider.get(leg)
        reconcile_leg(gateway, leg.leg_id)
        return
    path = "/api/v1/transfers" if hint.kind == "transfer" else CONVERSIONS_PATH
    try:
        obj = gateway.provider.get_object(hint.kind, path, hint.provider_id)
    except ProviderRefusal as refused:
        if refused.http == 404:
            return  # the provider holds no such object: nothing moved
        raise
    if obj.status not in MOVED_NOTHING:
        flag_orphan(gateway, obj.provider_id, f"{hint.kind} {obj.request_id} {obj.status} "
                    f"{obj.amount} {obj.currency} (webhook)")


class SqlWebhookEvents:
    """`webhook_events` in the observed store: an event id is stored once and handled once."""

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway

    def ingest_once(self, event: WebhookEvent, action: Callable[[], None]) -> None:
        conn = self.gateway.conn
        with self.gateway.transaction():
            row = conn.execute("SELECT handled FROM webhook_events WHERE event_id = ?",
                               (event.event_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO webhook_events (event_id, name, object_id, received_at,"
                    " timestamp_ms, handled) VALUES (?, ?, ?, ?, ?, FALSE)",
                    (event.event_id, event.name, event.object_id,
                     _ms(event.received_at_ms), event.timestamp_ms))
        if row is not None and row[0]:
            return
        action()  # raises to leave the event unhandled and the provider retrying
        with self.gateway.transaction():
            conn.execute("UPDATE webhook_events SET handled = TRUE WHERE event_id = ?",
                         (event.event_id,))


def webhook_verifier(gateway: Gateway, secret: str) -> WebhookVerifier:
    """What `POST /api/v1/webhooks/airwallex` calls with the raw body and the headers."""
    return WebhookVerifier(secret, SqlWebhookEvents(gateway), lambda hint: on_hint(gateway, hint))


def _ms(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, UTC).isoformat()

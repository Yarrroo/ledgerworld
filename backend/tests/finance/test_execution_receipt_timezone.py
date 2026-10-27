"""Execution times read back from the store are timezone-aware UTC on every dialect.

The execution tables declare `TIMESTAMP`. SQLite hands back the ISO text the outbox wrote,
zone included; PostgreSQL's `TIMESTAMP` drops the zone and psycopg hands back a naive datetime.
`ExecutionResponse` requires aware times, so on PostgreSQL every leg receipt's `observed_at` (and
every incident's `opened_at`) failed validation and GET /api/v1/executions/<id> answered 500.
Reads now go through `outbox.utc`, and writes store the UTC wall time on every dialect.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.api.v1 import routes
from app.execution import outbox as ob
from app.execution.gateway import Gateway
from app.finance import schemas as c6

OBSERVED = datetime(2026, 10, 27, 9, 30, 15, 123456)  # naive: what PostgreSQL reads back
LEG_ID = "0123456789ab-1-advance"


class NaiveTimestamps:
    """A server connection: every `TIMESTAMP` value comes back as a naive UTC datetime."""

    def __init__(self, rows: list[tuple], names: tuple[str, ...] = ()) -> None:
        self.rows = rows
        self.description = [(n,) for n in names]

    def execute(self, _sql: str, _args: tuple = ()) -> NaiveTimestamps:
        return self

    def fetchone(self) -> tuple | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple]:
        return list(self.rows)


def _leg(**over) -> SimpleNamespace:
    return SimpleNamespace(**{
        "leg_id": LEG_ID, "request_id": LEG_ID, "kind": "advance", "provider_id": "tfr_1",
        "provider_status": "PAID", "amount_minor": 12_345, "currency": "USD",
        "receipt_label": "advance", "state": "settled", "reconciled": True,
        "journal_id": "j-1", **over})


@pytest.mark.parametrize("stored", [
    OBSERVED,                                                     # PostgreSQL TIMESTAMP
    OBSERVED.replace(tzinfo=UTC).isoformat(),                     # SQLite, as written
    OBSERVED.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8))),  # a zoned driver
])
def test_a_stored_receipt_reads_back_as_aware_utc(stored):
    gateway = SimpleNamespace(conn=NaiveTimestamps([(json.dumps(["id", "status"]), stored)]))
    leg = c6.ExecutionLeg.model_validate(routes._leg(gateway, _leg(), "fake"))
    assert leg.receipt.observed_at == OBSERVED.replace(tzinfo=UTC)
    assert leg.receipt.observed_at.utcoffset() == timedelta(0)


def test_a_stored_incident_reads_back_as_aware_utc():
    names = ("incident_id", "kind", "leg_id", "provider_id", "detail", "opened_at",
             "closed_at", "closed_by")
    conn = NaiveTimestamps([("i-1", "outcome_unknown", LEG_ID, None, "timeout", OBSERVED,
                             OBSERVED + timedelta(seconds=5), "lookup")], names)
    (incident,) = Gateway.incidents(SimpleNamespace(conn=conn))
    assert incident["opened_at"] == OBSERVED.replace(tzinfo=UTC)
    assert incident["closed_at"] == OBSERVED.replace(tzinfo=UTC) + timedelta(seconds=5)
    c6.Incident.model_validate({**{k: incident[k] for k in ("incident_id", "leg_id", "kind")},
                                "state": "closed", "opened_at": incident["opened_at"]})


def test_the_outbox_stores_the_utc_wall_time_whatever_the_clock_zone():
    """PostgreSQL's `TIMESTAMP` keeps the wall time and drops the offset, so a zoned clock
    must be turned to UTC before it is written."""
    zoned = OBSERVED.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=-5)))
    assert ob.stamp(zoned) == OBSERVED.replace(tzinfo=UTC).isoformat()
    assert ob.utc(None) is None


def test_a_sqlite_execution_store_round_trips_receipt_times():
    conn = sqlite3.connect(":memory:")
    ob.install(conn)
    conn.execute("INSERT INTO approvals VALUES ('a', 'e', 'acct', 's', ?, 'fake', 'me', ?, ?, NULL)",
                 ("0" * 64, "2026-10-27T09:00:00+00:00", "2026-10-28T09:00:00+00:00"))
    conn.execute("INSERT INTO execution_legs (leg_id, approval_id, leg_index, kind, request_id,"
                 " source_account, counterparty, currency, amount_minor, state, provider_id,"
                 " provider_status, receipt_label, journal_id, reconciled, updated_at)"
                 " VALUES (?, 'a', 1, 'advance', ?, 'acct', 'cp', 'USD', 12345, 'settled',"
                 " 'tfr_1', 'PAID', 'advance', 'j-1', TRUE, ?)",
                 (LEG_ID, LEG_ID, ob.stamp(OBSERVED.replace(tzinfo=UTC))))
    conn.execute("INSERT INTO leg_events (leg_id, to_state, cause, provider_status, raw_keys, at)"
                 " VALUES (?, 'settled', 'get', 'PAID', '[]', ?)",
                 (LEG_ID, ob.stamp(OBSERVED.replace(tzinfo=UTC))))
    leg = c6.ExecutionLeg.model_validate(routes._leg(SimpleNamespace(conn=conn), _leg(), "fake"))
    assert leg.receipt.observed_at == OBSERVED.replace(tzinfo=UTC)

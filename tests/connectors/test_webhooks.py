"""The execution webhook fixture unchanged, with injected storage and GET-only reconciliation."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import pytest
from app.connectors.airwallex.client import AirwallexClient
from app.connectors.airwallex.fake import FakeClock, FakeTransport
from app.connectors.airwallex.webhooks import (
    MAX_AGE_MS,
    ReconciliationHint,
    WebhookVerifier,
)
from app.finance.schemas import Money

DESIGN = Path(__file__).resolve().parents[2] / "prp/2026-10-20-ledgerworld/design/modules/execution"
FIXTURE = json.loads((DESIGN / "fixtures/webhooks.json").read_text())
RAW = FIXTURE["raw_body"].encode()
NOW = FIXTURE["now_ms"]
VALID = FIXTURE["cases"][0]


class SQLiteEventStore:
    """Test adapter using the unchanged execution DDL, independent of any ledger.

    Serializes callbacks and rolls back failed delivery so a later attempt can
    retry. The gateway supplies its observed-store adapter at route binding.
    """

    def __init__(self, connection):
        self.connection = connection
        self.lock = Lock()

    def ingest_once(self, event, action):
        with self.lock, self.connection:
            row = self.connection.execute(
                "SELECT handled FROM webhook_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if row and row[0]:
                return
            if not row:
                self.connection.execute(
                    "INSERT INTO webhook_events "
                    "(event_id, name, object_id, received_at, timestamp_ms) VALUES (?, ?, ?, ?, ?)",
                    (event.event_id, event.name, event.object_id,
                     datetime.fromtimestamp(event.received_at_ms / 1000, UTC).isoformat(),
                     event.timestamp_ms),
                )
            action()
            self.connection.execute(
                "UPDATE webhook_events SET handled = TRUE WHERE event_id = ?", (event.event_id,)
            )

    def rows(self):
        return self.connection.execute("SELECT * FROM webhook_events").fetchall()


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript((DESIGN / "schema.sql").read_text())
    yield SQLiteEventStore(connection)
    connection.close()


def signed(raw=RAW, timestamp=None):
    timestamp = VALID["headers"]["x-timestamp"] if timestamp is None else str(timestamp)
    signature = hmac.new(
        FIXTURE["secret"].encode(), timestamp.encode() + raw, hashlib.sha256
    ).hexdigest()
    return {"x-timestamp": timestamp, "x-signature": signature}


def case_input(case):
    raw = RAW
    if case.get("body") == "raw_body with PAID → FAILED":
        raw = raw.replace(b"PAID", b"FAILED")
    elif case.get("body") == "raw_body parsed and re-dumped with spaces":
        raw = json.dumps(json.loads(raw)).encode()
    elif "event_name" in case or "object_request_id" in case:
        payload = json.loads(raw)
        if "event_name" in case:
            payload["name"] = case["event_name"]
        if "object_request_id" in case:
            payload["data"]["object"]["request_id"] = case["object_request_id"]
        raw = json.dumps(payload).encode()
    headers = case.get("headers", signed(raw)).copy()
    if headers.get("x-signature") == "<valid for that timestamp>":
        headers = signed(raw, headers["x-timestamp"])
    return headers, raw


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
def test_webhook_fixture(case, store):
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    if "repeat" in case:
        assert case["repeat"] == VALID["id"]
        assert verifier.verify_and_ingest(VALID["headers"], RAW, NOW) == 200
        calls.clear()
        expected = case["expect"]["second"]
        headers, raw = VALID["headers"], RAW
    else:
        expected = case["expect"]
        headers, raw = case_input(case)
    assert verifier.verify_and_ingest(headers, raw, case.get("now_ms", NOW)) == expected["http"]
    action = expected.get("action", "none")
    if action.startswith("GET"):
        request_id = case.get("object_request_id", "a1b2c3d4e5f6-1-payout")
        assert calls == [ReconciliationHint("transfer", "t-0001", request_id)]
    else:
        assert calls == []
    rows = store.rows()
    assert len(rows) == (1 if expected["http"] == 200 else 0)
    if rows:
        row = rows[0]
        assert row[0] == "evt-1"
        assert row[1] == case.get("event_name", "payout.transfer.paid")
        assert row[2] == "t-0001"
        assert row[4] == int(headers["x-timestamp"])
        assert row[5] == 1


def test_fixture_hmac_and_age_are_fixed():
    assert signed() == VALID["headers"]
    assert MAX_AGE_MS == FIXTURE["max_age_ms"]


@pytest.mark.parametrize("age", [-MAX_AGE_MS - 1, -MAX_AGE_MS, 0, MAX_AGE_MS, MAX_AGE_MS + 1])
def test_freshness_boundaries(age, store):
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    status = verifier.verify_and_ingest(signed(timestamp=NOW - age), RAW, NOW)
    accepted = abs(age) <= MAX_AGE_MS
    assert status == (200 if accepted else 401)
    assert len(calls) == len(store.rows()) == int(accepted)


@pytest.mark.parametrize("field,value", [
    ("x-timestamp", ""), ("x-timestamp", "not-ms"), ("x-timestamp", "1793872800"),
    ("x-timestamp", "1793872800000.0"), ("x-timestamp", "١٧٩٣٨٧٢٨٠٠٠٠٠"),
    ("x-timestamp", "1" * 5000), ("x-timestamp", None),
    ("x-signature", ""), ("x-signature", "0" * 64), ("x-signature", "é" * 64),
    ("x-signature", "a" * 63), ("x-signature", None),
])
def test_bad_auth_headers_are_refused(field, value, store):
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    headers = VALID["headers"] | {field: value}
    assert verifier.verify_and_ingest(headers, RAW, NOW) == 401
    assert not calls and not store.rows()


@pytest.mark.parametrize("missing", ["x-timestamp", "x-signature"])
def test_either_missing_header_is_refused(missing, store):
    headers = {key: value for key, value in VALID["headers"].items() if key != missing}
    verifier = WebhookVerifier(FIXTURE["secret"], store, pytest.fail)
    assert verifier.verify_and_ingest(headers, RAW, NOW) == 401
    assert not store.rows()


def test_header_names_are_case_insensitive_and_hex_may_be_uppercase(store):
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    headers = {key.title(): value.upper() for key, value in VALID["headers"].items()}
    assert verifier.verify_and_ingest(headers, RAW, NOW) == 200
    assert len(calls) == 1


def test_ambiguous_duplicate_headers_are_refused(store):
    verifier = WebhookVerifier(FIXTURE["secret"], store, pytest.fail)
    headers = VALID["headers"] | {"X-Timestamp": VALID["headers"]["x-timestamp"]}
    assert verifier.verify_and_ingest(headers, RAW, NOW) == 401
    assert not store.rows()


@pytest.mark.parametrize("raw", [
    b"not-json", b"\xff", b"[]", b"null", b"1", b"{}",
    b'{"id":1,"name":"conversion.settled"}',
    b'{"id":"evt","name":false}',
    b'{"id":"evt","name":"conversion.settled"}',
    b'{"id":"evt","name":"conversion.settled","data":[]}',
    b'{"id":"evt","name":"conversion.settled","data":{"object":[]}}',
    b'{"id":"evt","name":"conversion.settled","data":{"object":{"id":" "}}}',
    b'{"id":"evt","name":"conversion.settled","data":{"object":{"id":"c","request_id":3}}}',
])
def test_authenticated_malformed_payloads_are_refused(raw, store):
    verifier = WebhookVerifier(FIXTURE["secret"], store, pytest.fail)
    assert verifier.verify_and_ingest(signed(raw), raw, NOW) == 401
    assert not store.rows()


def test_invalid_signature_is_rejected_before_json_parsing(store, monkeypatch):
    monkeypatch.setattr("app.connectors.airwallex.webhooks.json.loads", pytest.fail)
    verifier = WebhookVerifier(FIXTURE["secret"], store, pytest.fail)
    assert verifier.verify_and_ingest(VALID["headers"], b"not-json", NOW) == 401


@pytest.mark.parametrize("name,kind", [
    ("payout.transfer.paid", "transfer"), ("payout.transfer.failed", "transfer"),
    ("conversion.settled", "conversion"),
])
def test_every_supported_event_is_a_status_free_get_hint(name, kind, store):
    payload = json.loads(RAW)
    payload["name"] = name
    payload["data"]["object"].pop("request_id")
    raw = json.dumps(payload).encode()
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    assert verifier.verify_and_ingest(signed(raw), raw, NOW) == 200
    assert calls == [ReconciliationHint(kind, "t-0001", None)]
    assert not hasattr(calls[0], "status")
    assert not hasattr(calls[0], "amount")


def test_unknown_event_without_an_object_is_stored_and_ignored(store):
    raw = b'{"id":"evt-other","name":"issuing.card.created"}'
    verifier = WebhookVerifier(FIXTURE["secret"], store, pytest.fail)
    assert verifier.verify_and_ingest(signed(raw), raw, NOW) == 200
    assert store.rows()[0][0:3] == ("evt-other", "issuing.card.created", None)


def test_dedupe_uses_event_id_not_body_or_timestamp(store):
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    assert verifier.verify_and_ingest(VALID["headers"], RAW, NOW) == 200
    raw = RAW.replace(b"PAID", b"FAILED")
    assert verifier.verify_and_ingest(signed(raw, NOW), raw, NOW) == 200
    assert len(calls) == len(store.rows()) == 1
    raw = raw.replace(b"evt-1", b"evt-2")
    assert verifier.verify_and_ingest(signed(raw), raw, NOW) == 200
    assert len(calls) == len(store.rows()) == 2


def test_replay_still_requires_authentication(store):
    verifier = WebhookVerifier(FIXTURE["secret"], store, lambda hint: None)
    assert verifier.verify_and_ingest(VALID["headers"], RAW, NOW) == 200
    assert verifier.verify_and_ingest({}, RAW, NOW) == 401
    assert verifier.verify_and_ingest(VALID["headers"], RAW, NOW + MAX_AGE_MS) == 401


def test_reconciliation_failure_is_not_acknowledged_and_can_retry(store):
    def unavailable(hint):
        raise RuntimeError("GET unavailable")

    verifier = WebhookVerifier(FIXTURE["secret"], store, unavailable)
    with pytest.raises(RuntimeError, match="GET unavailable"):
        verifier.verify_and_ingest(VALID["headers"], RAW, NOW)
    assert not store.rows()
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    assert verifier.verify_and_ingest(VALID["headers"], RAW, NOW) == 200
    assert len(calls) == len(store.rows()) == 1


def test_storage_failure_is_not_acknowledged(store):
    store.connection.close()
    verifier = WebhookVerifier(FIXTURE["secret"], store, pytest.fail)
    with pytest.raises(sqlite3.ProgrammingError):
        verifier.verify_and_ingest(VALID["headers"], RAW, NOW)


def test_simultaneous_replays_trigger_only_one_callback(store):
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(
            lambda _: verifier.verify_and_ingest(VALID["headers"], RAW, NOW), range(16)
        ))
    assert results == [200] * 16
    assert len(calls) == len(store.rows()) == 1


def test_dedupe_survives_verifier_and_store_restart(tmp_path):
    path = tmp_path / "events.sqlite"
    calls = []
    for first in (True, False):
        connection = sqlite3.connect(path)
        if first:
            connection.executescript((DESIGN / "schema.sql").read_text())
        store = SQLiteEventStore(connection)
        verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
        assert verifier.verify_and_ingest(VALID["headers"], RAW, NOW) == 200
        assert len(store.rows()) == 1
        connection.close()
    assert len(calls) == 1


def test_signed_failed_hint_reads_the_actual_provider_instead_of_changing_state(store):
    clock = FakeClock()
    transport = FakeTransport(clock=clock)
    client = AirwallexClient(transport, clock, api_version="2024-09-27")
    created = client.create_transfer(
        "a1b2c3d4e5f6-1-payout", beneficiary_id="ben-payroll-1",
        amount=Money(minor=100_000, currency="USD"),
    )
    before = list(transport.requests)
    observed = []

    def reconcile(hint):
        observed.append(client.get_transfer(hint.provider_id))

    case = next(case for case in FIXTURE["cases"] if case["id"] == "altered-body-own-signature")
    _, fixture_raw = case_input(case)
    payload = json.loads(fixture_raw)
    payload["data"]["object"]["id"] = created.provider_id
    raw = json.dumps(payload).encode()
    verifier = WebhookVerifier(FIXTURE["secret"], store, reconcile)
    assert verifier.verify_and_ingest(signed(raw), raw, NOW) == 200
    assert len(observed) == 1
    assert observed[0].status == created.status != "FAILED"
    new_calls = transport.requests[len(before):]
    assert [(call.method, call.path) for call in new_calls] == [
        ("GET", f"/api/v1/transfers/{created.provider_id}")
    ]


def test_secret_is_absent_from_repr_logs_storage_and_errors(store, caplog):
    verifier = WebhookVerifier(FIXTURE["secret"], store, lambda hint: None)
    assert verifier.verify_and_ingest(VALID["headers"], RAW, NOW) == 200
    with pytest.raises(ValueError) as error:
        verifier.verify_and_ingest(VALID["headers"], RAW, -1)
    output = repr(verifier) + repr(store.rows()) + caplog.text
    output += "".join(traceback.format_exception(error.value))
    assert FIXTURE["secret"] not in output


@pytest.mark.parametrize("secret", ["", None])
def test_missing_secret_refuses_configuration_without_echoing_it(secret, store):
    with pytest.raises(ValueError, match="webhook secret is required"):
        WebhookVerifier(secret, store, pytest.fail)


@pytest.mark.parametrize("field", ["id", "name", "object_id", "request_id"])
@pytest.mark.parametrize(
    "value", ["bad\x00id", chr(0xD800), chr(0xDFFF)],
    ids=["nul", "high-surrogate", "low-surrogate"],
)
def test_nonportable_identifiers_are_refused_before_ingestion(field, value, store):
    payload = json.loads(RAW)
    if field in {"id", "name"}:
        payload[field] = value
    else:
        key = "id" if field == "object_id" else "request_id"
        payload["data"]["object"][key] = value
    raw = json.dumps(payload).encode()
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    assert verifier.verify_and_ingest(signed(raw), raw, NOW) == 401
    assert not calls and not store.rows()


def test_utf8_identifiers_remain_valid(store):
    payload = json.loads(RAW)
    payload["id"] = "evt-é"
    payload["data"]["object"]["id"] = "t-€"
    raw = json.dumps(payload, ensure_ascii=False).encode()
    calls = []
    verifier = WebhookVerifier(FIXTURE["secret"], store, calls.append)
    assert verifier.verify_and_ingest(signed(raw), raw, NOW) == 200
    assert calls == [ReconciliationHint("transfer", "t-€", "a1b2c3d4e5f6-1-payout")]
    assert store.rows()[0][0] == "evt-é"

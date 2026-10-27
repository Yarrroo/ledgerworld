"""The outbox: one row per leg, written before any provider call, then driven to a terminal state.

The rules it keeps (design/modules/execution/HANDOFF.md, fixtures/crash-and-retry.json):

- A leg's `request_id` is fixed when it is queued and never changes; the leg id is the request id.
- The claim `pending → submitted` is a conditional update committed before the provider is called,
  provider id still empty, so only one worker sends and a crash always leaves a trace.
- An unknown outcome, a restart that finds `submitted` without a provider id, and a duplicate-id
  rejection all resolve by looking the leg up by `request_id`. A leg is sent again only under the
  same id, and only when the lookup found nothing and the attempt could not have left.
- A leg settles, and its journal posts, in one transaction, only when a `GET` shows a terminal
  success. Every state change writes one `leg_events` row in the same transaction as the leg.

The tables are the design's `schema.sql`, in the observed ledger store (SQLite here). The provider
is anything that implements `Provider`; the gateway adapts the Airwallex connector to it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.execution import state
from app.finance.schemas import BoundApproval

SCHEMA = (state.DESIGN / "schema.sql").read_text()
# An unknown leg whose lookup finds nothing is sent again only after one of these: the attempt
# provably never left (`timeout_before_send`), or a restart found it claimed and never answered.
RESENDABLE = frozenset({"timeout_before_send", "restart"})
MAX_PASSES = 32


class Rejected(Exception):
    """The provider refused the request outright; nothing moved."""


class DuplicateRequest(Exception):
    """The provider already holds this `request_id` (`duplicate_request_id`, or 409 in flight)."""


class OutcomeUnknown(Exception):
    """The call ended without an answer; `may_have_sent` is false only when it never left."""

    def __init__(self, may_have_sent: bool, detail: str = "") -> None:
        super().__init__(detail or ("timeout after send" if may_have_sent else "timeout before send"))
        self.may_have_sent = may_have_sent


class LookupFailed(Exception):
    """A `GET` or a lookup by `request_id` errored; the leg's state stays as it is."""


class _Lost(Exception):
    """Another worker changed the leg between the read and the conditional write."""


@dataclass(frozen=True)
class ProviderObject:
    """What the provider holds for a leg: its id, status and the amount in minor units."""

    provider_id: str
    request_id: str
    status: str
    amount_minor: int
    currency: str
    raw_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegPlan:
    """How a leg runs, from the connector's `leg_plan`: its receipt label and provider operation."""

    label: str
    provider_op: str | None = None
    ledger_only: bool = False


@dataclass(frozen=True)
class Leg:
    """One `execution_legs` row."""

    leg_id: str
    approval_id: str
    index: int
    kind: str
    request_id: str
    source: str
    counterparty: str
    currency: str
    amount_minor: int
    funded_by: str | None
    after: tuple[int, ...]
    provider_op: str | None
    ledger_only: bool
    state: str
    provider_id: str | None
    provider_status: str | None
    receipt_label: str
    journal_id: str | None
    reconciled: bool
    attempts: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Leg:
        return cls(
            leg_id=row["leg_id"], approval_id=row["approval_id"], index=row["leg_index"],
            kind=row["kind"], request_id=row["request_id"], source=row["source_account"],
            counterparty=row["counterparty"], currency=row["currency"],
            amount_minor=row["amount_minor"], funded_by=row["funded_by"],
            after=tuple(int(i) for i in row["after_legs"].split(",")) if row["after_legs"] else (),
            provider_op=row["provider_op"], ledger_only=bool(row["ledger_only"]),
            state=row["state"], provider_id=row["provider_id"],
            provider_status=row["provider_status"], receipt_label=row["receipt_label"],
            journal_id=row["journal_id"], reconciled=bool(row["reconciled"]),
            attempts=row["attempts"],
        )


class Provider(Protocol):
    """The provider operations the outbox needs, by leg; errors are the exceptions above."""

    def send(self, leg: Leg) -> ProviderObject: ...

    def find(self, leg: Leg) -> list[ProviderObject]: ...

    def get(self, leg: Leg) -> ProviderObject: ...


# Posts the leg's journal on the outbox's connection, inside the settle transaction; returns its id.
PostJournal = Callable[[sqlite3.Connection, Leg], str]


def request_id(plan_hash: str, index: int, kind: str) -> str:
    """The leg's fixed id: `<plan_hash[:12]>-<index>-<kind>`."""
    return f"{plan_hash[:12]}-{index}-{kind}"


def install(conn: sqlite3.Connection) -> None:
    """Create the execution tables once in this store."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'execution_legs'").fetchone():
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Outbox:
    """The execution legs of one store. It runs its own transactions, so it takes the connection
    in autocommit mode; `on_point(point, leg)` is called at each named crash point."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        post_journal: PostJournal,
        *,
        clock: Callable[[], str] = _now,
        on_point: Callable[[str, Leg], None] | None = None,
    ) -> None:
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys = ON")
        self.conn = conn
        self.post_journal = post_journal
        self.clock = clock
        self.on_point = on_point

    # ------------------------------------------------------------------------------ reading

    def _legs(self, where: str, args: tuple = ()) -> list[Leg]:
        cursor = self.conn.cursor()
        cursor.row_factory = sqlite3.Row
        rows = cursor.execute(f"SELECT * FROM execution_legs WHERE {where} ORDER BY leg_index", args)
        return [Leg.from_row(row) for row in rows]

    def legs(self, approval_id: str) -> list[Leg]:
        return self._legs("approval_id = ?", (approval_id,))

    def leg(self, leg_id: str) -> Leg:
        return self._legs("leg_id = ?", (leg_id,))[0]

    def _last_unknown_cause(self, leg: Leg) -> str | None:
        row = self.conn.execute(
            "SELECT cause FROM leg_events WHERE leg_id = ? AND to_state = 'unknown'"
            " ORDER BY event_seq DESC LIMIT 1", (leg.leg_id,)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------------------ writing

    @contextmanager
    def _tx(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def _write(self, leg: Leg, to: str, cause: str, obj: ProviderObject | None, **fields) -> bool:
        """The conditional update from the leg as read, and its `leg_events` row."""
        state.check(leg.state, to, ledger_only=leg.ledger_only)
        now = self.clock()
        sets = {"state": to, "updated_at": now, **fields}
        if obj is not None:
            sets |= {"provider_id": obj.provider_id, "provider_status": obj.status}
        matches = "provider_id IS NULL" if leg.provider_id is None else "provider_id = ?"
        updated = self.conn.execute(
            f"UPDATE execution_legs SET {', '.join(f'{k} = ?' for k in sets)}"
            f" WHERE leg_id = ? AND state = ? AND {matches}",
            (*sets.values(), leg.leg_id, leg.state,
             *(() if leg.provider_id is None else (leg.provider_id,))),
        ).rowcount
        if updated != 1:
            return False
        self.conn.execute(
            "INSERT INTO leg_events (leg_id, from_state, to_state, cause, provider_status,"
            " raw_keys, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (leg.leg_id, leg.state, to, cause, obj.status if obj else None,
             json.dumps(list(obj.raw_keys)) if obj else None, now),
        )
        return True

    def _move(
        self,
        leg: Leg,
        to: str,
        cause: str,
        obj: ProviderObject | None = None,
        *,
        journal: bool = False,
        incident: tuple[str, str] | None = None,
        close: tuple[str, ...] = (),
        **fields,
    ) -> bool:
        """One transition in one transaction, with the journal and incidents it carries; false
        when another worker moved the leg first (then nothing of it is written)."""
        try:
            with self._tx():
                if journal:
                    fields["journal_id"] = self.post_journal(self.conn, leg)
                if not self._write(leg, to, cause, obj, **fields):
                    raise _Lost
                if incident:
                    self._open_incident(leg, *incident)
                for kind in close:
                    self.conn.execute(
                        "UPDATE incidents SET closed_at = ?, closed_by = 'lookup'"
                        " WHERE leg_id = ? AND kind = ? AND closed_at IS NULL",
                        (self.clock(), leg.leg_id, kind))
        except _Lost:
            return False
        return True

    def _open_incident(self, leg: Leg, kind: str, detail: str) -> None:
        """Open `kind` on the leg unless one is already open (the schema allows one)."""
        open_or_count = self.conn.execute(
            "SELECT count(*), sum(closed_at IS NULL) FROM incidents WHERE leg_id = ? AND kind = ?",
            (leg.leg_id, kind)).fetchone()
        if open_or_count[1]:
            return
        self.conn.execute(
            "INSERT INTO incidents (incident_id, kind, leg_id, provider_id, detail, opened_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (f"{kind}-{leg.leg_id}-{open_or_count[0] + 1}", kind, leg.leg_id, leg.provider_id,
             detail, self.clock()))

    def _point(self, point: str, leg: Leg) -> None:
        if self.on_point is not None:
            self.on_point(point, leg)

    # ------------------------------------------------------------------------------- the API

    def queue(self, approval: BoundApproval, plan: Mapping[int, LegPlan]) -> list[Leg]:
        """Write every leg of the approval as `pending`, in one transaction. The approval row must
        exist. Queuing an approval again returns its legs unchanged."""
        if existing := self.legs(approval.approval_id):
            return existing
        now = self.clock()
        with self._tx():
            for leg in approval.legs:
                how = plan[leg.index]
                rid = request_id(approval.plan_hash, leg.index, leg.kind)
                self.conn.execute(
                    "INSERT INTO execution_legs (leg_id, approval_id, leg_index, kind, request_id,"
                    " source_account, counterparty, currency, amount_minor, funded_by, after_legs,"
                    " provider_op, ledger_only, state, receipt_label, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (rid, approval.approval_id, leg.index, leg.kind, rid, leg.source,
                     leg.counterparty, leg.amount.currency, leg.amount.minor, leg.funded_by,
                     ",".join(map(str, leg.after)) or None, how.provider_op, how.ledger_only,
                     how.label, now))
                self.conn.execute(
                    "INSERT INTO leg_events (leg_id, from_state, to_state, cause, at)"
                    " VALUES (?, NULL, 'pending', 'queued', ?)", (rid, now))
        return self.legs(approval.approval_id)

    def recover(self) -> list[Leg]:
        """At start-up: a leg claimed but never answered is unknown, to be looked up, never resent
        blind. Run it once per process, before any `drive`, never beside a live worker."""
        stranded = self._legs("state = 'submitted' AND provider_id IS NULL")
        for leg in stranded:
            self._move(leg, "unknown", "restart",
                       incident=("outcome_unknown", "restart found the leg claimed, unanswered"))
        return [self.leg(leg.leg_id) for leg in stranded]

    def drive(self, approval_id: str, provider: Provider) -> list[Leg]:
        """Advance every leg of the approval as far as the provider allows, in leg order."""
        for _ in range(MAX_PASSES):
            progressed = False
            for leg in self.legs(approval_id):
                progressed |= self._step(self.leg(leg.leg_id), provider)
            if not progressed:
                break
        return self.legs(approval_id)

    # ------------------------------------------------------------------------------ the steps

    def _step(self, leg: Leg, provider: Provider) -> bool:
        if leg.state == "pending":
            return self._start(leg, provider)
        if leg.state == "submitted" and leg.provider_id is not None:
            return self._observe(leg, provider)
        if leg.state == "unknown":
            return self._resolve(leg, provider)
        if leg.state == "settled" and not leg.reconciled and not leg.ledger_only:
            try:
                return self._reconcile(leg, provider.get(leg))
            except LookupFailed:
                return False
        # `submitted` without a provider id is in flight on a live worker; `recover` owns restarts.
        return False

    def _start(self, leg: Leg, provider: Provider) -> bool:
        by_index = {other.index: other.state for other in self.legs(leg.approval_id)}
        waits_for = [by_index[i] for i in leg.after]
        if "failed" in waits_for:
            return self._move(leg, "failed", "dependency_failed")
        if any(s != "settled" for s in waits_for):
            return False
        if leg.ledger_only:
            return self._move(leg, "settled", "ledger_only", journal=True)
        self._point("after_outbox_write_before_submitted", leg)
        if not self._move(leg, "submitted", "claimed", attempts=leg.attempts + 1):
            return False
        return self._send(self.leg(leg.leg_id), provider)

    def _send(self, leg: Leg, provider: Provider) -> bool:
        self._point("after_submitted_before_send", leg)
        try:
            obj = provider.send(leg)
        except Rejected:
            return self._move(leg, "failed", "rejected")
        except DuplicateRequest:
            return self._adopt_duplicate(leg, provider)
        except OutcomeUnknown as unknown:
            cause = "timeout_after_send" if unknown.may_have_sent else "timeout_before_send"
            return self._move(leg, "unknown", cause, incident=("outcome_unknown", str(unknown)))
        self._point("after_response_before_state_write", leg)
        return self._move(leg, "submitted", "accepted", obj)

    def _adopt_duplicate(self, leg: Leg, provider: Provider) -> bool:
        """A duplicate id is not a failure: the object exists, so look it up and adopt it."""
        try:
            found = provider.find(leg)
        except LookupFailed:
            found = []
        if len(found) == 1:
            return self._move(leg, "submitted", "adopted_on_duplicate", found[0])
        return self._move(leg, "unknown", "duplicate_unresolved",
                          incident=("outcome_unknown", "duplicate request id, lookup unresolved"))

    def _resolve(self, leg: Leg, provider: Provider) -> bool:
        """Unknown → lookup by `request_id`: one object is adopted; none is resent under the same
        id only when the attempt could not have left; an error or several stay unknown."""
        try:
            found = provider.find(leg)
        except LookupFailed:
            return False
        if len(found) == 1:
            return self._move(leg, "submitted", "adopted_by_lookup", found[0],
                              close=("outcome_unknown",))
        if len(found) > 1:
            with self._tx():
                self._open_incident(leg, "lookup_ambiguous",
                                    f"{len(found)} provider objects for {leg.request_id}")
            return False
        if self._last_unknown_cause(leg) not in RESENDABLE:
            return False
        return self._move(leg, "pending", "lookup_found_none", close=("outcome_unknown",))

    def _observe(self, leg: Leg, provider: Provider) -> bool:
        """`GET` by provider id: a terminal success settles the leg with its journal."""
        try:
            obj = provider.get(leg)
        except LookupFailed:
            return False
        if obj.status in state.SETTLED_STATUSES:
            self._point("after_settled_seen_before_journal", leg)
            if not self._move(leg, "settled", "provider_settled", obj, journal=True):
                return False
            self._point("after_journal_before_reconciled_flag", leg)
            self._reconcile(self.leg(leg.leg_id), obj)
            return True
        if obj.status in state.FAILED_STATUSES:
            return self._move(leg, "failed", "provider_failed", obj)
        return False

    def _reconcile(self, leg: Leg, obj: ProviderObject) -> bool:
        """Flag a settled leg whose provider object matches it; a mismatch is an incident and the
        ledger is never corrected to fit."""
        if obj.status in state.SETTLED_STATUSES and (obj.amount_minor, obj.currency) == (
            leg.amount_minor, leg.currency
        ):
            with self._tx():
                self.conn.execute(
                    "UPDATE execution_legs SET reconciled = TRUE, updated_at = ?"
                    " WHERE leg_id = ? AND state = 'settled'", (self.clock(), leg.leg_id))
            return True
        kind = "currency_mismatch" if obj.currency != leg.currency else "amount_mismatch"
        if obj.status in state.SETTLED_STATUSES:
            with self._tx():
                self._open_incident(leg, kind, f"provider {obj.amount_minor} {obj.currency}")
        return False

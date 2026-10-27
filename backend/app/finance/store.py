"""The ledger store: SQLAlchemy 2 Core over SQLite (tests) or PostgreSQL (`LEDGER_DATABASE_URL`).

Every write is one transaction, and a refused write leaves the store exactly as it was. Every
method takes an optional `conn` so a caller (`ledger.pay`, `ledger.settle_due`) can make a check
and several writes one transaction; inside a caller's transaction each write is a savepoint, so a
refusal the caller catches still leaves nothing of the refused write behind.

Buckets map to tables: settled ← Σ postings · reserved ← reservations held · pending_in/out ←
expected_flows pending · pledged ← pledges active · unknown ← account_observations.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Connection, Table, create_engine, event, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from . import migrations
from .models import (
    EPOCH,
    Journal,
    LedgerRefusal,
    Posting,
    UnknownAccount,
    account_observations,
    accounts,
    entities,
    expected_flows,
    journals,
    metadata,
    obligations,
    pledges,
    postings,
    reservations,
)
from .schemas import MINOR_MAX
from .spendability import AccountView, Due, Flow

EXTERNAL_ENTITY = "external"
OPEN_OBLIGATION = ("open", "missed")  # a missed obligation is still owed and still counted
KIND_MAX = 32  # the width of every kind/purpose column


def _naive(when: datetime) -> datetime:
    """Times are stored as naive UTC; an unzoned time is refused rather than guessed."""
    if when.tzinfo is None:
        raise ValueError("a ledger time carries its zone")
    return when.astimezone(UTC).replace(tzinfo=None)


def _aware(when: datetime | None) -> datetime | None:
    return None if when is None else when.replace(tzinfo=UTC)


def _kind(kind: str) -> str:
    return kind[:KIND_MAX]


def minor_amount(value: Any, *, positive: bool = False) -> int:
    """An integer number of minor units within BIGINT, never a float, a string or a bool.

    Zero is refused, and so is a negative amount where `positive` (a hold, a pledge, an outflow):
    the closed code set has no separate code for it, and both move nothing a caller asked for.
    """
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > MINOR_MAX:
        raise LedgerRefusal("amount_not_integer_minor", value=repr(value))
    if value == 0 or (positive and value < 0):
        raise LedgerRefusal("zero_amount", value=value)
    return value


def _sum(c: Connection, table: Table, account_id: str, *where: Any) -> int:
    return int(c.execute(select(func.coalesce(func.sum(table.c.amount_minor), 0))
                         .where(table.c.account_id == account_id, *where)).scalar())


class LedgerStore:
    """One branch's ledger: one SQLite database or one PostgreSQL database."""

    def __init__(self, url: str | None = None) -> None:
        url = url or os.environ.get("LEDGER_DATABASE_URL") or "sqlite://"
        if url.startswith("sqlite"):
            self.engine = create_engine(url, poolclass=StaticPool,
                                        connect_args={"check_same_thread": False})
            event.listen(self.engine, "connect", _sqlite_connect)
            event.listen(self.engine, "begin", _sqlite_begin)
        else:
            self.engine = create_engine(url)
        migrations.upgrade(self.engine)

    # ------------------------------------------------------------------------- transactions

    @contextmanager
    def transaction(self, conn: Connection | None = None) -> Iterator[Connection]:
        """A new transaction, or a savepoint inside the caller's when it passes one in."""
        if conn is not None:
            with conn.begin_nested():
                yield conn
            return
        with self.engine.begin() as new:
            yield new

    @contextmanager
    def reading(self, conn: Connection | None = None) -> Iterator[Connection]:
        """The caller's connection as it is (a read needs no savepoint), or a new transaction."""
        if conn is not None:
            yield conn
            return
        with self.engine.begin() as new:
            yield new

    # ------------------------------------------------------------------------------- setup

    def add_entity(self, entity_id: str, name: str, kind: str, *, synthetic: bool = True,
                   conn: Connection | None = None) -> None:
        with self.transaction(conn) as c:
            c.execute(insert(entities).values(entity_id=entity_id, name=name, kind=kind,
                                              synthetic=synthetic))

    def open_account(self, account_id: str, entity_id: str, currency: str, *, as_of: datetime,
                     kind: str = "cash", venue: str | None = None,
                     floor_minor: int | None = None,
                     observability: Literal["known", "unknown"] = "known",
                     conn: Connection | None = None) -> None:
        with self.transaction(conn) as c:
            c.execute(insert(accounts).values(
                account_id=account_id, entity_id=entity_id, currency=currency, kind=kind,
                venue=venue, floor_minor=floor_minor))
            c.execute(insert(account_observations).values(
                account_id=account_id, observability=observability, as_of=_naive(as_of)))

    def external_account(self, currency: str, conn: Connection | None = None) -> str:
        """The outside world's account in one currency: counterparty of arrivals and payees."""
        account_id = f"{EXTERNAL_ENTITY}/{currency}"
        with self.transaction(conn) as c:
            if self._account(c, account_id, required=False) is not None:
                return account_id
            if c.execute(select(entities.c.entity_id)
                         .where(entities.c.entity_id == EXTERNAL_ENTITY)).first() is None:
                self.add_entity(EXTERNAL_ENTITY, "Outside world", "external", conn=c)
            self.open_account(account_id, EXTERNAL_ENTITY, currency, kind="external",
                              as_of=EPOCH, conn=c)
        return account_id

    def observe(self, account_id: str, observability: Literal["known", "unknown"],
                as_of: datetime, conn: Connection | None = None) -> None:
        """Record what is observable of a balance now; stale is derived at read time."""
        with self.transaction(conn) as c:
            self._account(c, account_id)
            c.execute(update(account_observations)
                      .where(account_observations.c.account_id == account_id)
                      .values(observability=observability, as_of=_naive(as_of)))

    # ----------------------------------------------------------------------------- journals

    def apply(self, journal: Journal | Posting, conn: Connection | None = None) -> Journal:
        """Commit a balanced journal whole, or refuse it and change nothing.

        A bare `Posting` is accepted only to be refused: no posting exists outside a journal.
        """
        if isinstance(journal, Posting):
            raise LedgerRefusal("no_journal", account=journal.account_id)
        if not isinstance(journal, Journal):
            raise TypeError("apply takes a Journal")
        with self.transaction(conn) as c:
            return self._apply(c, journal)

    def _apply(self, c: Connection, journal: Journal) -> Journal:
        if not journal.postings:
            raise LedgerRefusal("zero_amount", journal_id=journal.journal_id)
        held = {r.account_id: r for r in c.execute(select(accounts).where(
            accounts.c.account_id.in_({p.account_id for p in journal.postings})))}
        rows, totals = [], defaultdict(int)
        for p in journal.postings:
            amount = minor_amount(p.amount_minor)
            if p.account_id not in held:
                raise UnknownAccount(p.account_id)
            currency = held[p.account_id].currency
            if p.currency is not None and p.currency != currency:
                raise LedgerRefusal("journal_unbalanced", account=p.account_id,
                                    currency=p.currency, holds=currency)
            totals[currency] += amount
            rows.append({"journal_id": journal.journal_id, "account_id": p.account_id,
                         "currency": currency, "amount_minor": amount})
        for currency, diff in sorted(totals.items()):
            if diff:
                raise LedgerRefusal("journal_unbalanced", currency=currency, diff=diff)
        seq = (c.execute(select(func.max(journals.c.seq))).scalar() or 0) + 1
        c.execute(insert(journals).values(
            journal_id=journal.journal_id, kind=_kind(journal.kind), round=journal.round,
            sim_time=_naive(journal.sim_time), seq=seq, source_intent_id=journal.source_intent_id,
            source_leg_id=journal.source_leg_id, mode=journal.mode))
        c.execute(insert(postings), rows)
        for account_id in {r["account_id"] for r in rows}:
            self._check_spoken_for(c, account_id)
        return Journal(**{**journal.__dict__, "seq": seq})

    def _free(self, c: Connection, account_id: str) -> tuple[Any, str, int, int]:
        """(account, observability, settled, free): free = settled − everything promised."""
        acc = self._account(c, account_id)
        observability = c.execute(select(account_observations.c.observability).where(
            account_observations.c.account_id == account_id)).scalar_one()
        settled = _sum(c, postings, account_id)
        free = (settled
                - _sum(c, reservations, account_id, reservations.c.state == "held")
                - _sum(c, pledges, account_id, pledges.c.state == "active")
                - _sum(c, expected_flows, account_id, expected_flows.c.direction == "out",
                       expected_flows.c.state == "pending"))
        return acc, observability, settled, free

    def _check_spoken_for(self, c: Connection, account_id: str) -> None:
        """reserved ≤ settled: no write may leave a known cash account below its promises.

        An unknown balance cannot be checked against anything; nothing executes on it anyway
        (`check_outflow` refuses `unknown_balance`).
        """
        acc, observability, settled, free = self._free(c, account_id)
        if acc.kind == "cash" and observability == "known" and free < 0:
            raise LedgerRefusal("reserved_exceeds_settled", account=account_id,
                                settled=settled, spoken_for=settled - free)

    def _room(self, c: Connection, account_id: str, amount: int, code: str,
              observed: bool) -> str:
        """Refuse a hold or a pledge the free units cannot cover; returns the currency.

        `observed` marks a write that records a snapshot's own buckets: on an unknown account
        those are taken as observed, since no balance exists to check them against.
        """
        acc, observability, _, free = self._free(c, account_id)
        if observability == "unknown":
            if not observed:
                raise LedgerRefusal("unknown_balance", account=account_id)
        elif amount > free:
            raise LedgerRefusal(code, account=account_id, amount=amount, free=free)
        return acc.currency

    # ------------------------------------------------------------------------- reservations

    def hold(self, account_id: str, amount_minor: int, *, now: datetime,
             reservation_id: str | None = None, purpose: str = "hold",
             expires_at: datetime | None = None, observed: bool = False,
             conn: Connection | None = None) -> str:
        """settled → reserved; refused when the free settled units do not cover it."""
        amount = minor_amount(amount_minor, positive=True)
        with self.transaction(conn) as c:
            currency = self._room(c, account_id, amount, "reserved_exceeds_settled", observed)
            if reservation_id and c.execute(select(reservations.c.reservation_id).where(
                    reservations.c.reservation_id == reservation_id)).first():
                raise ValueError(f"reservation id {reservation_id} is taken")
            reservation_id = reservation_id or self._next_id(c, reservations, "res")
            c.execute(insert(reservations).values(
                reservation_id=reservation_id, account_id=account_id, currency=currency,
                amount_minor=amount, state="held", purpose=_kind(purpose),
                created_at=_naive(now),
                expires_at=None if expires_at is None else _naive(expires_at)))
        return reservation_id

    def commit(self, reservation_id: str, *, due_at: datetime, flow_id: str | None = None,
               kind: str = "committed_outflow", conn: Connection | None = None) -> str:
        """reserved → pending_out in one step, so the units are never counted twice."""
        with self.transaction(conn) as c:
            res = self._held(c, reservation_id)
            flow_id = flow_id or f"out:{reservation_id}"
            c.execute(update(reservations).where(reservations.c.reservation_id == reservation_id)
                      .values(state="committed"))
            c.execute(insert(expected_flows).values(
                flow_id=flow_id, account_id=res.account_id, direction="out",
                currency=res.currency, amount_minor=res.amount_minor,
                expected_at=_naive(due_at), state="pending", reservation_id=reservation_id,
                kind=_kind(kind)))
        return flow_id

    def release(self, reservation_id: str, conn: Connection | None = None) -> None:
        with self.transaction(conn) as c:
            self._held(c, reservation_id)
            c.execute(update(reservations).where(reservations.c.reservation_id == reservation_id)
                      .values(state="released"))

    def expire_due(self, now: datetime, conn: Connection | None = None) -> list[str]:
        """Every held reservation whose `expires_at` ≤ now becomes expired."""
        with self.transaction(conn) as c:
            due = list(c.execute(
                select(reservations.c.reservation_id)
                .where(reservations.c.state == "held", reservations.c.expires_at.is_not(None),
                       reservations.c.expires_at <= _naive(now))
                .order_by(reservations.c.reservation_id)).scalars())
            if due:
                c.execute(update(reservations).where(reservations.c.reservation_id.in_(due))
                          .values(state="expired"))
        return due

    def settle(self, reservation_id: str, *, to_account: str, at: datetime,
               journal_id: str | None = None, round: int = 0,
               conn: Connection | None = None) -> Journal:
        """pending_out → settled out: the committed reservation's flow pays `to_account`."""
        with self.transaction(conn) as c:
            res = self._reservation(c, reservation_id)
            if res.state != "committed":
                raise LedgerRefusal("reservation_not_held", reservation_id=reservation_id,
                                    state=res.state)
            flow_id = c.execute(select(expected_flows.c.flow_id).where(
                expected_flows.c.reservation_id == reservation_id,
                expected_flows.c.state == "pending")).scalar_one()
            return self.settle_flow(flow_id, counterparty=to_account, at=at,
                                    journal_id=journal_id, round=round, conn=c)

    def settle_flow(self, flow_id: str, *, counterparty: str, at: datetime,
                    journal_id: str | None = None, round: int = 0,
                    conn: Connection | None = None) -> Journal:
        """A pending flow lands: an arrival from, or a payment to, `counterparty`."""
        with self.transaction(conn) as c:
            flow = c.execute(select(expected_flows)
                             .where(expected_flows.c.flow_id == flow_id)).one()
            if flow.state != "pending":
                raise ValueError(f"flow {flow_id} is {flow.state}, not pending")
            if counterparty == flow.account_id:
                raise ValueError(f"flow {flow_id} cannot settle against its own account")
            sign = 1 if flow.direction == "in" else -1
            c.execute(update(expected_flows).where(expected_flows.c.flow_id == flow_id)
                      .values(state="settled"))
            if flow.reservation_id:
                c.execute(update(reservations)
                          .where(reservations.c.reservation_id == flow.reservation_id)
                          .values(state="settled"))
                c.execute(update(obligations)
                          .where(obligations.c.reservation_id == flow.reservation_id,
                                 obligations.c.state.in_(OPEN_OBLIGATION))
                          .values(state="met"))
            return self._apply(c, Journal(
                journal_id=journal_id or f"settle:{flow_id}", kind=f"settle_{flow.kind}",
                round=round, sim_time=at, postings=(
                    Posting(flow.account_id, sign * flow.amount_minor),
                    Posting(counterparty, -sign * flow.amount_minor))))

    # ------------------------------------------------------------------------------ pledges

    def pledge(self, account_id: str, amount_minor: int, collateral_ref: str, *,
               pledge_id: str | None = None, facility_id: str | None = None,
               observed: bool = False, conn: Connection | None = None) -> str:
        """Move units to pledged; the same collateral_ref is never in two active pledges."""
        amount = minor_amount(amount_minor, positive=True)
        with self.transaction(conn) as c:
            active = c.execute(select(pledges.c.pledge_id).where(
                pledges.c.collateral_ref == collateral_ref, pledges.c.state == "active")).first()
            if active is not None:
                raise LedgerRefusal("already_pledged", collateral_ref=collateral_ref,
                                    pledge_id=active.pledge_id)
            if pledge_id and c.execute(select(pledges.c.pledge_id)
                                       .where(pledges.c.pledge_id == pledge_id)).first():
                raise ValueError(f"pledge id {pledge_id} is taken")
            currency = self._room(c, account_id, amount, "pledge_exceeds_free", observed)
            pledge_id = pledge_id or self._next_id(c, pledges, "pledge")
            try:
                c.execute(insert(pledges).values(
                    pledge_id=pledge_id, account_id=account_id, collateral_ref=collateral_ref,
                    currency=currency, amount_minor=amount, state="active",
                    facility_id=facility_id))
            except IntegrityError as exc:  # a concurrent pledge won the partial unique index
                raise LedgerRefusal("already_pledged", collateral_ref=collateral_ref) from exc
        return pledge_id

    def release_pledge(self, pledge_id: str, conn: Connection | None = None) -> None:
        with self.transaction(conn) as c:
            c.execute(update(pledges).where(pledges.c.pledge_id == pledge_id,
                                            pledges.c.state == "active")
                      .values(state="released"))

    # ----------------------------------------------------------- expected flows, obligations

    def expect(self, account_id: str, direction: Literal["in", "out"], amount_minor: int,
               expected_at: datetime, *, kind: str, flow_id: str | None = None,
               conn: Connection | None = None) -> str:
        """A movement not yet settled: a receivable, a withdrawal, an advance in flight."""
        amount = minor_amount(amount_minor, positive=True)
        with self.transaction(conn) as c:
            currency = self._account(c, account_id).currency
            flow_id = flow_id or self._next_id(c, expected_flows, "flow")
            c.execute(insert(expected_flows).values(
                flow_id=flow_id, account_id=account_id, direction=direction, currency=currency,
                amount_minor=amount, expected_at=_naive(expected_at), state="pending",
                kind=_kind(kind)))
            if direction == "out":
                self._check_spoken_for(c, account_id)
        return flow_id

    def reschedule(self, flow_id: str, expected_at: datetime,
                   conn: Connection | None = None) -> None:
        """A delay rewrites the expected time; a delayed receivable is never credited early."""
        with self.transaction(conn) as c:
            done = c.execute(update(expected_flows)
                             .where(expected_flows.c.flow_id == flow_id,
                                    expected_flows.c.state == "pending")
                             .values(expected_at=_naive(expected_at)))
            if done.rowcount != 1:
                raise ValueError(f"no pending flow {flow_id}")

    def due_flows(self, direction: Literal["in", "out"], now: datetime,
                  conn: Connection | None = None) -> list[Any]:
        """Pending flows expected by `now`, in time order."""
        with self.reading(conn) as c:
            return c.execute(select(expected_flows).where(
                expected_flows.c.direction == direction, expected_flows.c.state == "pending",
                expected_flows.c.expected_at <= _naive(now))
                .order_by(expected_flows.c.expected_at, expected_flows.c.flow_id)).all()

    def add_obligation(self, obligation_id: str, account_id: str, amount_minor: int,
                       due_at: datetime, *, kind: str, reservation_id: str | None = None,
                       mandatory: bool = True, state: str = "open",
                       conn: Connection | None = None) -> None:
        """An obligation; its reservation, when named, is on its account for its amount."""
        amount = minor_amount(amount_minor, positive=True)
        with self.transaction(conn) as c:
            account = self._account(c, account_id)
            if reservation_id and state in OPEN_OBLIGATION:
                self._covers(self._reservation(c, reservation_id), account_id, amount)
            c.execute(insert(obligations).values(
                obligation_id=obligation_id, entity_id=account.entity_id, account_id=account_id,
                currency=account.currency, amount_minor=amount, due_at=_naive(due_at),
                kind=_kind(kind), mandatory=mandatory, state=state,
                reservation_id=reservation_id))

    def attach_reservation(self, obligation_id: str, reservation_id: str,
                           conn: Connection | None = None) -> None:
        with self.transaction(conn) as c:
            ob = c.execute(select(obligations)
                           .where(obligations.c.obligation_id == obligation_id)).one()
            self._covers(self._reservation(c, reservation_id), ob.account_id, ob.amount_minor)
            c.execute(update(obligations).where(obligations.c.obligation_id == obligation_id)
                      .values(reservation_id=reservation_id))

    def set_obligation_state(self, obligation_id: str, state: str,
                             conn: Connection | None = None) -> None:
        with self.transaction(conn) as c:
            c.execute(update(obligations).where(obligations.c.obligation_id == obligation_id)
                      .values(state=state))

    def due_obligations(self, now: datetime, conn: Connection | None = None) -> list[Any]:
        """Mandatory obligations still owed (open or missed) and due by `now`, in time order."""
        with self.reading(conn) as c:
            return c.execute(select(obligations).where(
                obligations.c.state.in_(OPEN_OBLIGATION), obligations.c.mandatory.is_(True),
                obligations.c.due_at <= _naive(now))
                .order_by(obligations.c.due_at, obligations.c.obligation_id)).all()

    # -------------------------------------------------------------------------------- reads

    def view(self, account_id: str, conn: Connection | None = None) -> AccountView:
        """Every bucket of one account, read in one transaction."""
        with self.reading(conn) as c:
            acc = self._account(c, account_id)
            obs = c.execute(select(account_observations).where(
                account_observations.c.account_id == account_id)).one()
            settled = _sum(c, postings, account_id)
            reserved = _sum(c, reservations, account_id, reservations.c.state == "held")
            pledged = _sum(c, pledges, account_id, pledges.c.state == "active")
            flows = c.execute(select(expected_flows).where(
                expected_flows.c.account_id == account_id, expected_flows.c.state == "pending")
                .order_by(expected_flows.c.expected_at, expected_flows.c.flow_id)).all()
            dues = c.execute(select(obligations).where(
                obligations.c.account_id == account_id,
                obligations.c.state.in_(OPEN_OBLIGATION))
                .order_by(obligations.c.due_at, obligations.c.obligation_id)).all()
        pending = {d: tuple(Flow(f.flow_id, f.amount_minor, _aware(f.expected_at), f.kind,
                                 f.reservation_id) for f in flows if f.direction == d)
                   for d in ("in", "out")}
        # An obligation whose reservation is committed is counted once, through its flow.
        carried = {f.reservation_id for f in pending["out"] if f.reservation_id}
        return AccountView(
            account_id=acc.account_id, entity_id=acc.entity_id, currency=acc.currency,
            kind=acc.kind, floor_minor=acc.floor_minor, observability=obs.observability,
            as_of=_aware(obs.as_of), settled_minor=settled, reserved_minor=reserved,
            pledged_minor=pledged, pending_in=pending["in"], pending_out=pending["out"],
            obligations=tuple(Due(d.obligation_id, d.amount_minor, _aware(d.due_at), d.kind,
                                  d.reservation_id)
                              for d in dues if d.reservation_id not in carried))

    def reservation(self, reservation_id: str, conn: Connection | None = None) -> Any:
        with self.reading(conn) as c:
            return self._reservation(c, reservation_id)

    def rows(self, table_name: str, conn: Connection | None = None) -> list[dict]:
        """A table's rows in primary-key order (inspection and tests)."""
        table = metadata.tables[table_name]
        with self.reading(conn) as c:
            return [dict(r._mapping)
                    for r in c.execute(select(table).order_by(*table.primary_key.columns))]

    def dump(self) -> dict[str, list[dict]]:
        """Every table, every row: two equal dumps are the same ledger."""
        with self.reading() as c:
            return {name: self.rows(name, conn=c) for name in sorted(metadata.tables)}

    # ------------------------------------------------------------------------------ helpers

    def _account(self, c: Connection, account_id: str, required: bool = True) -> Any:
        row = c.execute(select(accounts).where(accounts.c.account_id == account_id)).first()
        if row is None and required:
            raise UnknownAccount(account_id)
        return row

    def _reservation(self, c: Connection, reservation_id: str) -> Any:
        row = c.execute(select(reservations)
                        .where(reservations.c.reservation_id == reservation_id)).first()
        if row is None:
            raise LedgerRefusal("reservation_not_held", reservation_id=reservation_id,
                                state=None)
        return row

    def _held(self, c: Connection, reservation_id: str) -> Any:
        res = self._reservation(c, reservation_id)
        if res.state != "held":
            raise LedgerRefusal("reservation_not_held", reservation_id=reservation_id,
                                state=res.state)
        return res

    @staticmethod
    def _covers(res: Any, account_id: str, amount: int) -> None:
        if res.account_id != account_id or res.amount_minor != amount:
            raise ValueError(f"reservation {res.reservation_id} is not {amount} on {account_id}")

    @staticmethod
    def _next_id(c: Connection, table: Table, prefix: str) -> str:
        """`<prefix>-<n>`, the first n past the row count that no row already uses."""
        key = next(iter(table.primary_key.columns))
        n = c.execute(select(func.count()).select_from(table)).scalar()
        while True:
            n += 1
            if c.execute(select(key).where(key == f"{prefix}-{n}")).first() is None:
                return f"{prefix}-{n}"


def _sqlite_connect(dbapi_connection: Any, _record: Any) -> None:
    # pysqlite's own transaction handling breaks SAVEPOINT; SQLAlchemy emits BEGIN instead.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _sqlite_begin(conn: Connection) -> None:
    conn.exec_driver_sql("BEGIN")

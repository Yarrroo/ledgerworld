"""Lender capacity K_p and revenue-based advances (system brief §6, LF-2).

K_p, the pool's usable capacity, is what it may still lend at its discretion:

    K_p = Σ settled of the pool's known, fresh cash accounts − committed undrawn − pledged
          − pool obligations due within the horizon − pool floor

Committed funding is kept apart from discretionary funding: an active committed line's undrawn
part is subtracted from K_p, so a draw on the line moves settled and committed undrawn together
and leaves K_p unchanged, while a discretionary advance lowers K_p by its principal and is refused
beyond it (`beyond_capacity`, the binding constraint named). An unknown or stale balance adds
nothing and reduces authority; it is never read as zero or as its last value. Every committed
outflow of the pool (a pending_out) counts as an obligation due, as it does in S: it is spoken
for from the moment of commit.

A repayment is a share of revenue the ledger has observed (`revenue_observations`); forecast
revenue never enters that table, and a period with no observation repays nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import Connection, insert, select
from sqlalchemy.exc import IntegrityError

from .contracts import (
    Facility,
    ensure_account,
    facility,
    outstanding_minor,
    pool_facilities,
    repayment_minor,
    set_facility,
)
from .ledger import check_outflow
from .models import (
    HORIZON,
    Journal,
    LedgerRefusal,
    Posting,
    accounts,
    journals,
    lending_pools,
    revenue_observations,
)
from .spendability import Authority, grouped, spendability, state_of
from .store import LedgerStore, _naive, minor_amount

Mode = Literal["simulation", "fake", "sandbox", "sandbox_simulation"]


@dataclass(frozen=True)
class CapacityParts:
    settled_known: int
    committed_undrawn: int
    pledged: int
    obligations_due: int
    floor: int


@dataclass(frozen=True)
class PoolCapacity:
    """K_p and the parts it is computed from, in the pool's currency (minor units)."""

    pool: str
    currency: str
    K_p: int  # the system brief's name for it
    authority: Authority
    parts: CapacityParts

    @property
    def binding(self) -> str:
        return f"K_p = {grouped(self.K_p, self.currency)}"


@dataclass(frozen=True)
class Repayment:
    facility_id: str
    period_end: datetime
    observed_revenue_minor: int | None  # None: nothing observed, so nothing repaid
    amount_minor: int
    outstanding_minor: int  # after this repayment
    journal: Journal | None


# ---------------------------------------------------------------------------------- capacity

def capacity(store: LedgerStore, pool: str, now: datetime, horizon: timedelta = HORIZON,
             conn: Connection | None = None) -> PoolCapacity:
    """K_p of a lending pool at `now`, read in one transaction."""
    end = now + horizon
    with store.reading(conn) as c:
        row = c.execute(select(lending_pools).where(
            lending_pools.c.pool_entity_id == pool)).first()
        if row is None:
            raise LookupError(f"no lending pool {pool}")
        cash = c.execute(select(accounts.c.account_id).where(
            accounts.c.entity_id == pool, accounts.c.kind == "cash",
            accounts.c.currency == row.currency).order_by(accounts.c.account_id)).scalars().all()
        settled = pledged = due = 0
        authority: Authority = "full"
        for account_id in cash:
            view = store.view(account_id, conn=c)
            if state_of(view, now) == "known":
                settled += view.settled_minor
            else:
                authority = "reduced"
            pledged += view.pledged_minor
            due += view.pending_out_minor + sum(d.amount_minor for d in view.obligations
                                                if d.at <= end)
        undrawn = sum(max(0, f.limit_minor - outstanding_minor(store, f, conn=c))
                      for f in pool_facilities(store, pool, conn=c)
                      if f.kind == "committed_line" and f.state == "active")
    parts = CapacityParts(settled_known=settled, committed_undrawn=undrawn, pledged=pledged,
                          obligations_due=due, floor=row.floor_minor)
    k_p = settled - undrawn - pledged - due - row.floor_minor
    return PoolCapacity(pool, row.currency, k_p, authority, parts)


def check_draw(store: LedgerStore, pool: str, amount_minor: int, now: datetime,
               horizon: timedelta = HORIZON,
               conn: Connection | None = None) -> LedgerRefusal | None:
    """None when a discretionary draw of `amount_minor` fits within K_p, else the refusal."""
    try:
        amount = minor_amount(amount_minor, positive=True)
    except LedgerRefusal as refusal:
        return refusal
    cap = capacity(store, pool, now, horizon, conn=conn)
    if amount > cap.K_p:
        return LedgerRefusal("beyond_capacity", pool=pool, amount=amount, K_p=cap.K_p,
                             binding=cap.binding, authority=cap.authority)
    return None


# ----------------------------------------------------------------------------- disbursal

def _cash_of(c: Connection, account_id: str, entity: str, currency: str) -> None:
    """Money moves only from and to an entity's own cash account in the facility's currency."""
    row = c.execute(select(accounts.c.entity_id, accounts.c.currency, accounts.c.kind)
                    .where(accounts.c.account_id == account_id)).first()
    if row is None or tuple(row) != (entity, currency, "cash"):
        raise ValueError(f"{account_id} is not a {currency} cash account of {entity}")


def _kind(f: Facility, kind: str, *states: str) -> None:
    if f.kind != kind or f.state not in states:
        raise ValueError(f"facility {f.facility_id} is a {f.state} {f.kind}, not "
                         f"{' or '.join(states)} {kind}")


def disburse(store: LedgerStore, facility_id: str, *, now: datetime,
             from_account: str | None = None, borrower_account: str | None = None,
             journal_id: str | None = None, round: int = 0, mode: Mode = "simulation",
             source_intent_id: str | None = None, source_leg_id: str | None = None,
             horizon: timedelta = HORIZON, conn: Connection | None = None) -> Journal:
    """Disburse an offered revenue advance whole, in one transaction; raises the refusal.

    The principal must fit within K_p and within the source account's S and floor headroom.
    The fee is recognised at disbursal: the lender's receivable and the borrower's payable both
    open at principal + fee.
    """
    with store.transaction(conn) as c:
        f = facility(store, facility_id, conn=c)
        _kind(f, "revenue_advance", "offered")
        source = from_account or f"{f.pool}/operating"
        payee = borrower_account or f"{f.borrower}/operating"
        _cash_of(c, source, f.pool, f.currency)
        _cash_of(c, payee, f.borrower, f.currency)
        refusal = (check_draw(store, f.pool, f.limit_minor, now, horizon, conn=c)
                   or check_outflow(store.view(source, conn=c), f.limit_minor, now, horizon))
        if refusal is not None:
            raise refusal
        income, expense = f"{f.pool}/fee-income", f"{f.borrower}/fee-expense"
        payable = f"{f.borrower}/advance-payable:{f.facility_id}"
        ensure_account(store, income, f.pool, f.currency, "income", c)
        ensure_account(store, expense, f.borrower, f.currency, "expense", c)
        ensure_account(store, payable, f.borrower, f.currency, "payable", c)
        fee, owed = f.fee_minor, f.owed_minor
        lines = [Posting(f.receivable_account, owed), Posting(source, -f.limit_minor),
                 Posting(income, -fee), Posting(payee, f.limit_minor), Posting(expense, fee),
                 Posting(payable, -owed)]
        journal = store.apply(Journal(
            journal_id=journal_id or f"disburse:{f.facility_id}", kind="advance_disbursal",
            round=round, sim_time=now, source_intent_id=source_intent_id,
            source_leg_id=source_leg_id, mode=mode,
            postings=tuple(p for p in lines if p.amount_minor)), conn=c)
        set_facility(store, f.facility_id, state="active", conn=c)
        return journal


def draw_line(store: LedgerStore, facility_id: str, amount_minor: int, *, now: datetime,
              borrower_account: str | None = None, journal_id: str | None = None,
              round: int = 0, mode: Mode = "simulation", source_intent_id: str | None = None,
              source_leg_id: str | None = None, conn: Connection | None = None) -> Journal:
    """A borrower draws on an active committed line, from the hold that keeps it undrawn.

    Committed funding is not discretionary: the draw is bounded by the line's undrawn part, not
    by K_p, and it leaves K_p unchanged (settled and committed undrawn fall together).
    """
    amount = minor_amount(amount_minor, positive=True)
    with store.transaction(conn) as c:
        f = facility(store, facility_id, conn=c)
        _kind(f, "committed_line", "active")
        undrawn = f.limit_minor - outstanding_minor(store, f, conn=c)
        if amount > undrawn:
            raise LedgerRefusal("beyond_capacity", facility=f.facility_id, amount=amount,
                                undrawn=undrawn,
                                binding=f"undrawn line = {grouped(undrawn, f.currency)}")
        held = store.reservation(f.reservation_id, conn=c) if f.reservation_id else None
        if held is not None and held.state != "held":
            held = None
        source = held.account_id if held is not None else f"{f.pool}/operating"
        payee = borrower_account or f"{f.borrower}/operating"
        _cash_of(c, source, f.pool, f.currency)
        _cash_of(c, payee, f.borrower, f.currency)
        if state_of(store.view(source, conn=c), now) == "unknown":
            raise LedgerRefusal("unknown_balance", account=source)
        if held is not None:
            store.release(held.reservation_id, conn=c)
        payable = f"{f.borrower}/line-payable:{f.facility_id}"
        ensure_account(store, payable, f.borrower, f.currency, "payable", c)
        journal = store.apply(Journal(
            journal_id=journal_id or f"draw:{f.facility_id}:{_seq(c) + 1}", kind="line_draw",
            round=round, sim_time=now, source_intent_id=source_intent_id,
            source_leg_id=source_leg_id, mode=mode,
            postings=(Posting(f.receivable_account, amount), Posting(source, -amount),
                      Posting(payee, amount), Posting(payable, -amount))), conn=c)
        if held is not None:
            rest = held.amount_minor - amount
            new_id = None
            if rest > 0:
                new_id = store.hold(source, rest, now=now, purpose="committed_line",
                                    reservation_id=f"{f.facility_id}:undrawn@{journal.seq}",
                                    conn=c)
            set_facility(store, f.facility_id, reservation_id=new_id, conn=c)
        return journal


def _seq(c: Connection) -> int:
    return int(c.execute(select(journals.c.seq).order_by(journals.c.seq.desc())
                         .limit(1)).scalar() or 0)


# ----------------------------------------------------------------------------- repayment

def observe_revenue(store: LedgerStore, facility_id: str, period_end: datetime,
                    revenue_minor: int, *, observed_at: datetime, source: str,
                    conn: Connection | None = None) -> None:
    """Record a borrower's revenue for a period once it has been observed.

    Revenue seen before its period ends is a forecast, and is refused: only what happened is
    a basis for repayment.
    """
    if isinstance(revenue_minor, bool) or not isinstance(revenue_minor, int):
        raise LedgerRefusal("amount_not_integer_minor", value=repr(revenue_minor))
    if revenue_minor:
        minor_amount(revenue_minor, positive=True)
    if observed_at < period_end:
        raise ValueError(f"revenue for the period ending {period_end.isoformat()} cannot be "
                         f"observed at {observed_at.isoformat()}: that is a forecast")
    with store.transaction(conn) as c:
        f = facility(store, facility_id, conn=c)
        try:
            c.execute(insert(revenue_observations).values(
                facility_id=f.facility_id, period_end=_naive(period_end), currency=f.currency,
                revenue_minor=revenue_minor, observed_at=_naive(observed_at), source=source))
        except IntegrityError as exc:
            raise ValueError(f"revenue for {facility_id} period {period_end.isoformat()} is "
                             "already observed") from exc


def observed_revenue(store: LedgerStore, facility_id: str, period_end: datetime,
                     now: datetime, conn: Connection | None = None) -> int | None:
    """The revenue observed for one period by `now`, or None when none has been."""
    with store.reading(conn) as c:
        return c.execute(select(revenue_observations.c.revenue_minor).where(
            revenue_observations.c.facility_id == facility_id,
            revenue_observations.c.period_end == _naive(period_end),
            revenue_observations.c.observed_at <= _naive(now))).scalar()


def repay(store: LedgerStore, facility_id: str, period_end: datetime, *, now: datetime,
          from_account: str | None = None, to_account: str | None = None,
          journal_id: str | None = None, round: int = 0, mode: Mode = "simulation",
          source_intent_id: str | None = None, source_leg_id: str | None = None,
          conn: Connection | None = None) -> Repayment:
    """One period's repayment of an advance: floor(observed revenue × share), capped at
    outstanding. No observation, no repayment; a period is repaid at most once."""
    with store.transaction(conn) as c:
        f = facility(store, facility_id, conn=c)
        _kind(f, "revenue_advance", "active", "repaid")
        journal_id = journal_id or f"repay:{f.facility_id}:{period_end:%Y%m%dT%H%MZ}"
        if c.execute(select(journals.c.journal_id)
                     .where(journals.c.journal_id == journal_id)).first():
            raise ValueError(f"period {period_end.isoformat()} of {facility_id} is already "
                             "repaid")
        revenue = observed_revenue(store, f.facility_id, period_end, now, conn=c)
        owed = outstanding_minor(store, f, conn=c)
        amount = repayment_minor(revenue, f.repay_share_bps, owed)
        if not amount:
            return Repayment(f.facility_id, period_end, revenue, 0, owed, None)
        payer = from_account or f"{f.borrower}/operating"
        payee = to_account or f"{f.pool}/operating"
        _cash_of(c, payer, f.borrower, f.currency)
        _cash_of(c, payee, f.pool, f.currency)
        view = store.view(payer, conn=c)
        state = state_of(view, now)
        if state != "known":
            raise LedgerRefusal(f"{state}_balance", account=payer)
        s_now = spendability(view, now, now).value
        if amount > s_now:
            raise LedgerRefusal("insufficient_spendable", account=payer, amount=amount,
                                S_now=s_now)
        journal = store.apply(Journal(
            journal_id=journal_id, kind="advance_repayment", round=round, sim_time=now,
            source_intent_id=source_intent_id, source_leg_id=source_leg_id, mode=mode,
            postings=(Posting(f"{f.borrower}/advance-payable:{f.facility_id}", amount),
                      Posting(payer, -amount), Posting(payee, amount),
                      Posting(f.receivable_account, -amount))), conn=c)
        if owed - amount == 0:
            set_facility(store, f.facility_id, state="repaid", conn=c)
        return Repayment(f.facility_id, period_end, revenue, amount, owed - amount, journal)

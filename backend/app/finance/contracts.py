"""Contract terms: committed lines, revenue advances, collateral facilities (system brief §6).

A snapshot contract (C5) becomes one `facilities` row and one receivable account of the lender,
`<lender>/loan:<contract_id>`, whose balance is what the borrower owes: the drawn part of a line,
the principal plus fee of a disbursed advance. Outstanding is therefore Σ postings, never a column.

The money rules of the terms are pure integer functions here, so lending, decisions and the API
compute the same numbers: the fee is bps on principal, recognised at disbursal; a repayment is
a share of observed revenue, capped at outstanding. Rounding is down, in the borrower's favour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Connection, insert, select, update

from .models import (
    EPOCH,
    Journal,
    Posting,
    accounts,
    facilities,
    journals,
    lending_pools,
    postings,
    reservations,
)
from .schemas import (
    CollateralFacility,
    CommittedLine,
    RevenueAdvance,
    Snapshot,
    SnapshotContract,
)
from .store import LedgerStore, _naive, _sum, minor_amount

BPS = 10000
FacilityKind = Literal["committed_line", "revenue_advance", "collateral"]
FacilityState = Literal["offered", "active", "repaid", "defaulted", "closed"]


@dataclass(frozen=True)
class Facility:
    """One contract between a lender pool and a borrower, as the ledger holds it.

    `limit_minor` is the line's limit, the advance's principal or the collateral facility's
    limit; `reservation_id` is the hold that keeps a committed line's undrawn part on the
    lender's account.
    """

    facility_id: str
    pool: str
    borrower: str
    kind: FacilityKind
    currency: str
    limit_minor: int
    fee_bps: int
    repay_share_bps: int | None
    reservation_id: str | None
    state: FacilityState
    receivable_account: str

    @property
    def fee_minor(self) -> int:
        return fee_minor(self.limit_minor, self.fee_bps)

    @property
    def owed_minor(self) -> int:
        """What a fully drawn facility owes at disbursal: principal plus fee."""
        return self.limit_minor + self.fee_minor


def _bps(value: Any, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= BPS \
            or (positive and value == 0):
        raise ValueError(f"basis points are an integer in [{int(positive)}, {BPS}], not {value!r}")
    return value


def fee_minor(principal_minor: int, fee_bps: int) -> int:
    """The flat fee on principal, rounded down: 1,000,000 at 800 bps -> 80,000."""
    return minor_amount(principal_minor, positive=True) * _bps(fee_bps) // BPS


def repayment_minor(observed_revenue_minor: int | None, repay_share_bps: int,
                    outstanding_minor: int) -> int:
    """A share of observed revenue, rounded down and capped at outstanding.

    No observation is no repayment: a forecast never stands in for revenue (`None` → 0).
    """
    share = _bps(repay_share_bps, positive=True)
    if observed_revenue_minor is None or outstanding_minor <= 0:
        return 0
    if observed_revenue_minor != 0:
        minor_amount(observed_revenue_minor, positive=True)
    return min(observed_revenue_minor * share // BPS, outstanding_minor)


def receivable_account(pool: str, facility_id: str) -> str:
    return f"{pool}/loan:{facility_id}"


def advance_payable(f: Facility) -> str:
    return f"{f.borrower}/advance-payable:{f.facility_id}"


def repay_journal_id(facility_id: str, period_end: datetime) -> str:
    """One id per facility and period, the same instant in any zone: what makes it repaid once."""
    return f"repay:{facility_id}:{_naive(period_end):%Y%m%dT%H%M%S%f}Z"


def _ids_fit(contract: SnapshotContract) -> None:
    """Every id this contract will generate fits its column (SQLite ignores widths; PG does not)."""
    cid, loan = contract.contract_id, receivable_account(contract.lender, contract.contract_id)
    width = {journals.c.journal_id: [f"open:{loan}"], reservations.c.reservation_id: [],
             accounts.c.account_id: [f"{loan}:opening"]}
    if isinstance(contract, CommittedLine):
        width[journals.c.journal_id].append(f"draw:{cid}-{10**9}")
        width[reservations.c.reservation_id].append(f"{cid}:undrawn@{10**9}")
        width[accounts.c.account_id].append(f"{contract.borrower}/line-payable:{cid}")
    if isinstance(contract, RevenueAdvance):
        width[journals.c.journal_id] += [f"disburse:{cid}", repay_journal_id(cid, EPOCH)]
        width[accounts.c.account_id].append(f"{contract.borrower}/advance-payable:{cid}")
    for column, ids in width.items():
        if not ids:
            continue
        longest = max(ids, key=len)
        if len(longest) > column.type.length:
            raise ValueError(f"contract {cid}: id {longest!r} is longer than {column} allows "
                             f"({column.type.length})")


def ensure_account(store: LedgerStore, account_id: str, entity_id: str, currency: str,
                   kind: str, conn: Connection) -> None:
    """Open a non-cash account (receivable, payable, income, expense) the first time it is used."""
    row = conn.execute(select(accounts.c.entity_id, accounts.c.currency, accounts.c.kind)
                       .where(accounts.c.account_id == account_id)).first()
    if row is None:
        store.open_account(account_id, entity_id, currency, kind=kind, as_of=EPOCH, conn=conn)
    elif tuple(row) != (entity_id, currency, kind):
        raise ValueError(f"account {account_id} is {tuple(row)}, not {(entity_id, currency, kind)}")


def register(store: LedgerStore, contract: SnapshotContract, *, as_of: datetime,
             conn: Connection | None = None) -> Facility:
    """Record one snapshot contract as a facility of its lender's pool.

    A line already drawn opens its receivable with the drawn amount, so a line's undrawn part is
    always `limit − outstanding`. The lender must be a lending pool of the ledger.
    """
    if isinstance(contract, CommittedLine):
        limit, fee, share = contract.limit, 0, None
    elif isinstance(contract, RevenueAdvance):
        limit, fee, share = contract.principal, contract.fee_bps, contract.repay_share_bps
    elif isinstance(contract, CollateralFacility):
        limit, fee, share = contract.limit, 0, None
    else:
        raise TypeError(f"not a contract: {contract!r}")
    if isinstance(contract, RevenueAdvance) and contract.state in ("active", "defaulted"):
        # C5 carries no outstanding for an advance; reading it as zero would hide the exposure.
        raise ValueError(f"contract {contract.contract_id}: a {contract.state} advance needs "
                         "its outstanding, which a snapshot does not carry")
    _ids_fit(contract)
    with store.transaction(conn) as c:
        pool = c.execute(select(lending_pools.c.currency).where(
            lending_pools.c.pool_entity_id == contract.lender)).first()
        if pool is None:
            raise ValueError(f"contract {contract.contract_id}: lender {contract.lender!r} is "
                             "not a lending pool")
        if pool.currency != limit.currency:
            raise ValueError(f"contract {contract.contract_id}: pool {contract.lender} lends "
                             f"{pool.currency}, not {limit.currency}")
        loan = receivable_account(contract.lender, contract.contract_id)
        ensure_account(store, loan, contract.lender, limit.currency, "receivable", c)
        c.execute(insert(facilities).values(
            facility_id=contract.contract_id, pool_entity_id=contract.lender,
            borrower_entity_id=contract.borrower, kind=contract.kind, currency=limit.currency,
            limit_minor=limit.minor, fee_bps=fee, repay_share_bps=share,
            reservation_id=getattr(contract, "reservation_id", None), state=contract.state,
            receivable_account=loan))
        drawn = contract.drawn.minor if isinstance(contract, CommittedLine) else 0
        if drawn:
            opening = f"{loan}:opening"
            ensure_account(store, opening, contract.lender, limit.currency, "external", c)
            store.apply(Journal(journal_id=f"open:{loan}", kind="opening", sim_time=as_of,
                                postings=(Posting(loan, drawn), Posting(opening, -drawn))),
                        conn=c)
        return facility(store, contract.contract_id, conn=c)


def load(store: LedgerStore, snapshot: Snapshot, conn: Connection | None = None) -> None:
    """Every contract of a snapshot, in its order; called by `ledger.from_snapshot`."""
    with store.transaction(conn) as c:
        for contract in snapshot.contracts:
            register(store, contract, as_of=snapshot.as_of, conn=c)


def _facility(row: Any) -> Facility:
    return Facility(
        facility_id=row.facility_id, pool=row.pool_entity_id, borrower=row.borrower_entity_id,
        kind=row.kind, currency=row.currency, limit_minor=row.limit_minor, fee_bps=row.fee_bps,
        repay_share_bps=row.repay_share_bps, reservation_id=row.reservation_id, state=row.state,
        receivable_account=row.receivable_account)


def facility(store: LedgerStore, facility_id: str, conn: Connection | None = None,
             lock: bool = False) -> Facility:
    """One facility; `lock` holds its row until `conn`'s transaction ends, so a writer reads its
    state, outstanding and undrawn only after a concurrent writer of the same facility commits."""
    if lock and conn is None:
        raise ValueError("a facility lock is held by the caller's transaction: pass conn")
    query = select(facilities).where(facilities.c.facility_id == facility_id)
    with store.reading(conn) as c:
        row = c.execute(query.with_for_update(key_share=True) if lock else query).first()
    if row is None:
        raise LookupError(f"no facility {facility_id}")
    return _facility(row)


def pool_facilities(store: LedgerStore, pool: str,
                    conn: Connection | None = None) -> list[Facility]:
    with store.reading(conn) as c:
        rows = c.execute(select(facilities).where(facilities.c.pool_entity_id == pool)
                         .order_by(facilities.c.facility_id)).all()
    return [_facility(r) for r in rows]


def outstanding_minor(store: LedgerStore, f: Facility, conn: Connection | None = None) -> int:
    """What the borrower owes now: the balance of the lender's receivable for the facility."""
    with store.reading(conn) as c:
        return _sum(c, postings, f.receivable_account)


def set_facility(store: LedgerStore, facility_id: str, conn: Connection | None = None,
                 **values: Any) -> None:
    with store.transaction(conn) as c:
        c.execute(update(facilities).where(facilities.c.facility_id == facility_id)
                  .values(**values))

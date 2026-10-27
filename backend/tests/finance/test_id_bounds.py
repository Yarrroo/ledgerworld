"""Every id the ledger generates fits its column, at the longest source ids the columns hold.

SQLite ignores VARCHAR widths and PostgreSQL does not, so an id derived from a valid source id
(`settle:out:<obligation>`, `<pool>/loan:<contract>`, ...) that outgrows its column passes the
offline gate and fails on PostgreSQL. The ledger bounds each generated id to its column: one
that fits is kept as written, one that does not keeps its head and a hash of the whole, so it
is still one id per source and never collides with another. The offline tests scan every
column after the loading and settlement paths; the `pg` test runs the same paths on PostgreSQL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from app.finance import contracts
from app.finance.ledger import from_snapshot, pay, settle_due
from app.finance.lending import disburse, draw_line, observe_revenue, repay
from app.finance.models import (
    accounts,
    bounded_id,
    entities,
    expected_flows,
    facilities,
    journals,
    metadata,
    obligations,
    reservations,
    revenue_observations,
)
from app.finance.store import LedgerStore
from sqlalchemy import String, create_engine

T0 = datetime(2026, 1, 5, tzinfo=UTC)
WEEK = timedelta(days=7)


def wide(name: str, column) -> str:
    """`name` padded to exactly the width of the column a source id of its kind lands in."""
    return name + "-" + "x" * (column.type.length - len(name) - 1)


POOL = wide("pool", entities.c.entity_id)
BORROWER = wide("borrower", entities.c.entity_id)
OUTSIDE = wide("outside", entities.c.entity_id)
OPERATING = wide("pool/operating", accounts.c.account_id)
BORROWER_OPERATING = f"{BORROWER}/operating"
LINE = wide("line", facilities.c.facility_id)
ADVANCE = wide("advance", facilities.c.facility_id)
LINE_HOLD = wide("res-line", reservations.c.reservation_id)
OB_HELD = wide("ob-held", obligations.c.obligation_id)
OB_HOLD = wide("res-ob", reservations.c.reservation_id)
OB_FREE = wide("ob-free", obligations.c.obligation_id)
PENDING_OUT = wide("flow-out", expected_flows.c.flow_id)
PENDING_OUT_HOLD = wide("res-out", reservations.c.reservation_id)
PENDING_IN = wide("flow-in", expected_flows.c.flow_id)


def usd(minor: int) -> dict:
    return {"minor": minor, "currency": "USD"}


def snapshot() -> dict:
    """A pool at the widest ids: holds, a pledge, flows both ways, obligations, two contracts."""
    return {
        "snapshot_id": "wide", "as_of": T0.isoformat(),
        "entities": [{"entity_id": POOL, "name": "Pool (synthetic)", "kind": "lender pool"},
                     {"entity_id": BORROWER, "name": "Borrower (synthetic)", "kind": "borrower"},
                     {"entity_id": OUTSIDE, "name": "Outside (synthetic)", "kind": "external"}],
        "accounts": [{
            "id": OPERATING, "entity": POOL, "currency": "USD", "observability": "known",
            "as_of": T0.isoformat(),
            "buckets": {
                "settled": usd(10_000_000), "reserved": usd(1_000_000 + 200_000 + 50_000 + 7),
                "pledged": usd(30_000),
                "pending_in": [{"flow_id": PENDING_IN, "amount": usd(40_000),
                                "expected_at": (T0 + timedelta(hours=1)).isoformat(),
                                "kind": "receivable"}],
                "pending_out": [{"flow_id": PENDING_OUT, "amount": usd(50_000),
                                 "expected_at": (T0 + timedelta(hours=1)).isoformat(),
                                 "kind": "payable", "reservation_id": PENDING_OUT_HOLD}]}}],
        "obligations": [
            {"obligation_id": OB_HELD, "entity": POOL, "account": OPERATING,
             "amount": usd(200_000), "due_at": (T0 + timedelta(hours=2)).isoformat(),
             "kind": "payroll", "reservation_id": OB_HOLD},
            {"obligation_id": OB_FREE, "entity": POOL, "account": OPERATING,
             "amount": usd(60_000), "due_at": (T0 + timedelta(hours=2)).isoformat(),
             "kind": "tax"}],
        "contracts": [
            {"contract_id": LINE, "kind": "committed_line", "lender": POOL, "borrower": BORROWER,
             "limit": usd(1_500_000), "drawn": usd(500_000), "state": "active",
             "reservation_id": LINE_HOLD, "reserved_on": OPERATING},
            {"contract_id": ADVANCE, "kind": "revenue_advance", "lender": POOL,
             "borrower": BORROWER, "principal": usd(1_000_000), "fee_bps": 800,
             "repay_share_bps": 1500, "state": "offered"}],
        "exposures": [],
        "pools": [{"entity": POOL, "floor": usd(100_000)}],
    }


def run_paths(url: str) -> LedgerStore:
    """Load the wide snapshot, then settle, pay, draw, disburse and repay on it."""
    store = LedgerStore(url)
    from_snapshot(store, snapshot())
    store.open_account(BORROWER_OPERATING, BORROWER, "USD", as_of=T0)
    store.open_account(f"{OUTSIDE}/usd", OUTSIDE, "USD", kind="external", as_of=T0)
    later = T0 + timedelta(hours=3)
    store.observe(OPERATING, "known", later)
    assert len(settle_due(store, later)) == 4  # the arrival, the outflow, two obligations
    pay(store, OPERATING, 1_000, to_account=f"{OUTSIDE}/usd", now=later,
        journal_id=wide("pay", journals.c.journal_id))
    draw_line(store, LINE, 100_000, now=later)
    disburse(store, ADVANCE, now=later, from_account=OPERATING)
    end = T0 + WEEK
    store.observe(BORROWER_OPERATING, "known", end)
    observe_revenue(store, ADVANCE, end, 2_400_000, observed_at=end,
                    source=wide("sales", revenue_observations.c.source))
    assert repay(store, ADVANCE, end, now=end, to_account=OPERATING).journal is not None
    hold = store.hold(OPERATING, 10, now=end, reservation_id=wide("res", reservations.c.
                                                                    reservation_id))
    store.commit(hold, due_at=end + timedelta(hours=1))  # its default flow id
    return store


def too_long(store: LedgerStore) -> list[tuple[str, str, int, str]]:
    """Every value longer than its column allows, as (table, column, width, value)."""
    found = []
    for name, table in metadata.tables.items():
        widths = {c.name: c.type.length for c in table.columns
                  if isinstance(c.type, String) and c.type.length}
        for row in store.rows(name):
            found += [(name, col, width, row[col]) for col, width in widths.items()
                      if row[col] is not None and len(row[col]) > width]
    return found


def test_every_generated_id_fits_its_column_at_the_widest_source_ids():
    store = run_paths("sqlite://")
    assert too_long(store) == []
    assert len(store.rows("journals")) >= 10  # every path above posted


def test_settlement_ids_at_the_widest_obligation_stay_one_per_obligation():
    store = run_paths("sqlite://")
    settled = {r["journal_id"] for r in store.rows("journals") if r["kind"] == "settle_payroll"}
    assert settled == {bounded_id(journals.c.journal_id, f"settle:{OB_HELD}")}
    assert settle_due(store, T0 + timedelta(hours=4)) == []  # paid once, not again


def test_a_bounded_id_is_kept_when_it_fits_and_hashed_when_it_does_not():
    column = journals.c.journal_id
    width = column.type.length
    assert bounded_id(column, "settle:short") == "settle:short"
    exact = "j" * width
    assert bounded_id(column, exact) == exact
    a, b = "settle:" + "o" * width + "a", "settle:" + "o" * width + "b"
    assert len(bounded_id(column, a)) == width
    assert bounded_id(column, a) == bounded_id(column, a)  # the same source, the same id
    assert bounded_id(column, a) != bounded_id(column, b)  # sources differing only at the end
    assert bounded_id(column, a).startswith("settle:o")  # still readable
    assert len(bounded_id(column, a, room=12)) == width - 12


def test_a_line_drawn_at_the_widest_contract_id_keeps_its_rest_held():
    store = run_paths("sqlite://")
    f = contracts.facility(store, LINE)
    assert f.reservation_id is not None and len(f.reservation_id) \
        <= reservations.c.reservation_id.type.length
    assert store.reservation(f.reservation_id).state == "held"


@pytest.mark.pg
def test_every_generated_id_fits_on_postgres():
    url = os.environ.get("LEDGER_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("LEDGER_DATABASE_URL names no PostgreSQL database")
    engine = create_engine(url)
    metadata.drop_all(engine)
    engine.dispose()
    assert too_long(run_paths(url)) == []

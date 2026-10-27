"""Clearing and posting agree on arrivals due now (system brief §7.2, steps 7–8).

S(now) counts a pending arrival expected by `now`, so `check_outflow` clears a payment that
arrival funds. Posting that payment must not then refuse it against settled cash the arrival
has not yet reached: the payment lands the account's due arrivals first, in the same
transaction, and a refusal still leaves the store as it was. An arrival expected later funds
nothing now.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.finance import contracts
from app.finance.ledger import check_outflow, from_snapshot, pay, settle_due
from app.finance.lending import capacity, disburse, observe_revenue, repay
from app.finance.models import Journal, LedgerRefusal, Posting
from app.finance.schemas import RevenueAdvance
from app.finance.store import LedgerStore

ROOT = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 1, 5, tzinfo=UTC)
ACCOUNT = "a/operating"
PAYEE = "x/external"


def world(settled: int = 10000) -> LedgerStore:
    store = LedgerStore("sqlite://")
    store.add_entity("a", "Entity A (synthetic)", "treasury")
    store.add_entity("x", "Outside (synthetic)", "external")
    store.open_account(ACCOUNT, "a", "USD", as_of=T0)
    store.open_account(PAYEE, "x", "USD", kind="external", as_of=T0)
    store.apply(Journal("open", (Posting(ACCOUNT, settled), Posting(PAYEE, -settled)),
                        kind="opening", sim_time=T0))
    return store


def test_a_payment_funded_by_an_arrival_due_now_clears_and_posts():
    store = world()
    flow = store.expect(ACCOUNT, "in", 50000, T0, kind="receivable")
    assert check_outflow(store.view(ACCOUNT), 40000, T0) is None
    pay(store, ACCOUNT, 40000, to_account=PAYEE, now=T0, journal_id="pay-1", round=3)
    view = store.view(ACCOUNT)
    assert view.settled_minor == 10000 + 50000 - 40000
    assert view.pending_in == ()
    landed = [j for j in store.rows("journals") if j["journal_id"] == f"settle:{flow}"]
    assert len(landed) == 1 and landed[0]["round"] == 3
    assert settle_due(store, T0) == []  # the arrival landed once, not again at step 8


def test_an_arrival_due_earlier_funds_a_payment_now():
    store = world()
    store.expect(ACCOUNT, "in", 50000, T0 - timedelta(hours=1), kind="receivable")
    pay(store, ACCOUNT, 60000, to_account=PAYEE, now=T0, journal_id="pay-1")
    assert store.view(ACCOUNT).settled_minor == 0


def test_a_future_arrival_funds_nothing_now():
    store = world()
    store.expect(ACCOUNT, "in", 50000, T0 + timedelta(hours=1), kind="receivable")
    refusal = check_outflow(store.view(ACCOUNT), 40000, T0)
    assert refusal is not None and refusal.code == "insufficient_spendable"
    before = store.dump()
    with pytest.raises(LedgerRefusal) as refused:
        pay(store, ACCOUNT, 40000, to_account=PAYEE, now=T0, journal_id="pay-1")
    assert refused.value.code == "insufficient_spendable"
    assert store.dump() == before


def test_a_refused_payment_lands_no_arrival():
    store = world()
    store.expect(ACCOUNT, "in", 50000, T0, kind="receivable")
    before = store.dump()
    with pytest.raises(LedgerRefusal) as refused:
        pay(store, ACCOUNT, 70000, to_account=PAYEE, now=T0, journal_id="pay-1")
    assert refused.value.code == "insufficient_spendable"
    assert store.dump() == before  # the arrival is left for step 8, still pending


def lender_world() -> LedgerStore:
    """LF-2 from its snapshot, an offered 30k advance to borrower-a, and a second pool account."""
    store = LedgerStore("sqlite://")
    lf2 = json.loads((ROOT / "fixtures/lf2_lender.json").read_text(encoding="utf-8"))
    from_snapshot(store, lf2["snapshot"])
    store.open_account("borrower-a/operating", "borrower-a", "USD", as_of=T0)
    store.open_account("lender/collections", "lender", "USD", as_of=T0)
    contracts.register(store, RevenueAdvance(
        contract_id="adv-30k", kind="revenue_advance", lender="lender", borrower="borrower-a",
        state="offered", principal={"minor": 3000000, "currency": "USD"}, fee_bps=800,
        repay_share_bps=1500), as_of=T0)
    return store


def test_an_advance_funded_by_an_arrival_due_now_disburses():
    """K_p sums the pool's cash; the source account's S counts its arrival due now."""
    store = lender_world()
    store.expect("lender/collections", "in", 3000000, T0, kind="receivable")
    assert capacity(store, "lender", T0).K_p >= 3000000
    disburse(store, "adv-30k", now=T0, from_account="lender/collections")
    assert store.view("lender/collections").settled_minor == 0
    assert store.view("borrower-a/operating").settled_minor == 3000000


def test_a_repayment_funded_by_an_arrival_due_now_posts():
    store = lender_world()
    disburse(store, "adv-30k", now=T0)
    pay(store, "borrower-a/operating", 3000000, to_account=store.external_account("USD"), now=T0,
        journal_id="spent")
    end = T0 + timedelta(days=7)
    store.observe("borrower-a/operating", "known", end)
    store.expect("borrower-a/operating", "in", 150000, end, kind="receivable")
    observe_revenue(store, "adv-30k", end, 1000000, observed_at=end, source="sales ledger")
    paid = repay(store, "adv-30k", end, now=end)
    assert paid.amount_minor == 150000
    assert store.view("borrower-a/operating").settled_minor == 0


def test_step_8_skips_an_arrival_an_outflow_landed_after_it_was_read(monkeypatch):
    """A concurrent writer (PostgreSQL) lands an arrival between step 8's read and its write."""
    store = world()
    flow = store.expect(ACCOUNT, "in", 50000, T0, kind="receivable")
    read = store.due_flows("in", T0)
    pay(store, ACCOUNT, 40000, to_account=PAYEE, now=T0, journal_id="pay-1")
    real = store.due_flows
    monkeypatch.setattr(store, "due_flows",
                        lambda direction, now, **kw: read if direction == "in"
                        else real(direction, now, **kw))
    assert settle_due(store, T0) == []  # skipped, not raised: step 8 still runs whole
    assert [j["journal_id"] for j in store.rows("journals")].count(f"settle:{flow}") == 1
    assert store.view(ACCOUNT).settled_minor == 20000

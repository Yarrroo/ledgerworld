"""Lender capacity K_p and the revenue-based advance (T05).

LF-2 is loaded from `fixtures/lf2_lender.json` through `ledger.from_snapshot` and every number
of its `expected` block comes out of `lending`, asserted with the parts K_p is computed from
(never only the total). The disbursal and week-1 repayment journals are asserted posting by
posting against the design fixture `advance-journals.json`, unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from functools import cache
from pathlib import Path

import pytest
from app.finance import contracts
from app.finance.contracts import fee_minor, repayment_minor
from app.finance.ledger import from_snapshot
from app.finance.lending import (
    CapacityParts,
    capacity,
    check_draw,
    disburse,
    draw_line,
    observe_revenue,
    repay,
)
from app.finance.models import Journal, LedgerRefusal, Posting
from app.finance.schemas import RevenueAdvance
from app.finance.store import LedgerStore

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "prp/2026-10-20-ledgerworld/design/modules/ledger/fixtures"
T0 = datetime(2026, 1, 5, tzinfo=UTC)
POOL = "lender"
WEEK = timedelta(days=7)


@cache
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def lf2() -> dict:
    return json.loads(_read(ROOT / "fixtures/lf2_lender.json"))


def design(name: str) -> dict:
    return json.loads(_read(DESIGN / f"{name}.json"))


def h(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def world(snapshot: dict | None = None, borrower_cash: int = 0,
          url: str = "sqlite://") -> LedgerStore:
    """LF-2 loaded from its snapshot, plus the borrowers' operating accounts it lends to."""
    store = LedgerStore(url)
    from_snapshot(store, snapshot or lf2()["snapshot"])
    for borrower in ("borrower-a", "borrower-b"):
        account = f"{borrower}/operating"
        store.open_account(account, borrower, "USD", as_of=T0)
        if borrower_cash:
            store.open_account(f"{account}:opening", borrower, "USD", kind="external", as_of=T0)
            store.apply(Journal(f"open:{account}", (Posting(account, borrower_cash),
                                                    Posting(f"{account}:opening",
                                                            -borrower_cash))))
    return store


def frozen() -> LedgerStore:
    return world(lf2()["stressed"]["venue_freeze"])


def advance(contract_id: str, principal: int) -> RevenueAdvance:
    return RevenueAdvance(contract_id=contract_id, kind="revenue_advance", lender=POOL,
                          borrower="borrower-a", state="offered",
                          principal={"minor": principal, "currency": "USD"}, fee_bps=800,
                          repay_share_bps=1500)


def postings_of(store: LedgerStore, journal_id: str) -> list[tuple[str, int]]:
    return sorted((r["account_id"], r["amount_minor"]) for r in store.rows("postings")
                  if r["journal_id"] == journal_id)


def balance(store: LedgerStore, account_id: str) -> int:
    return sum(r["amount_minor"] for r in store.rows("postings") if r["account_id"] == account_id)


def test_the_repo_fixture_carries_the_design_expectations_unchanged():
    assert lf2()["expected"] == design("lf2-lender")["expected"]


# ----------------------------------------------------------------------------------- K_p

def test_lf2_capacity_before_stress():
    want = lf2()["expected"]["K_p_before"]
    cap = capacity(world(), POOL, T0)
    assert cap.parts == CapacityParts(settled_known=6000000, committed_undrawn=1000000,
                                      pledged=0, obligations_due=0, floor=800000)
    assert (cap.K_p, cap.authority) == (want["value"], "full")
    assert cap.binding == "K_p = 42,000.00"


@pytest.mark.parametrize("stress", ["snapshot", "observed"])
def test_lf2_capacity_under_venue_freeze(stress):
    """The venue's 15,000 becomes unknown, not zero: loaded that way or observed later."""
    want = lf2()["expected"]["stress_venue_freeze"]
    if stress == "snapshot":
        store = frozen()
    else:
        store = world()
        store.observe("lender/venue", "unknown", T0)
    cap = capacity(store, POOL, T0)
    assert store.view("lender/venue").observability == want["lender/venue"]
    assert cap.parts == CapacityParts(settled_known=4500000, committed_undrawn=1000000,
                                      pledged=0, obligations_due=0, floor=800000)
    assert (cap.K_p, cap.authority) == (want["K_p"], want["authority"])
    assert cap.binding == "K_p = 27,000.00"


def test_a_stale_pool_balance_adds_nothing_and_reduces_authority():
    store = world()
    cap = capacity(store, POOL, h(6))  # exactly 6 h old is still fresh
    assert (cap.K_p, cap.authority) == (4200000, "full")
    cap = capacity(store, POOL, h(6) + timedelta(seconds=1))
    assert (cap.parts.settled_known, cap.authority) == (0, "reduced")


def test_a_redemption_spike_lowers_capacity_by_its_increase():
    store = world()
    store.add_obligation("redeem-1", "lender/operating", 500000, h(24), kind="redemption")
    store.add_obligation("redeem-late", "lender/operating", 900000, h(100), kind="redemption")
    before = capacity(store, POOL, T0)
    assert before.parts.obligations_due == 500000  # the one due after the horizon is not
    assert before.K_p == 4200000 - 500000
    store.add_obligation("redeem-spike", "lender/operating", 300000, h(30), kind="redemption")
    assert capacity(store, POOL, T0).K_p == before.K_p - 300000


def test_a_committed_outflow_of_the_pool_counts_as_an_obligation_due():
    store = world()
    res = store.hold("lender/operating", 200000, now=T0, purpose="redemption")
    store.commit(res, due_at=h(200))  # spoken for from commit, whatever its due
    cap = capacity(store, POOL, T0)
    assert (cap.parts.obligations_due, cap.K_p) == (200000, 4000000)


# -------------------------------------------------------------------- draws against K_p

def test_lf2_draw_beyond_capacity_is_rejected_with_the_binding_constraint():
    want = lf2()["expected"]["draw_30k_under_stress"]
    store = frozen()
    contracts.register(store, advance("adv-30k", 3000000), as_of=T0)
    refusal = check_draw(store, POOL, 3000000, T0)
    assert refusal is not None and refusal.code == want["reason"]
    before = store.dump()
    with pytest.raises(LedgerRefusal) as refused:
        disburse(store, "adv-30k", now=T0)
    assert refused.value.code == want["reason"] == "beyond_capacity"
    assert refused.value.detail["binding"] == want["binding"]
    assert refused.value.detail["K_p"] == want["K_p_minor"]
    assert store.dump() == before  # refused whole: nothing moved, the advance still offered
    assert contracts.facility(store, "adv-30k").state == "offered"


def test_lf2_draw_within_capacity_is_accepted():
    want = lf2()["expected"]["draw_30k_no_stress"]
    store = world()
    contracts.register(store, advance("adv-30k", 3000000), as_of=T0)
    assert check_draw(store, POOL, 3000000, T0) is None
    disburse(store, "adv-30k", now=T0)
    assert want["status"] == "accepted"
    assert capacity(store, POOL, T0).K_p == want["K_p_after"]


def test_a_disbursed_advance_is_not_disbursed_again():
    store = world()
    disburse(store, "adv-a", now=T0)
    before = store.dump()
    with pytest.raises(ValueError, match="active revenue_advance"):
        disburse(store, "adv-a", now=T0)
    assert store.dump() == before


def test_an_advance_moves_only_the_pools_own_cash():
    store = world()
    with pytest.raises(ValueError, match="cash account of lender"):
        disburse(store, "adv-a", now=T0, from_account="borrower-b/operating")


# ------------------------------------------------------------------- committed line draw

def test_lf2_committed_line_draw_leaves_capacity_unchanged():
    want = lf2()["expected"]["committed_line_draw"]
    store = world()
    line = contracts.facility(store, "line-b")
    assert line.borrower == want["borrower"]
    draw_line(store, "line-b", want["amount"], now=T0)
    cap = capacity(store, POOL, T0)
    assert cap.K_p == want["K_p_after"]
    assert (cap.parts.settled_known, cap.parts.committed_undrawn) == (5000000, 0)
    assert store.view("lender/operating").reserved_minor == 0
    assert balance(store, "borrower-b/operating") == want["amount"]


def test_a_partial_line_draw_keeps_the_rest_held_and_refuses_beyond_it():
    store = world()
    draw_line(store, "line-b", 400000, now=T0)
    assert store.view("lender/operating").reserved_minor == 600000
    assert capacity(store, POOL, T0).K_p == 4200000
    before = store.dump()
    with pytest.raises(LedgerRefusal) as refused:
        draw_line(store, "line-b", 600001, now=T0)
    assert refused.value.code == "beyond_capacity"
    assert refused.value.detail["binding"] == "undrawn line = 6,000.00"
    assert store.dump() == before
    draw_line(store, "line-b", 600000, now=T0)
    assert capacity(store, POOL, T0).parts.committed_undrawn == 0


# --------------------------------------------------------------- the advance, end to end

def test_lf2_advance_disbursal_journal():
    want = lf2()["expected"]["advance"]["disburse"]
    journals = design("advance-journals")
    store = world()
    adv = contracts.facility(store, "adv-a")
    assert (adv.limit_minor, adv.fee_minor, adv.owed_minor) == (
        want["principal"], want["fee"], want["owed"])
    journal = disburse(store, "adv-a", now=T0)
    fixture = journals["journals"][0]
    assert journal.kind == fixture["kind"]
    assert postings_of(store, journal.journal_id) == sorted(
        (p["account"], p["amount"]) for p in fixture["postings"])
    assert contracts.outstanding_minor(store, adv) == want["owed"]
    assert contracts.facility(store, "adv-a").state == "active"
    assert capacity(store, POOL, T0).K_p == want["K_p_after"]


def test_lf2_week_1_repayment_journal():
    journals = design("advance-journals")
    want = lf2()["expected"]["advance"]["week_1"]
    store = world()
    disburse(store, "adv-a", now=T0)
    end = T0 + WEEK
    store.observe("borrower-a/operating", "known", end)
    observe_revenue(store, "adv-a", end, want["observed_revenue"], observed_at=end,
                    source="sales ledger")
    paid = repay(store, "adv-a", end, now=end)
    fixture = journals["journals"][1]
    assert paid.journal is not None and paid.journal.kind == fixture["kind"]
    assert postings_of(store, paid.journal.journal_id) == sorted(
        (p["account"], p["amount"]) for p in fixture["postings"])
    assert (paid.amount_minor, paid.outstanding_minor) == (want["repayment"],
                                                           want["outstanding"])
    expect = journals["expect"]
    assert paid.outstanding_minor == expect["outstanding"]
    for account in ("lender/loan:adv-a", "borrower-a/advance-payable:adv-a"):
        assert balance(store, account) == expect["balances_after"][account]
    assert balance(store, "lender/operating") - 4500000 \
        == expect["balances_after"]["lender/operating_change"]
    assert balance(store, "borrower-a/operating") \
        == expect["balances_after"]["borrower-a/operating_change"]
    for journal_id in {r["journal_id"] for r in store.rows("postings")}:
        assert sum(a for _, a in postings_of(store, journal_id)) == 0


def test_lf2_repayment_weeks_1_to_4():
    """Observed revenue only, rounded down, capped at outstanding; the advance ends repaid."""
    want = lf2()["expected"]["advance"]
    store = world(borrower_cash=10000000)
    disburse(store, "adv-a", now=T0)
    for n, week in enumerate(("week_1", "week_2_forecast_only", "week_3", "week_4"), start=1):
        case, end = want[week], T0 + n * WEEK
        store.observe("borrower-a/operating", "known", end)
        if case["observed_revenue"] is not None:
            observe_revenue(store, "adv-a", end, case["observed_revenue"], observed_at=end,
                            source="sales ledger")
        else:  # only a forecast exists; recording it as revenue is refused
            with pytest.raises(ValueError, match="forecast"):
                observe_revenue(store, "adv-a", end, case["forecast_revenue"],
                                observed_at=end - timedelta(days=3), source="forecast")
        paid = repay(store, "adv-a", end, now=end)
        assert paid.observed_revenue_minor == case["observed_revenue"]
        assert (paid.amount_minor, paid.outstanding_minor) == (case["repayment"],
                                                               case["outstanding"]), week
        assert (paid.journal is None) == (case["repayment"] == 0)
    assert contracts.facility(store, "adv-a").state == "repaid"


def test_revenue_observed_later_is_not_read_before_it_is_observed():
    store = world(borrower_cash=1000000)
    disburse(store, "adv-a", now=T0)
    end = T0 + WEEK
    store.observe("borrower-a/operating", "known", end)
    observe_revenue(store, "adv-a", end, 2400000, observed_at=end + timedelta(days=1),
                    source="sales ledger")
    assert repay(store, "adv-a", end, now=end).amount_minor == 0
    late = end + timedelta(days=1)
    store.observe("borrower-a/operating", "known", late)
    assert repay(store, "adv-a", end, now=late).amount_minor == 360000


def test_a_period_is_repaid_at_most_once():
    store = world(borrower_cash=1000000)
    disburse(store, "adv-a", now=T0)
    end = T0 + WEEK
    store.observe("borrower-a/operating", "known", end)
    observe_revenue(store, "adv-a", end, 2400000, observed_at=end, source="sales ledger")
    repay(store, "adv-a", end, now=end)
    before = store.dump()
    with pytest.raises(ValueError, match="already repaid"):
        repay(store, "adv-a", end, now=end)
    with pytest.raises(ValueError, match="already observed"):
        observe_revenue(store, "adv-a", end, 9999999, observed_at=end, source="sales ledger")
    assert store.dump() == before


def test_a_repayment_from_a_stale_borrower_balance_is_refused():
    store = world()
    disburse(store, "adv-a", now=T0)
    end = T0 + WEEK
    observe_revenue(store, "adv-a", end, 2400000, observed_at=end, source="sales ledger")
    before = store.dump()
    with pytest.raises(LedgerRefusal) as refused:
        repay(store, "adv-a", end, now=end)
    assert refused.value.code == "stale_balance"
    assert store.dump() == before


# --------------------------------------------------------------------------- the terms

def test_contract_terms_are_integer_and_round_down():
    assert fee_minor(1000000, 800) == 80000
    assert fee_minor(333, 800) == 26  # 26.64 rounded down
    assert repayment_minor(2400000, 1500, 1080000) == 360000
    assert repayment_minor(333333, 1500, 720000) == 49999
    assert repayment_minor(10000000, 1500, 670001) == 670001
    assert repayment_minor(None, 1500, 720000) == 0
    assert repayment_minor(0, 1500, 720000) == 0
    with pytest.raises(LedgerRefusal):
        repayment_minor(2400000.0, 1500, 720000)
    with pytest.raises(ValueError):
        repayment_minor(2400000, 0, 720000)
    with pytest.raises(ValueError):
        fee_minor(1000000, 10001)


def test_a_contract_whose_lender_is_not_a_pool_is_refused():
    snap = lf2()["snapshot"]
    snap["pools"] = []
    store = LedgerStore("sqlite://")
    with pytest.raises(ValueError, match="not a lending pool"):
        from_snapshot(store, snap)
    assert store.rows("accounts") == []  # the snapshot loads whole or not at all


def test_a_line_draw_from_a_stale_pool_balance_is_refused():
    store = world()
    before = store.dump()
    with pytest.raises(LedgerRefusal) as refused:
        draw_line(store, "line-b", 100000, now=h(7))
    assert refused.value.code == "stale_balance"
    assert store.dump() == before


def test_a_period_written_in_another_zone_is_still_repaid_once():
    store = world(borrower_cash=1000000)
    disburse(store, "adv-a", now=T0)
    end = T0 + WEEK
    store.observe("borrower-a/operating", "known", end)
    observe_revenue(store, "adv-a", end, 2400000, observed_at=end, source="sales ledger")
    repay(store, "adv-a", end, now=end)
    before = store.dump()
    same = end.astimezone(timezone(timedelta(hours=2)))
    with pytest.raises(ValueError, match="already repaid"):
        repay(store, "adv-a", same, now=end)
    assert store.dump() == before


def test_a_caller_cannot_name_the_repayment_journal():
    """The once-per-period guard is the journal id; a caller-chosen id would bypass it."""
    store = world(borrower_cash=1000000)
    disburse(store, "adv-a", now=T0)
    end = T0 + WEEK
    store.observe("borrower-a/operating", "known", end)
    observe_revenue(store, "adv-a", end, 2400000, observed_at=end, source="sales ledger")
    with pytest.raises(TypeError):
        repay(store, "adv-a", end, now=end, journal_id="leg-1")
    with pytest.raises(TypeError):
        repay(store, "adv-a", end, now=end, journal_id="leg-2")
    assert balance(store, "lender/loan:adv-a") == 1080000


def test_a_line_named_with_a_reservation_but_no_hold_draws_from_free_cash():
    snap = lf2()["snapshot"]
    line = next(c for c in snap["contracts"] if c["contract_id"] == "line-b")
    del line["reserved_on"]  # no hold is created for it
    snap["accounts"][0]["buckets"]["reserved"]["minor"] = 0
    store = world(snap)
    draw_line(store, "line-b", 100000, now=T0)
    assert balance(store, "borrower-b/operating") == 100000
    assert capacity(store, POOL, T0).parts.committed_undrawn == 900000


def test_an_active_advance_in_a_snapshot_is_refused_not_read_as_repaid():
    snap = lf2()["snapshot"]
    next(c for c in snap["contracts"] if c["contract_id"] == "adv-a")["state"] = "active"
    with pytest.raises(ValueError, match="needs its outstanding"):
        from_snapshot(LedgerStore("sqlite://"), snap)


def test_a_contract_id_as_wide_as_its_column_loads_and_disburses():
    """Its generated ids are bounded to their columns (`models.bounded_id`), not refused."""
    snap = lf2()["snapshot"]
    wide = "a" * 64
    next(c for c in snap["contracts"] if c["contract_id"] == "adv-a")["contract_id"] = wide
    store = world(snap)
    journal = disburse(store, wide, now=T0)
    assert len(journal.journal_id) <= 64 and contracts.facility(store, wide).state == "active"


def unheld_line(operating_minor: int = 4500000) -> dict:
    """LF-2 with line-b naming a reservation but no account to hold it on."""
    snap = lf2()["snapshot"]
    line = next(c for c in snap["contracts"] if c["contract_id"] == "line-b")
    del line["reserved_on"]
    operating = snap["accounts"][0]["buckets"]
    operating["reserved"]["minor"], operating["settled"]["minor"] = 0, operating_minor
    return snap


def test_a_line_draw_beyond_the_pools_free_cash_is_refused_as_insufficient():
    store = world(unheld_line(operating_minor=500000))
    before = store.dump()
    with pytest.raises(LedgerRefusal) as refused:
        draw_line(store, "line-b", 600000, now=T0)
    assert refused.value.code == "insufficient_spendable"
    assert store.dump() == before


def test_a_line_draw_with_no_live_hold_clears_the_facilitys_reservation():
    store = world(unheld_line())
    assert contracts.facility(store, "line-b").reservation_id == "res-line-b"
    draw_line(store, "line-b", 100000, now=T0)
    assert contracts.facility(store, "line-b").reservation_id is None


def test_a_stale_refusal_carries_the_balances_as_of():
    store = world()
    with pytest.raises(LedgerRefusal) as refused:
        draw_line(store, "line-b", 100000, now=h(7))
    assert refused.value.detail["as_of"] == T0.isoformat()


@pytest.mark.parametrize("state", ["repaid", "closed"])
def test_a_finished_advance_in_a_snapshot_loads_with_nothing_outstanding(state):
    snap = lf2()["snapshot"]
    next(c for c in snap["contracts"] if c["contract_id"] == "adv-a")["state"] = state
    store = world(snap)
    adv = contracts.facility(store, "adv-a")
    assert (adv.state, contracts.outstanding_minor(store, adv)) == (state, 0)
    assert capacity(store, POOL, T0).K_p == 4200000


def test_two_periods_within_one_second_are_each_repaid():
    store = world(borrower_cash=1000000)
    disburse(store, "adv-a", now=T0)
    first = T0 + WEEK + timedelta(microseconds=250000)
    second = first + timedelta(microseconds=500000)
    store.observe("borrower-a/operating", "known", second)
    for end in (first, second):
        observe_revenue(store, "adv-a", end, 100000, observed_at=second, source="sales ledger")
        assert repay(store, "adv-a", end, now=second).amount_minor == 15000


def test_a_line_id_is_not_measured_against_ids_only_an_advance_generates():
    snap = lf2()["snapshot"]
    next(c for c in snap["contracts"] if c["contract_id"] == "line-b")["contract_id"] = "b" * 45
    store = world(snap)
    assert contracts.facility(store, "b" * 45).kind == "committed_line"


def test_a_facility_lock_needs_the_callers_transaction():
    with pytest.raises(ValueError, match="pass conn"):
        contracts.facility(world(), "adv-a", lock=True)

"""Realised feasibility counts only cash that was usable: an unknown balance adds nothing (T11).

The ledger keeps an account's postings whatever its observability, so a frozen venue's balance
is still in ``settled``; the floor and an unmet obligation's shortfall must not lean on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.decisions.feasibility import assess
from app.finance.models import Journal, Posting
from app.finance.store import LedgerStore

T0 = datetime(2026, 1, 5, tzinfo=UTC)
ACCOUNT = "a/operating"


def world(*, obligation_minor: int | None = None) -> SimpleNamespace:
    """1,000,000 settled from round 0 on a floor of 500,000; optionally one unpaid obligation
    due at t = 12 h (round 3)."""
    store = LedgerStore("sqlite://")
    store.add_entity("a", "Entity A (synthetic)", "treasury")
    store.open_account(ACCOUNT, "a", "USD", as_of=T0, floor_minor=500_000)
    store.open_account("a/opening", "a", "USD", kind="external", as_of=T0)
    store.apply(Journal("open", (Posting(ACCOUNT, 1_000_000), Posting("a/opening", -1_000_000)),
                        sim_time=T0))
    if obligation_minor is not None:
        store.add_obligation("ob-1", ACCOUNT, obligation_minor, T0 + timedelta(hours=12),
                             kind="payroll")
    return SimpleNamespace(store=store, clock=SimpleNamespace(epoch=T0))


def seen(unknown: set[int], rounds: range = range(1, 6)) -> dict[int, str]:
    return {r: "unknown" if r in unknown else "known" for r in rounds}


@pytest.mark.parametrize(("unknown", "breach", "unknown_h"), [
    (set(), None, ()),
    ({2, 3, 4, 5}, (8, 20), (8, 12, 16, 20)),  # sustained: below the floor to the horizon
    ({2, 3}, (8, 16), (8, 12)),  # frozen, then recovered at round 4
])
def test_an_unknown_balance_is_not_usable_against_the_floor(unknown, breach, unknown_h):
    f = assess(world(), ACCOUNT, from_round=0, to_round=5, observability=seen(unknown))
    assert f.settled == {h: 1_000_000 for h in (4, 8, 12, 16, 20)}  # the ledger is unchanged
    assert f.unknown_h == unknown_h
    assert f.floor.breach_h == breach
    if breach is None:
        assert (f.floor.min_cash, f.floor.at_h, f.floor.short_minor) == (1_000_000, 4, 0)
        assert f.feasible
    else:
        assert (f.floor.min_cash, f.floor.at_h, f.floor.short_minor) == (0, 8, 500_000)
        assert not f.feasible
    assert f.as_dict()["unknown_h"] == list(unknown_h)


@pytest.mark.parametrize(("unknown", "short"), [
    (set(), 500_000),  # 1,500,000 due against 1,000,000 free
    ({3}, 1_500_000),  # unknown at its due round: nothing was free to pay it
    ({2}, 500_000),  # unknown earlier, known again by the due round
])
def test_an_unmet_obligations_shortfall_counts_no_unknown_cash(unknown, short):
    f = assess(world(obligation_minor=1_500_000), ACCOUNT, from_round=0, to_round=5,
               observability=seen(unknown))
    (ob,) = f.obligations
    assert (ob.id, ob.due_h, ob.met, ob.short_minor) == ("ob-1", 12, False, short)


def test_an_unknown_balance_still_counts_what_it_owes():
    """A debit posted while the balance is unknown (the store checks no promise against it) can
    take it below zero; masking it hides nothing usable, so the debt is still counted."""
    w = world()
    w.store.observe(ACCOUNT, "unknown", T0)
    w.store.apply(Journal("fee", (Posting(ACCOUNT, -1_200_000), Posting("a/opening", 1_200_000)),
                          round=2, sim_time=T0 + timedelta(hours=8)))
    f = assess(w, ACCOUNT, from_round=0, to_round=5, observability=seen({2, 3, 4, 5}))
    assert f.settled[8] == -200_000
    assert (f.floor.min_cash, f.floor.at_h, f.floor.short_minor) == (-200_000, 8, 700_000)
    assert f.floor.breach_h == (8, 20)


@pytest.mark.parametrize(("obligation_minor", "unknown", "binding"), [
    (None, {2, 3, 4, 5},
     "min cash 0.00 at t=8 (balance unknown) < floor 5,000.00; no remedy closed it"),
    (1_500_000, {3},  # the obligation due at t=12 binds before the floor breach there
     "free cash 0.00 at t=12 (balance unknown) < ob-1 15,000.00; no reservation is touched"),
    (1_500_000, set(),
     "free cash 10,000.00 at t=12 < ob-1 15,000.00; no reservation is touched"),
])
def test_the_escalation_says_the_binding_balance_was_unknown(obligation_minor, unknown, binding):
    from app.decisions.objective import Evaluation, rank

    f = assess(world(obligation_minor=obligation_minor), ACCOUNT, from_round=0, to_round=5,
               observability=seen(unknown))
    result = rank([Evaluation("s1", "integrated", "b", f)], escalate_to="treasury operator")
    assert result.escalation["binding"] == binding


@pytest.mark.parametrize(("paid_h", "met"), [(12, True), (20, False)])
def test_a_committed_obligation_is_met_only_when_its_flow_landed_by_its_due_round(paid_h, met):
    """Paid through its committed reservation, an obligation has no journal of its own: the flow's
    settlement journal dates the payment, so one that landed after its due round is unmet even
    though the ledger marks it met."""
    from app.finance.ledger import settle_due

    w = world()
    res = w.store.hold(ACCOUNT, 300_000, now=T0, purpose="payroll")
    w.store.add_obligation("ob-1", ACCOUNT, 300_000, T0 + timedelta(hours=12), kind="payroll",
                           reservation_id=res)
    w.store.commit(res, due_at=T0 + timedelta(hours=paid_h), kind="payroll")
    for h in range(4, 24, 4):
        settle_due(w.store, T0 + timedelta(hours=h), round=h // 4)
    assert w.store.rows("obligations")[0]["state"] == "met"  # the ledger says met either way
    f = assess(w, ACCOUNT, from_round=0, to_round=5, observability=seen(set()))
    (ob,) = f.obligations
    assert (ob.id, ob.due_h, ob.met) == ("ob-1", 12, met)
    assert f.feasible is met
    if not met:  # 1,000,000 settled at t=12, nothing else reserved: the cash was there, late
        assert ob.short_minor == 0


def test_a_committed_payment_under_a_journal_of_its_own_naming_falls_back_to_the_state():
    """A settlement whose journal id the caller named (the execution gateway's ``j-<leg>``) dates
    nothing feasibility can find; the obligation is then judged by the state the ledger left."""
    w = world()
    res = w.store.hold(ACCOUNT, 300_000, now=T0, purpose="payroll")
    w.store.add_obligation("ob-1", ACCOUNT, 300_000, T0 + timedelta(hours=12), kind="payroll",
                           reservation_id=res)
    w.store.commit(res, due_at=T0 + timedelta(hours=8), kind="payroll")
    w.store.settle(res, to_account="a/opening", at=T0 + timedelta(hours=8), journal_id="j-leg-1",
                   round=2)
    f = assess(w, ACCOUNT, from_round=0, to_round=5, observability=seen(set()))
    (ob,) = f.obligations
    assert (ob.id, ob.met) == ("ob-1", True)


def test_a_round_with_no_recorded_observability_is_refused():
    with pytest.raises(ValueError, match=r"rounds \[4, 5\]"):
        assess(world(), ACCOUNT, from_round=0, to_round=5,
               observability=seen(set(), range(1, 4)))


@pytest.mark.parametrize("state", ["stale", "Known", None])
def test_an_observability_that_is_neither_known_nor_unknown_is_refused(state):
    with pytest.raises(ValueError, match="known or unknown"):
        assess(world(), ACCOUNT, from_round=0, to_round=5,
               observability={**seen(set()), 3: state})

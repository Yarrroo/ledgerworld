"""LF-1 reproduced by the ledger engine (T04): the `expected` block of fixtures/lf1_treasury.json.

`tests/fixtures/test_fixture_data.py` re-derives the same numbers with a pencil; this file loads
the snapshot into the store and asks the engine. Both must agree with the fixture to the cent.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

import pytest
from app.finance.ledger import check_outflow, from_snapshot, pay, settle_due
from app.finance.models import LedgerRefusal
from app.finance.spendability import floor_check, headroom, projected_cash, spendability
from app.finance.store import LedgerStore

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "borrower-a/operating"
URL = "sqlite://"


@cache
def lf1() -> dict:
    return json.loads((ROOT / "fixtures/lf1_treasury.json").read_text(encoding="utf-8"))


def t0() -> datetime:
    return datetime.fromisoformat(lf1()["t0"])


def h(hours: float) -> datetime:
    return t0() + timedelta(hours=hours)


def hours(when: datetime) -> int:
    return int((when - t0()) / timedelta(hours=1))


def horizon() -> timedelta:
    return timedelta(hours=lf1()["horizon_h"])


def world(url: str = URL, *, shock: bool = False, plan: bool = False) -> LedgerStore:
    store = LedgerStore(url)
    from_snapshot(store, lf1()["snapshot"])
    if shock:
        rcv = next(f for f in lf1()["snapshot"]["accounts"][0]["buckets"]["pending_in"]
                   if f["flow_id"] == "rcv-1")
        store.reschedule("rcv-1", datetime.fromisoformat(rcv["expected_at"])
                         + timedelta(hours=240))
    if plan:
        for action in lf1()["expected"]["integrated_plan"]["actions"]:
            assert action["arrives_h"] <= action["deadline_h"]
            store.expect(ACCOUNT, "in", action["amount"], h(action["arrives_h"]),
                         kind=action["type"], flow_id="advance-1")
    return store


def assert_paths(store: LedgerStore, expected: dict) -> None:
    view = store.view(ACCOUNT)
    if "S" in expected:
        assert {k: spendability(view, h(int(k)), t0()).value for k in expected["S"]} == \
            expected["S"]
    assert {k: projected_cash(view, h(int(k))) for k in expected["P"]} == expected["P"]
    check = floor_check(view, t0(), horizon())
    assert {"value": check.min_p, "at_h": hours(check.at)} == expected["min_P"]
    assert check.feasible is expected["feasible"]
    if "breach" in expected:
        assert {"at_h": hours(check.at), "short_minor": check.short_minor,
                "binding": check.binding} == expected["breach"]
    if "headroom_0" in expected:
        assert headroom(view, t0(), horizon()).value == expected["headroom_0"]


def test_lf1_no_shock():
    assert_paths(world(), lf1()["expected"]["no_shock"])


def test_lf1_shock_receipt_delayed_240h():
    assert_paths(world(shock=True), lf1()["expected"]["shock_receipt_delayed_240h"])


def test_lf1_integrated_plan():
    assert_paths(world(shock=True, plan=True), lf1()["expected"]["integrated_plan"])


REJECTIONS = {r["id"]: r for r in lf1()["expected"]["rejections"]}


def payee(store: LedgerStore) -> str:
    return store.external_account("USD")


@pytest.mark.parametrize("rid", ["pay-80k", "pay-20k-breaks-floor", "pay-10k-keeps-floor"])
def test_lf1_payment_at_t0(rid):
    case = REJECTIONS[rid]
    intent = case["intent"]
    store = world()
    to = payee(store)
    now = h(intent["at_h"])
    refusal = check_outflow(store.view(ACCOUNT), intent["amount"], now, horizon())
    before = store.dump()
    if case["status"] == "rejected":
        assert refusal is not None and refusal.code == case["reason"]
        if "S_0" in case:
            assert refusal.detail["S_now"] == case["S_0"]
        with pytest.raises(LedgerRefusal):
            pay(store, ACCOUNT, intent["amount"], to_account=to, now=now,
                journal_id=rid)
        assert store.dump() == before
    else:
        assert refusal is None
        pay(store, ACCOUNT, intent["amount"], to_account=to, now=now,
            journal_id=rid)
        view = store.view(ACCOUNT)
        check = floor_check(view, now, horizon())
        assert check.feasible and check.min_p == view.floor_minor  # P(40) = 30,000 = floor


def test_lf1_double_pledge():
    case = REJECTIONS["double-pledge"]
    store = world()
    got = []
    for intent in case["intents"]:
        try:
            store.pledge(ACCOUNT, intent["amount"], intent["collateral_ref"])
            got.append("accepted")
        except LedgerRefusal as refusal:
            got.append("rejected")
            assert refusal.code == case["reason"]
    assert got == case["status"]


def test_lf1_inaction_keeps_the_obligation():
    """No actor acts; each hour runs the mandatory settlements. Payroll settles at t=40."""
    store = world()
    for hour in range(lf1()["horizon_h"] + 1):
        settle_due(store, h(hour))
        state = {o["obligation_id"]: o["state"] for o in store.rows("obligations")}
        assert state == {"payroll-1": "open" if hour < 40 else "met"}, hour
        if hour in (40, 48):  # what landed equals what P promised
            expected_p = lf1()["expected"]["no_shock"]["P"][str(hour)]
            assert store.view(ACCOUNT).settled_minor == expected_p
    assert store.reservation("res-payroll-1").state == "settled"


def test_every_lf1_rejection_is_reproduced():
    assert set(REJECTIONS) == {"pay-80k", "pay-20k-breaks-floor", "pay-10k-keeps-floor",
                               "double-pledge", "inaction-keeps-obligation"}

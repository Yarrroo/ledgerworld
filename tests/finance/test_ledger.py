"""The ledger's invariants and reservation lifecycle (T04).

Every case of the design fixtures `invariants.json` and `reservation-lifecycle.json` is run
unchanged and its `expect` block asserted; each invariant has a named test that runs its cases.
A refused write must leave the store identical, row for row.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

import pytest
from app.finance.ledger import check_outflow, from_snapshot, pay, settle_due
from app.finance.models import Journal, LedgerRefusal, Posting, metadata, pledges, postings
from app.finance.spendability import projected_cash, spendability
from app.finance.store import LedgerStore
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, insert, inspect
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "prp/2026-10-20-ledgerworld/design/modules/ledger"
T0 = datetime(2026, 1, 5, tzinfo=UTC)
URL = "sqlite://"


@cache
def design(name: str) -> dict:
    return json.loads((DESIGN / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))


def case(case_id: str) -> dict:
    return next(c for c in design("invariants")["cases"] if c["id"] == case_id)


def h(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


# ------------------------------------------------------------------------------------- world

def invariants_world(url: str = URL) -> LedgerStore:
    """The `start` block of invariants.json: owned accounts open with their settled balance."""
    store = LedgerStore(url)
    store.add_entity("a", "Entity A (synthetic)", "treasury")
    store.add_entity("x", "Outside (synthetic)", "external")
    for account_id, spec in design("invariants")["start"]["accounts"].items():
        kind = spec.get("kind", "cash")
        entity = account_id.split("/")[0]
        store.open_account(account_id, entity, spec["currency"], kind=kind, as_of=T0)
        if spec.get("settled"):
            opening = f"{account_id}:opening"
            store.open_account(opening, entity, spec["currency"], kind="external", as_of=T0)
            store.apply(Journal(f"open:{account_id}", (
                Posting(account_id, spec["settled"]), Posting(opening, -spec["settled"])),
                kind="opening", sim_time=T0))
    return store


def write(store: LedgerStore, op: dict) -> str | dict:
    """Run one fixture write; 'committed', or the refusal as {refused: code, **detail}."""
    try:
        if "journal" in op:
            store.apply(Journal(f"j-{len(store.rows('journals'))}", tuple(
                Posting(p["account"], p["amount"]) for p in op["journal"]), sim_time=T0))
        elif "posting_without_journal" in op:
            p = op["posting_without_journal"]
            store.apply(Posting(p["account"], p["amount"]))
        elif "hold" in op:
            spec = op["hold"]
            store.hold(spec.get("account", "a/operating"), spec["amount"], now=T0,
                       reservation_id=spec.get("reservation_id"),
                       expires_at=h(spec["expires_h"]) if "expires_h" in spec else None)
        elif "pledge" in op:
            spec = op["pledge"]
            store.pledge(spec["account"], spec["amount"], spec["collateral_ref"])
        elif "commit" in op:
            store.commit(op["commit"], due_at=h(op.get("due_h", 0)))
        elif "release" in op:
            store.release(op["release"])
        elif "settle" in op:
            store.settle(op["settle"], to_account="payroll/external", at=h(op["at_h"]))
        elif "pay_now" in op:
            spec = op["pay_now"]
            pay(store, spec["account"], spec["amount"], to_account="x/external", now=T0,
                journal_id="pay-now")
        else:
            raise AssertionError(f"unknown write {op}")
    except LedgerRefusal as refusal:
        return {"refused": refusal.code, **refusal.detail}
    return "committed"


def matches(got: str | dict, expected: str | dict) -> None:
    if isinstance(expected, str):
        assert got == expected
        return
    assert isinstance(got, dict), f"expected a refusal {expected}, got {got}"
    for key, value in expected.items():
        if key != "note":
            assert got.get(key) == value, f"{key}: {got}"


def run_case(c: dict, url: str = URL) -> None:
    """Run one invariants.json case against a fresh world and assert its `expect`."""
    store = invariants_world(url)
    if "set" in c:
        spec = c["set"]
        if spec.get("observability"):
            store.observe(spec["account"], spec["observability"], T0)
        if "settled" in spec:
            moved = store.view(spec["account"]).settled_minor - spec["settled"]
            store.apply(Journal("set-settled", (Posting(spec["account"], -moved),
                                                Posting("x/external", moved)), sim_time=T0))
        if "as_of_age_h" in spec:
            store.observe(spec["account"], "known", T0 - timedelta(hours=spec["as_of_age_h"]))
        view = store.view(spec["account"])
        got = spendability(view, T0, T0)
        expect = c["expect"]
        for key in ("value", "state", "authority"):
            if key in expect:
                assert getattr(got, key) == expect[key], (c["id"], key, got)
        if "execution" in expect:
            refusal = check_outflow(view, 1, T0)
            assert refusal is not None and refusal.code == expect["execution"]["refused"]
        if got.state != "known":
            assert check_outflow(view, 1, T0) is not None, "reduced authority never executes"
        return
    ops = c["writes"] if "writes" in c else [c["write"]]
    expects = c["expect"] if "writes" in c else [c["expect"]]
    for op, expected in zip(ops, expects, strict=True):
        before = store.dump()
        got = write(store, op)
        matches(got, expected)
        if isinstance(got, dict):
            assert store.dump() == before, f"{c['id']}: a refused write changed the store"


def run(*ids: str) -> None:
    for case_id in ids:
        run_case(case(case_id))


# -------------------------------------------------------------------------- the invariants

def test_every_journal_balances_per_currency():
    run("balances-per-currency", "unbalanced", "balanced-total-unbalanced-per-currency")


def test_no_posting_without_a_journal():
    run("orphan-posting")
    store = invariants_world()
    for journal_id in (None, "no-such-journal"):
        with pytest.raises(IntegrityError), store.transaction() as c:
            c.execute(insert(postings).values(journal_id=journal_id, account_id="a/operating",
                                              currency="USD", amount_minor=100))
    assert store.view("a/operating").settled_minor == 1000000


def test_zero_and_float_amounts_are_refused():
    run("zero-posting", "float-amount")


def test_reserved_never_exceeds_settled():
    run("reserved-over-settled", "reserved-equal-settled")
    store = invariants_world()
    store.hold("a/operating", 600000, now=T0)
    before = store.dump()
    got = write(store, {"journal": [{"account": "a/operating", "amount": -500000},
                                    {"account": "x/external", "amount": 500000}]})
    assert got["refused"] == "reserved_exceeds_settled"
    assert store.dump() == before


def test_the_same_units_are_never_pledged_twice():
    run("double-pledge", "pledge-over-free")
    store = invariants_world()
    store.pledge("a/operating", 1000, "lot-9")
    with pytest.raises(IntegrityError), store.transaction() as c:  # the database refuses too
        c.execute(insert(pledges).values(pledge_id="race", account_id="a/operating",
                                         collateral_ref="lot-9", currency="USD",
                                         amount_minor=1000, state="active"))


def test_a_committed_outflow_is_not_respendable():
    run("committed-outflow-not-respendable")


def test_unknown_is_not_zero_and_lowers_authority():
    run("unknown-is-not-zero", "known-zero")


def test_stale_means_strictly_older_than_six_hours():
    run("stale-after-6h", "fresh-at-6h")


def test_every_invariant_case_has_a_named_test():
    named = {
        "balances-per-currency", "unbalanced", "balanced-total-unbalanced-per-currency",
        "orphan-posting", "zero-posting", "float-amount", "reserved-over-settled",
        "reserved-equal-settled", "double-pledge", "pledge-over-free",
        "committed-outflow-not-respendable", "unknown-is-not-zero", "known-zero",
        "stale-after-6h", "fresh-at-6h",
    }
    assert {c["id"] for c in design("invariants")["cases"]} == named


def test_a_refusal_code_outside_the_closed_set_is_impossible():
    with pytest.raises(ValueError, match="unknown refusal code"):
        LedgerRefusal("not_a_code")


# ------------------------------------------------------------------- reservation lifecycle

def lifecycle_world(url: str = URL) -> LedgerStore:
    store = LedgerStore(url)
    store.add_entity("a", "Entity A (synthetic)", "treasury")
    store.add_entity("payroll", "Payroll (synthetic)", "counterparty")
    store.open_account("a/operating", "a", "USD", as_of=T0)
    store.open_account("a/opening", "a", "USD", kind="external", as_of=T0)
    store.open_account("payroll/external", "payroll", "USD", kind="external", as_of=T0)
    store.apply(Journal("open", (Posting("a/operating", 7000000),
                                 Posting("a/opening", -7000000)), sim_time=T0))
    return store


def buckets(store: LedgerStore, now: datetime) -> dict:
    view = store.view("a/operating")
    return {"settled": view.settled_minor, "reserved": view.reserved_minor,
            "pending_out": view.pending_out_minor,
            "S_now": spendability(view, now, now).value}


def run_path(path: dict, url: str = URL) -> None:
    store, now = lifecycle_world(url), T0
    for step in path["steps"]:
        op = step["do"]
        if "advance_clock_h" in op:
            now += timedelta(hours=op["advance_clock_h"])
            store.expire_due(now)
            got = "committed"
        else:
            if "hold" in op:
                op = {"hold": {"account": "a/operating", **op["hold"]}}
            got = write(store, op)
        if "expect" in step:
            matches(got, step["expect"])
            reservation = op[next(iter(op))]
            assert store.reservation(reservation).state == step["expect"]["state"]
        else:
            assert got == "committed", (path["id"], op, got)
        for key, value in step.get("after", {}).items():
            if key.endswith("_state"):
                assert store.reservation(key[:-len("_state")]).state == value
            else:
                assert buckets(store, now)[key] == value, (path["id"], op, key)
        if "journal" in step:
            journal_id = store.rows("journals")[-1]["journal_id"]
            lines = [{"account": p["account_id"], "amount": p["amount_minor"]}
                     for p in store.rows("postings") if p["journal_id"] == journal_id]
            assert lines == step["journal"]


@pytest.mark.parametrize("path", design("reservation-lifecycle")["paths"], ids=lambda p: p["id"])
def test_reservation_lifecycle(path):
    run_path(path)


def test_a_committed_reservation_is_counted_once():
    store = lifecycle_world()
    store.hold("a/operating", 5000000, now=T0, reservation_id="r1")
    held = buckets(store, T0)
    store.commit("r1", due_at=h(40))
    committed = buckets(store, T0)
    assert held["S_now"] == committed["S_now"] == 2000000
    assert held["reserved"] + held["pending_out"] == committed["reserved"] + \
        committed["pending_out"] == 5000000


# ---------------------------------------------------------------------- schema and ordering

def test_tables_match_the_design_schema(tmp_path):
    designed = sqlite3.connect(tmp_path / "design.db")
    designed.executescript((DESIGN / "schema.sql").read_text(encoding="utf-8"))
    designed.close()
    ours = create_engine(f"sqlite:///{tmp_path / 'ours.db'}")
    metadata.create_all(ours)
    a, b = inspect(create_engine(f"sqlite:///{tmp_path / 'design.db'}")), inspect(ours)
    assert sorted(a.get_table_names()) == sorted(b.get_table_names())
    for table in a.get_table_names():
        pk = a.get_pk_constraint(table)["constrained_columns"]
        assert pk == b.get_pk_constraint(table)["constrained_columns"], table
        # SQLite lets a non-integer primary key be null unless it says NOT NULL; ours says it.
        cols = {c["name"]: c["nullable"] and c["name"] not in pk for c in a.get_columns(table)}
        assert cols == {c["name"]: c["nullable"] for c in b.get_columns(table)}, table
        assert {i["name"] for i in a.get_indexes(table)} == \
            {i["name"] for i in b.get_indexes(table)}, table


def test_seq_is_the_commit_order_and_settled_is_the_sum_of_postings():
    store = invariants_world()
    write(store, {"journal": [{"account": "a/operating", "amount": -1},
                              {"account": "x/external", "amount": 1}]})
    seqs = [j["seq"] for j in sorted(store.rows("journals"), key=lambda j: j["seq"])]
    assert seqs == list(range(1, len(seqs) + 1))
    assert store.view("a/operating").settled_minor == sum(
        p["amount_minor"] for p in store.rows("postings") if p["account_id"] == "a/operating")


def test_an_unzoned_time_is_refused():
    with pytest.raises(ValueError, match="zone"):
        invariants_world().hold("a/operating", 1, now=datetime(2026, 1, 5))


# ------------------------------------------------------------------------- property tests

ACCOUNTS = ["a/operating", "a/eur", "x/external"]
posting = st.tuples(st.sampled_from(ACCOUNTS), st.integers(-2_000_000, 2_000_000))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.lists(posting, min_size=1, max_size=4), max_size=8))
def test_property_any_sequence_of_journals_keeps_every_currency_balanced(batches):
    store = invariants_world()
    for i, batch in enumerate(batches):
        try:
            store.apply(Journal(f"p{i}", tuple(Posting(a, n) for a, n in batch), sim_time=T0))
        except LedgerRefusal:
            pass
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for p in store.rows("postings"):
        totals[(p["journal_id"], p["currency"])] += p["amount_minor"]
    assert all(v == 0 for v in totals.values())
    for account in ("a/operating", "a/eur"):
        view = store.view(account)
        assert view.reserved_minor <= view.settled_minor


pledge_op = st.one_of(
    st.tuples(st.just("pledge"), st.sampled_from(["lot-1", "lot-2", "lot-3"]),
              st.integers(1, 600_000)),
    st.tuples(st.just("release"), st.integers(1, 6), st.just(0)),
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(pledge_op, max_size=12))
def test_property_no_collateral_ref_is_in_two_active_pledges(ops):
    store = invariants_world()
    for kind, ref, amount in ops:
        try:
            if kind == "pledge":
                store.pledge("a/operating", amount, ref)
            else:
                store.release_pledge(f"pledge-{ref}")
        except LedgerRefusal:
            pass
    active = [p["collateral_ref"] for p in store.rows("pledges") if p["state"] == "active"]
    assert len(active) == len(set(active))
    assert sum(p["amount_minor"] for p in store.rows("pledges") if p["state"] == "active") \
        <= store.view("a/operating").settled_minor


# ------------------------------------------------------- settlement and loading regressions

def lf1_snapshot() -> dict:
    snap = json.loads((ROOT / "fixtures/lf1_treasury.json").read_text(encoding="utf-8"))
    return snap["snapshot"]


def test_a_committed_obligation_is_paid_once():
    store = lifecycle_world()
    store.hold("a/operating", 300, now=T0, reservation_id="r1")
    store.add_obligation("ob", "a/operating", 300, h(1), kind="payroll", reservation_id="r1")
    store.commit("r1", due_at=h(5))
    settle_due(store, h(2))
    assert store.rows("obligations")[0]["state"] == "open"  # its flow lands at t=5
    settle_due(store, h(6))
    assert store.view("a/operating").settled_minor == 7000000 - 300
    assert store.rows("obligations")[0]["state"] == "met"


def test_settle_due_leaves_a_discretionary_obligation_alone():
    store = lifecycle_world()
    store.add_obligation("bonus", "a/operating", 1000, h(1), kind="bonus", mandatory=False)
    settle_due(store, h(2))
    assert store.view("a/operating").settled_minor == 7000000
    assert store.rows("obligations")[0]["state"] == "open"


def test_a_missed_obligation_stays_owed_and_is_retried():
    store = lifecycle_world()
    store.add_obligation("rent", "a/operating", 8000000, h(1), kind="rent")
    settle_due(store, h(1))
    assert store.rows("obligations")[0]["state"] == "missed"
    assert projected_cash(store.view("a/operating"), h(1)) == 7000000 - 8000000
    store.expect("a/operating", "in", 2000000, h(2), kind="receivable")
    settle_due(store, h(2))
    assert store.rows("obligations")[0]["state"] == "met"
    assert store.view("a/operating").settled_minor == 1000000


def test_a_snapshot_obligation_already_committed_loads_once():
    snap = lf1_snapshot()
    buckets = snap["accounts"][0]["buckets"]
    buckets["reserved"]["minor"] = 0
    buckets["pending_out"] = [{"flow_id": "pay-1", "amount": {"minor": 5000000, "currency": "USD"},
                               "expected_at": "2026-01-06T16:00:00Z", "kind": "payroll",
                               "reservation_id": "res-payroll-1"}]
    store = LedgerStore(URL)
    from_snapshot(store, snap)
    view = store.view("borrower-a/operating")
    assert (view.reserved_minor, view.pending_out_minor) == (0, 5000000)
    assert projected_cash(view, h(40)) == 4000000  # payroll counted once, through its flow


def test_a_snapshot_met_obligation_holds_nothing():
    snap = lf1_snapshot()
    snap["accounts"][0]["buckets"]["reserved"]["minor"] = 0
    snap["obligations"][0]["state"] = "met"
    store = LedgerStore(URL)
    from_snapshot(store, snap)
    assert store.view("borrower-a/operating").reserved_minor == 0
    assert store.rows("reservations") == []


def test_a_snapshot_unknown_account_keeps_its_observed_reservations():
    snap = lf1_snapshot()
    account = snap["accounts"][0]
    account["observability"], account["buckets"]["settled"] = "unknown", None
    store = LedgerStore(URL)
    from_snapshot(store, snap)
    assert store.view("borrower-a/operating").reserved_minor == 5000000
    with pytest.raises(LedgerRefusal) as refused:
        store.hold("borrower-a/operating", 1, now=T0)
    assert refused.value.code == "unknown_balance"


def test_a_refusal_caught_inside_a_transaction_leaves_nothing():
    store = lifecycle_world()
    store.hold("a/operating", 6000000, now=T0)
    before = store.dump()
    with store.transaction() as c, pytest.raises(LedgerRefusal):
        store.apply(Journal("drain", (Posting("a/operating", -2000000),
                                      Posting("payroll/external", 2000000)),
                            sim_time=T0), conn=c)
    assert store.dump() == before


def test_an_automatic_id_never_takes_an_explicit_one():
    store = lifecycle_world()
    store.hold("a/operating", 1, now=T0, reservation_id="res-2")
    assert store.hold("a/operating", 1, now=T0) == "res-3"


def test_a_duplicate_pledge_id_is_not_a_double_pledge():
    store = lifecycle_world()
    store.pledge("a/operating", 1, "lot-1", pledge_id="p1")
    with pytest.raises(ValueError, match="taken"):
        store.pledge("a/operating", 1, "lot-2", pledge_id="p1")


def test_a_flow_cannot_settle_against_its_own_account():
    store = lifecycle_world()
    store.hold("a/operating", 500, now=T0, reservation_id="r1")
    store.commit("r1", due_at=h(1))
    with pytest.raises(ValueError, match="own account"):
        store.settle("r1", to_account="a/operating", at=h(1))
    assert store.reservation("r1").state == "committed"


def test_an_obligation_reservation_covers_its_account_and_amount():
    store = lifecycle_world()
    store.hold("a/operating", 1, now=T0, reservation_id="tiny")
    with pytest.raises(ValueError, match="is not"):
        store.add_obligation("ob", "a/operating", 100, h(1), kind="rent", reservation_id="tiny")


def test_an_amount_beyond_bigint_is_refused():
    store = lifecycle_world()
    with pytest.raises(LedgerRefusal) as refused:
        store.hold("a/operating", 2**63, now=T0)
    assert refused.value.code == "amount_not_integer_minor"

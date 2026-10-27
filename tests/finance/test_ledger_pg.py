"""The same ledger cases on PostgreSQL (`LEDGER_DATABASE_URL`); marked `pg`, run in CI only.

The merge gate deselects `pg`; CI's postgres job runs `pytest -m pg` against a fresh database.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from app.finance import contracts
from app.finance.ledger import pay
from app.finance.lending import disburse, draw_line, observe_revenue, repay
from app.finance.models import Journal, LedgerRefusal, Posting, metadata
from app.finance.store import LedgerStore
from sqlalchemy import Connection, create_engine, make_url, text
from test_fixtures import assert_paths, lf1
from test_fixtures import world as lf1_world
from test_ledger import T0, design, run_case, run_path
from test_lending import unheld_line
from test_lending import world as lending_world

pytestmark = pytest.mark.pg


@pytest.fixture
def url():
    url = os.environ.get("LEDGER_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("LEDGER_DATABASE_URL names no PostgreSQL database")
    engine = create_engine(url)
    metadata.drop_all(engine)
    engine.dispose()
    return url


@pytest.mark.parametrize("case", design("invariants")["cases"], ids=lambda c: c["id"])
def test_invariant_on_postgres(url, case):
    run_case(case, url)


@pytest.mark.parametrize("path", design("reservation-lifecycle")["paths"], ids=lambda p: p["id"])
def test_reservation_lifecycle_on_postgres(url, path):
    run_path(path, url)


def test_lf1_on_postgres(url):
    assert_paths(lf1_world(url), lf1()["expected"]["no_shock"])


# ------------------------------------------------------------------------- concurrent writers
#
# Each race runs claim A inside an open transaction on one connection, then claim B on a second
# connection, and commits A only once B has either finished or is blocked on a lock A holds.
# Unserialized, B reads what A has not committed yet and acts on it; serialized, B waits and
# then reads A's committed write.

Claim = Callable[[LedgerStore, str, Connection | None], object]


def race(url: str, first: Claim, second: Claim, pause: str | None = None) -> dict[str, str]:
    """{"a": outcome, "b": outcome}: "committed", a refusal code, or the escaped error's name.

    `pause` names a method of A's store: A stops just before its first call until B has
    finished or is blocked on A, so B can take locks in the middle of A's claim.
    """
    b_url = make_url(url).update_query_dict({"application_name": "race-b"})
    stores = {"a": LedgerStore(url),
              "b": LedgerStore(b_url.render_as_string(hide_password=False))}
    probe = create_engine(url)
    outcome: dict[str, str] = {}
    a_pid: list[int] = []
    a_ready = threading.Event()

    def run(name: str, claim: Claim, conn: Connection | None) -> None:
        try:
            claim(stores[name], name, conn)
            outcome[name] = "committed"
        except LedgerRefusal as refusal:
            outcome[name] = refusal.code
        except Exception as exc:  # noqa: BLE001 - the outcome names what escaped
            outcome[name] = type(exc).__name__

    b = threading.Thread(target=run, args=("b", second, None))

    def b_is_settled() -> bool:
        if not b.is_alive():
            return True
        with probe.connect() as c:  # blocked by A itself, not by anything else
            return bool(c.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE application_name = 'race-b'"
                " AND :a = ANY(pg_blocking_pids(pid))"), {"a": a_pid[0]}).scalar())

    def wait_for_b() -> None:
        a_ready.set()
        deadline = time.monotonic() + 20
        while not (b.ident is not None and b_is_settled()):
            assert time.monotonic() < deadline, "claim B neither finished nor blocked on A"
            time.sleep(0.02)

    if pause:
        inner, paused = getattr(stores["a"], pause), []

        def paused_once(*args, **kwargs):
            if not paused:
                paused.append(True)
                wait_for_b()
            return inner(*args, **kwargs)
        setattr(stores["a"], pause, paused_once)

    def claim_a() -> None:
        with stores["a"].engine.connect() as conn, conn.begin():
            a_pid.append(conn.execute(text("SELECT pg_backend_pid()")).scalar())
            run("a", first, conn)
            wait_for_b()

    a = threading.Thread(target=claim_a)
    try:
        a.start()
        assert a_ready.wait(20), "claim A never reached the point B starts at"
        b.start()
        a.join(30)
        b.join(30)
    finally:
        probe.dispose()
        for store in stores.values():
            store.engine.dispose()
    assert set(outcome) == {"a", "b"}, outcome
    return outcome


def funded(url: str) -> LedgerStore:
    """One known cash account holding 1,000 settled, paid in from an opening account."""
    store = LedgerStore(url)
    store.add_entity("a", "Entity A (synthetic)", "treasury")
    store.open_account("a/cash", "a", "USD", as_of=T0)
    store.open_account("a/opening", "a", "USD", kind="external", as_of=T0)
    store.open_account("a/payee", "a", "USD", kind="external", as_of=T0)
    store.apply(Journal("open", (Posting("a/cash", 1000), Posting("a/opening", -1000)),
                        kind="opening", sim_time=T0))
    return store


CLAIMS: dict[str, Claim] = {
    "hold": lambda s, n, c: s.hold("a/cash", 700, now=T0, reservation_id=f"res-{n}", conn=c),
    "pledge": lambda s, n, c: s.pledge("a/cash", 700, f"collateral-{n}", pledge_id=f"pledge-{n}",
                                       conn=c),
    "pay": lambda s, n, c: pay(s, "a/cash", 700, to_account="a/payee", now=T0,
                               journal_id=f"pay-{n}", conn=c),
}


@pytest.mark.parametrize("first,second", [("hold", "hold"), ("pledge", "hold"),
                                          ("hold", "pledge"), ("pay", "pay"), ("hold", "pay"),
                                          ("pay", "hold")])
def test_two_connections_never_claim_more_than_settled(url, first, second):
    """Two 700 claims on 1,000 settled, with distinct ids: one commits, one is refused by name."""
    store = funded(url)
    outcome = race(url, CLAIMS[first], CLAIMS[second])
    assert outcome["a"] == "committed"
    assert outcome["b"] in ("reserved_exceeds_settled", "pledge_exceeds_free",
                            "insufficient_spendable"), outcome
    assert store.view("a/cash").free_minor == 300


def test_two_connections_settle_one_flow_once(url):
    store = funded(url)
    store.hold("a/cash", 400, now=T0, reservation_id="res")
    flow = store.commit("res", due_at=T0)

    def settle(s: LedgerStore, n: str, c: Connection | None) -> None:
        s.settle_flow(flow, counterparty="a/payee", at=T0, journal_id=f"settle-{n}", conn=c)

    assert race(url, settle, settle) == {"a": "committed", "b": "ValueError"}
    assert store.view("a/cash").settled_minor == 600


def test_two_connections_never_expire_a_committed_reservation(url):
    store = funded(url)
    store.hold("a/cash", 400, now=T0, reservation_id="res", expires_at=T0 + timedelta(hours=1))

    def commit(s: LedgerStore, n: str, c: Connection | None) -> None:
        s.commit("res", due_at=T0, conn=c)

    expired: list[str] = []

    def expire(s: LedgerStore, n: str, c: Connection | None) -> None:
        expired.extend(s.expire_due(T0 + timedelta(hours=2), conn=c))

    assert race(url, commit, expire) == {"a": "committed", "b": "committed"}
    assert (store.reservation("res").state, expired) == ("committed", [])


def test_settling_against_a_cash_account_never_deadlocks_a_payment(url):
    """A settlement on b/cash paid from a/cash, and a payment a/cash → b/cash, at once.

    A stops before posting its journal while B locks both accounts: each must lock both in id
    order up front, or each holds the account the other waits on.
    """
    store = funded(url)
    store.add_entity("b", "Entity B (synthetic)", "treasury")
    store.open_account("b/cash", "b", "USD", as_of=T0)
    store.apply(Journal("open-b", (Posting("b/cash", 1000), Posting("a/opening", -1000)),
                        kind="opening", sim_time=T0))
    store.hold("b/cash", 400, now=T0, reservation_id="res")
    flow = store.commit("res", due_at=T0)

    def settle(s: LedgerStore, n: str, c: Connection | None) -> None:
        s.settle_flow(flow, counterparty="a/cash", at=T0, journal_id="settle", conn=c)

    def payment(s: LedgerStore, n: str, c: Connection | None) -> None:
        pay(s, "a/cash", 100, to_account="b/cash", now=T0, journal_id="pay", conn=c)

    assert race(url, settle, payment, pause="_apply") == {"a": "committed", "b": "committed"}
    assert (store.view("a/cash").settled_minor, store.view("b/cash").settled_minor) == (1300, 700)


def test_two_connections_disburse_one_advance_once(url):
    store = lending_world(url=url)

    def disbursal(s: LedgerStore, n: str, c: Connection | None) -> None:
        disburse(s, "adv-a", now=T0, journal_id=f"disburse-{n}", conn=c)

    assert race(url, disbursal, disbursal) == {"a": "committed", "b": "ValueError"}
    adv = contracts.facility(store, "adv-a")
    assert contracts.outstanding_minor(store, adv) == adv.owed_minor


def test_two_connections_never_draw_a_line_past_its_limit(url):
    store = lending_world(unheld_line(), url=url)

    def draw(s: LedgerStore, n: str, c: Connection | None) -> None:
        draw_line(s, "line-b", 600000, now=T0, journal_id=f"draw-{n}", conn=c)

    assert race(url, draw, draw) == {"a": "committed", "b": "beyond_capacity"}
    line = contracts.facility(store, "line-b")
    assert contracts.outstanding_minor(store, line) == 600000


def test_two_connections_never_repay_more_than_is_owed(url):
    store = lending_world(borrower_cash=10000000, url=url)
    disburse(store, "adv-a", now=T0)
    week_1, week_2 = T0 + timedelta(days=7), T0 + timedelta(days=14)
    for end in (week_1, week_2):  # each period's share alone would repay the whole advance
        observe_revenue(store, "adv-a", end, 100000000, observed_at=end, source="sales ledger")
    store.observe("borrower-a/operating", "known", week_2)

    def repayment(end: datetime) -> Claim:
        return lambda s, n, c: repay(s, "adv-a", end, now=week_2, conn=c)

    assert race(url, repayment(week_1), repayment(week_2)) == {"a": "committed",
                                                               "b": "committed"}
    adv = contracts.facility(store, "adv-a")
    assert (adv.state, contracts.outstanding_minor(store, adv)) == ("repaid", 0)

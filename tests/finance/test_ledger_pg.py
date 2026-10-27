"""The same ledger cases on PostgreSQL (`LEDGER_DATABASE_URL`); marked `pg`, run in CI only.

The merge gate deselects `pg`; CI's postgres job runs `pytest -m pg` against a fresh database.
"""

from __future__ import annotations

import os
import threading
import time

import pytest
from app.finance.ledger import pay
from app.finance.models import Journal, LedgerRefusal, Posting, metadata
from app.finance.store import LedgerStore
from sqlalchemy import create_engine, text
from test_fixtures import assert_paths, lf1
from test_fixtures import world as lf1_world
from test_ledger import T0, design, run_case, run_path

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


# ------------------------------------------------------------------- concurrent fund claims

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


CLAIMS = {
    "hold": lambda s, n: s.hold("a/cash", 700, now=T0, reservation_id=f"res-{n}"),
    "pledge": lambda s, n: s.pledge("a/cash", 700, f"collateral-{n}", pledge_id=f"pledge-{n}"),
    "pay": lambda s, n: pay(s, "a/cash", 700, to_account="a/payee", now=T0,
                            journal_id=f"pay-{n}"),
}


@pytest.mark.parametrize("first,second", [("hold", "hold"), ("pledge", "hold"),
                                          ("pay", "pay"), ("pay", "hold")])
def test_two_connections_never_claim_more_than_settled(url, first, second):
    """Two 700 claims on 1,000 settled, from two connections with distinct ids: one commits.

    Every read of an account's funds is a rendezvous: a claim that has read waits until the
    other has read as often, has finished, or is blocked on a lock. Unserialized, both read
    1,000 and both commit (a hold or pledge), or the second dies on a raw integrity error (a
    payment); serialized, the second reads after the first commits and is refused by name.
    """
    funded(url)
    stores = {"a": LedgerStore(url), "b": LedgerStore(url)}
    reads = {name: 0 for name in stores}
    done = {name: threading.Event() for name in stores}
    probe = create_engine(url)

    def someone_waits_on_a_lock() -> bool:
        with probe.connect() as c:
            return bool(c.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
                " AND datname = current_database()")).scalar())

    def rendezvous(name: str, method: str) -> None:
        inner, other = getattr(stores[name], method), "b" if name == "a" else "a"

        def wrapped(*args, **kwargs):
            got = inner(*args, **kwargs)
            reads[name] += 1
            deadline = time.monotonic() + 20
            while (reads[other] < reads[name] and not done[other].is_set()
                   and not someone_waits_on_a_lock()):
                assert time.monotonic() < deadline, f"claim {other} neither read nor blocked"
                time.sleep(0.02)
            return got
        setattr(stores[name], method, wrapped)

    outcome: dict[str, str] = {}

    def claim(name: str, kind: str) -> None:
        try:
            CLAIMS[kind](stores[name], name)
            outcome[name] = "committed"
        except LedgerRefusal as refusal:
            outcome[name] = refusal.code
        except Exception as exc:  # noqa: BLE001 - the outcome names what escaped
            outcome[name] = type(exc).__name__
        finally:
            done[name].set()

    for name in stores:
        rendezvous(name, "view")
        rendezvous(name, "_free")
    threads = [threading.Thread(target=claim, args=(name, kind))
               for name, kind in (("a", first), ("b", second))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    probe.dispose()

    assert sorted(outcome.values()).count("committed") == 1, outcome
    refused = next(v for v in outcome.values() if v != "committed")
    assert refused in ("reserved_exceeds_settled", "pledge_exceeds_free",
                       "insufficient_spendable"), outcome
    view = LedgerStore(url).view("a/cash")
    assert view.settled_minor - view.reserved_minor - view.pledged_minor == 300

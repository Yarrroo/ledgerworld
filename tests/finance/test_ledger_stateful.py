"""Random ledger sequences against an independent reference model (T34).

A hypothesis state machine sends the same writes (post, reserve, release, commit, settle, pledge,
release a pledge, observe, let time pass) to a `LedgerStore` and to `ledger_reference.Reference`.
Each write must get the same outcome from both: committed, or the same refusal code. After every
step the five g1 ledger invariants are checked against the reference: journals balance, no
orphan posting, reserved ≤ settled, no double pledge, unknown ≠ zero. So a passing g1 covers
sequences, not just samples. The seed and the example budget are fixed, so the merge gate runs
the same sequences every time, offline.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.finance.ledger import check_outflow
from app.finance.models import Journal, LedgerRefusal, Posting
from app.finance.spendability import AccountView, projected_cash, spendability, state_of
from app.finance.store import LedgerStore
from hypothesis import HealthCheck, seed, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)
from ledger_reference import Reference, Refused

T0 = datetime(2026, 1, 5, tzinfo=UTC)
CASH = {"a/usd": "USD", "a/usd-2": "USD", "a/eur": "EUR"}
EXTERNAL = {"x/usd": "USD", "x/eur": "EUR"}
ACCOUNTS = [*CASH, *EXTERNAL]
OUTSIDE = {currency: account_id for account_id, currency in EXTERNAL.items()}
LOTS = ["lot-1", "lot-2", "lot-3"]  # few collateral refs, so pledges collide
SEED = 20261027
BUDGET = settings(max_examples=80, stateful_step_count=25, deadline=None, database=None,
                  suppress_health_check=[HealthCheck.too_slow])

cash = st.sampled_from(list(CASH))
anywhere = st.sampled_from(ACCOUNTS)


def outcome(write: Callable[[], object], *, own_account: bool = False) -> str:
    """'ok', or the refusal's code; a settlement against its own account is 'own_account'."""
    try:
        write()
    except (LedgerRefusal, Refused) as refusal:
        return refusal.code
    except ValueError:
        if not own_account:
            raise
        return "own_account"
    return "ok"


@seed(SEED)
class LedgerMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.store = LedgerStore("sqlite://")
        self.ref = Reference()
        self.now = T0
        self.n = 0
        self.writes = 0  # every write sent to the store bumps it, refused or not
        self.read: tuple[int, dict[str, AccountView]] | None = None
        self.store.add_entity("a", "Entity A (synthetic)", "treasury")
        self.store.add_entity("x", "Outside (synthetic)", "external")
        for account_id, currency in {**CASH, **EXTERNAL}.items():
            kind = "cash" if account_id in CASH else "external"
            self.store.open_account(account_id, account_id[0], currency, kind=kind, as_of=T0)
            self.ref.open(account_id, currency, cash=kind == "cash", as_of=T0)

    # ---------------------------------------------------------------------------- helpers

    def next_id(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n}"

    def same(self, store_write: Callable[[], object], ref_write: Callable[[], object], *,
             own_account: bool = False) -> str:
        """Run one write on both sides; they must agree on its outcome."""
        self.writes += 1
        ref = outcome(ref_write, own_account=own_account)
        store = outcome(store_write, own_account=own_account)
        assert store == ref, f"store {store!r}, reference {ref!r}"
        return store

    def journal(self, legs: list[tuple[str, int]]) -> str:
        journal = Journal(self.next_id("j"), tuple(Posting(a, n) for a, n in legs),
                          sim_time=self.now)
        return self.same(lambda: self.store.apply(journal), lambda: self.ref.post(legs))

    def amount(self, data: st.DataObject, account_id: str) -> int:
        """Any amount, one the free units cover, or exactly them or one past: the edge breaks."""
        free = self.ref.free(account_id)
        near = [st.integers(1, free), st.just(free), st.just(free + 1)] if free > 0 else []
        return data.draw(st.one_of(st.integers(1, 2_500_000), *near))

    def reservation(self, data: st.DataObject, state: str) -> str:
        """Mostly one in `state`, so the write can land; sometimes any, so it can be refused."""
        every = sorted(self.ref.reservations)
        apt = [rid for rid in every if self.ref.reservations[rid].state == state]
        return data.draw(st.sampled_from(apt) | st.sampled_from(every) if apt
                         else st.sampled_from(every))

    def views(self) -> dict[str, AccountView]:
        """Every account's buckets, read again whenever a write has been sent since."""
        if self.read is None or self.read[0] != self.writes:
            with self.store.reading() as c:
                self.read = self.writes, {a: self.store.view(a, conn=c) for a in ACCOUNTS}
        return self.read[1]

    # ------------------------------------------------------------------------------ rules

    @initialize(funding=st.lists(st.integers(0, 2_000_000), min_size=3, max_size=3))
    def fund(self, funding: list[int]) -> None:
        for (account_id, currency), amount in zip(CASH.items(), funding, strict=True):
            if amount:
                assert self.journal([(OUTSIDE[currency], -amount), (account_id, amount)]) == "ok"

    @rule(src=anywhere, dst=anywhere, data=st.data(),
          shape=st.sampled_from(["journal", "journal", "unbalanced", "bare posting"]))
    def post(self, src: str, dst: str, data: st.DataObject, shape: str) -> None:
        amount = self.amount(data, src)
        if shape == "bare posting":
            assert self.same(lambda: self.store.apply(Posting(src, amount)),
                             self.ref.posting_without_journal) == "no_journal"
        elif shape == "unbalanced":
            skew = data.draw(st.integers(1, 1_000))
            assert self.journal([(src, -amount), (dst, amount + skew)]) == "journal_unbalanced"
        elif self.ref.state(src, self.now) == "unknown":
            # Nothing executes on an unknown balance: the outflow is refused before any write.
            refusal = check_outflow(self.store.view(src), amount, self.now)
            assert refusal is not None and refusal.code == "unknown_balance"
        else:
            self.journal([(src, -amount), (dst, amount)])

    @rule(account=cash, data=st.data())
    def reserve(self, account: str, data: st.DataObject) -> None:
        amount, rid = self.amount(data, account), self.next_id("r")
        self.same(lambda: self.store.hold(account, amount, now=self.now, reservation_id=rid),
                  lambda: self.ref.hold(rid, account, amount))

    @precondition(lambda self: self.ref.reservations)
    @rule(data=st.data())
    def release(self, data: st.DataObject) -> None:
        rid = self.reservation(data, "held")
        self.same(lambda: self.store.release(rid), lambda: self.ref.release(rid))

    @precondition(lambda self: self.ref.reservations)
    @rule(data=st.data(), due_in_h=st.integers(0, 96))
    def commit(self, data: st.DataObject, due_in_h: int) -> None:
        rid = self.reservation(data, "held")
        due = self.now + timedelta(hours=due_in_h)
        self.same(lambda: self.store.commit(rid, due_at=due), lambda: self.ref.commit(rid))

    @precondition(lambda self: self.ref.reservations)
    @rule(data=st.data(), to=anywhere)
    def settle(self, data: st.DataObject, to: str) -> None:
        rid = self.reservation(data, "committed")
        self.same(lambda: self.store.settle(rid, to_account=to, at=self.now),
                  lambda: self.ref.settle(rid, to), own_account=True)

    @rule(account=cash, lot=st.sampled_from(LOTS), data=st.data())
    def pledge(self, account: str, lot: str, data: st.DataObject) -> None:
        amount, pid = self.amount(data, account), self.next_id("p")
        self.same(lambda: self.store.pledge(account, amount, lot, pledge_id=pid),
                  lambda: self.ref.pledge(pid, account, lot, amount))

    @precondition(lambda self: self.ref.pledges)
    @rule(data=st.data())
    def release_pledge(self, data: st.DataObject) -> None:
        pid = data.draw(st.sampled_from(sorted(self.ref.pledges)))
        self.same(lambda: self.store.release_pledge(pid), lambda: self.ref.release_pledge(pid))

    @rule(account=cash, unknown=st.booleans())
    def observe(self, account: str, unknown: bool) -> None:
        self.writes += 1
        self.store.observe(account, "unknown" if unknown else "known", self.now)
        self.ref.observe(account, unknown, self.now)

    @rule(hours=st.integers(1, 3))
    def let_time_pass(self, hours: int) -> None:
        self.now += timedelta(hours=hours)

    # ------------------------------------------------------------------------- invariants

    @invariant()
    def journals_balance(self) -> None:
        """ledger_balance: every journal sums to zero per currency, and so does the world."""
        per_journal: dict[tuple[str, str], int] = defaultdict(int)
        for p in self.store.rows("postings"):
            per_journal[(p["journal_id"], p["currency"])] += p["amount_minor"]
        assert all(total == 0 for total in per_journal.values()), per_journal
        world: dict[str, int] = defaultdict(int)
        for account_id, view in self.views().items():
            assert view.settled_minor == self.ref.accounts[account_id].settled, account_id
            world[view.currency] += view.settled_minor
        assert all(total == 0 for total in world.values()), world
        assert len(self.store.rows("journals")) == len(self.ref.journals)

    @invariant()
    def no_orphan_posting(self) -> None:
        """ledger_no_orphan_posting: every posting is a line of a journal that holds two or more."""
        journal_ids = {j["journal_id"] for j in self.store.rows("journals")}
        lines: dict[str, int] = defaultdict(int)
        for p in self.store.rows("postings"):
            assert p["journal_id"] in journal_ids, p
            lines[p["journal_id"]] += 1
        assert set(lines) == journal_ids and all(n >= 2 for n in lines.values())
        assert sum(lines.values()) == self.ref.postings

    @invariant()
    def reserved_within_settled(self) -> None:
        """ledger_reserved_le_settled: a known cash account never promises more than it holds."""
        for account_id, view in self.views().items():
            assert (view.reserved_minor, view.pledged_minor, view.pending_out_minor) == (
                self.ref.held(account_id), self.ref.pledged(account_id),
                self.ref.pending_out(account_id)), account_id
            if self.ref.checked(account_id):
                assert (view.reserved_minor + view.pledged_minor + view.pending_out_minor
                        <= view.settled_minor), account_id
        states = {r["reservation_id"]: r["state"] for r in self.store.rows("reservations")}
        assert states == {rid: r.state for rid, r in self.ref.reservations.items()}

    @invariant()
    def no_double_pledge(self) -> None:
        """ledger_no_double_pledge: one collateral ref is in at most one active pledge."""
        rows = self.store.rows("pledges")
        active = [p["collateral_ref"] for p in rows if p["state"] == "active"]
        assert len(active) == len(set(active)), active
        assert {p["pledge_id"]: (p["collateral_ref"], p["amount_minor"], p["state"])
                for p in rows} == {pid: (p.collateral_ref, p.amount, p.state)
                                   for pid, p in self.ref.pledges.items()}

    @invariant()
    def unknown_is_not_zero(self) -> None:
        """ledger_unknown_not_zero: unknown has no value, stale keeps one; both lower authority."""
        views = self.views()
        for account_id in CASH:
            view, state = views[account_id], self.ref.state(account_id, self.now)
            s = spendability(view, self.now, self.now)
            assert (state_of(view, self.now), s.state) == (state, state), account_id
            first = check_outflow(view, 1, self.now)
            if state == "unknown":
                assert s.value is None and s.authority == "reduced"
                assert projected_cash(view, self.now) is None
                assert first is not None and first.code == "unknown_balance"
                continue
            free = self.ref.free(account_id)
            assert s.value == free
            if state == "stale":
                assert s.authority == "reduced"
                assert first is not None and first.code == "stale_balance"
                continue
            assert s.authority == "full"
            beyond = check_outflow(view, free + 1, self.now)
            assert beyond is not None and beyond.code == "insufficient_spendable"
            if free > 0:
                assert check_outflow(view, free, self.now) is None


def test_random_ledger_sequences_match_the_reference_and_keep_every_invariant():
    run_state_machine_as_test(LedgerMachine, settings=BUDGET)

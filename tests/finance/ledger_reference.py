"""An independent reference model of the ledger's money, for the stateful test (T34).

Plain dicts and integers: settled balances, reservations and pledges, and the refusal each write
earns by the system brief §5. It imports nothing from `app.finance`, so a rule the ledger gets
wrong cannot be copied into the model that judges it; `test_ledger_stateful.py` drives both with
the same writes and compares them after every step.

A refused write changes nothing here, as it changes nothing in the store.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

STALE_AFTER = timedelta(hours=6)  # §5: a balance strictly older than this is stale


class Refused(Exception):
    """A write the reference refuses; `code` is the ledger's refusal code for it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Account:
    currency: str
    cash: bool  # a cash account carries promises; an external one may go below zero
    as_of: datetime
    settled: int = 0
    unknown: bool = False


@dataclass
class Reservation:
    account: str
    amount: int
    state: str = "held"  # held → committed → settled | released


@dataclass
class Pledge:
    account: str
    collateral_ref: str
    amount: int
    state: str = "active"  # active → released


class Reference:
    """What the ledger must hold after any sequence of writes, kept by hand."""

    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}
        self.reservations: dict[str, Reservation] = {}
        self.pledges: dict[str, Pledge] = {}
        self.journals: list[list[tuple[str, int]]] = []

    def open(self, account_id: str, currency: str, *, cash: bool, as_of: datetime) -> None:
        self.accounts[account_id] = Account(currency, cash, as_of)

    # ------------------------------------------------------------------------------- reads

    def held(self, account_id: str) -> int:
        return sum(r.amount for r in self.reservations.values()
                   if r.account == account_id and r.state == "held")

    def pending_out(self, account_id: str) -> int:
        """A committed reservation is a pending_out flow until it settles."""
        return sum(r.amount for r in self.reservations.values()
                   if r.account == account_id and r.state == "committed")

    def pledged(self, account_id: str) -> int:
        return sum(p.amount for p in self.pledges.values()
                   if p.account == account_id and p.state == "active")

    def free(self, account_id: str) -> int:
        """Settled units nothing is promised against: S(now) with no pending_in."""
        return (self.accounts[account_id].settled - self.held(account_id)
                - self.pledged(account_id) - self.pending_out(account_id))

    def state(self, account_id: str, now: datetime) -> str:
        account = self.accounts[account_id]
        if account.unknown:
            return "unknown"
        return "stale" if now - account.as_of > STALE_AFTER else "known"

    def checked(self, account_id: str) -> bool:
        """A known cash account: no write may leave it below its promises."""
        account = self.accounts[account_id]
        return account.cash and not account.unknown

    @property
    def postings(self) -> int:
        return sum(len(legs) for legs in self.journals)

    # ------------------------------------------------------------------------------ writes

    def post(self, legs: list[tuple[str, int]]) -> None:
        """A journal: it balances per currency and leaves every checked account covered."""
        totals: dict[str, int] = defaultdict(int)
        moved: dict[str, int] = defaultdict(int)
        for account_id, amount in legs:
            totals[self.accounts[account_id].currency] += amount
            moved[account_id] += amount
        if any(totals.values()):
            raise Refused("journal_unbalanced")
        for account_id, amount in moved.items():
            if self.checked(account_id) and self.free(account_id) + amount < 0:
                raise Refused("reserved_exceeds_settled")
        for account_id, amount in moved.items():
            self.accounts[account_id].settled += amount
        self.journals.append(list(legs))

    def posting_without_journal(self) -> None:
        raise Refused("no_journal")

    def hold(self, reservation_id: str, account_id: str, amount: int) -> None:
        if self.accounts[account_id].unknown:
            raise Refused("unknown_balance")
        if amount > self.free(account_id):
            raise Refused("reserved_exceeds_settled")
        self.reservations[reservation_id] = Reservation(account_id, amount)

    def release(self, reservation_id: str) -> None:
        self._held(reservation_id).state = "released"

    def commit(self, reservation_id: str) -> None:
        self._held(reservation_id).state = "committed"

    def settle(self, reservation_id: str, to_account: str) -> None:
        """A committed reservation pays `to_account` out of settled."""
        res = self.reservations[reservation_id]
        if res.state != "committed":
            raise Refused("reservation_not_held")
        if to_account == res.account:
            raise Refused("own_account")
        res.state = "settled"
        try:
            self.post([(res.account, -res.amount), (to_account, res.amount)])
        except Refused:
            res.state = "committed"
            raise

    def pledge(self, pledge_id: str, account_id: str, collateral_ref: str, amount: int) -> None:
        if any(p.collateral_ref == collateral_ref and p.state == "active"
               for p in self.pledges.values()):
            raise Refused("already_pledged")
        if self.accounts[account_id].unknown:
            raise Refused("unknown_balance")
        if amount > self.free(account_id):
            raise Refused("pledge_exceeds_free")
        self.pledges[pledge_id] = Pledge(account_id, collateral_ref, amount)

    def release_pledge(self, pledge_id: str) -> None:
        """Releasing a pledge that is not active changes nothing."""
        pledge = self.pledges[pledge_id]
        if pledge.state == "active":
            pledge.state = "released"

    def observe(self, account_id: str, unknown: bool, as_of: datetime) -> None:
        account = self.accounts[account_id]
        account.unknown, account.as_of = unknown, as_of

    def _held(self, reservation_id: str) -> Reservation:
        res = self.reservations[reservation_id]
        if res.state != "held":
            raise Refused("reservation_not_held")
        return res

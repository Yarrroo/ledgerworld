"""Spendability S, projected cash P and the reserve-floor headroom (system brief §5).

Two measures, never conflated (design/modules/ledger/HANDOFF.md):

- S(t) = settled − reserved − pledged − Σ all pending_out + Σ pending_in expected ≤ t: what is
  free to commit. A committed outflow is spoken for from the moment of commit, whatever its due.
- P(t) = settled + Σ pending_in expected ≤ t − Σ pending_out due ≤ t − Σ obligations due ≤ t
  (reserved or not): what the account will hold at t. The reserve floor is checked on P.

Everything here is a pure function of an `AccountView` (read in one transaction by
`LedgerStore.view`), so clearing, decisions and the API read the same numbers without a store.
An unknown balance has no value (never 0); a stale one keeps its value with reduced authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .models import HORIZON, STALE_AFTER
from .schemas import EXPONENT

State = Literal["known", "stale", "unknown"]
Authority = Literal["full", "reduced"]


@dataclass(frozen=True)
class Flow:
    """A pending movement: `at` is the expected arrival (in) or the due time (out)."""

    flow_id: str
    amount_minor: int
    at: datetime
    kind: str
    reservation_id: str | None = None


@dataclass(frozen=True)
class Due:
    """An open obligation not yet carried by a pending_out flow."""

    obligation_id: str
    amount_minor: int
    at: datetime
    kind: str
    reservation_id: str | None = None


@dataclass(frozen=True)
class AccountView:
    """One account's buckets at one moment; settled is Σ postings, never a stored column."""

    account_id: str
    entity_id: str
    currency: str
    kind: str
    floor_minor: int | None
    observability: Literal["known", "unknown"]
    as_of: datetime
    settled_minor: int
    reserved_minor: int
    pledged_minor: int
    pending_in: tuple[Flow, ...] = ()
    pending_out: tuple[Flow, ...] = ()
    obligations: tuple[Due, ...] = ()

    @property
    def pending_out_minor(self) -> int:
        return sum(f.amount_minor for f in self.pending_out)

    @property
    def free_minor(self) -> int:
        """Settled units not yet spoken for: what a hold or a pledge may still take."""
        return (self.settled_minor - self.reserved_minor - self.pledged_minor
                - self.pending_out_minor)


@dataclass(frozen=True)
class Spendable:
    value: int | None
    state: State
    authority: Authority


@dataclass(frozen=True)
class Headroom:
    """min over [now, horizon] of (P(t) − floor), floored at 0; `binding_t` is where it binds."""

    value: int | None
    binding_t: datetime | None


@dataclass(frozen=True)
class FloorCheck:
    feasible: bool | None
    min_p: int | None
    at: datetime | None
    short_minor: int
    binding: str | None


def state_of(view: AccountView, now: datetime) -> State:
    """unknown when not observable; stale when `as_of` is strictly older than STALE_AFTER."""
    if view.observability == "unknown":
        return "unknown"
    return "stale" if now - view.as_of > STALE_AFTER else "known"


def spendability(view: AccountView, t: datetime, now: datetime) -> Spendable:
    """S[a, c, t]: how much can reach this account in its currency by time t."""
    state = state_of(view, now)
    if state == "unknown":
        return Spendable(None, state, "reduced")
    value = view.free_minor + sum(f.amount_minor for f in view.pending_in if f.at <= t)
    return Spendable(value, state, "full" if state == "known" else "reduced")


def projected_cash(view: AccountView, t: datetime) -> int | None:
    """P[a, t]: what the account will hold at t once everything due by t has moved."""
    if view.observability == "unknown":
        return None
    return (view.settled_minor
            + sum(f.amount_minor for f in view.pending_in if f.at <= t)
            - sum(f.amount_minor for f in view.pending_out if f.at <= t)
            - sum(d.amount_minor for d in view.obligations if d.at <= t))


def min_projected(view: AccountView, now: datetime,
                  horizon: timedelta = HORIZON) -> tuple[int | None, datetime | None]:
    """The lowest P over [now, now + horizon] and the earliest time it is reached.

    P is a step function that moves only at a flow's or an obligation's time, so its minimum is
    taken over `now` and those times; nothing between them can be lower.
    """
    if view.observability == "unknown":
        return None, None
    end = now + horizon
    events = [f.at for f in view.pending_in + view.pending_out] + [d.at for d in view.obligations]
    points = sorted({now, *(at for at in events if now < at <= end)})
    best, best_at = None, None
    for at in points:
        p = projected_cash(view, at)
        if best is None or p < best:
            best, best_at = p, at
    return best, best_at


def headroom(view: AccountView, now: datetime, horizon: timedelta = HORIZON) -> Headroom:
    """How much a discretionary outflow at `now` may take before P breaks the floor."""
    low, at = min_projected(view, now, horizon)
    if low is None:
        return Headroom(None, None)
    return Headroom(max(0, low - (view.floor_minor or 0)), at)


def floor_check(view: AccountView, now: datetime, horizon: timedelta = HORIZON) -> FloorCheck:
    """Feasible when P(t) ≥ floor for every t in the horizon (the floor holds when equal)."""
    low, at = min_projected(view, now, horizon)
    if low is None:
        return FloorCheck(None, None, None, 0, None)
    floor = view.floor_minor or 0
    short = max(0, floor - low)
    binding = (f"reserve floor {grouped(floor, view.currency)} on {view.account_id}"
               if short else None)
    return FloorCheck(short == 0, low, at, short, binding)


def grouped(minor: int, currency: str) -> str:
    """Minor units as a grouped decimal for a reason or a label: 3000000 USD -> '30,000.00'."""
    exponent = EXPONENT[currency]
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 10**exponent)
    return f"{sign}{whole:,}" + (f".{frac:0{exponent}d}" if exponent else "")

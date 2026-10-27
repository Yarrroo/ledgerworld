"""Feasibility of one policy branch, read from its realised ledger (§9, HANDOFF `assess`).

Judge outcomes, not intentions: nothing here looks at what a policy projected. Settled cash at
each round end is the sum of the account's postings in journals of that round or earlier; an
obligation is met when its settlement journal (its own, or its committed reservation's flow's)
falls in its due round or earlier, by its state only when the ledger names no such journal, and
unmet otherwise, short by its amount less the cash that was free then (settled less the
reservations still backing later obligations, less pledged; never below zero). An obligation
due at or before the checkpoint and still outstanding there is carried in with its original
deadline, unmet and overdue; its "then" is the first assessed round end, its first chance in
the branch, read before its own payment when the branch paid it there. One paid by the
checkpoint is history and left out. Funding cost is the expense the entity booked in the branch
(an advance's fee is recognised at disbursal). Every number is an integer in minor units.

The obligations are the entity's on every cash account it holds, not the assessed account's
alone: one on another account (a EUR invoice on a EUR account) is met or short against that
account's own settled cash, reservations and pledges, and carries its account and currency.
The floor is the assessed account's.

Cash is usable only at the end of a round whose balance was known: an unknown balance adds
nothing (HANDOFF), so the floor and an unmet obligation's shortfall count only what it owes
(``min(settled, 0)``) whatever the ledger holds. The store keeps only the current
observability, so the caller records it per round.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from ..finance.models import accounts, bounded_id, expected_flows, journals, postings
from ..simulation.clock import ROUND_HOURS
from ..simulation.world import due_hour

__all__ = ["Feasibility", "FloorResult", "ObligationResult", "assess", "settled_by_round"]


@dataclass(frozen=True)
class ObligationResult:
    id: str
    due_h: int
    amount_minor: int
    met: bool
    short_minor: int | None = None
    # Outstanding past its deadline at the checkpoint: the first assessed round end, whose free
    # cash its shortfall counts.
    overdue_h: int | None = None
    # Held on another of the entity's accounts: that account, and its currency when it is not
    # the assessed account's.
    account: str | None = None
    currency: str | None = None

    @property
    def checked_h(self) -> int:
        """The hour whose free cash its shortfall counts: its deadline, or for one overdue at
        the checkpoint the first assessed round end."""
        return self.due_h if self.overdue_h is None else self.overdue_h

    def as_dict(self) -> dict:
        out = {"id": self.id, "due_h": self.due_h, "amount_minor": self.amount_minor,
               "met": self.met}
        for key in ("short_minor", "overdue_h", "account", "currency"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        return out


@dataclass(frozen=True)
class FloorResult:
    min_cash: int
    at_h: int
    short_minor: int
    breach_h: tuple[int, int] | None  # first hour below the floor, first hour back or horizon

    def as_dict(self) -> dict:
        return {"min_cash": self.min_cash, "at_h": self.at_h, "short_minor": self.short_minor,
                "breach_h": None if self.breach_h is None else list(self.breach_h)}


@dataclass(frozen=True)
class Feasibility:
    account: str
    settled: dict[int, int]  # hour -> settled at the end of the round at that hour
    obligations: tuple[ObligationResult, ...]
    floor: FloorResult
    funding_cost_minor: int
    unknown_h: tuple[int, ...] = ()  # round ends whose balance was unknown: nothing usable

    @property
    def unmet(self) -> list[ObligationResult]:
        return [o for o in self.obligations if not o.met]

    @property
    def obligations_unmet(self) -> int:
        return len(self.unmet)

    @property
    def breached(self) -> bool:
        return self.floor.breach_h is not None

    @property
    def feasible(self) -> bool:
        return not self.unmet and not self.breached

    def unknown_at(self, h: int) -> bool:
        """Whether the round end holding hour ``h`` (the round it is due in) was unknown."""
        return -(-h // ROUND_HOURS) * ROUND_HOURS in self.unknown_h

    def as_dict(self) -> dict:
        return {"account": self.account, "settled": {str(h): v for h, v in self.settled.items()},
                "obligations": [o.as_dict() for o in self.obligations],
                "floor": self.floor.as_dict(), "obligations_unmet": self.obligations_unmet,
                "funding_cost_minor": self.funding_cost_minor, "feasible": self.feasible,
                "unknown_h": list(self.unknown_h)}


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def settled_by_round(store: Any, account: str, rounds: range) -> dict[int, int]:
    """Settled at the end of each round of ``rounds``, keyed by its hour."""
    with store.reading() as c:
        rows = c.execute(
            select(journals.c.round, func.sum(postings.c.amount_minor))
            .join(journals, journals.c.journal_id == postings.c.journal_id)
            .where(postings.c.account_id == account)
            .group_by(journals.c.round)).all()
    by_round = {r: int(total) for r, total in rows}
    so_far = sum(v for r, v in by_round.items() if r < rounds.start)
    out = {}
    for r in rounds:
        so_far += by_round.get(r, 0)
        out[r * ROUND_HOURS] = so_far
    return out


def _expense(store: Any, entity: str, after_round: int) -> int:
    with store.reading() as c:
        total = c.execute(
            select(func.coalesce(func.sum(postings.c.amount_minor), 0))
            .join(journals, journals.c.journal_id == postings.c.journal_id)
            .join(accounts, accounts.c.account_id == postings.c.account_id)
            .where(accounts.c.entity_id == entity, accounts.c.kind == "expense",
                   journals.c.round > after_round)).scalar()
    return int(total)


def _paid_round(store: Any, ob: Mapping) -> int | None:
    """The round of the journal that paid ``ob``, None when the ledger names none.

    Paid from its own hold or free cash, the journal is ``settle:<obligation>``; paid through a
    reservation committed beforehand, it is the settled flow's ``settle:<flow>``.
    """
    names = [f"settle:{ob['obligation_id']}"]
    with store.reading() as c:
        if ob["reservation_id"]:
            names += [f"settle:{f}" for f in c.execute(select(expected_flows.c.flow_id).where(
                expected_flows.c.reservation_id == ob["reservation_id"],
                expected_flows.c.state == "settled")).scalars()]
        ids = [bounded_id(journals.c.journal_id, n) for n in names]
        return c.execute(select(func.min(journals.c.round))
                         .where(journals.c.journal_id.in_(ids))).scalar()


def _check(account: str, rounds: range, observability: Mapping[int, str]) -> None:
    missing = [r for r in rounds if r not in observability]
    if missing:
        raise ValueError(f"no observability of {account} recorded for rounds {missing}")
    odd = {r: observability[r] for r in rounds if observability[r] not in ("known", "unknown")}
    if odd:
        raise ValueError(f"observability of {account} is known or unknown, not {odd}")


def assess(world: Any, account: str, *, from_round: int, to_round: int,
           observability: Mapping[int, str],
           observability_of: Mapping[str, Mapping[int, str]] | None = None) -> Feasibility:
    """The branch's realised outcome on ``account`` over the rounds after ``from_round`` through
    ``to_round`` (the horizon). ``world`` is a branch's world, or the ``Branch`` holding it;
    ``observability`` is the account's at the end of each of those rounds, and
    ``observability_of`` the same for the entity's other cash accounts (one not recorded there
    is read as it is now, for every round)."""
    world = getattr(world, "world", world)
    store, epoch = world.store, world.clock.epoch
    if to_round <= from_round:
        raise ValueError(f"nothing to assess between rounds {from_round} and {to_round}")
    rounds = range(from_round + 1, to_round + 1)
    _check(account, rounds, observability)
    view = store.view(account)
    settled = settled_by_round(store, account, rounds)
    unknown = {r * ROUND_HOURS for r in rounds if observability[r] == "unknown"}
    usable = {h: min(v, 0) if h in unknown else v for h, v in settled.items()}

    held = {account: (view, settled, unknown)}  # account -> its view, settled, unknown hours
    for a in store.rows("accounts"):
        other = a["account_id"]
        if a["entity_id"] != view.entity_id or a["kind"] != "cash" or other == account:
            continue
        other_view = store.view(other)
        seen = (observability_of or {}).get(other) or {r: other_view.observability
                                                        for r in rounds}
        _check(other, rounds, seen)
        held[other] = (other_view, settled_by_round(store, other, rounds),
                       {r * ROUND_HOURS for r in rounds if seen[r] == "unknown"})

    obligations = []
    rows = [r for r in store.rows("obligations") if r["account_id"] in held]
    for ob in sorted(rows, key=lambda r: (_aware(r["due_at"]), r["obligation_id"])):
        where = ob["account_id"]
        own_view, own_settled, own_unknown = held[where]
        elsewhere = {} if where == account else {
            "account": where,
            "currency": None if own_view.currency == view.currency else own_view.currency}
        due_h = due_hour(_aware(ob["due_at"]), epoch)
        due_round = -(-due_h // ROUND_HOURS)
        if due_round > to_round:
            continue
        overdue = due_round <= from_round  # due by the checkpoint, before any assessed round
        paid = _paid_round(store, ob)
        # Paid by its due round, or for an overdue one by the checkpoint. No journal it can name:
        # met before the ledger opened (a snapshot), or settled under a journal id its caller
        # chose. Only then does the state the ledger left decide.
        met = paid <= max(due_round, from_round) if paid is not None else ob["state"] == "met"
        if met:  # an overdue one met by the checkpoint is history, not the branch's outcome
            if not overdue:
                obligations.append(ObligationResult(ob["obligation_id"], due_h,
                                                    ob["amount_minor"], True, **elsewhere))
            continue
        # Its first chance in the branch: its due round, or for an overdue one the first round.
        first_h = max(due_round, rounds.start) * ROUND_HOURS
        later = sum(o["amount_minor"] for o in rows
                    if o["reservation_id"] and o["obligation_id"] != ob["obligation_id"]
                    and o["account_id"] == where and _aware(o["due_at"]) > _aware(ob["due_at"]))
        # Paid there, late: the cash then is read before it went out, and an unknown round end
        # still counts none of it.
        then = own_settled[first_h] + (ob["amount_minor"]
                                       if paid == first_h // ROUND_HOURS else 0)
        free = (min(then, 0) if first_h in own_unknown else then) - later - own_view.pledged_minor
        # Paid late from cash that was there then (a committed flow landing after its due round,
        # an overdue one paid at its first chance) is unmet with nothing short.
        obligations.append(ObligationResult(
            ob["obligation_id"], due_h, ob["amount_minor"], False,
            max(0, ob["amount_minor"] - max(0, free)), overdue_h=first_h if overdue else None,
            **elsewhere))

    floor = view.floor_minor or 0
    series = list(usable.items())
    min_cash = min(v for _, v in series)
    at_h = next(h for h, v in series if v == min_cash)
    first = next((h for h, v in series if v < floor), None)
    breach = None
    if first is not None:
        back = next((h for h, v in series if h > first and v >= floor), to_round * ROUND_HOURS)
        breach = (first, back)
    return Feasibility(
        account=account, settled=settled, obligations=tuple(obligations),
        floor=FloorResult(min_cash, at_h, max(0, floor - min_cash), breach),
        funding_cost_minor=_expense(store, view.entity_id, from_round), unknown_h=tuple(sorted(unknown)))

"""The observed-state screens: Overview, Treasury and Lending, as C6 bodies.

Every figure is read from the observed ledger store through the finance module (S and P from
`spendability`, K_p from `lending.capacity`); nothing here recomputes money of its own. A metric
carries its status: an unknown balance has no value (never 0), a stale one keeps its value and
says so, a figure nothing has observed yet is `unassessed`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ...finance import contracts
from ...finance.lending import capacity
from ...finance.models import HORIZON
from ...finance.schemas import Snapshot
from ...finance.spendability import (
    AccountView,
    projected_cash,
    spendability,
    state_of,
)
from ...finance.store import LedgerStore, _aware

Body = dict[str, Any]


def iso(when: datetime | None) -> str | None:
    return None if when is None else when.isoformat()


def metric(minor: int | None, currency: str, status: str, as_of: datetime | None = None) -> Body:
    """A C6 metric: a value only when known or stale."""
    return {"minor": minor if status in ("known", "stale") else None, "currency": currency,
            "status": status, "as_of": iso(as_of)}


def _worst(states: list[str]) -> str:
    for s in ("unknown", "stale"):
        if s in states:
            return s
    return "known"


def treasury_entity(snapshot: Snapshot) -> str:
    return next(e.entity_id for e in snapshot.entities if e.kind == "treasury")


def cash_accounts(store: LedgerStore, entity: str) -> list[AccountView]:
    return [store.view(r["account_id"]) for r in store.rows("accounts")
            if r["entity_id"] == entity and r["kind"] == "cash"]


def _sum_metric(views: list[AccountView], now: datetime, value) -> Body:
    """One metric over accounts of one currency: unknown when any is, stale when any is."""
    currency = views[0].currency
    states = [state_of(v, now) for v in views]
    status = _worst(states)
    total = None if status == "unknown" else sum(value(v) for v in views)
    return metric(total, currency, status, min(v.as_of for v in views))


def _primary(store: LedgerStore, snapshot: Snapshot) -> tuple[str, list[AccountView]]:
    entity = treasury_entity(snapshot)
    views = cash_accounts(store, entity)
    if not views:
        raise LookupError(f"treasury {entity} holds no cash account")
    currency = views[0].currency
    return entity, [v for v in views if v.currency == currency]


def _completeness(store: LedgerStore, now: datetime) -> Body:
    """The cash accounts that are not current, each with its reason: a stale account was
    observed (and keeps its value), an unknown one was not."""
    views = sorted((store.view(r["account_id"]) for r in store.rows("accounts")
                    if r["kind"] == "cash"), key=lambda v: v.account_id)
    accounts = [{"account_id": v.account_id, "status": state,
                 "as_of": iso(v.as_of) if state == "stale" else None}
                for v in views if (state := state_of(v, now)) != "known"]
    return {"status": "partial" if accounts else "complete",
            "missing": [a["account_id"] for a in accounts], "accounts": accounts}


def _pool(store: LedgerStore) -> str | None:
    pools = store.rows("lending_pools")
    return pools[0]["pool_entity_id"] if pools else None


def _pool_capacity(store: LedgerStore, pool: str, now: datetime) -> tuple[Any, str]:
    """K_p of ``pool`` and its status: stale when any of the pool's cash accounts is."""
    cap = capacity(store, pool, now)
    stale = any(state_of(v, now) == "stale" for v in cash_accounts(store, pool))
    return cap, "stale" if stale else "known"


def _capacity_metric(store: LedgerStore, pool: str | None, now: datetime,
                     currency: str) -> Body:
    if pool is None:
        return metric(None, currency, "unassessed")
    cap, status = _pool_capacity(store, pool, now)
    return metric(cap.K_p, cap.currency, status, now)


def _combined_low(views: list[AccountView], now: datetime,
                  horizon: timedelta = HORIZON) -> tuple[int, datetime]:
    """The lowest P of the accounts together over the horizon, and when it is first reached;
    P moves only at a flow's or an obligation's time, so only those times are evaluated."""
    end = now + horizon
    times = sorted({now, *(x.at for v in views
                           for x in v.pending_in + v.pending_out + v.obligations
                           if now < x.at <= end)})
    return min(((sum(projected_cash(v, t) for v in views), t) for t in times),
               key=lambda pair: pair[0])


# ---------------------------------------------------------------------------- Overview

def overview(store: LedgerStore, snapshot: Snapshot, now: datetime, demo: Body) -> Body:
    entity, views = _primary(store, snapshot)
    currency = views[0].currency
    cash = _sum_metric(views, now, lambda v: v.settled_minor)
    spendable = _sum_metric(views, now, lambda v: spendability(v, now, now).value or 0)
    status = cash["status"]
    low, at = (None, None) if status == "unknown" else _combined_low(views, now)
    floor_minor = sum(v.floor_minor or 0 for v in views)
    floor_known = any(v.floor_minor is not None for v in views)
    floor = metric(floor_minor, currency, "known" if floor_known else "unassessed")
    headroom = metric(None if low is None else low - floor_minor, currency,
                      status if floor_known else "unassessed")
    outflows = [
        {"obligation_id": o["obligation_id"], "kind": o["kind"],
         "amount": {"minor": o["amount_minor"], "currency": o["currency"]},
         "due_at": iso(_aware(o["due_at"])), "reserved": o["reservation_id"] is not None}
        for o in sorted(store.rows("obligations"), key=lambda o: (o["due_at"], o["obligation_id"]))
        if o["entity_id"] == entity and o["state"] == "open" and _aware(o["due_at"]) >= now
    ]
    return {
        "snapshot_id": snapshot.snapshot_id, "cash": cash, "spendable": spendable,
        "upcoming_outflows": outflows,
        "coverage": {"min_projected": metric(low, currency, status, now), "at": iso(at),
                     "floor": floor, "headroom": headroom},
        "lender_capacity": _capacity_metric(store, _pool(store), now, currency),
        "completeness": _completeness(store, now), "demo": demo,
    }


# ---------------------------------------------------------------------------- Treasury

def _flow(f: Any, currency: str) -> Body:
    return {"flow_id": f.flow_id, "amount": {"minor": f.amount_minor, "currency": currency},
            "expected_at": iso(f.at), "kind": f.kind, "reservation_id": f.reservation_id}


def treasury_account(view: AccountView, now: datetime, horizon: timedelta = HORIZON) -> Body:
    state = state_of(view, now)
    known = view.observability == "known"
    c = view.currency
    s = spendability(view, now, now)
    events = sorted({now, *(x.at for x in view.pending_in + view.pending_out + view.obligations
                            if now < x.at <= now + horizon)})
    return {
        "id": view.account_id, "entity": view.entity_id, "currency": c, "kind": view.kind,
        "floor": None if view.floor_minor is None else metric(view.floor_minor, c, "known"),
        "observability": view.observability, "as_of": iso(view.as_of),
        "buckets": {
            "settled": {"minor": view.settled_minor, "currency": c} if known else None,
            "reserved": {"minor": view.reserved_minor, "currency": c},
            "pledged": {"minor": view.pledged_minor, "currency": c},
            "pending_in": [_flow(f, c) for f in view.pending_in],
            "pending_out": [_flow(f, c) for f in view.pending_out],
        },
        "spendable": metric(s.value, c, s.state, view.as_of),
        "authority": s.authority,
        "projected": [{"t": iso(t), "value": metric(projected_cash(view, t), c, state)}
                      for t in events],
    }


def treasury(store: LedgerStore, snapshot: Snapshot, now: datetime) -> Body:
    entity = treasury_entity(snapshot)
    obligations = [
        {"obligation_id": o["obligation_id"], "entity": o["entity_id"],
         "account": o["account_id"],
         "amount": {"minor": o["amount_minor"], "currency": o["currency"]},
         "due_at": iso(_aware(o["due_at"])), "kind": o["kind"], "mandatory": o["mandatory"],
         "reservation_id": o["reservation_id"], "state": o["state"]}
        for o in store.rows("obligations") if o["entity_id"] == entity]
    return {"snapshot_id": snapshot.snapshot_id,
            "accounts": [treasury_account(v, now) for v in cash_accounts(store, entity)],
            "obligations": obligations}


# ----------------------------------------------------------------------------- Lending

def _observed_revenue(store: LedgerStore, facility_id: str, now: datetime,
                      currency: str) -> Body:
    seen = [r for r in store.rows("revenue_observations")
            if r["facility_id"] == facility_id and _aware(r["observed_at"]) <= now]
    if not seen:
        return metric(None, currency, "unassessed")
    last = max(seen, key=lambda r: r["period_end"])
    return metric(last["revenue_minor"], currency, "known", _aware(last["observed_at"]))


def lending(store: LedgerStore, snapshot: Snapshot, now: datetime) -> Body | None:
    pool = _pool(store)
    if pool is None:
        return None
    cap, status = _pool_capacity(store, pool, now)
    c = cap.currency
    parts = {k: metric(getattr(cap.parts, k), c, "known", now)
             for k in ("settled_known", "committed_undrawn", "pledged", "obligations_due",
                       "floor")}
    facilities = []
    for f in contracts.pool_facilities(store, pool):
        outstanding = contracts.outstanding_minor(store, f)
        facilities.append({
            "facility_id": f.facility_id, "kind": f.kind, "borrower": f.borrower,
            "principal": {"minor": f.limit_minor, "currency": f.currency},
            "fee": {"minor": f.fee_minor, "currency": f.currency},
            "owed": {"minor": f.owed_minor if f.kind == "revenue_advance" else outstanding,
                     "currency": f.currency},
            "observed_revenue": _observed_revenue(store, f.facility_id, now, f.currency),
            "outstanding": {"minor": outstanding, "currency": f.currency},
            "state": f.state,
        })
    return {"snapshot_id": snapshot.snapshot_id, "pool": pool,
            "capacity": {"K_p": metric(cap.K_p, c, status, now), "authority": cap.authority,
                         "parts": parts},
            "facilities": facilities}

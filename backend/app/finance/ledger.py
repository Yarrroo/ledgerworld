"""The ledger's rules: clearing an outflow, mandatory settlement, loading a C5 snapshot.

The model proposes; the ledger and the rules decide (system brief §1, §5). A discretionary
outflow clears only if it is within S(now) and within the floor headroom on P over the horizon;
an execution needs a known, fresh balance. A due obligation settles from its reservation without
any actor acting on it: an obligation is never removed by inaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, insert, select

from .models import (
    HORIZON,
    Journal,
    LedgerRefusal,
    Posting,
    expected_flows,
    lending_pools,
    obligations,
)
from .schemas import CommittedLine, Snapshot
from .spendability import AccountView, headroom, spendability, state_of
from .store import LedgerStore, _naive, minor_amount


def check_outflow(view: AccountView, amount_minor: int, now: datetime,
                  horizon: timedelta = HORIZON) -> LedgerRefusal | None:
    """None when a discretionary outflow of `amount_minor` at `now` clears, else the refusal.

    Called by the coordinator when it clears an intent and by the gateway before a leg.
    """
    try:
        amount = minor_amount(amount_minor, positive=True)
    except LedgerRefusal as refusal:
        return refusal
    state = state_of(view, now)
    if state == "unknown":
        return LedgerRefusal("unknown_balance", account=view.account_id)
    if state == "stale":
        return LedgerRefusal("stale_balance", account=view.account_id,
                             as_of=view.as_of.isoformat())
    s_now = spendability(view, now, now).value
    if amount > s_now:
        return LedgerRefusal("insufficient_spendable", account=view.account_id, amount=amount,
                             S_now=s_now)
    room = headroom(view, now, horizon)
    if amount > room.value:
        return LedgerRefusal("breaks_floor", account=view.account_id, amount=amount,
                             headroom=room.value, binding_t=room.binding_t.isoformat(),
                             floor=view.floor_minor or 0)
    return None


def pay(store: LedgerStore, account_id: str, amount_minor: int, *, to_account: str,
        now: datetime, journal_id: str, round: int = 0, source_intent_id: str | None = None,
        source_leg_id: str | None = None, horizon: timedelta = HORIZON,
        conn: Connection | None = None) -> Journal:
    """Check and post a discretionary payment in one transaction; raises the refusal."""
    with store.transaction(conn) as c:
        refusal = check_outflow(store.view(account_id, conn=c), amount_minor, now, horizon)
        if refusal is not None:
            raise refusal
        return store.apply(Journal(
            journal_id=journal_id, kind="payment", round=round, sim_time=now,
            source_intent_id=source_intent_id, source_leg_id=source_leg_id,
            postings=(Posting(account_id, -amount_minor), Posting(to_account, amount_minor))),
            conn=c)


def settle_due(store: LedgerStore, now: datetime, *, round: int = 0,
               conn: Connection | None = None) -> list[Journal]:
    """The round's mandatory settlements (system brief §7.2 step 8), in one transaction.

    Expire lapsed holds; land every pending flow due by `now` (arrivals before payments); pay
    every open obligation due by `now` from its reservation, or from free cash when it has none;
    an unreserved obligation the cash cannot cover is marked missed, never dropped.
    """
    done: list[Journal] = []
    with store.transaction(conn) as c:
        store.expire_due(now, conn=c)
        for direction in ("in", "out"):
            for flow in _due_flows(store, c, direction, now):
                outside = store.external_account(flow.currency, conn=c)
                done.append(store.settle_flow(flow.flow_id, counterparty=outside, at=now,
                                              round=round, conn=c))
        due = c.execute(select(obligations).where(
            obligations.c.state == "open", obligations.c.due_at <= _naive(now))
            .order_by(obligations.c.due_at, obligations.c.obligation_id)).all()
        for ob in due:
            outside = store.external_account(ob.currency, conn=c)
            reservation_id = ob.reservation_id
            held = reservation_id and store.reservation(reservation_id, conn=c).state == "held"
            if not held:
                try:
                    reservation_id = store.hold(ob.account_id, ob.amount_minor, now=now,
                                                purpose=ob.kind[:32], conn=c)
                except LedgerRefusal:
                    store.set_obligation_state(ob.obligation_id, "missed", conn=c)
                    continue
                c.execute(obligations.update()
                          .where(obligations.c.obligation_id == ob.obligation_id)
                          .values(reservation_id=reservation_id))
            store.commit(reservation_id, due_at=now, flow_id=f"out:{ob.obligation_id}",
                         kind=ob.kind[:32], conn=c)
            done.append(store.settle(reservation_id, to_account=outside, at=now,
                                     journal_id=f"settle:{ob.obligation_id}", round=round,
                                     conn=c))
    return done


def from_snapshot(store: LedgerStore, snapshot: Snapshot | dict) -> None:
    """Load a C5 snapshot into an empty store, in one transaction.

    Settled opens as a journal against `<account>:opening`, so settled stays Σ postings. The
    reserved bucket is split into the named holds of obligations and committed lines, and the
    rest is one hold `<account>:reserved`; the pledged bucket is one pledge
    `<account>#snapshot`. A pending flow carrying a reservation is a committed reservation.
    """
    snap = snapshot if isinstance(snapshot, Snapshot) else Snapshot.model_validate(snapshot)
    as_of = snap.as_of
    named: dict[str, list[tuple[str, int, str]]] = {}
    for ob in snap.obligations:
        if ob.reservation_id:
            named.setdefault(ob.account, []).append((ob.reservation_id, ob.amount.minor, ob.kind))
    for contract in snap.contracts:
        if isinstance(contract, CommittedLine) and contract.reservation_id and contract.reserved_on:
            undrawn = contract.limit.minor - contract.drawn.minor
            if undrawn:
                named.setdefault(contract.reserved_on, []).append(
                    (contract.reservation_id, undrawn, "committed_line"))
    with store.transaction() as c:
        for e in snap.entities:
            store.add_entity(e.entity_id, e.name, e.kind, synthetic=e.synthetic, conn=c)
        for p in snap.pools:
            c.execute(insert(lending_pools).values(
                pool_entity_id=p.entity, currency=p.floor.currency, floor_minor=p.floor.minor))
        for a in snap.accounts:
            _load_account(store, c, a, as_of, named.get(a.id, []))
        for ob in snap.obligations:
            store.add_obligation(ob.obligation_id, ob.account, ob.amount.minor, ob.due_at,
                                 kind=ob.kind, reservation_id=ob.reservation_id,
                                 mandatory=ob.mandatory, state=ob.state, conn=c)


def _load_account(store: LedgerStore, c: Connection, a, as_of: datetime,
                  named: list[tuple[str, int, str]]) -> None:
    b = a.buckets
    store.open_account(a.id, a.entity, a.currency, kind=a.kind, venue=a.venue,
                       floor_minor=a.floor.minor if a.floor else None,
                       observability=a.observability, as_of=a.as_of, conn=c)
    if b.settled is not None and b.settled.minor:
        opening = f"{a.id}:opening"
        store.open_account(opening, a.entity, a.currency, kind="external", as_of=a.as_of, conn=c)
        store.apply(Journal(journal_id=f"open:{a.id}", kind="opening", sim_time=as_of,
                            postings=(Posting(a.id, b.settled.minor),
                                      Posting(opening, -b.settled.minor))), conn=c)
    for flow in b.pending_out:
        if flow.reservation_id:
            store.hold(a.id, flow.amount.minor, now=as_of, reservation_id=flow.reservation_id,
                       purpose=flow.kind[:32], conn=c)
            store.commit(flow.reservation_id, due_at=flow.expected_at, flow_id=flow.flow_id,
                         kind=flow.kind[:32], conn=c)
        else:
            store.expect(a.id, "out", flow.amount.minor, flow.expected_at, kind=flow.kind[:32],
                         flow_id=flow.flow_id, conn=c)
    rest = b.reserved.minor - sum(amount for _, amount, _ in named)
    if rest < 0:
        raise ValueError(f"account {a.id}: named holds exceed its reserved bucket")
    holds = [*named, *([(f"{a.id}:reserved", rest, "snapshot")] if rest else [])]
    for reservation_id, amount, purpose in holds:
        store.hold(a.id, amount, now=as_of, reservation_id=reservation_id,
                   purpose=purpose[:32], conn=c)
    if b.pledged.minor:
        store.pledge(a.id, b.pledged.minor, f"{a.id}#snapshot", conn=c)
    for flow in b.pending_in:
        store.expect(a.id, "in", flow.amount.minor, flow.expected_at, kind=flow.kind[:32],
                     flow_id=flow.flow_id, conn=c)


def _due_flows(store: LedgerStore, c: Connection, direction: str, now: datetime) -> list:
    return c.execute(select(expected_flows).where(
        expected_flows.c.direction == direction, expected_flows.c.state == "pending",
        expected_flows.c.expected_at <= _naive(now))
        .order_by(expected_flows.c.expected_at, expected_flows.c.flow_id)).all()


"""The ledger's rules: clearing an outflow, mandatory settlement, loading a C5 snapshot.

The model proposes; the ledger and the rules decide (system brief §1, §5). A discretionary
outflow clears only if it is within S(now) and within the floor headroom on P over the horizon;
an execution needs a known, fresh balance. A due obligation settles from its reservation without
any actor acting on it: an obligation is never removed by inaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, insert

from . import contracts
from .models import HORIZON, Journal, LedgerRefusal, Posting, lending_pools
from .schemas import Account, CommittedLine, Snapshot
from .spendability import AccountView, headroom, spendability, state_of
from .store import OPEN_OBLIGATION, LedgerStore, minor_amount


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
    every mandatory obligation due by `now` from its held reservation, or from free cash when it
    has none. One whose reservation is already committed waits for its pending_out flow. One the
    cash cannot cover is marked missed: still owed, still in P, and tried again next round. One
    on an unknown balance stays open: nothing observed says the cash is short.
    """
    done: list[Journal] = []
    with store.transaction(conn) as c:
        outside: dict[str, str] = {}

        def payee(currency: str) -> str:
            if currency not in outside:
                outside[currency] = store.external_account(currency, conn=c)
            return outside[currency]

        store.expire_due(now, conn=c)
        for direction in ("in", "out"):
            for flow in store.due_flows(direction, now, conn=c):
                done.append(store.settle_flow(flow.flow_id, counterparty=payee(flow.currency),
                                              at=now, round=round, conn=c))
        for ob in store.due_obligations(now, conn=c):
            reservation_id = ob.reservation_id
            state = store.reservation(reservation_id, conn=c).state if reservation_id else None
            if state == "settled":  # paid through its reservation already
                store.set_obligation_state(ob.obligation_id, "met", conn=c)
                continue
            if state == "committed":
                continue
            if state != "held":
                try:
                    reservation_id = store.hold(ob.account_id, ob.amount_minor, now=now,
                                                purpose=ob.kind, conn=c)
                except LedgerRefusal as refusal:
                    # An unknown balance is not a shortfall: the obligation waits, still open.
                    if refusal.code != "unknown_balance":
                        store.set_obligation_state(ob.obligation_id, "missed", conn=c)
                    continue
                store.attach_reservation(ob.obligation_id, reservation_id, conn=c)
            flow_id = store.commit(reservation_id, due_at=now, flow_id=f"out:{ob.obligation_id}",
                                   kind=ob.kind, conn=c)
            done.append(store.settle_flow(flow_id, counterparty=payee(ob.currency), at=now,
                                          journal_id=f"settle:{ob.obligation_id}", round=round,
                                          conn=c))
    return done


def from_snapshot(store: LedgerStore, snapshot: Snapshot | dict) -> None:
    """Load a C5 snapshot into an empty store, in one transaction.

    Settled opens as a journal against `<account>:opening`, so settled stays Σ postings. A
    pending_out flow carrying a reservation is a committed reservation. The reserved bucket is
    split into the named holds of open obligations and committed lines not already committed,
    and the rest is one hold `<account>:reserved`; the pledged bucket is one pledge
    `<account>#snapshot`. On an unknown account the buckets are taken as observed. Every contract
    becomes a facility of its lender's pool (`contracts.load`).
    """
    snap = snapshot if isinstance(snapshot, Snapshot) else Snapshot.model_validate(snapshot)
    committed = {f.reservation_id for a in snap.accounts for f in a.buckets.pending_out
                 if f.reservation_id}
    named: dict[str, list[tuple[str, int, str]]] = {}
    for ob in snap.obligations:
        if ob.reservation_id and ob.state in OPEN_OBLIGATION \
                and ob.reservation_id not in committed:
            named.setdefault(ob.account, []).append((ob.reservation_id, ob.amount.minor, ob.kind))
    for contract in snap.contracts:
        if isinstance(contract, CommittedLine) and contract.reservation_id and contract.reserved_on:
            undrawn = contract.limit.minor - contract.drawn.minor
            if undrawn and contract.reservation_id not in committed:
                named.setdefault(contract.reserved_on, []).append(
                    (contract.reservation_id, undrawn, "committed_line"))
    with store.transaction() as c:
        for e in snap.entities:
            store.add_entity(e.entity_id, e.name, e.kind, synthetic=e.synthetic, conn=c)
        for p in snap.pools:
            c.execute(insert(lending_pools).values(
                pool_entity_id=p.entity, currency=p.floor.currency, floor_minor=p.floor.minor))
        for a in snap.accounts:
            _load_account(store, c, a, snap.as_of, named.get(a.id, []))
        for ob in snap.obligations:
            store.add_obligation(ob.obligation_id, ob.account, ob.amount.minor, ob.due_at,
                                 kind=ob.kind, reservation_id=ob.reservation_id,
                                 mandatory=ob.mandatory, state=ob.state, conn=c)
        contracts.load(store, snap, conn=c)


def _load_account(store: LedgerStore, c: Connection, a: Account, as_of: datetime,
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
                       purpose=flow.kind, observed=True, conn=c)
            store.commit(flow.reservation_id, due_at=flow.expected_at, flow_id=flow.flow_id,
                         kind=flow.kind, conn=c)
        else:
            store.expect(a.id, "out", flow.amount.minor, flow.expected_at, kind=flow.kind,
                         flow_id=flow.flow_id, conn=c)
    rest = b.reserved.minor - sum(amount for _, amount, _ in named)
    if rest < 0:
        raise ValueError(f"account {a.id}: named holds exceed its reserved bucket")
    holds = [*named, *([(f"{a.id}:reserved", rest, "snapshot")] if rest else [])]
    for reservation_id, amount, purpose in holds:
        store.hold(a.id, amount, now=as_of, reservation_id=reservation_id, purpose=purpose,
                   observed=True, conn=c)
    if b.pledged.minor:
        store.pledge(a.id, b.pledged.minor, f"{a.id}#snapshot", observed=True, conn=c)
    for flow in b.pending_in:
        store.expect(a.id, "in", flow.amount.minor, flow.expected_at, kind=flow.kind,
                     flow_id=flow.flow_id, conn=c)

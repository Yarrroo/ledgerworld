"""The execution gateway: the only door from a bound approval (C3) to provider money.

`Gateway(store, client, ...)` runs on the observed ledger store and keeps the rules of
design/modules/execution/HANDOFF.md:

- `record(approval)` stores what `approval.bind` returned; `execute(presented, ...)` verifies the
  presented approval against it (`approval.verify`), then runs the ledger-backed preflight over
  every leg: ownership, the beneficiary allowlist, the exact held reservation, a known and fresh
  balance, `check_outflow` (K_p as well for an advance) and, in sandbox mode, the provider
  wallet. Any refusal refuses the whole approval and writes nothing.
- An accepted approval is marked used, its legs are queued and their ledger effects (a committed
  reservation, a pending flow) are written in one transaction; then the outbox drives the legs.
- The outbox and the ledger share one store connection and one transaction, so a leg settles
  and its journal posts together (`Outbox(transaction=...)`).
- `ConnectorProvider` adapts the Airwallex client to the outbox's `Provider`: a duplicate id or a
  409 is adopted by lookup, a timeout is unknown and looked up before any resend under the same
  id, and the truth of a leg is a `GET` by its provider id.

Mode A (connected accounts) and Mode B (fallback) take their operation and receipt label from the
connector's `leg_plan`. A Mode B deposit carries no `request_id`, so its reference carries the leg
id; the client has no deposit list or GET, so an unknown deposit stays unknown for the operator.
"""

from __future__ import annotations

from app.execution.boundary import require_execution

require_execution()

from collections import defaultdict
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import quote as urlquote

from app.connectors.airwallex import client as aw
from app.connectors.airwallex.errors import AirwallexError, DuplicateRequest, OutcomeUnknown
from app.connectors.airwallex.errors import ProviderError as ProviderRefusal
from app.execution import approval as binding
from app.execution import outbox as ob
from app.finance import contracts, lending
from app.finance.contracts import Facility
from app.finance.ledger import check_outflow
from app.finance.models import (
    Journal,
    LedgerRefusal,
    Posting,
    UnknownAccount,
    bounded_id,
    expected_flows,
    journals,
    reservations,
    revenue_observations,
)
from app.finance.schemas import EXPONENT, ApprovalLeg, BoundApproval, Mode, Money
from app.finance.spendability import AccountView, spendability, state_of
from app.finance.store import LedgerStore, _naive
from sqlalchemy import Connection, select, text, update

# Beside the design's `approvals`: the bound terms, to compare a presented approval against and
# to give a restarted gateway each leg's facility and target currency.
TERMS_DDL = """
CREATE TABLE IF NOT EXISTS approval_terms (
    approval_id  VARCHAR(64) PRIMARY KEY REFERENCES approvals (approval_id),
    terms        TEXT NOT NULL
)
"""
# The leg kinds whose provider operation takes money out of the platform wallet, by mode.
DEBITS_WALLET = frozenset({("payout", "A"), ("payout", "B"), ("fx", "A"), ("fx", "B"),
                           ("advance", "A")})
LEDGER_CODES = frozenset({"stale_balance", "unknown_balance", "breaks_floor",
                          "insufficient_spendable"})


@dataclass(frozen=True)
class Execution:
    """An accepted approval: its id is the execution id, and its legs as the outbox left them."""

    execution_id: str
    legs: list[ob.Leg]
    ok: ClassVar[bool] = True


def _utc_now() -> datetime:
    return datetime.now(UTC)


def collection(kind: str, leg_mode: str) -> tuple[str, str]:
    """The provider object kind and its collection path for a leg kind in a mode."""
    if kind == "advance":
        if leg_mode == "A":
            return "connected_account_transfer", "/api/v1/connected_account_transfers"
        return "deposit", "/api/v1/deposits"
    if kind == "repayment":
        return "charge", "/api/v1/charges"
    if kind == "fx":
        return "conversion", aw.CONVERSIONS_PATH
    return "transfer", "/api/v1/transfers"


def deposit_reference(leg: ob.Leg) -> str:
    """A Mode B deposit's reference: its receipt label and the leg id it belongs to."""
    return f"{leg.receipt_label} {leg.request_id}"


# ---------------------------------------------------------------------------- the provider


class ConnectorProvider:
    """The outbox's `Provider` over the Airwallex client, one operation per leg kind and mode.

    `seen` keeps the last provider object read for each leg, so the settle journal (an fx leg's
    buy side) is built from what the `GET` showed."""

    def __init__(
        self,
        client: aw.AirwallexClient,
        leg_mode: aw.LegMode,
        *,
        target: Callable[[ob.Leg], str],
        connected_account: str | None = None,
        global_account_id: str | None = None,
    ) -> None:
        self.client = client
        self.leg_mode = leg_mode
        self.target = target  # an fx leg's buy currency, from the approval's stored terms
        self.connected_account = connected_account
        self.global_account_id = global_account_id
        self.seen: dict[str, aw.ProviderObject] = {}

    def send(self, leg: ob.Leg) -> ob.ProviderObject:
        amount = Money(minor=leg.amount_minor, currency=leg.currency)
        rid = leg.request_id
        try:
            match (leg.kind, self.leg_mode):
                case ("advance", "A"):
                    obj = self.client.connected_account_transfer(
                        rid, amount=amount, destination=self._connected())
                case ("advance", "B"):
                    obj = self.client.simulate_deposit(
                        amount=amount, global_account_id=self._global_account(leg.currency),
                        reference=deposit_reference(leg))
                case ("repayment", "A"):
                    obj = self.client.charge(rid, amount=amount, source=self._connected())
                case ("fx", _):
                    buy = self.target(leg)
                    quote = self.client.quote(sell_currency=leg.currency, buy_currency=buy,
                                              amount=amount)
                    obj = self.client.create_conversion(
                        rid, sell_currency=leg.currency, buy_currency=buy, amount=amount,
                        quote_id=quote.get("quote_id") if isinstance(quote, dict) else None)
                case ("payout", mode):
                    obj = self.client.create_transfer(
                        rid, beneficiary_id=leg.counterparty, amount=amount,
                        reference=leg.receipt_label,
                        on_behalf_of=self._connected() if mode == "A" else None)
                case _:
                    raise ob.Rejected(f"{leg.kind} has no provider operation in Mode "
                                      f"{self.leg_mode}")
        except DuplicateRequest as duplicate:
            raise ob.DuplicateRequest(str(duplicate)) from None
        except OutcomeUnknown as unknown:  # the client says "timeout" only when nothing left
            raise ob.OutcomeUnknown(unknown.reason != "timeout", unknown.reason) from None
        except ProviderRefusal as refused:
            if refused.retryable:  # throttled or unreachable: the request was not taken
                raise ob.OutcomeUnknown(False, refused.code) from None
            raise ob.Rejected(refused.code) from None
        try:
            return self._ours(leg, obj)
        except ob.LookupFailed as unreadable:  # accepted, but unreadable: it may have moved
            raise ob.OutcomeUnknown(True, str(unreadable)) from None

    def find(self, leg: ob.Leg) -> list[ob.ProviderObject]:
        kind, path = collection(leg.kind, self.leg_mode)
        if kind == "deposit":
            raise ob.LookupFailed("the deposit simulation has no list by request_id")
        try:
            if kind == "transfer":
                found = self.client.find_transfer(leg.request_id)
            elif kind == "conversion":
                found = self.client.find_conversion(leg.request_id)
            else:
                found = self.client._find(kind, path, leg.request_id)
            return [self._ours(leg, obj) for obj in found]
        except AirwallexError as failed:
            raise ob.LookupFailed(str(failed)) from None

    def get(self, leg: ob.Leg) -> ob.ProviderObject:
        kind, path = collection(leg.kind, self.leg_mode)
        if leg.provider_id is None:
            raise ob.LookupFailed(f"{leg.leg_id} has no provider id")
        if kind == "deposit":  # no GET either: the create answer is all there is
            obj = self.seen.get(leg.leg_id)
            if obj is None or obj.provider_id != leg.provider_id:
                raise ob.LookupFailed("the deposit simulation has no GET")
            return self._ours(leg, obj)
        try:
            return self._ours(leg, self.get_object(kind, path, leg.provider_id))
        except AirwallexError as failed:
            raise ob.LookupFailed(str(failed)) from None

    def get_object(self, kind: str, path: str, provider_id: str) -> aw.ProviderObject:
        """`GET` one provider object by its id: reconciliation's truth."""
        if kind == "transfer":
            return self.client.get_transfer(provider_id)
        if kind == "conversion":
            return self.client.get_conversion(provider_id)
        raw = self.client._request("GET", f"{path}/{urlquote(provider_id, safe='')}")
        return aw.ProviderObject.parse(kind, raw)

    def list_all(self, kind: str, path: str) -> list[aw.ProviderObject]:
        """Every object of a kind the provider holds, for the sweep's orphan check."""
        answer = self.client._request("GET", path)
        return [aw.ProviderObject.parse(kind, item) for item in self.client._items(answer)]

    def _ours(self, leg: ob.Leg, obj: aw.ProviderObject) -> ob.ProviderObject:
        """The connector's object in the leg's terms; a deposit's id comes from its reference."""
        request_id = obj.request_id or ""
        if obj.kind == "deposit":
            reference = obj.raw.get("reference")
            request_id = leg.request_id if reference == deposit_reference(leg) else ""
        if obj.amount is None or obj.currency not in EXPONENT:
            raise ob.LookupFailed(f"{obj.kind} {obj.provider_id} shows no amount")
        if request_id == leg.request_id:
            self.seen[leg.leg_id] = obj
        return ob.ProviderObject(obj.provider_id, request_id, obj.status or "",
                                 aw.to_money(obj.amount, obj.currency).minor, obj.currency,
                                 tuple(obj.raw_keys))

    def _connected(self) -> str:
        if not self.connected_account:
            raise ob.Rejected("Mode A needs the connected account id")
        return self.connected_account

    def _global_account(self, currency: str) -> str:
        if self.global_account_id:
            return self.global_account_id
        if found := self.client.global_account_in(currency):
            self.global_account_id = found
            return found
        raise ob.Rejected(f"no Global Account in {currency} for the Mode B advance")


# ----------------------------------------------------------------------------- the gateway


@dataclass
class _Claims:
    """What the legs of one approval checked so far already claim (`Gateway.preflight`)."""

    spend: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    owed: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    drawing: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))  # K_p
    advancing: set[str] = field(default_factory=set)  # facilities this approval disburses
    repaying: set[str] = field(default_factory=set)  # facilities this approval repays
    holding: set[str] = field(default_factory=set)  # reservations a leg already spends


class _Rows:
    """Materialize a result before its pooled connection is returned."""

    def __init__(self, result: Any) -> None:
        self.rowcount = result.rowcount
        names = result.keys() if result.returns_rows else ()
        self.description = [(name,) for name in names] if result.returns_rows else None
        self._rows = iter([tuple(row) for row in result] if result.returns_rows else [])
        result.close()

    def __iter__(self):
        return self._rows

    def fetchone(self):
        return next(self._rows, None)

    def fetchall(self):
        return list(self._rows)


class _StoreConnection:
    """The execution SQL joins the same SQLAlchemy transaction as ledger writes.

    The private queries use qmark binds; SQLAlchemy renders the driver's parameter style.
    No raw driver connection survives a pool checkout, and reads leave no idle transaction.
    """

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway

    def execute(self, sql: str, args: tuple = ()) -> _Rows:
        # Escape literal colons (such as ':out') before adding SQLAlchemy's named binds.
        parts = sql.replace(":", "\\:").split("?")
        if len(parts) != len(args) + 1:
            raise ValueError("execution SQL bind count does not match its arguments")
        statement = parts[0] + "".join(f":p{i}{part}" for i, part in enumerate(parts[1:]))
        with self.gateway.transaction():
            return _Rows(self.gateway.sa.execute(
                text(statement), {f"p{i}": value for i, value in enumerate(args)}))


class Gateway:
    """The execution legs of one observed ledger store, driven through one provider."""

    def __init__(
        self,
        store: LedgerStore,
        client: aw.AirwallexClient,
        *,
        mode: Mode,
        leg_mode: aw.LegMode,
        beneficiaries: Collection[str],
        clock: Callable[[], datetime] = _utc_now,
        connected_account: str | None = None,
        global_account_id: str | None = None,
        on_point: Callable[[str, ob.Leg], None] | None = None,
    ) -> None:
        self.store = store
        self.mode = mode
        self.leg_mode = leg_mode
        self.beneficiaries = frozenset(beneficiaries)
        self.clock = clock
        self.plan = {kind: ob.LegPlan(leg.label, leg.op, leg.op.startswith("none"))
                     for kind, leg in aw.leg_plan(leg_mode).items()}
        self.provider = ConnectorProvider(
            client, leg_mode, target=lambda leg: self.bound(leg).to_currency,
            connected_account=connected_account, global_account_id=global_account_id)
        proxy = store.engine.raw_connection()
        try:
            ob.install(proxy.driver_connection)
            proxy.driver_connection.execute(TERMS_DDL)
            proxy.commit()
        except BaseException:
            proxy.rollback()
            raise
        finally:
            proxy.close()
        self._sa: Connection | None = None
        self.conn = _StoreConnection(self)
        self.outbox = ob.Outbox(self.conn, self._post_journal,
                                clock=lambda: self.clock().isoformat(), on_point=on_point,
                                transaction=self.transaction)

    # -------------------------------------------------------------------- transactions

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """One ledger transaction; a nested call joins the one already open."""
        if self._sa is not None:
            yield
            return
        with self.store.engine.begin() as sa:
            self._sa = sa
            try:
                yield
            finally:
                self._sa = None

    @property
    def sa(self) -> Connection:
        if self._sa is None:
            raise RuntimeError("a ledger write outside the gateway's transaction")
        return self._sa

    # ------------------------------------------------------------------------- approvals

    def record(self, approval: BoundApproval) -> None:
        """Store a bound approval: what the approvals route does after `approval.bind`."""
        with self.transaction():
            self.conn.execute(
                "INSERT INTO approvals (approval_id, entity_id, account_id, snapshot_id,"
                " plan_hash, mode, approver, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (approval.approval_id, approval.entity, approval.account, approval.snapshot_id,
                 approval.plan_hash, approval.mode, approval.approver, self.clock().isoformat(),
                 approval.expires_at.isoformat()))
            self.conn.execute("INSERT INTO approval_terms VALUES (?, ?)",
                              (approval.approval_id, approval.model_dump_json()))

    def stored(self, approval_id: str) -> BoundApproval | None:
        row = self.conn.execute("SELECT terms FROM approval_terms WHERE approval_id = ?",
                                (approval_id,)).fetchone()
        return None if row is None else BoundApproval.model_validate_json(row[0])

    def bound(self, leg: ob.Leg) -> ApprovalLeg:
        """The C3 leg an outbox row was queued from."""
        return next(x for x in self.stored(leg.approval_id).legs if x.index == leg.index)

    def execute(
        self, presented: object, *, current_snapshot_id: str
    ) -> Execution | binding.Refusal:
        """Verify, preflight, queue and drive; a refusal writes nothing."""
        if isinstance(presented, BoundApproval):
            presented = presented.model_dump(mode="json")
        approval_id = presented.get("approval_id") if isinstance(presented, Mapping) else None
        stored = self.stored(approval_id) if isinstance(approval_id, str) else None
        now = self.clock()
        used = {r[0] for r in self.conn.execute(
            "SELECT approval_id FROM approvals WHERE used_at IS NOT NULL")}
        verdict = binding.verify(stored, presented, now, current_snapshot_id, self.mode,
                                 used=used)
        if not verdict.ok:
            return verdict
        if refusal := self.preflight(stored, now):
            return refusal
        with self.transaction():
            marked = self.conn.execute(
                "UPDATE approvals SET used_at = ? WHERE approval_id = ? AND used_at IS NULL",
                (now.isoformat(), stored.approval_id)).rowcount
            if marked != 1:
                return binding.Refusal("approval_used", f"{stored.approval_id} already executed")
            rows = self.outbox.queue(stored, {leg.index: self.plan[leg.kind]
                                              for leg in stored.legs})
            for leg, row in zip(stored.legs, rows, strict=True):
                self._at_queue(leg, row, now)
        return Execution(stored.approval_id, self.run(stored.approval_id))

    def run(self, execution_id: str) -> list[ob.Leg]:
        """Drive an execution's legs as far as the provider allows, then release failed legs."""
        self.outbox.drive(execution_id, self.provider)
        self.release_failed(execution_id)
        return self.outbox.legs(execution_id)

    def legs(self, execution_id: str) -> list[ob.Leg]:
        return self.outbox.legs(execution_id)

    def incidents(self, *, open_only: bool = False) -> list[dict[str, Any]]:
        cursor = self.conn.execute(
            "SELECT * FROM incidents" + (" WHERE closed_at IS NULL" if open_only else "")
            + " ORDER BY opened_at, incident_id")
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    # ------------------------------------------------------------------------- preflight

    def preflight(self, approval: BoundApproval, now: datetime) -> binding.Refusal | None:
        """Every leg against the ledger (and, in sandbox mode, the wallet): the first refusal.

        The legs paid from one account are checked together, so two legs cannot each pass on
        the same spendable cash: discretionary ones against S(now) and the floor headroom
        (`check_outflow`), and with the repayments, which are owed, against S(now) alone.
        Overdue arrivals add nothing (`observed_view`); one held reservation funds one leg, a
        facility disburses or repays through one leg at a time, and a pool's draws share K_p."""
        claims = _Claims()
        wallet: dict[tuple[str, bool], int] = defaultdict(int)
        for leg in approval.legs:
            if refusal := self._check_leg(approval.entity, leg, now, claims):
                return refusal
            if (leg.kind, self.leg_mode) in DEBITS_WALLET:
                on_behalf = self.leg_mode == "A" and leg.kind == "payout"
                wallet[(leg.amount.currency, on_behalf)] += leg.amount.minor
        for account_id in sorted(claims.spend.keys() | claims.owed.keys()):
            view = observed_view(self.store.view(account_id), now)
            spend = claims.spend[account_id]
            if spend:
                refusal = check_outflow(view, spend, now)
                if refusal is not None:
                    return _from_ledger(refusal, f"{account_id} pays {spend}")
            total, s_now = spend + claims.owed[account_id], spendability(view, now, now).value
            if total > s_now:
                return binding.Refusal("insufficient_spendable",
                                       f"{account_id} pays {total} of {s_now} spendable")
        return self._wallet(wallet) if self.mode == "sandbox" else None

    def _check_leg(self, entity: str, leg: ApprovalLeg, now: datetime,
                   claims: _Claims) -> binding.Refusal | None:
        source, other = self._view(leg.source), self._view(leg.counterparty)
        owner = source.entity_id if source else None
        other_owner = other.entity_id if other else None
        f = self._facility(leg.facility_id)
        if leg.kind in ("advance", "repayment"):
            if f is None or f.borrower != entity or f.currency != leg.amount.currency:
                return binding.Refusal("unowned_funds",
                                       f"leg {leg.index} names no facility of {entity}")
            payer, payee = (f.pool, entity) if leg.kind == "advance" else (entity, f.pool)
            if (owner, other_owner) != (payer, payee):
                return binding.Refusal("unowned_funds",
                                       f"leg {leg.index} does not move {payer}'s money to {payee}")
        elif owner != entity:
            return binding.Refusal("unowned_funds", f"{leg.source} is not an account of {entity}")
        if leg.kind == "payout" and leg.counterparty not in self.beneficiaries:
            return binding.Refusal("beneficiary_not_allowed",
                                   f"{leg.counterparty} is not on the beneficiary allowlist")
        if leg.kind == "fx" and (other_owner != entity or other.currency != leg.to_currency):
            return binding.Refusal("unowned_funds",
                                   f"{leg.counterparty} is not {entity}'s {leg.to_currency} account")
        if source.currency != leg.amount.currency:
            return binding.Refusal("unowned_funds", f"{leg.source} holds no {leg.amount.currency}")
        view = source
        state = state_of(view, now)
        if state != "known":
            return binding.Refusal(f"{state}_balance", f"{leg.source} is {state}")
        if leg.kind == "advance":
            if leg.amount.minor != f.limit_minor or f.state != "offered":
                return binding.Refusal("reservation_mismatch", f"{f.facility_id} disburses its "
                                       f"principal {f.limit_minor} once, while offered")
            # It stays offered until its leg settles: one already on its way is not sent again.
            if f.facility_id in claims.advancing or self._in_flight("advance", f.facility_id):
                return binding.Refusal("reservation_mismatch", f"{f.facility_id} disburses "
                                       "once; its advance is already on its way")
            claims.advancing.add(f.facility_id)
            claims.drawing[f.pool] += leg.amount.minor
            refusal = lending.check_draw(self.store, f.pool, claims.drawing[f.pool], now)
            if refusal is not None:
                return _from_ledger(refusal, f"K_p of {f.pool}")
        elif leg.kind == "repayment":
            if f.facility_id in claims.repaying or self._in_flight("repayment", f.facility_id):
                return binding.Refusal("reservation_mismatch", f"{f.facility_id} repays one "
                                       "period at a time; one is already on its way")
            claims.repaying.add(f.facility_id)
            if self.period(f, leg.amount.minor, now) is None:
                return binding.Refusal("reservation_mismatch", f"leg {leg.index} pays exactly "
                                       f"what the oldest unrepaid period of {f.facility_id} owes")
        if leg.funded_by and leg.funded_by.startswith("reservation:"):
            return self._held(leg, claims.holding)
        # A repayment is owed, not chosen: it needs S(now), and the floor does not apply.
        (claims.owed if leg.kind == "repayment" else claims.spend)[leg.source] += \
            leg.amount.minor
        return None

    def _held(self, leg: ApprovalLeg, holding: set[str]) -> binding.Refusal | None:
        reservation_id = leg.funded_by.removeprefix("reservation:")
        if reservation_id in holding:  # it is committed once, by the first leg naming it
            return binding.Refusal("reservation_mismatch", f"leg {leg.index} spends "
                                   f"{reservation_id}, which an earlier leg already spends")
        holding.add(reservation_id)
        try:
            res = self.store.reservation(reservation_id)
        except LedgerRefusal:
            res = None
        if res is None or res.state != "held" or res.account_id != leg.source \
                or (res.amount_minor, res.currency) != (leg.amount.minor, leg.amount.currency):
            return binding.Refusal("reservation_mismatch",
                                   f"leg {leg.index} spends exactly the held {reservation_id}")
        return None

    def _wallet(self, wallet: Mapping[tuple[str, bool], int]) -> binding.Refusal | None:
        """Sandbox mode: the provider wallet covers every debit, before anything is queued."""
        for on_behalf in sorted({b for _, b in wallet}):
            account = self.provider.connected_account if on_behalf else None
            try:
                held = {b.currency: b.available.minor
                        for b in self.provider.client.balances(on_behalf_of=account)}
            except AirwallexError as failed:
                return binding.Refusal("unknown_balance", f"provider balances: {failed}")
            for (currency, b), amount in sorted(wallet.items()):
                if b == on_behalf and held.get(currency, 0) < amount:
                    return binding.Refusal("insufficient_spendable", f"the provider wallet holds "
                                           f"{held.get(currency, 0)} {currency} of {amount}")
        return None

    def period(self, f: Facility, amount: int, now: datetime,
               conn: Connection | None = None) -> datetime | None:
        """The facility's oldest observed, unrepaid period that owes anything, when it owes
        exactly `amount`. A period that owes nothing (no revenue) never blocks the next."""
        if f.state != "active":
            return None
        with self.store.reading(conn) as c:
            rows = c.execute(select(revenue_observations.c.period_end,
                                    revenue_observations.c.revenue_minor).where(
                revenue_observations.c.facility_id == f.facility_id,
                revenue_observations.c.observed_at <= _naive(now))
                .order_by(revenue_observations.c.period_end)).all()
            ends = {contracts.repay_journal_id(f.facility_id, end.replace(tzinfo=UTC)): end
                    for end, _ in rows}
            repaid = set(c.execute(select(journals.c.journal_id).where(
                journals.c.journal_id.in_(ends))).scalars())
            outstanding = contracts.outstanding_minor(self.store, f, conn=c)
        for end, revenue in rows:
            if contracts.repay_journal_id(f.facility_id, end.replace(tzinfo=UTC)) in repaid:
                continue
            due = contracts.repayment_minor(revenue, f.repay_share_bps, outstanding)
            if due:
                return end.replace(tzinfo=UTC) if due == amount else None
        return None

    def _in_flight(self, kind: str, facility_id: str) -> bool:
        """A leg of this kind on the facility is already queued and not finished."""
        return any(self.bound(leg).facility_id == facility_id for leg in self.outbox._legs(
            "kind = ? AND state IN ('pending', 'submitted', 'unknown')", (kind,)))

    def _view(self, account_id: str) -> AccountView | None:
        try:
            return self.store.view(account_id)
        except LookupError:
            return None

    def _facility(self, facility_id: str | None) -> Facility | None:
        if facility_id is None:
            return None
        try:
            return contracts.facility(self.store, facility_id)
        except LookupError:
            return None

    # --------------------------------------------------------------------- ledger effects

    def _at_queue(self, leg: ApprovalLeg, row: ob.Leg, now: datetime) -> None:
        """What the ledger records the moment a leg is queued: the money it will spend is
        spoken for on its source (a committed reservation or a pending_out), and an advance is
        a pending_in to the borrower until it settles."""
        c, out = self.sa, out_flow(row.leg_id, leg.kind)
        if leg.funded_by and leg.funded_by.startswith("reservation:"):
            self.store.commit(leg.funded_by.removeprefix("reservation:"), due_at=now,
                              flow_id=out, kind=f"{leg.kind}_leg", conn=c)
        else:
            self.store.expect(leg.source, "out", leg.amount.minor, now, kind=f"{leg.kind}_leg",
                              flow_id=out, conn=c)
        if leg.kind == "advance":
            self.store.expect(leg.counterparty, "in", leg.amount.minor, now,
                              kind="advance_in_flight", flow_id=row.leg_id, conn=c)

    def _post_journal(self, _conn: object, leg: ob.Leg) -> str:
        """The leg's journal, inside the settle transaction; returns its id. A refusal by the
        ledger is the outbox's `JournalRefused` (an incident); any other error propagates."""
        try:
            return self._journal(leg)
        except (LedgerRefusal, UnknownAccount, ValueError) as refused:
            raise ob.JournalRefused(f"{type(refused).__name__}: {refused}") from refused

    def _journal(self, leg: ob.Leg) -> str:
        c, now, mode = self.sa, self.clock(), self._journal_mode()
        bound = self.bound(leg)
        if leg.kind == "payout":  # the committed flow pays out: reservation and obligation close
            return self.store.settle_flow(
                leg.leg_id, counterparty=self.store.external_account(leg.currency, conn=c),
                at=now, journal_id=bounded_id(journals.c.journal_id, f"j-{leg.leg_id}"),
                conn=c).journal_id
        self._flows(leg.leg_id, "settled")  # the journal below carries the cash itself
        if leg.kind == "advance":
            return lending.disburse(
                self.store, bound.facility_id, now=now, from_account=leg.source,
                borrower_account=leg.counterparty,
                journal_id=bounded_id(journals.c.journal_id, f"j-{bound.facility_id}-disburse"),
                mode=mode, source_leg_id=leg.leg_id, land=False, conn=c).journal_id
        if leg.kind == "repayment":
            return self._repay(bound, leg, now, mode)
        seen = self.provider.seen[leg.leg_id]  # fx: the buy side as the GET showed it
        buy = aw.to_money(seen.raw["buy_amount"], seen.raw["buy_currency"])
        if buy.currency != bound.to_currency:
            raise ValueError(f"{leg.leg_id} bought {buy.currency}, bound {bound.to_currency}")
        sold_to = self.store.external_account(leg.currency, conn=c)
        bought_from = self.store.external_account(buy.currency, conn=c)
        return self.store.apply(Journal(
            journal_id=bounded_id(journals.c.journal_id, f"j-{leg.leg_id}"), kind="fx_conversion",
            sim_time=now,
            source_leg_id=leg.leg_id, mode=mode,
            postings=(Posting(leg.source, -leg.amount_minor), Posting(sold_to, leg.amount_minor),
                      Posting(bought_from, -buy.minor), Posting(leg.counterparty, buy.minor))),
            conn=c).journal_id

    def _repay(self, bound: ApprovalLeg, leg: ob.Leg, now: datetime, mode: str) -> str:
        """The facility's oldest observed, unrepaid period, repaid in exactly the leg's amount."""
        f = contracts.facility(self.store, bound.facility_id, conn=self.sa)
        end = self.period(f, leg.amount_minor, now, conn=self.sa)
        if end is None:
            raise ValueError(f"{leg.leg_id}: no observed, unrepaid period of {f.facility_id} "
                             f"owes {leg.amount_minor}")
        paid = lending.repay(self.store, f.facility_id, end, now=now, from_account=leg.source,
                             to_account=leg.counterparty, mode=mode, source_leg_id=leg.leg_id,
                             land=False, conn=self.sa)
        if paid.journal is None or paid.amount_minor != leg.amount_minor:
            raise ValueError(f"{leg.leg_id}: the period repays {paid.amount_minor}, the leg "
                             f"{leg.amount_minor}")
        return paid.journal.journal_id

    def _journal_mode(self) -> str:
        if self.mode == "fake":
            return "fake"
        return "sandbox_simulation" if self.leg_mode == "B" else "sandbox"

    def _flows(self, leg_id: str, state: str) -> int:
        """Close the leg's pending flows (`settled` or `cancelled`) and the reservation its
        outflow committed: settled with it, or held again for its obligation when cancelled."""
        c, ids = self.sa, (leg_id, f"{leg_id}:out")
        flows = c.execute(select(expected_flows.c.reservation_id).where(
            expected_flows.c.flow_id.in_(ids), expected_flows.c.state == "pending")).all()
        c.execute(update(expected_flows).where(expected_flows.c.flow_id.in_(ids),
                                               expected_flows.c.state == "pending")
                  .values(state=state))
        for (reservation_id,) in flows:
            if reservation_id:
                c.execute(update(reservations).where(
                    reservations.c.reservation_id == reservation_id,
                    reservations.c.state == "committed")
                    .values(state="settled" if state == "settled" else "held"))
        return len(flows)

    def release_failed(self, execution_id: str | None = None) -> None:
        """A failed leg moved nothing: its pending flows are cancelled, and a reservation it
        committed is held again for the obligation it was made for."""
        # Only failed legs with a flow still pending: a released leg is not read again.
        where = ("state = 'failed' AND (leg_id IN (SELECT flow_id FROM expected_flows"
                 " WHERE state = 'pending') OR leg_id || ':out' IN (SELECT flow_id FROM"
                 " expected_flows WHERE state = 'pending'))")
        args: tuple = ()
        if execution_id is not None:
            where, args = f"{where} AND approval_id = ?", (execution_id,)
        for leg in self.outbox._legs(where, args):
            with self.transaction():
                self._flows(leg.leg_id, "cancelled")


def observed_view(view: AccountView, now: datetime) -> AccountView:
    """The view an execution spends from: without the arrivals promised by `now` not landed.

    On the observed ledger nothing lands until it is observed, so a pending arrival past its
    promise is overdue and adds nothing to S or P, as in the decisions module's projection;
    the ledger's own S(now) counts it because a simulated round lands it at step 2.
    """
    return replace(view, pending_in=tuple(f for f in view.pending_in if f.at > now))


def out_flow(leg_id: str, kind: str) -> str:
    """The pending_out a leg spends through; an advance's own id names its pending_in."""
    return f"{leg_id}:out" if kind == "advance" else leg_id


def _from_ledger(refusal: LedgerRefusal, where: str) -> binding.Refusal:
    """A ledger refusal as the approval's: K_p beyond capacity is spendable cash short."""
    code = refusal.code if refusal.code in LEDGER_CODES else "insufficient_spendable"
    return binding.Refusal(code, f"{where}: {refusal}")

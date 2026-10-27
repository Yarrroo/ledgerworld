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
- The outbox and the ledger share one SQLite connection and one transaction, so a leg settles
  and its journal posts together (`Outbox(transaction=...)`).
- `ConnectorProvider` adapts the Airwallex client to the outbox's `Provider`: a duplicate id or a
  409 is adopted by lookup, a timeout is unknown and looked up before any resend under the same
  id, and the truth of a leg is a `GET` by its provider id.

Mode A (connected accounts) and Mode B (fallback) take their operation and receipt label from the
connector's `leg_plan`. A Mode B deposit carries no `request_id`, so its reference carries the leg
id; the client has no deposit list or GET, so an unknown deposit stays unknown for the operator.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
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
    expected_flows,
    journals,
    reservations,
    revenue_observations,
)
from app.finance.schemas import EXPONENT, ApprovalLeg, BoundApproval, Mode, Money
from app.finance.spendability import AccountView, spendability, state_of
from app.finance.store import LedgerStore
from sqlalchemy import Connection, select, update

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
        return "conversion", "/api/v1/conversions"
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
        for account in self.client.global_accounts():
            if isinstance(account, dict) and account.get("currency") == currency:
                self.global_account_id = account["id"]
                return account["id"]
        raise ob.Rejected(f"no Global Account in {currency} for the Mode B advance")


# ----------------------------------------------------------------------------- the gateway


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
        proxy = store.engine.raw_connection()  # SQLite's StaticPool: the store's one connection
        self.conn = proxy.driver_connection
        proxy.close()
        ob.install(self.conn)
        self.conn.execute(TERMS_DDL)
        self._sa: Connection | None = None
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
        (`check_outflow`), and with the repayments, which are owed, against S(now) alone."""
        spend: dict[str, int] = defaultdict(int)
        owed: dict[str, int] = defaultdict(int)
        wallet: dict[tuple[str, bool], int] = defaultdict(int)
        for leg in approval.legs:
            if refusal := self._check_leg(approval.entity, leg, now, spend, owed):
                return refusal
            if (leg.kind, self.leg_mode) in DEBITS_WALLET:
                on_behalf = self.leg_mode == "A" and leg.kind == "payout"
                wallet[(leg.amount.currency, on_behalf)] += leg.amount.minor
        for account_id in sorted(spend.keys() | owed.keys()):
            view = self.store.view(account_id)
            if spend[account_id]:
                refusal = check_outflow(view, spend[account_id], now)
                if refusal is not None:
                    return _from_ledger(refusal, f"{account_id} pays {spend[account_id]}")
            total, s_now = spend[account_id] + owed[account_id], spendability(view, now, now).value
            if total > s_now:
                return binding.Refusal("insufficient_spendable",
                                       f"{account_id} pays {total} of {s_now} spendable")
        return self._wallet(wallet) if self.mode == "sandbox" else None

    def _check_leg(self, entity: str, leg: ApprovalLeg, now: datetime,
                   spend: dict[str, int], owed: dict[str, int]) -> binding.Refusal | None:
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
            refusal = lending.check_draw(self.store, f.pool, leg.amount.minor, now)
            if refusal is not None:
                return _from_ledger(refusal, f"K_p of {f.pool}")
        elif leg.kind == "repayment" and self.period(f, leg.amount.minor, now) is None:
            return binding.Refusal("reservation_mismatch", f"leg {leg.index} pays exactly what "
                                   f"the oldest observed, unrepaid period of {f.facility_id} owes")
        if leg.funded_by and leg.funded_by.startswith("reservation:"):
            return self._held(leg)
        # A repayment is owed, not chosen: it needs S(now), and the floor does not apply.
        (owed if leg.kind == "repayment" else spend)[leg.source] += leg.amount.minor
        return None

    def _held(self, leg: ApprovalLeg) -> binding.Refusal | None:
        reservation_id = leg.funded_by.removeprefix("reservation:")
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
        """The facility's oldest observed, unrepaid period, when it owes exactly `amount`."""
        if f.state != "active":
            return None
        with self.store.reading(conn) as c:
            periods = c.execute(select(revenue_observations.c.period_end).where(
                revenue_observations.c.facility_id == f.facility_id,
                revenue_observations.c.observed_at <= now.astimezone(UTC).replace(tzinfo=None))
                .order_by(revenue_observations.c.period_end)).scalars().all()
            repaid = set(c.execute(select(journals.c.journal_id).where(
                journals.c.kind == "advance_repayment")).scalars())
            for period in periods:
                end = period.replace(tzinfo=UTC)
                if contracts.repay_journal_id(f.facility_id, end) in repaid:
                    continue
                revenue = lending.observed_revenue(self.store, f.facility_id, end, now, conn=c)
                due = contracts.repayment_minor(revenue, f.repay_share_bps,
                                                contracts.outstanding_minor(self.store, f, conn=c))
                return end if due == amount else None
        return None

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
        """The leg's journal, inside the settle transaction; returns its id."""
        c, now, mode = self.sa, self.clock(), self._journal_mode()
        bound = self.bound(leg)
        if leg.kind == "payout":  # the committed flow pays out: reservation and obligation close
            return self.store.settle_flow(
                leg.leg_id, counterparty=self.store.external_account(leg.currency, conn=c),
                at=now, journal_id=f"j-{leg.leg_id}", conn=c).journal_id
        self._flows(leg.leg_id, "settled")  # the journal below carries the cash itself
        if leg.kind == "advance":
            return lending.disburse(
                self.store, bound.facility_id, now=now, from_account=leg.source,
                borrower_account=leg.counterparty, journal_id=f"j-{bound.facility_id}-disburse",
                mode=mode, source_leg_id=leg.leg_id, conn=c).journal_id
        if leg.kind == "repayment":
            return self._repay(bound, leg, now, mode)
        seen = self.provider.seen[leg.leg_id]  # fx: the buy side as the GET showed it
        buy = aw.to_money(seen.raw["buy_amount"], seen.raw["buy_currency"])
        if buy.currency != bound.to_currency:
            raise ValueError(f"{leg.leg_id} bought {buy.currency}, bound {bound.to_currency}")
        sold_to = self.store.external_account(leg.currency, conn=c)
        bought_from = self.store.external_account(buy.currency, conn=c)
        return self.store.apply(Journal(
            journal_id=f"j-{leg.leg_id}", kind="fx_conversion", sim_time=now,
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
                             conn=self.sa)
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


def out_flow(leg_id: str, kind: str) -> str:
    """The pending_out a leg spends through; an advance's own id names its pending_in."""
    return f"{leg_id}:out" if kind == "advance" else leg_id


def _from_ledger(refusal: LedgerRefusal, where: str) -> binding.Refusal:
    """A ledger refusal as the approval's: K_p beyond capacity is spendable cash short."""
    code = refusal.code if refusal.code in LEDGER_CODES else "insufficient_spendable"
    return binding.Refusal(code, f"{where}: {refusal}")

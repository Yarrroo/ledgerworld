"""The round coordinator: one transactional round of the coupled world (system brief §7.2).

``run_round`` captures the world, then runs the ten steps inside one ledger transaction:

1. advance the clock · 2. deliver the scheduled events due now, land due inflows (an advance in
transit included) and mark ``overdue`` every pending_in promised by now that did not land ·
3. publish the scheduled posts · 4. build each actor's scoped observation · 5. ``env.step``:
every agent answers at once and its tool calls queue C1 intents; the OASIS clock must then read
this round · 6. validate the drained intents (schema, branch, round, mandate) · 7. clear them in
``(priority class, minute, actor, call)`` order against the ledger · 8. run the mandatory
settlements · 9. keep the C2 results for delivery next round · 10. record the transcript and
commit the ledger, the durable point.

Any exception or cancellation before that commit aborts the round: admission closes, every task
the round created (``env.step``'s gather children and theirs, found by a context variable) is
cancelled and joined, the platform is fenced so a write a cancelled agent already sent has
landed, then the ledger rolls back and every captured component is restored and checked
against the capture. If a writer outlives its cancellation, the platform cannot be fenced or the
restored world differs from its capture, the world is marked unusable and refuses every later
round. This is exception rollback, not process-crash recovery. A rejected intent, or malformed
output the guardrail turned into ``no_action``, is a C2 result, not a failed round.

Clearing, per intent type (the actor acts from ``<actor>/operating``):

- ``pay`` → ``ledger.pay`` to ``<to>/operating`` or the outside world; a refusal is the reason.
- ``request_advance`` → against an ``offered`` advance of that lender (``facility_id``, or the
  one offered for that amount) it disburses through ``lending.disburse`` into the borrower's
  in-transit account, landing as a pending_in at the next round boundary; otherwise it becomes
  the message ``req:<actor>:r<round>`` to the lender, read from the next round on.
- ``accept`` (a request) and ``offer`` → a revenue advance in state ``offered`` on LF-2's terms.
- ``disburse`` (an accepted request) → as an offered request, through ``lending.disburse``.
- ``release`` → an offered advance of the lender is withdrawn (``closed``).
- ``pledge`` → ``store.pledge``; ``repay``, ``defer``, ``convert`` are rejected with the reason.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from typing import Any

from oasis_finance.actions import (
    FinancialActionType,
    ToolCallError,
    clearing_key,
    parse_tool_call,
)
from pydantic import ValidationError
from sqlalchemy import Connection, select

from ..finance import ledger, lending
from ..finance.contracts import (
    ensure_account,
    facility,
    pool_facilities,
    register,
    set_facility,
)
from ..finance.models import Journal, LedgerRefusal, accounts, expected_flows, journals
from ..finance.schemas import ActionIntent, Amount, ClearedAction, RevenueAdvance
from .clock import ROUND_HOURS
from .world import TRANSIT, World, WorldUnusable

__all__ = ["Cleared", "Coordinator", "RoundContext", "RoundResult", "WorldUnusable",
           "clear_intents", "validate_intents"]

# LF-2's advance terms (system brief §6), for an advance a lender offers or accepts.
ADVANCE_FEE_BPS = 800
ADVANCE_REPAY_SHARE_BPS = 1500

_ROUND = contextvars.ContextVar("ledgerworld_round", default=None)

Hook = Callable[..., Any]


class Rejected(Exception):
    """An intent the rules refuse; it becomes a rejected C2, never a failed round."""

    def __init__(self, reason: str, binding: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.binding = binding


@dataclass(frozen=True)
class Cleared:
    """One intent's verdict, with what the actor saw when it proposed it."""

    intent_id: str
    actor_id: str
    type: str
    c2: ClearedAction
    journal: Journal | None
    obs_hash: str | None
    evidence_ids: tuple[str, ...]
    detail: Mapping[str, Any] = field(default_factory=dict)

    def record(self) -> dict:
        return {**self.c2.model_dump(mode="json", exclude_none=True), "actor_id": self.actor_id,
                "type": self.type, "obs_hash": self.obs_hash,
                "evidence_ids": list(self.evidence_ids)}


@dataclass(frozen=True)
class RoundResult:
    round: int
    cleared: list[ClearedAction]
    journals: list[Journal]
    transcript_entry: dict
    records: list[Cleared] = field(default_factory=list)


@dataclass
class RoundContext:
    """The round in hand, as a hook sees it."""

    round: int
    conn: Connection
    journals: list[Journal] = field(default_factory=list)
    observations: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------- step 6


def _intent_id(raw: Mapping[str, Any], round_: int, n: int) -> str:
    value = raw.get("intent_id")
    if isinstance(value, str) and 1 <= len(value) <= 128:
        return value
    return f"i-r{round_}-{raw.get('actor_id', 'unknown')}-invalid-{n}"[:128]


def validate_intents(
    world: World, intents: Iterable[ActionIntent | Mapping[str, Any]]
) -> tuple[list[ActionIntent], list[Cleared]]:
    """§7.2 step 6: the intents that may clear, and a rejection for each that may not."""
    round_ = world.clock.round
    valid, rejected = [], []
    for n, item in enumerate(intents, 1):
        if not isinstance(item, ActionIntent):
            try:
                item = ActionIntent.model_validate(dict(item))
            except ValidationError as error:
                money = any(tuple(e["loc"][:2]) == ("params", "amount")
                            for e in error.errors(include_url=False))
                raw = dict(item)
                rejected.append(_rejection(
                    _intent_id(raw, round_, n), str(raw.get("actor_id", "unknown")),
                    str(raw.get("type", "unknown")), round_,
                    "amount_not_integer_minor" if money else "malformed_intent"))
                continue
        spec = world.actors.get(item.actor_id)
        reason = None
        if item.branch_id != world.branch_id:
            reason = "wrong_branch"
        elif item.round != round_:
            reason = "wrong_round"
        elif spec is None:
            reason = "unknown_actor"
        elif item.type != "no_action" and item.type not in spec["tools"]:
            reason = "not_in_mandate"
        elif len(item.intent_id) > journals.c.source_intent_id.type.length:
            reason = "intent_id_too_long"  # its journal could not name it
        elif not _fits_its_tool(item):
            reason = "malformed_intent"
        if reason is None:
            valid.append(item)
        else:
            rejected.append(_rejection(item.intent_id, item.actor_id, item.type, round_, reason,
                                       item=item))
    return valid, rejected


def _fits_its_tool(intent: ActionIntent) -> bool:
    """An intent's params validate against its tool's argument schema, whoever queued it (a
    tool already did; an injected or policy-made intent is held to the same shape)."""
    args = intent.params.model_dump(mode="json", exclude_none=True)
    amount = args.pop("amount", None)
    if amount is not None:
        args.update(amount_minor=amount["minor"], currency=amount["currency"])
    action = FinancialActionType(intent.type)
    return not isinstance(parse_tool_call(intent.type, args, [action]), ToolCallError)


def _rejection(intent_id: str, actor_id: str, type_: str, round_: int, reason: str,
               binding: str | None = None, item: ActionIntent | None = None,
               detail: Mapping[str, Any] | None = None) -> Cleared:
    c2 = ClearedAction(intent_id=intent_id, status="rejected", reason=reason, binding=binding,
                       round=round_)
    return Cleared(intent_id, actor_id, type_, c2, None, item.obs_hash if item else None,
                   tuple(item.evidence_ids) if item else (), dict(detail or {}))


# ------------------------------------------------------------------------------- step 7


def clear_intents(world: World, conn: Connection, intents: Iterable[ActionIntent]) -> list[Cleared]:
    """§7.2 step 7: clear the intents against the ledger in the deterministic order.

    Each intent clears in its own savepoint, so a refused one leaves nothing behind and the
    next is cleared against what the earlier ones did. Every reference the model chose (an
    account, a counterparty, a request) is checked before the ledger is asked, so what the
    model got wrong is a C2 reason, and an exception left over is the coordinator's own fault.
    """
    out = []
    for intent in sorted(intents, key=clearing_key):
        try:
            with world.store.transaction(conn) as c:
                journal = _clear(world, c, intent)
        except Rejected as refusal:
            out.append(_rejection(intent.intent_id, intent.actor_id, intent.type, intent.round,
                                  refusal.reason, refusal.binding, intent))
            continue
        except LedgerRefusal as refusal:
            out.append(_rejection(intent.intent_id, intent.actor_id, intent.type, intent.round,
                                  refusal.code, _binding(refusal), intent, refusal.detail))
            continue
        c2 = ClearedAction(intent_id=intent.intent_id, status="accepted",
                           journal_id=journal.journal_id if journal else None, round=intent.round)
        out.append(Cleared(intent.intent_id, intent.actor_id, intent.type, c2, journal,
                           intent.obs_hash, tuple(intent.evidence_ids)))
    return out


def _binding(refusal: LedgerRefusal) -> str | None:
    d = refusal.detail
    if "binding" in d:
        return str(d["binding"])
    for key in ("S_now", "headroom", "K_p"):
        if key in d:
            return f"{key} = {d[key]}"
    return None


def _money(intent: ActionIntent) -> tuple[int, str]:
    amount = intent.params.amount
    return amount.minor, amount.currency


def _param(intent: ActionIntent, key: str) -> Any:
    return (intent.params.__pydantic_extra__ or {}).get(key)


def _clear(world: World, c: Connection, intent: ActionIntent) -> Journal | None:
    handler = CLEARING.get(intent.type)
    if handler is None:
        raise Rejected("no_clearing_rule")
    return handler(world, c, intent)


def _no_action(world: World, c: Connection, intent: ActionIntent) -> None:
    return None


def _fit_id(prefix: str, base: str, width: int) -> str:
    """``<prefix>:<base>`` when it fits ``width``, else a stable ``<prefix>-<hash>`` that does."""
    readable = f"{prefix}:{base}"
    if len(readable) <= width:
        return readable
    return f"{prefix}-{hashlib.sha256(base.encode()).hexdigest()[:width - len(prefix) - 1]}"


def _journal_id(intent_id: str) -> str:
    """The journal of one intent."""
    return _fit_id("j", intent_id, journals.c.journal_id.type.length)


def _account(c: Connection, account_id: str) -> Any:
    return c.execute(select(accounts).where(accounts.c.account_id == account_id)).first()


def _cash_of(c: Connection, account_id: str, entity: str, currency: str, what: str) -> None:
    """A movement leaves from or arrives at a cash account of ``entity`` in ``currency``."""
    row = _account(c, account_id)
    if row is None or row.kind != "cash" or row.entity_id != entity \
            or account_id.endswith(f"/{TRANSIT}"):
        raise Rejected(what, f"{account_id} is not a cash account of {entity}")
    if row.currency != currency:
        raise Rejected("currency_mismatch", f"{account_id} holds {row.currency}, not {currency}")


def _pay(world: World, c: Connection, intent: ActionIntent) -> Journal:
    """A payment to another entity's operating account, to a cash account named by id, or out
    of the world (a counterparty the world does not hold); never into a loan, payable or
    in-transit account, and never of an obligation, which settles when due (step 8)."""
    amount, currency = _money(intent)
    if _param(intent, "obligation_id") is not None:
        raise Rejected("obligation_settles_when_due",
                       "a due obligation is paid by the round's mandatory settlement")
    source = world.operating(intent.actor_id)
    _cash_of(c, source, intent.actor_id, currency, "no_operating_account")
    to = str(_param(intent, "to"))
    if _account(c, world.operating(to)) is not None:
        payee = world.operating(to)
        _cash_of(c, payee, to, currency, "payee_not_cash")
    elif (row := _account(c, to)) is not None:
        payee = to
        _cash_of(c, payee, row.entity_id, currency, "payee_not_cash")
    else:
        payee = world.store.external_account(currency, conn=c)
    if payee == source:
        raise Rejected("payee_is_payer")
    return ledger.pay(world.store, source, amount, to_account=payee, now=world.clock.now,
                      journal_id=_journal_id(intent.intent_id), round=intent.round,
                      source_intent_id=intent.intent_id, conn=c)


def _pools(world: World, c: Connection) -> dict[str, str]:
    """Each lending pool and the currency it lends."""
    return {p["pool_entity_id"]: p["currency"]
            for p in world.store.rows("lending_pools", conn=c)}


def _advance_parties(world: World, c: Connection, lender: str, borrower: str,
                     currency: str) -> None:
    """An advance runs from a pool in its currency to a borrower's operating account in the
    same currency, so its arrival can land."""
    pools = _pools(world, c)
    if lender not in pools:
        raise Rejected("unknown_lender", f"{lender} is not a lending pool")
    if pools[lender] != currency:
        raise Rejected("currency_mismatch", f"{lender} lends {pools[lender]}, not {currency}")
    if borrower == lender:
        raise Rejected("unknown_counterparty", "a pool does not lend to itself")
    _cash_of(c, world.operating(borrower), borrower, currency, "unknown_counterparty")


# A facility's longest derived id is its arrival's settlement journal, settle:arrive:<facility>.
FACILITY_ID_MAX = journals.c.journal_id.type.length - len("settle:arrive:")


def _facility_id(base: str) -> str:
    return _fit_id("adv", base, FACILITY_ID_MAX)


def _offer_advance(world: World, c: Connection, *, facility_id: str, lender: str,
                   borrower: str, amount: int, currency: str, fee_bps: int) -> None:
    register(world.store, RevenueAdvance(
        contract_id=facility_id, lender=lender, borrower=borrower, state="offered",
        kind="revenue_advance", principal=Amount(minor=amount, currency=currency),
        fee_bps=fee_bps, repay_share_bps=ADVANCE_REPAY_SHARE_BPS), as_of=world.clock.now, conn=c)


def _message(world: World, item: dict) -> None:
    world.state.items.append({"kind": "message", "visible_from_h": world.clock.t_hours, **item})


def _disburse(world: World, c: Connection, facility_id: str, intent: ActionIntent,
              from_account: str | None = None) -> Journal:
    """Disburse an offered advance into the borrower's in-transit account; it lands on the
    borrower's operating account at the next round boundary (step 2 of the next round)."""
    f = facility(world.store, facility_id, conn=c)
    store, now = world.store, world.clock.now
    _advance_parties(world, c, f.pool, f.borrower, f.currency)
    if from_account is not None:
        _cash_of(c, from_account, f.pool, f.currency, "not_own_account")
    transit = f"{f.borrower}/{TRANSIT}"
    ensure_account(store, transit, f.borrower, f.currency, "cash", c)
    journal = lending.disburse(store, facility_id, now=now, from_account=from_account,
                               borrower_account=transit, journal_id=_journal_id(intent.intent_id),
                               round=intent.round, source_intent_id=intent.intent_id, conn=c)
    lands = intent.round + 1
    flow_id = store.expect(world.operating(f.borrower), "in", f.limit_minor,
                           world.clock.at(lands), kind="advance",
                           flow_id=f"arrive:{facility_id}", conn=c)
    world.state.arrivals[flow_id] = {"round": lands, "from": transit}
    world.state.expected_h[flow_id] = lands * ROUND_HOURS
    world.state.flow_status[flow_id] = "expected"
    return journal


def _offered(world: World, c: Connection, lender: str, borrower: str) -> list[Any]:
    return [f for f in pool_facilities(world.store, lender, conn=c)
            if f.kind == "revenue_advance" and f.state == "offered" and f.borrower == borrower]


def _request_advance(world: World, c: Connection, intent: ActionIntent) -> Journal | None:
    amount, currency = _money(intent)
    lender = str(_param(intent, "from"))
    _advance_parties(world, c, lender, intent.actor_id, currency)
    wanted = _param(intent, "facility_id")
    offers = _offered(world, c, lender, intent.actor_id)
    if wanted is not None:
        offers = [f for f in offers if f.facility_id == wanted]
        if not offers:
            raise Rejected("no_offered_facility", f"{wanted} is not offered to {intent.actor_id}")
    offers = [f for f in offers if (f.limit_minor, f.currency) == (amount, currency)]
    if wanted is not None and not offers:
        raise Rejected("amount_differs_from_offer")
    if offers:
        facility_id = offers[0].facility_id
        journal = _disburse(world, c, facility_id, intent)
        for request in world.state.requests.values():  # an accepted request it answers
            if request["facility_id"] == facility_id:
                request["status"] = "disbursed"
        return journal
    base = f"req:{intent.actor_id}:r{intent.round}"
    request_id, n = base, 1
    while request_id in world.state.requests:
        n += 1
        request_id = f"{base}-{n}"
    world.state.requests[request_id] = {
        "borrower": intent.actor_id, "lender": lender, "amount_minor": amount,
        "currency": currency, "intent_id": intent.intent_id, "status": "open",
        "facility_id": None}
    _message(world, {"id": request_id, "to": lender, "from": intent.actor_id,
                     "intent_id": intent.intent_id, "amount_minor": amount, "currency": currency,
                     "reason": _param(intent, "reason")})
    return None


def _request(world: World, intent: ActionIntent, *statuses: str) -> tuple[str, dict]:
    request_id = _param(intent, "request")
    request = world.state.requests.get(request_id)
    if request is None or request["lender"] != intent.actor_id:
        raise Rejected("unknown_request", f"no request {request_id} to {intent.actor_id}")
    if request["status"] not in statuses:
        raise Rejected("request_not_open", f"{request_id} is {request['status']}")
    return request_id, request


def _accept(world: World, c: Connection, intent: ActionIntent) -> None:
    request_id, request = _request(world, intent, "open")
    _advance_parties(world, c, intent.actor_id, request["borrower"], request["currency"])
    facility_id = _facility_id(request_id)
    _offer_advance(world, c, facility_id=facility_id, lender=intent.actor_id,
                   borrower=request["borrower"], amount=request["amount_minor"],
                   currency=request["currency"], fee_bps=ADVANCE_FEE_BPS)
    request.update(status="accepted", facility_id=facility_id)
    _message(world, {"id": f"offer:{facility_id}", "to": request["borrower"],
                     "from": intent.actor_id, "intent_id": intent.intent_id,
                     "facility_id": facility_id, "request": request_id})


def _offer(world: World, c: Connection, intent: ActionIntent) -> None:
    amount, currency = _money(intent)
    borrower = str(_param(intent, "to"))
    _advance_parties(world, c, intent.actor_id, borrower, currency)
    facility_id = _facility_id(intent.intent_id)
    fee = _param(intent, "fee_bps")
    _offer_advance(world, c, facility_id=facility_id, lender=intent.actor_id, borrower=borrower,
                   amount=amount, currency=currency,
                   fee_bps=ADVANCE_FEE_BPS if fee is None else fee)
    _message(world, {"id": f"offer:{facility_id}", "to": borrower, "from": intent.actor_id,
                     "intent_id": intent.intent_id, "facility_id": facility_id,
                     "amount_minor": amount, "currency": currency})


def _disburse_request(world: World, c: Connection, intent: ActionIntent) -> Journal:
    _, request = _request(world, intent, "accepted")
    amount, currency = _money(intent)
    if (amount, currency) != (request["amount_minor"], request["currency"]):
        raise Rejected("amount_differs_from_facility")
    source = _param(intent, "from_account")
    journal = _disburse(world, c, request["facility_id"], intent,
                        None if source is None else str(source))
    request["status"] = "disbursed"
    return journal


def _release(world: World, c: Connection, intent: ActionIntent) -> None:
    target = str(_param(intent, "target")).removeprefix("offer:").removeprefix("contract:")
    offers = [f for f in pool_facilities(world.store, intent.actor_id, conn=c)
              if f.facility_id == target and f.state == "offered"]
    if not offers:
        raise Rejected("nothing_to_release", f"{target} is no offer of {intent.actor_id}")
    set_facility(world.store, target, state="closed", conn=c)
    for request in world.state.requests.values():
        if request["facility_id"] == target:
            request["status"] = "released"


def _pledge(world: World, c: Connection, intent: ActionIntent) -> None:
    amount, currency = _money(intent)
    account = world.operating(intent.actor_id)
    _cash_of(c, account, intent.actor_id, currency, "no_operating_account")
    world.store.pledge(account, amount, f"pledge:{intent.intent_id}", conn=c)


def _refuse(reason: str, binding: str) -> Callable[..., None]:
    def refuse(world: World, c: Connection, intent: ActionIntent) -> None:
        raise Rejected(reason, binding)

    return refuse


CLEARING: dict[str, Callable[[World, Connection, ActionIntent], Journal | None]] = {
    "no_action": _no_action,
    "pay": _pay,
    "request_advance": _request_advance,
    "accept": _accept,
    "offer": _offer,
    "disburse": _disburse_request,
    "release": _release,
    "pledge": _pledge,
    "repay": _refuse("repayment_follows_observed_revenue",
                     "a repayment is a share of observed revenue, settled by the ledger"),
    "defer": _refuse("not_deferrable", "no contract of this world allows a deferral"),
    "convert": _refuse("no_fx_quote", "the round world has no FX quote to convert at"),
}


# ------------------------------------------------------------------------------- step 2


def deliver(world: World, conn: Connection) -> tuple[list[dict], list[Journal]]:
    """§7.2 step 2: refresh what is observable, apply the due events, land due inflows and mark
    every inflow promised by now that did not land ``overdue``. Returns the due posts (step 3's)
    and the arrival journals."""
    store, now, t = world.store, world.clock.now, world.clock.t_hours
    for obs in store.rows("account_observations", conn=conn):
        if obs["observability"] == "known":
            store.observe(obs["account_id"], "known", now, conn=conn)
    posts = []
    for event in world.due_events():
        kind = event["kind"]
        event_id = event.get("id") or event.get("post_id") or f"{kind}@r{event['round']}"
        if kind == "public_post":
            posts.append(event)
        elif kind == "delay_receipt":
            expected_at = conn.execute(select(expected_flows.c.expected_at).where(
                expected_flows.c.flow_id == event["flow_id"])).scalar()
            if expected_at is None:
                raise ValueError(f"scheduled event {event_id} delays no flow {event['flow_id']}")
            store.reschedule(event["flow_id"], expected_at.replace(tzinfo=UTC)
                             + timedelta(hours=event["delay_h"]), conn=conn)
        elif kind == "message":
            _message(world, {"id": event["id"], "to": event["to"], "text": event["text"]})
        elif kind == "observe":
            store.observe(event["account"], event["observability"], now, conn=conn)
        else:
            raise ValueError(f"scheduled event {event_id} has an unknown kind {kind!r}")
        world.state.deliveries.append(event_id)
    journals = []
    for flow in store.due_flows("in", now, conn=conn):
        transit = world.state.arrivals.pop(flow.flow_id, None)
        counterparty = transit["from"] if transit else store.external_account(flow.currency,
                                                                              conn=conn)
        journals.append(store.settle_flow(flow.flow_id, counterparty=counterparty, at=now,
                                          round=world.clock.round, conn=conn))
        world.state.flow_status[flow.flow_id] = "arrived"
    for flow_id, expected_h in world.state.expected_h.items():
        if expected_h <= t and world.state.flow_status.get(flow_id) == "expected":
            world.state.flow_status[flow_id] = "overdue"
    return posts, journals


# --------------------------------------------------------------------------- the round


class Coordinator:
    """Runs rounds of a world; ``hooks`` are test seams, called by name at fixed points.

    Hook points: ``advanced`` (after step 1), ``delivered`` (after step 2), ``before_observations``
    (after step 3), ``observed`` (after step 4), ``stepped`` (after step 5), ``intents``
    (receives the drained intents and returns what step 6 validates), ``cleared`` (after step 7),
    ``settled`` (after step 8), ``before_transcript`` (step 10, before anything is recorded).
    A hook takes ``(world, ctx)`` (``intents`` also the list) and may be a coroutine function.
    """

    def __init__(self, hooks: Mapping[str, Hook] | None = None,
                 quiesce_timeout_s: float = 5.0) -> None:
        self.hooks = dict(hooks or {})
        self.quiesce_timeout_s = quiesce_timeout_s

    async def _hook(self, name: str, *args: Any) -> Any:
        hook = self.hooks.get(name)
        if hook is None:
            return args[-1] if name == "intents" else None
        result = hook(*args)
        if inspect.isawaitable(result):
            result = await result
        return result

    @staticmethod
    def round_tasks(token: object) -> list[asyncio.Task]:
        """Every live task created inside the round, at any depth."""
        return [t for t in asyncio.all_tasks()
                if not t.done() and t.get_context().get(_ROUND) is token]

    async def run_round(self, world: World) -> RoundResult:
        if world.unusable is not None:
            raise WorldUnusable(world.unusable)
        if world.env is None:
            raise RuntimeError("start the world before running a round")
        capture = world.capture()
        round_ = capture.round + 1
        token = object()
        context = contextvars.copy_context()
        context.run(_ROUND.set, token)
        conn = world.store.engine.connect()
        trans = conn.begin()
        body = asyncio.create_task(self._steps(world, conn, trans), context=context,
                                   name=f"round-{round_}")
        try:
            # Shielded: a cancelled coordinator closes admission before any round task is
            # cancelled, rather than having its cancellation reach them first.
            result = await asyncio.shield(body)
        except BaseException as error:
            if world.committed_round == round_:  # cancelled after the durable point
                conn.close()
                raise
            world.unusable = f"round {round_} is aborting"
            await self._abort(world, token, conn, trans, capture, error)
            raise
        conn.close()
        return result

    async def _abort(self, world: World, token: object, conn: Connection, trans: Any,
                     capture: Any, error: BaseException) -> None:
        status = "cancelled" if isinstance(error, asyncio.CancelledError) else "failed"
        round_ = capture.round + 1
        world.close_admission()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.quiesce_timeout_s
        pending = self.round_tasks(token)
        while pending and loop.time() < deadline:
            for task in pending:
                task.cancel()
            done, _ = await asyncio.wait(pending, timeout=max(0.0, deadline - loop.time()))
            for task in done:
                if not task.cancelled():
                    task.exception()  # retrieved: the round's own error is the one raised
                world.lifecycle.append(("task_done", task.get_name()))
            pending = self.round_tasks(token)
        trans.rollback()
        conn.close()
        failure = {"round": round_, "status": status, "error": repr(error)}
        world.failures.append(failure)
        if pending:
            world.unusable = (f"round {round_}: {len(pending)} round task(s) outlived their "
                              "cancellation")
            world.lifecycle.append(("quiescence_unproved", world.unusable))
            return
        if not await world.fence_platform(self.quiesce_timeout_s):
            world.unusable = f"round {round_}: the platform could not be fenced"
            world.lifecycle.append(("quiescence_unproved", world.unusable))
            return
        world.lifecycle.append(("restore_begin", str(len(self.round_tasks(token)))))
        world.restore(capture)
        differs = sorted(k for k, v in world.fingerprint().items()
                         if capture.fingerprint[k] != v)
        if differs:
            world.unusable = f"round {round_}: restored world differs from its capture: {differs}"
            world.lifecycle.append(("restore_differs", world.unusable))
            return
        world.lifecycle.append(("restore_end", f"round {round_} {status}"))
        world.unusable = None

    async def _steps(self, world: World, conn: Connection, trans: Any) -> RoundResult:
        round_ = world.clock.advance()  # 1
        ctx = RoundContext(round_, conn)
        await self._hook("advanced", world, ctx)
        posts, arrivals = deliver(world, conn)  # 2
        ctx.journals += arrivals
        await self._hook("delivered", world, ctx)
        await world.publish(posts)  # 3
        await self._hook("before_observations", world, ctx)
        ctx.observations = world.observe_all(conn)  # 4
        delivered_c2 = [c["intent_id"] for c in world.state.pending_c2]
        await self._hook("observed", world, ctx)
        await world.env.step({agent: world.oasis.LLMAction()  # 5
                              for agent in world.agents.values()})
        world.clock.check(world.platform.sandbox_clock.time_step)
        world.ingest_posts()
        await self._hook("stepped", world, ctx)
        intents = await self._hook("intents", world, ctx, world.queue.drain())
        valid, rejected = validate_intents(world, intents)  # 6
        cleared = clear_intents(world, conn, valid) + rejected  # 7
        ctx.journals += [c.journal for c in cleared if c.journal is not None]
        await self._hook("cleared", world, ctx)
        ctx.journals += ledger.settle_due(world.store, world.clock.now, round=round_,
                                          conn=conn)  # 8
        await self._hook("settled", world, ctx)
        world.state.pending_c2 = [  # 9
            {"actor_id": c.actor_id, **c.c2.model_dump(mode="json", exclude_none=True)}
            for c in cleared if not (c.type == "no_action" and c.c2.status == "accepted")]
        await self._hook("before_transcript", world, ctx)  # 10
        tool_calls = world.round_tool_calls()
        for actor_id, obs in ctx.observations.items():
            world.transcript.record(round_, actor_id, obs.obs_hash, tool_calls[actor_id])
        for intent in valid:
            world.state.intents[intent.intent_id] = intent.model_dump(mode="json")
        entry = {
            "round": round_,
            "t_hours": world.clock.t_hours,
            "observations": {a: o.obs_hash for a, o in ctx.observations.items()},
            "evidence": {a: list(o.evidence_ids) for a, o in ctx.observations.items()},
            "tool_calls": tool_calls,
            "intents": [c.intent_id for c in cleared],
            "c2": [c.record() for c in cleared],
            "c2_delivered": delivered_c2,
            "journal_ids": [j.journal_id for j in ctx.journals],
        }
        world.state.rounds.append(entry)
        trans.commit()  # the durable point
        world.committed_round = round_
        return RoundResult(round_, [c.c2 for c in cleared], list(ctx.journals), entry, cleared)


"""Three candidate policies, evaluated on the same scenario tree (§9, decisions HANDOFF).

A policy decides from a ``PolicyView`` (``nonanticipativity.py``) and returns plan actions in the
treasury's tools: ``request_advance{facility, amount_minor}``, ``defer{flow, to_h}``,
``convert{buy, sell_currency, for_obligation}``, ``pay``; an empty list is ``no_action``.

- ``NoAction`` does nothing; mandatory settlements still run.
- ``FixedReserve`` keeps the floor by deferring discretionary outflows that carry
  ``defer_to_h``, cheapest first, and never borrows.
- ``Integrated`` closes a projected shortfall with the cheapest remedy first (a free deferral,
  then a paid one, then an eligible advance, all or nothing) and converts a foreign-currency
  obligation one round before it is due.

The projection a policy makes is settled + pending_in expected and not overdue − pending_out −
obligations (reserved or not), all due within the horizon; overdue, unknown and stale add
nothing. A policy never sees a lender's K_p: a draw beyond it comes back as a rejected C2, and a
rejected facility is never asked again in that branch.

``evaluate`` forks one fresh branch per (scenario, policy) from one checkpoint. In a policy
branch the treasury's agent leaves the acting set, so its model is never called; the policy
decides at step 4 (when the agents observe) on the treasury's own observation, and its C1
intents carry ``params.source = "policy:<id>"``. Feasibility is ``assess``-ed from each
branch's realised ledger and ``rank`` orders the policies. ``plan_for_now`` has the selected
policy decide again on the current observed snapshot, never on a branch, and returns the legs
the execution module binds; a decision is never an approval.

The policy's world is flat: scalars (``t_h``, ``settled``, ``floor_minor``, ``horizon_h``,
``account``, ``currency``) and one leaf per record (``pending_in[rcv-1]``,
``obligations[payroll-1]``, ``facilities[adv-a]``, ``c2_seen[<intent>]``, ``prices[EUR/USD]``),
every one available at t, plus ``scenario.*`` leaves that are never observable.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from ..execution.approval import is_observed_snapshot
from ..finance.contracts import fee_minor, pool_facilities
from ..finance.lending import capacity
from ..finance.schemas import Snapshot
from ..simulation.branches import BranchMismatch, Checkpoint, fork
from ..simulation.coordinator import Coordinator
from ..simulation.world import World, _digest, due_hour, hours_of
from ..testing.scripted_model import ScriptedPlan
from .feasibility import assess
from .nonanticipativity import HOURS_PER_ROUND, Leaf, PolicyView, guarded_decide
from .objective import DecisionResult, Evaluation, rank

__all__ = ["ALL", "FixedReserve", "Integrated", "NoAction", "Projection", "Proposal",
           "branch_observation", "decide", "evaluate", "plan_for_now", "project",
           "snapshot_observation", "view_world"]

DEFAULT_HORIZON_H = 72
CONVERT_LEAD_H = HOURS_PER_ROUND  # a foreign-currency obligation is converted one round early
SCALARS = ("t_h", "account", "currency", "settled", "floor_minor", "horizon_h")
RECORDS = {"pending_in": "flow_id", "pending_out": "flow_id", "obligations": "id",
           "outflows": "id", "facilities": "id", "reserved": "id", "c2_seen": "intent"}
NEVER_OBSERVABLE = ("scenario.params", "scenario.events", "scenario.rng")


# ----------------------------------------------------------------------- the policy's world

def view_world(obs: Mapping[str, Any], never: Sequence[str] = NEVER_OBSERVABLE) -> dict[str, Leaf]:
    """An observation at ``obs["t_h"]`` as a world of leaves, each available from then."""
    t = obs["t_h"]
    leaves: dict[str, Leaf] = {}
    for key, value in obs.items():
        if key in RECORDS:
            for record in value:
                path = f"{key}[{record[RECORDS[key]]}]"
                if path in leaves:
                    raise ValueError(f"{path} appears twice in the observation")
                leaves[path] = Leaf.at(t, dict(record))
        elif key == "prices":
            for pair, rate in value.items():
                leaves[f"prices[{pair}]"] = Leaf.at(t, {"pair": pair, "rate": rate})
        elif key in SCALARS:
            leaves[key] = Leaf.at(t, value)
        else:
            raise ValueError(f"an observation has no field {key!r}")
    for path in never:
        leaves[path] = Leaf.never()
    return leaves


def read(view: PolicyView) -> dict[str, Any]:
    """Everything the view shows now, as the observation it was built from (every read is
    recorded as evidence)."""
    obs: dict[str, Any] = {"t_h": view.t_h, "currency": "USD", "settled": 0, "floor_minor": 0}
    for key in SCALARS[1:]:
        if key in view.paths(key):
            obs[key] = view.get(key)
    obs.setdefault("horizon_h", view.t_h + DEFAULT_HORIZON_H)
    for key in RECORDS:
        obs[key] = [view.get(p) for p in view.paths(key)]
    obs["prices"] = {r["pair"]: r["rate"] for r in (view.get(p) for p in view.paths("prices"))}
    return obs


# ------------------------------------------------------------------------------ projection

@dataclass(frozen=True)
class Projection:
    min_minor: int
    at_h: int
    short_minor: int
    breach_h: int | None  # the first hour the projected cash is below the floor

    def as_dict(self) -> dict:
        return {"min": self.min_minor, "at_h": self.at_h, "short_minor": self.short_minor}


def value_in(amount: int, currency: str, obs: Mapping[str, Any]) -> int | None:
    """``amount`` of ``currency`` in the account's currency at the observed public price,
    rounded up (an outflow is never undervalued); None when no price is observed."""
    home = obs["currency"]
    if currency == home:
        return amount
    rate = obs["prices"].get(f"{currency}/{home}")
    if rate is None:
        return None
    return int((Decimal(amount) * Decimal(str(rate))).to_integral_value(ROUND_CEILING))


def project(obs: Mapping[str, Any], *, deferred: Mapping[str, int] | None = None,
            advances: Sequence[tuple[int, int]] = (), fees: int = 0) -> Projection:
    """P over the horizon from ``obs``, with ``deferred`` outflows moved to their new hour,
    ``advances`` (arrival hour, amount) added and ``fees`` paid now."""
    deferred = deferred or {}
    t, end = obs["t_h"], obs["horizon_h"]
    deltas: dict[int, int] = {}

    def at(hour: int, amount: int) -> None:
        hour = max(hour, t)  # an amount already due and still open counts now
        if hour <= end:
            deltas[hour] = deltas.get(hour, 0) + amount

    for f in obs["pending_in"]:
        if f.get("status", "expected") == "expected":
            at(f["expected_h"], f["amount"])
    for f in obs["pending_out"]:
        at(f["due_h"], -f["amount"])
    for o in obs["obligations"]:
        value = value_in(o["amount"], o.get("currency", obs["currency"]), obs)
        if value is not None:  # an unpriced obligation adds nothing it cannot be valued at
            at(o["due_h"], -value)
    for o in obs["outflows"]:
        at(deferred.get(o["id"], o["due_h"]), -o["amount"])
    for hour, amount in advances:
        at(hour, amount)
    cash = obs["settled"] - fees + deltas.pop(t, 0)
    points = [(t, cash)]
    for hour in sorted(deltas):
        cash += deltas[hour]
        points.append((hour, cash))
    low = min(v for _, v in points)
    floor = obs["floor_minor"]
    return Projection(low, next(h for h, v in points if v == low), max(0, floor - low),
                      next((h for h, v in points if v < floor), None))


# -------------------------------------------------------------------------------- policies

@dataclass(frozen=True)
class Proposal:
    """A policy's decision with its working: the shortfall it saw and what is left after."""

    actions: list[dict]
    projected_short: Projection
    projected_after: Projection
    funding_cost_minor: int = 0
    reason: str | None = None
    detail: str | None = None


class _Policy:
    id = ""

    def decide(self, view: PolicyView) -> list[dict]:
        return self.propose(view).actions

    def propose(self, view: PolicyView) -> Proposal:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def _defer(obs: Mapping[str, Any], before: Projection, actions: list[dict],
           deferred: dict[str, int]) -> tuple[Projection, int]:
    """Defer the deferrable outflows, cheapest first, while each still narrows the shortfall."""
    now, cost = before, 0
    options = sorted((o for o in obs["outflows"]
                      if o.get("defer_to_h") is not None and not o.get("reserved")
                      and o["due_h"] > obs["t_h"]),
                     key=lambda o: (o.get("fee_minor", 0), o["due_h"], o["id"]))
    for o in options:
        if now.short_minor == 0:
            break
        trial = project(obs, deferred={**deferred, o["id"]: o["defer_to_h"]},
                        fees=cost + o.get("fee_minor", 0))
        if trial.min_minor > now.min_minor:
            deferred[o["id"]] = o["defer_to_h"]
            cost += o.get("fee_minor", 0)
            actions.append({"type": "defer", "flow": o["id"], "to_h": o["defer_to_h"]})
            now = trial
    return now, cost


class NoAction(_Policy):
    id = "no-action"

    def propose(self, view: PolicyView) -> Proposal:
        none = Projection(0, view.t_h, 0, None)
        return Proposal([], none, none)


class FixedReserve(_Policy):
    id = "fixed-reserve"

    def propose(self, view: PolicyView) -> Proposal:
        obs = read(view)
        before = project(obs)
        actions: list[dict] = []
        after, cost = _defer(obs, before, actions, {})
        return Proposal(actions, before, after, cost)


class Integrated(_Policy):
    id = "integrated"

    def propose(self, view: PolicyView) -> Proposal:
        obs = read(view)
        t = obs["t_h"]
        before = project(obs)
        actions: list[dict] = []
        for o in obs["obligations"]:
            currency = o.get("currency", obs["currency"])
            if currency != obs["currency"] and t < o["due_h"] <= t + CONVERT_LEAD_H \
                    and value_in(o["amount"], currency, obs) is not None:  # priced, or not now
                actions.append({"type": "convert", "buy": {"minor": o["amount"],
                                                           "currency": currency},
                                "sell_currency": obs["currency"], "for_obligation": o["id"]})
        deferred: dict[str, int] = {}
        after, cost = _defer(obs, before, actions, deferred)
        paid_now = cost  # deferral fees leave cash; an advance's fee is owed, not paid
        drawn: list[tuple[int, int]] = []
        reason = detail = None
        if after.short_minor:
            arrival = t + HOURS_PER_ROUND
            refused = [c for c in obs["c2_seen"] if c.get("status") == "rejected"
                       and c.get("type", "request_advance") == "request_advance"]
            excluded: list[tuple[str, str | None]] = []
            for f in sorted(obs["facilities"], key=lambda f: (f.get("fee_minor", 0), f["id"])):
                why = _ineligible(f, refused, arrival, after)
                if why is not None:
                    excluded.append(why)
                    continue
                trial = project(obs, deferred=deferred, fees=paid_now,
                                advances=[*drawn, (arrival, f["principal"])])
                if trial.min_minor > after.min_minor:  # all or nothing: drawn whole or not
                    actions.append({"type": "request_advance", "facility": f["id"],
                                    "amount_minor": f["principal"]})
                    drawn.append((arrival, f["principal"]))
                    cost += f.get("fee_minor", 0)
                    after = trial
                    if not after.short_minor:
                        break
            if after.short_minor and not any(a["type"] == "request_advance" for a in actions):
                rank_ = {"facility_rejected": 0, "arrives_after_deadline": 1}
                reason, detail = min(excluded, key=lambda w: rank_.get(w[0], 2),
                                     default=("no_eligible_advance", None))
        return Proposal(actions, before, after, cost, reason, detail)


def _ineligible(f: Mapping[str, Any], refused: list[dict], arrival: int,
                now: Projection) -> tuple[str, str | None] | None:
    if any(c.get("facility") in (None, f["id"]) for c in refused):
        return "facility_rejected", None
    if f.get("state") != "offered":
        return "no_eligible_advance", f"{f['id']} is {f.get('state')}"
    deadline = f.get("arrive_by_h")
    if deadline is not None and arrival > deadline:
        return "arrives_after_deadline", f"arrival t={arrival} > arrive_by_h {deadline}"
    if now.breach_h is not None and arrival > now.breach_h:
        return "arrives_after_deadline", f"arrival t={arrival} > first breach t={now.breach_h}"
    return None


ALL: tuple[_Policy, ...] = (NoAction(), FixedReserve(), Integrated())


# --------------------------------------------------------------------- observations: branch

def _facilities(store: Any, borrower: str, terms: Mapping[str, Mapping[str, Any]],
                conn: Connection | None = None) -> list[dict]:
    out = []
    for pool in store.rows("lending_pools", conn=conn):
        for f in pool_facilities(store, pool["pool_entity_id"], conn=conn):
            if f.borrower == borrower and f.kind == "revenue_advance":
                out.append({"id": f.facility_id, "state": f.state, "lender": f.pool,
                            "principal": f.limit_minor, "currency": f.currency,
                            "fee_minor": f.fee_minor,
                            "arrive_by_h": terms.get(f.facility_id, {}).get("arrive_by_h")})
    return out


def branch_observation(world: World, conn: Connection, actor: str, *,
                       terms: Mapping[str, Mapping[str, Any]] | None = None,
                       horizon_h: int = DEFAULT_HORIZON_H) -> dict[str, Any]:
    """What ``actor`` observes of its own position at the current round of ``world``: its
    operating account, the pending flows with their promised hour and status, its open
    obligations, the advances offered to it, every C2 it has been shown, the public prices."""
    t, epoch = world.clock.t_hours, world.clock.epoch
    account = world.operating(actor)
    v = world.store.view(account, conn=conn)
    c2_seen = []
    for entry in world.state.rounds:  # committed rounds: each C2 shown the round after
        for c in entry["c2"]:
            if c.get("actor_id") != actor:
                continue
            params = world.state.intents.get(c["intent_id"], {}).get("params", {})
            c2_seen.append({"intent": c["intent_id"], "round": c["round"], "type": c["type"],
                            "status": c["status"], "reason": c.get("reason"),
                            "binding": c.get("binding"), "facility": params.get("facility_id")})
    prices: dict[str, str] = {}
    for item in world.state.items:
        if item.get("kind") == "public_price" and item.get("visible_from_h", 0) <= t:
            prices[item["pair"]] = item["rate"]
    return {
        "t_h": t, "account": account, "currency": v.currency, "horizon_h": horizon_h,
        "settled": v.settled_minor if v.observability == "known" else 0,
        "floor_minor": v.floor_minor or 0,
        "pending_in": [{"flow_id": f.flow_id, "amount": f.amount_minor,
                        "expected_h": world.state.expected_h.get(f.flow_id, due_hour(f.at, epoch)),
                        "status": world.state.flow_status.get(f.flow_id, "expected")}
                       for f in v.pending_in],
        "pending_out": [{"flow_id": f.flow_id, "amount": f.amount_minor,
                         "due_h": hours_of(f.at, epoch)} for f in v.pending_out],
        "obligations": [{"id": d.obligation_id, "amount": d.amount_minor,
                         "currency": v.currency, "due_h": hours_of(d.at, epoch),
                         "reserved": d.reservation_id is not None} for d in v.obligations],
        "outflows": [],  # this world holds no contract that lets an outflow be deferred
        "facilities": _facilities(world.store, actor, terms or {}, conn),
        "c2_seen": c2_seen, "prices": prices,
    }


def to_intent(action: Mapping[str, Any], *, policy_id: str, world: World, actor: str,
              round_: int, n: int, obs: Mapping[str, Any], evidence_ids: Sequence[str],
              obs_hash: str) -> dict:
    """A plan action as the treasury's C1 intent, marked as the policy's."""
    source = f"policy:{policy_id}"
    kind = action["type"]
    if kind == "request_advance":
        f = next(f for f in obs["facilities"] if f["id"] == action["facility"])
        params = {"amount": {"minor": action["amount_minor"], "currency": f["currency"]},
                  "from": f["lender"], "facility_id": f["id"]}
    elif kind == "defer":
        params = {"obligation_id": action["flow"], "reason": f"defer to t={action['to_h']} h"}
    elif kind == "convert":
        buy = action["buy"]
        sell = value_in(buy["minor"], buy["currency"], obs)
        if sell is None:
            raise ValueError(f"no observed {buy['currency']}/{obs['currency']} price to convert "
                             f"for {action['for_obligation']}")
        params = {"amount": {"minor": sell, "currency": action["sell_currency"]},
                  "to_currency": buy["currency"], "reason": f"for {action['for_obligation']}"}
    elif kind == "pay":
        params = {k: v for k, v in action.items() if k != "type"}
    else:
        raise ValueError(f"a policy has no tool {kind!r}")
    return {"intent_id": f"i-r{round_}-{actor}-p{n}", "branch_id": world.branch_id,
            "round": round_, "actor_id": actor, "type": kind, "params": {**params,
                                                                         "source": source},
            "evidence_ids": [e for e in evidence_ids if len(e) <= 128], "obs_hash": obs_hash,
            "priority_class": world.actors[actor].get("priority_class"),
            "sim_minute": world.clock.sim_minute}


class _Driver:
    """The policy in place of the treasury's model: decides at step 4, queues at step 5."""

    def __init__(self, policy: _Policy, actor: str, terms: Mapping[str, Any], horizon_h: int):
        self.policy, self.actor, self.terms, self.horizon_h = policy, actor, terms, horizon_h
        self.pending: tuple[Any, dict] | None = None
        self.actions: list[dict] = []
        self.decisions: list[dict] = []
        self.queued: list[dict] = []
        self.intent_ids: set[str] = set()

    def observed(self, world: World, ctx: Any) -> None:
        obs = branch_observation(world, ctx.conn, self.actor, terms=self.terms,
                                 horizon_h=self.horizon_h)
        self.pending = (guarded_decide(self.policy, view_world(obs), ctx.round), obs)

    def intents(self, world: World, ctx: Any, intents: list) -> list:
        decision, obs = self.pending
        self.pending = None
        built = [to_intent(a, policy_id=self.policy.id, world=world, actor=self.actor,
                           round_=ctx.round, n=n, obs=obs, evidence_ids=decision.evidence_ids,
                           obs_hash=decision.obs_hash)
                 for n, a in enumerate(decision.actions, 1)]
        self.actions += [{"round": ctx.round, **a} for a in decision.actions]
        self.decisions.append({"round": ctx.round, "obs_hash": decision.obs_hash,
                               "actions": decision.actions,
                               "evidence_ids": list(decision.evidence_ids)})
        self.queued += built
        self.intent_ids |= {i["intent_id"] for i in built}
        return [*intents, *built]


def _chain(*hooks: Callable | None) -> Callable:
    async def run(*args: Any) -> Any:
        result = None
        for hook in hooks:
            if hook is not None:
                result = hook(*args)
                if inspect.isawaitable(result):
                    result = await result
        return result
    return run


def _pools(world: World) -> dict[str, int]:
    return {p["pool_entity_id"]: capacity(world.store, p["pool_entity_id"], world.clock.now).K_p
            for p in world.store.rows("lending_pools")}


async def evaluate(run_id: str, cp: Checkpoint, scenarios: Mapping[str, Sequence[Mapping]],
                   policies: Sequence[_Policy] = ALL, *, model: Callable[[str, World], Any],
                   workdir: str | Path, actor: str = "treasury",
                   terms: Mapping[str, Mapping[str, Any]] | None = None,
                   horizon_h: int = DEFAULT_HORIZON_H,
                   hooks: Mapping[str, Callable] | None = None) -> list[Evaluation]:
    """Every policy on every scenario, each in a fresh branch ``<run_id>-<scenario>-<policy>``
    forked from ``cp`` with the scenario's events; returns one ``Evaluation`` per pair.

    ``model(actor_id, world)`` answers for every model actor except ``actor``, whose model is
    never called in a policy branch. ``hooks`` are the coordinator's (a family's market, say);
    the policy's own two run after them. Raises ``BranchMismatch`` when the branches of one
    scenario differ in seed or schedule, and ``AnticipationViolation`` when a policy reads what
    it could not yet observe.
    """
    to_round = horizon_h // HOURS_PER_ROUND
    if to_round <= cp.round:
        raise ValueError(f"the horizon t={horizon_h} h is not after the checkpoint")
    hooks = dict(hooks or {})
    out = []
    for sid, events in scenarios.items():
        schedule = None
        for policy in policies:
            driver = _Driver(policy, actor, terms or {}, horizon_h)
            silent = ScriptedPlan([])  # any call to the treasury's model would be recorded

            def factory(actor_id: str, world: World, _silent: ScriptedPlan = silent) -> Any:
                if actor_id == actor:
                    return _silent.model(actor_id, lambda: world.clock.round)
                return model(actor_id, world)

            coordinator = Coordinator({
                **hooks, "observed": _chain(hooks.get("observed"), driver.observed),
                "intents": _intents_after(hooks.get("intents"), driver)})
            branch = await fork(cp, f"{run_id}-{sid}-{policy.id}", model=factory,
                                workdir=workdir, scenario=list(events), coordinator=coordinator)
            async with branch:
                world = branch.world
                world.agents.pop(actor, None)  # the policy drives the treasury here
                digest = _digest(world.events)
                if schedule is None:
                    schedule = digest
                if digest != schedule or world.seed != cp.seed:
                    raise BranchMismatch(f"{world.branch_id}: its schedule or seed differs from "
                                         f"the other branches of {sid}")
                capacity_by_round: dict[str, dict[int, int]] = {}
                c2: list[dict] = []
                for _ in range(to_round - cp.round):
                    result = await world.coordinator.run_round(world)
                    for pool, k_p in _pools(world).items():
                        capacity_by_round.setdefault(pool, {})[result.round] = k_p
                    c2 += [{"round": result.round, "intent_id": c.intent_id, "type": c.type,
                            "status": c.c2.status, **({"reason": c.c2.reason} if c.c2.reason
                                                      else {}),
                            **({"binding": c.c2.binding} if c.c2.binding else {})}
                           for c in result.records if c.intent_id in driver.intent_ids]
                out.append(Evaluation(
                    scenario=sid, policy=policy.id, branch_id=world.branch_id,
                    feasibility=assess(world, world.operating(actor), from_round=cp.round,
                                       to_round=to_round),
                    actions=driver.actions, c2=c2, intents=driver.queued,
                    decisions=driver.decisions, capacity=capacity_by_round,
                    schedule_hash=digest, seed=world.seed,
                    treasury_model_calls=len(silent.calls), replay=branch.replay))
    return out


def _intents_after(first: Callable | None, driver: _Driver) -> Callable:
    async def run(world: World, ctx: Any, intents: list) -> list:
        if first is not None:
            intents = first(world, ctx, intents)
            if inspect.isawaitable(intents):
                intents = await intents
        return driver.intents(world, ctx, intents)
    return run


# ------------------------------------------------------------------ the plan for now

def snapshot_observation(snapshot: Snapshot, *, epoch: datetime, account: str | None = None,
                         terms: Mapping[str, Mapping[str, Any]] | None = None,
                         prices: Mapping[str, str] | None = None,
                         horizon_h: int | None = None) -> dict[str, Any]:
    """The treasury's position on an observed C5 snapshot, at ``as_of`` hours after ``epoch``.

    A pending inflow promised at or before ``as_of`` that is still pending is overdue.
    ``account`` defaults to the operating account of the snapshot's treasury entity.
    """
    t = hours_of(snapshot.as_of, epoch)
    if t % HOURS_PER_ROUND or snapshot.as_of != epoch + timedelta(hours=t):
        raise ValueError(f"the snapshot's as_of is not a round boundary: t={t} h")
    if account is None:
        entity = next(e.entity_id for e in snapshot.entities if e.kind == "treasury")
        account = next(a.id for a in snapshot.accounts if a.entity == entity)
    acct = next(a for a in snapshot.accounts if a.id == account)
    b = acct.buckets
    terms = terms or {}
    committed = {f.reservation_id for f in b.pending_out if f.reservation_id}  # paid as flows
    pending_in = []
    for f in b.pending_in:
        expected_h = due_hour(f.expected_at, epoch)
        pending_in.append({"flow_id": f.flow_id, "amount": f.amount.minor,
                           "expected_h": expected_h,
                           "status": "overdue" if expected_h <= t else "expected"})
    return {
        "t_h": t, "account": account, "currency": acct.currency,
        "horizon_h": horizon_h if horizon_h is not None else t + DEFAULT_HORIZON_H,
        "settled": b.settled.minor if acct.observability == "known" and b.settled else 0,
        "floor_minor": acct.floor.minor if acct.floor else 0,
        "pending_in": pending_in,
        "pending_out": [{"flow_id": f.flow_id, "amount": f.amount.minor,
                         "due_h": hours_of(f.expected_at, epoch)} for f in b.pending_out],
        "obligations": [{"id": o.obligation_id, "amount": o.amount.minor,
                         "currency": o.amount.currency, "due_h": hours_of(o.due_at, epoch),
                         "reserved": o.reservation_id is not None,
                         "reservation_id": o.reservation_id}
                        for o in snapshot.obligations
                        if o.account == account and o.state in ("open", "missed")
                        and (o.reservation_id is None or o.reservation_id not in committed)],
        "outflows": [],
        "facilities": [{"id": c.contract_id, "state": c.state, "lender": c.lender,
                        "principal": c.principal.minor, "currency": c.principal.currency,
                        "fee_minor": fee_minor(c.principal.minor, c.fee_bps),
                        "arrive_by_h": terms.get(c.contract_id, {}).get("arrive_by_h")}
                       for c in snapshot.contracts
                       if c.kind == "revenue_advance" and c.borrower == acct.entity],
        "c2_seen": [], "prices": dict(prices or {}),
    }


def plan_for_now(policy: _Policy, observed_snapshot: Snapshot, *, epoch: datetime,
                 beneficiaries: Mapping[str, str], account: str | None = None,
                 terms: Mapping[str, Mapping[str, Any]] | None = None,
                 prices: Mapping[str, str] | None = None) -> dict | None:
    """The selected policy decides again on the current observed snapshot; returns the plan
    ``{observed_snapshot_id, entity, account, legs}`` the execution module binds, or None when
    it does nothing. Funding legs come first; each obligation the funding protects (due by the
    shortfall it closes) follows as a payout leg ``after`` them. Never an approval."""
    if not is_observed_snapshot(observed_snapshot.snapshot_id):
        raise ValueError(f"not_observed_snapshot: {observed_snapshot.snapshot_id} is a branch's")
    obs = snapshot_observation(observed_snapshot, epoch=epoch, account=account, terms=terms,
                               prices=prices)
    view = PolicyView(view_world(obs), obs["t_h"] // HOURS_PER_ROUND)
    proposal = policy.propose(view)
    account, currency = obs["account"], obs["currency"]
    entity = next(a.entity for a in observed_snapshot.accounts if a.id == account)
    legs: list[dict] = []
    for action in proposal.actions:
        if action["type"] == "request_advance":
            f = next(f for f in obs["facilities"] if f["id"] == action["facility"])
            legs.append({"index": len(legs) + 1, "kind": "advance",
                         "amount": {"minor": action["amount_minor"], "currency": f["currency"]},
                         "source": f"{f['lender']}/operating", "counterparty": account,
                         "facility_id": f["id"]})
        elif action["type"] == "convert":
            buy = action["buy"]
            sell = value_in(buy["minor"], buy["currency"], obs)
            if sell is None:
                raise ValueError(f"no observed {buy['currency']}/{currency} price to convert at")
            legs.append({"index": len(legs) + 1, "kind": "fx",
                         "amount": {"minor": sell, "currency": currency},
                         "source": account, "counterparty": account,
                         "to_currency": buy["currency"]})
    if not legs:
        return None
    funding = [leg["index"] for leg in legs]
    short_at = proposal.projected_short.at_h
    for o in sorted(obs["obligations"], key=lambda o: (o["due_h"], o["id"])):
        if not obs["t_h"] < o["due_h"] <= short_at or o["currency"] != currency:
            continue
        if o["id"] not in beneficiaries:
            raise ValueError(f"no beneficiary for {o['id']}, which this plan's funding protects")
        legs.append({"index": len(legs) + 1, "kind": "payout",
                     "amount": {"minor": o["amount"], "currency": currency},
                     "source": account, "counterparty": beneficiaries[o["id"]],
                     "funded_by": f"reservation:{o['reservation_id']}" if o["reserved"]
                     else "spendable", "after": funding})
    return {"observed_snapshot_id": observed_snapshot.snapshot_id, "entity": entity,
            "account": account, "legs": legs}


# ------------------------------------------------------------------------------ the whole

async def decide(run_id: str, cp: Checkpoint, scenarios: Mapping[str, Sequence[Mapping]],
                 observed_snapshot: Snapshot, *, model: Callable[[str, World], Any],
                 workdir: str | Path, beneficiaries: Mapping[str, str],
                 policies: Sequence[_Policy] = ALL, actor: str = "treasury",
                 terms: Mapping[str, Mapping[str, Any]] | None = None,
                 horizon_h: int = DEFAULT_HORIZON_H, account: str | None = None,
                 hooks: Mapping[str, Callable] | None = None) -> DecisionResult:
    """``evaluate`` → ``rank`` → ``plan_for_now`` of the selected policy, as one result."""
    evaluations = await evaluate(run_id, cp, scenarios, policies, model=model, workdir=workdir,
                                 actor=actor, terms=terms, horizon_h=horizon_h, hooks=hooks)
    escalate_to = next((e.escalation for e in cp.snapshot.entities if e.entity_id == actor),
                       None)
    result = rank(evaluations, order=[p.id for p in policies], run_id=run_id,
                  checkpoint={"branch": cp.branch_id, "round": cp.round,
                              "snapshot_id": cp.snapshot.snapshot_id},
                  escalate_to=escalate_to)
    if result.selected is None:
        return result
    chosen = next(p for p in policies if p.id == result.selected)
    return result.with_plan(plan_for_now(chosen, observed_snapshot, epoch=cp.epoch,
                                         beneficiaries=beneficiaries, account=account,
                                         terms=terms))

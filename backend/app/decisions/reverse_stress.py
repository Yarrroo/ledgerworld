"""Reverse stress: the smallest shock that breaks the reserve floor under the selected policy
(system brief §2 "Break", §15; decisions HANDOFF ``reverse_stress``).

A search, not a forecast: every result carries ``LABEL``, nothing carries a probability, and
the cohort is ``reverse_stress``, apart from the policy comparison (nothing here ranks).

Each family is searched alone on top of a baseline, in two steps over its integer size: an
8-point grid that checks the response is monotone, then an exact integer binary search for the
smallest size that breaks it. A size breaks as ``assess`` judges a branch infeasible: the floor
breached, or an obligation unmet (a payment the cash cannot make is missed and keeps the floor,
which is worse, not better). A grid point below the found size that breaks sets
``non_monotone`` and becomes the answer; a grid point above it that holds sets it too.

The search runs on a rules-replay world, round by round on the treasury's account and the
lender pool's usable capacity: the scheduled events, the arrivals and the overdue mark of
step 2, the selected policy deciding at step 4 on a ``PolicyView`` (as in a policy branch), the
other actors' recorded money reactions at step 5, the draw cleared against K_p at step 7 (the
units arrive at the next round boundary) and the mandatory settlements of step 8. A recorded
reaction replays only while its actor has observed exactly the events it had observed when it
acted; otherwise it becomes ``no_action`` and the result says ``reactions_frozen``. One fresh
branch of the coupled world (``evaluate`` with the selected policy only) then confirms each
found point on its realised ledger; a shock the round world cannot stage (a partial delay, a
depeg loss, a silent borrower) is reported unconfirmed rather than staged differently.

``size_bps = floor(size × 10000 / scale)``; the smallest shock of a baseline is the breaking
family with the lowest ``size_bps``, ties kept in the order the families were given.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..finance.ledger import from_snapshot
from ..finance.lending import capacity
from ..finance.models import HORIZON
from ..finance.schemas import Snapshot
from ..finance.spendability import grouped
from ..finance.store import LedgerStore
from ..simulation.branches import Checkpoint
from ..simulation.world import World, due_hour, hours_of
from .candidates import DEFAULT_HORIZON_H, evaluate, snapshot_observation, view_world
from .feasibility import FloorResult
from .nonanticipativity import HOURS_PER_ROUND, guarded_decide

__all__ = ["COHORT", "LABEL", "Baseline", "FreshBranch", "Reaction", "ReplayPath",
           "SearchFamily", "borrower_silence", "confidence_rumour", "delayed_receipt",
           "fx_gap", "lender_redemption", "obligation_growth", "replay_world",
           "reverse_stress", "stablecoin_depeg"]

LABEL = "search result, not a forecast"
COHORT = "reverse_stress"
GRID_POINTS = 8
BPS = 10_000
POOL_HORIZON_H = HORIZON // timedelta(hours=1)  # K_p counts pool obligations due within it


# ------------------------------------------------------------------------------- baseline

@dataclass(frozen=True)
class Reaction:
    """One other actor's money reaction, recorded on the selected policy's branch: what it did
    to the pool's capacity and to the treasury's cash, and the event ids it had observed."""

    round: int
    actor_id: str
    seen: frozenset[str] = frozenset()
    pool_minor: int = 0  # a draw on the pool is negative
    treasury_minor: int = 0
    what: str = ""


@dataclass(frozen=True)
class FreshBranch:
    """Where a found point is confirmed: a checkpoint of the coupled world at the baseline's
    start, the model every other actor answers with, and a directory for the branch files."""

    cp: Checkpoint
    model: Callable[[str, World], Any]
    workdir: str | Path
    actor: str = "treasury"


@dataclass(frozen=True)
class Baseline:
    """The world a family is searched on: an observed snapshot, the baseline's own shock
    events, the other actors' recorded reactions and (to confirm) a fresh branch of it."""

    id: str
    snapshot: Snapshot
    epoch: datetime
    pool: str
    shock: tuple[dict, ...] = ()
    reactions: tuple[Reaction, ...] = ()
    account: str | None = None
    terms: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    horizon_h: int = DEFAULT_HORIZON_H
    branch: FreshBranch | None = None


# ------------------------------------------------------------------------------- families

@dataclass(frozen=True)
class SearchFamily:
    """A shock family's search: its size range and scale, and the events a size stands for.

    A family that cannot be searched on this baseline says why (``status``, or ``applies``
    returning one). ``descending`` families are larger shocks at smaller sizes (the first
    silent round)."""

    id: str
    range: tuple[int, int] = (0, 0)
    scale: int = 1
    events: Callable[[int], list[dict]] | None = None
    status: str | None = None
    applies: Callable[[Baseline], str | None] | None = None
    descending: bool = False

    def size_bps(self, size: int) -> int:
        return size * BPS // self.scale


def delayed_receipt(flow_id: str, *, range_: tuple[int, int], scale: int) -> SearchFamily:
    """Size: the part of ``flow_id`` that slips past the horizon (minor units), seen when the
    rest lands at its promised hour."""

    def applies(b: Baseline) -> str | None:
        promised = _flow_hours(b).get(flow_id)
        if promised is None:
            return "not_applicable"
        late = sum(e["delay_h"] for e in b.shock
                   if e["kind"] == "delay_receipt" and e["flow_id"] == flow_id)
        return "at_maximum_in_baseline" if promised + late > b.horizon_h else None

    return SearchFamily("delayed-receipt", range_, scale, applies=applies, events=lambda size: [
        {"round": None, "kind": "partial_delay", "flow_id": flow_id, "late_minor": size}]
        if size else [])


def obligation_growth(obligation_id: str, *, announce_round: int, range_: tuple[int, int],
                      scale: int) -> SearchFamily:
    """Size: how much ``obligation_id`` grows, announced at ``announce_round`` and due with it."""
    return SearchFamily("obligation-growth", range_, scale, events=lambda size: [
        {"round": announce_round, "kind": "obligation", "grows": obligation_id,
         "obligation_id": f"{obligation_id}-growth", "amount_minor": size}] if size else [])


def lender_redemption(account: str, *, announce_round: int, due_h: int,
                      range_: tuple[int, int], scale: int) -> SearchFamily:
    """Size: a new redemption owed by the pool from ``account``, announced to the pool at
    ``announce_round`` and due at ``due_h``."""
    entity = account.split("/")[0]

    def events(size: int) -> list[dict]:
        if not size:
            return []
        return [{"round": announce_round, "kind": "obligation",
                 "obligation_id": "redemption-stress", "account": account,
                 "amount_minor": size, "due_h": due_h, "kind_of": "redemption"},
                {"round": announce_round, "kind": "message",
                 "id": f"redemption-notice-r{announce_round}", "to": entity,
                 "text": f"Redemption requests of {size} USD minor units, due at t={due_h} h."}]

    return SearchFamily("lender-redemption", range_, scale, events=events)


def stablecoin_depeg(flow_id: str, *, settle_delay_h: int, range_: tuple[int, int],
                     scale: int) -> SearchFamily:
    """Size: the price drop in bps of ``flow_id`` (held as a stablecoin), which also settles
    ``settle_delay_h`` late."""
    return SearchFamily("stablecoin-depeg", range_, scale, events=lambda size: [
        {"round": None, "kind": "depeg", "flow_id": flow_id, "drop_bps": size,
         "delay_h": settle_delay_h}])


def borrower_silence(actor_id: str, *, to: str, range_: tuple[int, int],
                     scale: int) -> SearchFamily:
    """Size: the first round ``actor_id`` neither repays nor answers; ``to`` is told."""
    return SearchFamily("borrower-silence", range_, scale, descending=True,
                        events=lambda size: [{"round": size, "kind": "silence",
                                              "actor": actor_id, "to": to}])


def fx_gap() -> SearchFamily:
    """Not searched on frozen reactions: applies only where the treasury holds a second
    currency, and the replay world holds one currency."""

    def applies(b: Baseline) -> str:
        acct = _account(b)
        other = [o for o in b.snapshot.obligations
                 if o.entity == acct.entity and o.amount.currency != acct.currency]
        other += [a for a in b.snapshot.accounts
                  if a.entity == acct.entity and a.currency != acct.currency]
        return "not_replayable" if other else "not_applicable"

    return SearchFamily("fx-gap", applies=applies)


def confidence_rumour() -> SearchFamily:
    """None in money: it acts only through the agents, so frozen reactions cannot search it."""
    return SearchFamily("confidence-rumour", status="live_only")


# --------------------------------------------------------------------- rules-replay world

@dataclass(frozen=True)
class ReplayPath:
    """One run of the rules-replay world: settled by hour (the start hour is the opening),
    the floor result over the rounds after the start, and what happened, round by round."""

    settled: dict[int, int]
    floor: FloorResult
    obligations_unmet: int
    events: list[dict]
    actions: list[dict]
    reactions_frozen: bool
    floor_minor: int

    @property
    def breaks(self) -> bool:
        """As ``assess`` judges a branch infeasible: the floor breached or an obligation unmet
        (a payment the cash cannot make is missed, which keeps the floor and is worse)."""
        return self.floor.breach_h is not None or self.obligations_unmet > 0

    @property
    def margin_minor(self) -> int:
        return self.floor.min_cash - self.floor_minor


def _account(b: Baseline) -> Any:
    if b.account is not None:
        return next(a for a in b.snapshot.accounts if a.id == b.account)
    entity = next(e.entity_id for e in b.snapshot.entities if e.kind == "treasury")
    return next(a for a in b.snapshot.accounts if a.entity == entity)


def _flow_hours(b: Baseline) -> dict[str, int]:
    return {f.flow_id: due_hour(f.expected_at, b.epoch)
            for f in _account(b).buckets.pending_in}


def _pool_state(b: Baseline) -> tuple[int, dict[str, int]]:
    """K_p at the snapshot, by the ledger's own rule, and the pool's known balances."""
    store = LedgerStore("sqlite://")
    from_snapshot(store, b.snapshot)
    k_p = capacity(store, b.pool, b.snapshot.as_of).K_p
    known = {a.id: a.buckets.settled.minor for a in b.snapshot.accounts
             if a.entity == b.pool and a.observability == "known" and a.buckets.settled}
    return k_p, known


def resolve(b: Baseline, events: Sequence[Mapping[str, Any]]) -> list[dict]:
    """``events`` with what the baseline knows filled in: a flow event's round (the flow's
    promised round), a grown obligation's account, due hour and kind."""
    flows = _flow_hours(b)
    out = []
    for e in events:
        e = dict(e)
        if e["round"] is None:
            e["round"] = -(-flows[e["flow_id"]] // HOURS_PER_ROUND)
        if "grows" in e:
            o = next(o for o in b.snapshot.obligations if o.obligation_id == e["grows"])
            e |= {"account": o.account, "due_h": hours_of(o.due_at, b.epoch),
                  "kind_of": o.kind}
        out.append(e)
    return out


def _n(minor: int) -> str:
    return f"{minor:,}"


def replay_world(selected: Any, b: Baseline, events: Sequence[Mapping[str, Any]] = (),
                 *, actor: str = "treasury") -> ReplayPath:
    """Run the rules-replay world of ``b`` with ``events`` added to its shock, the selected
    policy driving the treasury, to the horizon."""
    events = resolve(b, [*b.shock, *events])
    obs0 = snapshot_observation(b.snapshot, epoch=b.epoch, account=_account(b).id,
                                terms=b.terms, horizon_h=b.horizon_h)
    t0 = obs0["t_h"]
    start, end = t0 // HOURS_PER_ROUND, b.horizon_h // HOURS_PER_ROUND
    if end <= start:
        raise ValueError(f"the horizon t={b.horizon_h} h is not after the snapshot")
    settled, floor = obs0["settled"], obs0["floor_minor"]
    flows = {f["flow_id"]: {**f, "lands_h": f["expected_h"], "value": f["amount"], "late": 0,
                            "landed": False} for f in obs0["pending_in"]}
    outs = [dict(f, paid=False) for f in obs0["pending_out"]]
    obligations = [dict(o, paid_round=None, missed=False) for o in obs0["obligations"]]
    facilities = copy.deepcopy(obs0["facilities"])
    k_p, pool_known = _pool_state(b)
    pool_due: list[tuple[int, int]] = []  # (due hour, amount) announced so far
    seen: dict[str, set[str]] = {}
    public: set[str] = set()
    silent: dict[str, int] = {}
    transit: list[tuple[int, int, str]] = []
    c2_seen: list[dict] = []
    log: list[dict] = []
    actions: list[dict] = []
    frozen = False
    by_h = {t0: settled}
    breached = False

    def say(r: int, text: str, t: int | None = None) -> None:
        log.append({"round": r, "t_h": r * HOURS_PER_ROUND,
                    "text": f"r{r}{f' (t={t})' if t is not None else ''}: {text}"})

    for r in range(start + 1, end + 1):
        t = r * HOURS_PER_ROUND
        # 2. scheduled events, then arrivals, then the overdue mark
        for e in (e for e in events if e["round"] == r):
            kind = e["kind"]
            if kind == "delay_receipt":
                flows[e["flow_id"]]["lands_h"] += e["delay_h"]
                say(r, f"{e['flow_id']} delayed {e['delay_h']} h")
            elif kind == "partial_delay":
                f = flows[e["flow_id"]]
                f["late"] = min(e["late_minor"], f["amount"])
                say(r, f"{_n(f['late'])} of {e['flow_id']} slips past the horizon")
            elif kind == "depeg":
                f = flows[e["flow_id"]]
                f["lands_h"] += e["delay_h"]
                f["value"] = f["amount"] * (BPS - e["drop_bps"]) // BPS
                say(r, f"{e['flow_id']} drops {e['drop_bps']} bps and settles "
                       f"{e['delay_h']} h late")
            elif kind == "obligation":
                if e["account"] == obs0["account"]:
                    obligations.append({"id": e["obligation_id"], "amount": e["amount_minor"],
                                        "currency": obs0["currency"], "due_h": e["due_h"],
                                        "reserved": False, "paid_round": None,
                                        "missed": False})
                    what = (f"{e['grows']} grows by {_n(e['amount_minor'])}" if "grows" in e
                            else f"{e['obligation_id']} {_n(e['amount_minor'])} owed")
                elif e["account"].split("/")[0] == b.pool:
                    pool_due.append((e["due_h"], e["amount_minor"]))
                    what = (f"the pool owes {e['obligation_id']} {_n(e['amount_minor'])} "
                            f"at t={e['due_h']}")
                else:
                    raise ValueError(f"the replay world holds no account {e['account']!r}")
                say(r, f"{what} (announced)")
            elif kind == "message":
                seen.setdefault(e["to"], set()).add(e["id"])
            elif kind == "public_post":
                public.add(e["post_id"])
            elif kind == "observe":
                if e["account"] not in pool_known or e["observability"] != "unknown":
                    raise ValueError(f"the replay world cannot observe {e['account']} "
                                     f"{e['observability']}")
                k_p -= pool_known.pop(e["account"])
                say(r, f"{e['account']} becomes unknown")
            elif kind == "silence":
                silent[e["actor"]] = r
                seen.setdefault(e["to"], set()).add(f"silence-{e['actor']}-r{r}")
                say(r, f"{e['actor']} falls silent")
            else:
                raise ValueError(f"the replay world has no event {kind!r}")
        for h, a in [x for x in pool_due if x[0] <= t + POOL_HORIZON_H]:
            k_p -= a  # an announced pool obligation comes off K_p once it is within range
            pool_due.remove((h, a))
        for f in flows.values():
            if not f["landed"] and f["lands_h"] is not None and f["lands_h"] <= t:
                amount = (f["amount"] - f["late"]) if f["late"] else f["value"]
                settled += amount
                if f["late"]:  # the rest stays promised and overdue past the horizon
                    f |= {"amount": f["late"], "lands_h": None, "late": 0}
                else:
                    f["landed"] = True
                if amount:
                    say(r, f"{f['flow_id']} {_n(amount)} arrives")
        for hour, amount, facility in [x for x in transit if x[0] <= t]:
            transit.remove((hour, amount, facility))
            settled += amount
            say(r, f"{facility} {_n(amount)} arrives")
        for f in flows.values():
            if not f["landed"] and f["expected_h"] <= t and f["status"] == "expected":
                f["status"] = "overdue"
                say(r, f"{f['flow_id']} overdue")

        # 4. the policy observes what the treasury sees, and decides
        obs = {"t_h": t, "account": obs0["account"], "currency": obs0["currency"],
               "horizon_h": b.horizon_h, "settled": settled, "floor_minor": floor,
               "pending_in": [{"flow_id": f["flow_id"], "amount": f["amount"],
                               "expected_h": f["expected_h"], "status": f["status"]}
                              for f in flows.values() if not f["landed"]],
               "pending_out": [{"flow_id": f["flow_id"], "amount": f["amount"],
                                "due_h": f["due_h"]} for f in outs if not f["paid"]],
               "obligations": [{k: o[k] for k in ("id", "amount", "currency", "due_h",
                                                  "reserved")}
                               for o in obligations if o["paid_round"] is None],
               "outflows": [], "facilities": copy.deepcopy(facilities),
               "c2_seen": list(c2_seen), "prices": {}}
        decision = guarded_decide(selected, view_world(obs), r)

        # 5. the other actors' recorded reactions, replayed while their observation matches
        for x in (x for x in b.reactions if x.round == r):
            if x.actor_id in silent and r >= silent[x.actor_id]:
                continue
            if seen.get(x.actor_id, set()) | public != set(x.seen):
                frozen = True
                say(r, f"{x.actor_id}'s recorded {x.what or 'reaction'} no longer matches: "
                       "no_action")
                continue
            k_p += x.pool_minor
            settled += x.treasury_minor
            say(r, f"{x.actor_id} {x.what or 'reacts'} (replayed)")

        # 7. the policy's intents cleared against the ledger's rules
        shown = []
        for n, a in enumerate(decision.actions, 1):
            c2 = {"intent": f"i-r{r}-{actor}-p{n}", "round": r, "type": a["type"],
                  "status": "accepted", "reason": None, "binding": None, "facility": None}
            actions.append({"round": r, **a})
            if a["type"] == "request_advance":
                f = next(f for f in facilities if f["id"] == a["facility"])
                c2["facility"] = f["id"]
                amount = a["amount_minor"]
                if f["state"] != "offered":
                    c2 |= {"status": "rejected", "reason": "not_offered"}
                elif amount > k_p:
                    c2 |= {"status": "rejected", "reason": "beyond_capacity",
                           "binding": f"K_p = {grouped(k_p, f['currency'])}"}
                else:
                    k_p -= amount
                    f["state"] = "active"
                    transit.append((t + HOURS_PER_ROUND, amount, f["id"]))
                verdict = ("" if c2["status"] == "accepted"
                           else f" — rejected, {c2['binding'] or c2['reason']}")
                say(r, f"{selected.id} requests {f['id']} {_n(amount)}{verdict}")
            elif a["type"] in ("defer", "convert"):  # as the round world refuses them
                c2 |= {"status": "rejected",
                       "reason": "not_deferrable" if a["type"] == "defer" else "no_fx_quote"}
            else:
                raise ValueError(f"the replay world has no tool {a['type']!r}")
            shown.append(c2)

        # 8. mandatory settlements: due outflows, then obligations (held ones first)
        for f in outs:
            if not f["paid"] and f["due_h"] <= t:
                settled -= f["amount"]
                f["paid"] = True
        due = sorted((o for o in obligations if o["paid_round"] is None and o["due_h"] <= t),
                     key=lambda o: (not o["reserved"], o["due_h"], o["id"]))
        for o in due:
            held = sum(x["amount"] for x in obligations
                       if x["reserved"] and x["paid_round"] is None and x is not o)
            if o["reserved"] or settled - held >= o["amount"]:
                settled -= o["amount"]
                o["paid_round"] = r
                say(r, f"{o['id']} {_n(o['amount'])} paid", t)
            elif not o["missed"]:
                o["missed"] = True
                say(r, f"{o['id']} {_n(o['amount'])} missed", t)

        by_h[t] = settled
        if settled < floor and not breached:
            breached = True
            say(r, f"settled {_n(settled)} < floor {_n(floor)}", t)
        elif settled >= floor and breached:
            breached = False
            say(r, "breach ends", t)
        c2_seen += shown  # each C2 is shown the round after

    series = [(h, v) for h, v in by_h.items() if h > t0]
    low = min(v for _, v in series)
    first = next((h for h, v in series if v < floor), None)
    breach = None
    if first is not None:
        breach = (first, next((h for h, v in series if h > first and v >= floor),
                              end * HOURS_PER_ROUND))
    unmet = sum(1 for o in obligations if start * HOURS_PER_ROUND < o["due_h"] <= b.horizon_h
                and (o["paid_round"] is None
                     or o["paid_round"] > -(-o["due_h"] // HOURS_PER_ROUND)))
    return ReplayPath(by_h, FloorResult(low, next(h for h, v in series if v == low),
                                        max(0, floor - low), breach),
                      unmet, log, actions, frozen, floor)


# --------------------------------------------------------------------------------- search

def _search(selected: Any, b: Baseline, family: SearchFamily,
            actor: str) -> tuple[dict, int | None, ReplayPath | None]:
    """The grid, then the exact binary search; returns the result, the found size (None when
    nothing in range breaks) and the replay path at it."""
    lo, hi = family.range
    span = hi - lo
    paths: dict[int, ReplayPath] = {}

    def size(k: int) -> int:  # severity k = 0 is the mildest shock of the range
        return hi - k if family.descending else lo + k

    def probe(k: int) -> ReplayPath:
        if k not in paths:
            paths[k] = replay_world(selected, b, family.events(size(k)), actor=actor)
        return paths[k]

    grid = sorted({span * n // (GRID_POINTS - 1) for n in range(GRID_POINTS)})
    breaking = [k for k in grid if probe(k).breaks]
    result: dict[str, Any] = {"label": LABEL}
    if not breaking:
        result |= {"breaks": False,
                   "min_margin_minor": min(probe(k).margin_minor for k in grid),
                   "non_monotone": False}
        found = None
    else:
        top = span if probe(span).breaks else breaking[0]
        if probe(0).breaks:
            found = 0
        else:
            below, above = 0, top  # holds at below, breaks at above
            while above - below > 1:
                mid = (below + above) // 2
                below, above = (below, mid) if probe(mid).breaks else (mid, above)
            found = above
        earlier = [k for k in breaking if k < found]
        if earlier:
            found = earlier[0]
        non_monotone = bool(earlier) or any(not probe(k).breaks for k in grid if k >= found)
        at = probe(found)
        result |= {"breaks": True, "breaking_size": size(found),
                   "size_bps": family.size_bps(size(found)),
                   "short_minor": at.floor.short_minor, "at_h": at.floor.at_h,
                   "obligations_unmet": at.obligations_unmet, "non_monotone": non_monotone}
    result |= {"reactions_frozen": any(p.reactions_frozen for p in paths.values()),
               "probes": len(paths), "grid": [size(k) for k in grid]}
    if found is None:
        return result, None, None
    return result, size(found), paths[found]


def _staged(b: Baseline, events: Sequence[Mapping[str, Any]]) -> tuple[list, list] | None:
    """``events`` as the round world stages them: world events and the pool's or treasury's
    added obligations (the ``delivered`` hook's); None when one has no staging there."""
    flows = {f.flow_id: f.amount.minor for f in _account(b).buckets.pending_in}
    world, market = [], []
    for e in resolve(b, events):
        kind = e["kind"]
        if kind in ("delay_receipt", "message", "public_post", "observe"):
            world.append(e)
        elif kind == "obligation":
            market.append(e)
        elif kind == "partial_delay" and e["late_minor"] >= flows[e["flow_id"]]:
            world.append({"round": e["round"], "kind": "delay_receipt",
                          "flow_id": e["flow_id"], "delay_h": b.horizon_h})
        else:  # a partial delay, a depeg loss, a silent borrower: no staging in the round world
            return None
    return world, market


async def _confirm(selected: Any, b: Baseline, family: SearchFamily, size: int,
                   path: ReplayPath) -> dict:
    """One fresh branch at the found point, judged on its realised ledger."""
    staged = _staged(b, [*b.shock, *family.events(size)])
    if staged is None:
        return {"confirmed": None, "unconfirmed": "no_branch_staging"}
    world_events, market = staged
    fresh = b.branch

    def deliver(world: World, ctx: Any) -> None:
        for e in market:
            if e["round"] == ctx.round:
                world.store.add_obligation(
                    e["obligation_id"], e["account"], e["amount_minor"],
                    world.clock.epoch + timedelta(hours=e["due_h"]), kind=e["kind_of"],
                    conn=ctx.conn)

    (ev,) = await evaluate(f"{COHORT}-{b.id}-{family.id}", fresh.cp, {"confirm": world_events},
                           [selected], model=fresh.model, workdir=fresh.workdir,
                           actor=fresh.actor, terms=b.terms, horizon_h=b.horizon_h,
                           hooks={"delivered": deliver})
    f = ev.feasibility
    return {"confirmed": not f.feasible, "branch_id": ev.branch_id, "replay": ev.replay,
            "matches_replay": all(path.settled.get(h) == v for h, v in f.settled.items()),
            "branch_settled": dict(f.settled)}


async def reverse_stress(selected: Any, baseline: Baseline, families: Sequence[SearchFamily],
                         confirm: bool = True, *, actor: str = "treasury") -> dict:
    """Search every family on ``baseline`` under the ``selected`` policy; returns
    ``{label, cohort, baseline, policy, results{family: …}, smallest, sensitivity_table,
    failure_path}``. With ``confirm`` each found point is re-run in one fresh branch of
    ``baseline.branch``."""
    if confirm and baseline.branch is None:
        raise ValueError(f"baseline {baseline.id} has no fresh branch to confirm in")
    if confirm and baseline.branch.cp.snapshot.snapshot_id != baseline.snapshot.snapshot_id:
        raise ValueError(f"baseline {baseline.id}'s fresh branch holds another snapshot")
    results: dict[str, dict] = {}
    found: list[tuple[int, int, str, int, ReplayPath]] = []
    for order, family in enumerate(families):
        status = family.status or (family.applies(baseline) if family.applies else None)
        if status is not None:
            results[family.id] = {"label": LABEL, "breaks": None, "status": status}
            continue
        result, size, path = _search(selected, baseline, family, actor)
        if size is not None:
            if confirm:
                result |= await _confirm(selected, baseline, family, size, path)
            found.append((result["size_bps"], order, family.id, size, path))
        results[family.id] = result

    table = [{"family": fid, "label": LABEL,
              "status": r.get("status") or ("breaks" if r["breaks"] else "holds"),
              **{k: r.get(k) for k in ("breaking_size", "size_bps", "short_minor", "at_h",
                                       "min_margin_minor", "non_monotone",
                                       "reactions_frozen", "confirmed")}}
             for fid, r in results.items()]
    smallest = failure_path = None
    if found:
        size_bps, _, fid, size, path = min(found, key=lambda x: (x[0], x[1]))
        smallest = {"family": fid, "breaking_size": size, "size_bps": size_bps}
        failure_path = {"label": LABEL, "family": fid, "settled_by_h": dict(path.settled),
                        "events": path.events, "actions": path.actions,
                        "breach_h": list(path.floor.breach_h or ()) or None,
                        "confirmed": results[fid].get("confirmed")}
    return {"label": LABEL, "cohort": COHORT, "baseline": baseline.id, "policy": selected.id,
            "results": results, "smallest": smallest, "sensitivity_table": table,
            "failure_path": failure_path}

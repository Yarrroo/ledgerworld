"""The demo world and its six scenario families (system brief §7.1, §7.3; T10).

``load_world`` reads ``scenarios/world.json``: eight synthetic actors (``actors.json`` of the
agent-world design, unchanged) and one C5 snapshot whose treasury is LF-1 and whose lender pool is
LF-2. ``load_family(id, seed, params)`` reads ``scenarios/families/<id>.json`` and turns its
parameters into what a world is hit with:

- ``events``: scheduled events the ``World`` delivers itself (``public_post``, ``delay_receipt``,
  ``message``);
- ``market``: what the round coordinator has no event kind for, applied by the family's
  ``delivered`` hook inside the round's transaction: a market-maker ``price`` (a
  ``public_price`` item, the rate a decimal string) and a grown ``obligation`` (a ledger
  obligation of the increase);
- ``overlay``: accounts, flows and obligations the family adds to the snapshot before round 1
  (the USDC redemption, the EUR invoice, the pool's standing redemption), so the base world stays
  LF-1 and LF-2 exactly.

A family file also carries ``script``, the ``ScriptedModel`` plan its demo and tests run on, and
``cleared``, the (actor, type) pairs that plan clears in the family's rounds; both fit the file's
own parameters, so a family loaded with others is not ``scripted`` and its run brings its own
model. An override the world could not run (a delay after its flow landed, a grown obligation
due before it is added) is refused at load, never mid-round. ``build_world`` puts the three
together into a ``World`` on the family's seed.

Where the round world cannot do what the design names, the family says so rather than
pretending: ``convert`` and ``defer`` are refused by the coordinator (no FX quote, no deferrable
contract), so the depeg and FX-gap families record that refusal (``refused``) and clear an
advance request instead; a depegged inflow's loss is not booked, because it settles after the
family's rounds; borrower silence is the lender's message plus a script in which the borrower
only takes ``no_action``.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from oasis_finance.observation import iso_utc

from ..finance.schemas import Snapshot
from ..testing.scripted_model import ScriptedPlan
from .clock import ROUND_HOURS
from .coordinator import Coordinator, RoundContext
from .world import ModelFactory, World

__all__ = ["FAMILY_IDS", "DemoWorld", "Family", "build_world", "load_family", "load_world"]

ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "scenarios" / "world.json"
FAMILIES_DIR = ROOT / "scenarios" / "families"
FAMILY_IDS = ("delayed-receipt", "confidence-rumour", "stablecoin-depeg", "borrower-silence",
              "redemption-spike", "fx-gap")
IDLE = {"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}
_RATE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class DemoWorld:
    world_id: str
    epoch: datetime
    actors: list[dict]
    snapshot: Snapshot


def load_world(path: str | Path = WORLD_PATH) -> DemoWorld:
    """The demo world: its actors and its C5 snapshot (validated)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    snapshot = Snapshot.model_validate(raw["snapshot"])
    epoch = datetime.fromisoformat(raw["epoch"])
    if raw["round_hours"] != ROUND_HOURS or snapshot.as_of != epoch:
        raise ValueError(f"{path}: the world starts at its epoch on {ROUND_HOURS} h rounds")
    entities = {e.entity_id for e in snapshot.entities}
    missing = [a["actor_id"] for a in raw["actors"] if a["actor_id"] not in entities]
    if missing:
        raise ValueError(f"{path}: actors with no entity in the snapshot: {missing}")
    return DemoWorld(raw["world_id"], epoch, raw["actors"], snapshot)


@dataclass(frozen=True)
class Family:
    """One parameterised, seeded shock; ``build_world`` runs it."""

    id: str
    seed: int
    starts_round: int
    rounds: int
    params: dict[str, Any]
    events: list[dict]
    market: list[dict]
    overlay: dict[str, list[dict]]
    script: list[dict]
    cleared: list[tuple[str, str]]
    refused: dict[str, str] = field(default_factory=dict)
    scripted: bool = True  # the script fits these params: they are the file's own

    @property
    def last_round(self) -> int:
        return self.starts_round + self.rounds - 1

    def snapshot(self, base: Snapshot) -> Snapshot:
        """The base snapshot with this family's accounts, flows and obligations added."""
        def at(item: dict) -> dict:  # hours from the snapshot's as_of, as C5 times
            item = copy.deepcopy(item)
            for key, field_ in (("as_of_h", "as_of"), ("due_h", "due_at"),
                                ("expected_h", "expected_at")):
                if key in item:
                    item[field_] = iso_utc(item.pop(key), base.as_of)
            return item

        snap = base.model_dump(mode="json")
        snap["accounts"] += [at(a) for a in self.overlay.get("accounts", [])]
        snap["obligations"] += [at(o) for o in self.overlay.get("obligations", [])]
        by_id = {a["id"]: a for a in snap["accounts"]}
        for flow in self.overlay.get("pending_in", []):
            flow = at(flow)
            by_id[flow.pop("account")]["buckets"]["pending_in"].append(flow)
        result = Snapshot.model_validate(snap)
        due = {f.flow_id: (f.expected_at - result.as_of) // timedelta(hours=1)
               for a in result.accounts for f in a.buckets.pending_in}
        for event in self.events:  # a delay lands before its flow does, or a round fails
            if event["kind"] == "delay_receipt" and (
                    event["flow_id"] not in due
                    or event["round"] > _due_round(due[event["flow_id"]])):
                raise ValueError(f"family {self.id}: {event['id']} in round {event['round']} "
                                 f"delays no pending flow {event['flow_id']!r} still due then")
        return result

    def plan(self) -> ScriptedPlan:
        if not self.scripted:
            raise ValueError(f"family {self.id}: its script fits the file's parameters only; "
                             "a run with other parameters brings its own model")
        return ScriptedPlan([*copy.deepcopy(self.script), IDLE], source=f"family:{self.id}")

    def deliver_market(self, world: World, ctx: RoundContext) -> None:
        """The family's market events due this round, inside the round's transaction (the
        coordinator's ``delivered`` hook): a rollback undoes them with the round."""
        t = world.clock.t_hours
        for event in self.market:
            if event["round"] != ctx.round:
                continue
            if event["kind"] == "price":
                world.state.items.append({
                    "id": event["id"], "kind": "public_price", "owner": "market-maker",
                    "visible_from_h": t, "pair": event["pair"], "rate": event["rate"]})
            elif event["kind"] == "obligation":
                world.store.add_obligation(
                    event["obligation_id"], event["account"], event["amount_minor"],
                    world.clock.epoch + timedelta(hours=event["due_h"]), kind=event["kind_of"],
                    conn=ctx.conn)
            else:
                raise ValueError(f"family {self.id}: unknown market event {event['kind']!r}")

    def coordinator(self, **kwargs: Any) -> Coordinator:
        return Coordinator({"delivered": self.deliver_market}, **kwargs)


def _int(params: Mapping[str, Any], key: str, minimum: int = 0) -> int:
    value = params[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{key} must be an integer >= {minimum}, not {value!r}")
    return value


def _rates(params: Mapping[str, Any], key: str) -> list[str]:
    path = params[key]
    if not isinstance(path, list) or not path \
            or not all(isinstance(r, str) and _RATE.match(r) for r in path):
        raise ValueError(f"{key} must be a list of decimal strings, not {path!r}")
    return path


def _prices(pair: str, tag: str, path: list[str], from_round: int) -> list[dict]:
    return [{"round": from_round + n, "kind": "price", "id": f"px-{tag}-r{from_round + n}",
             "pair": pair, "rate": rate} for n, rate in enumerate(path)]


def _due_round(hours: int) -> int:
    return -(-hours // ROUND_HOURS)


def _delayed_receipt(p: Mapping[str, Any]) -> tuple[list, list, dict]:
    event = {"round": _int(p, "at_round", 1), "kind": "delay_receipt", "flow_id": p["flow_id"],
             "delay_h": _int(p, "delay_h", 1), "id": f"delay-{p['flow_id']}"}
    return [event], [], {}


def _confidence_rumour(p: Mapping[str, Any]) -> tuple[list, list, dict]:
    if p["audience"] != "public":
        raise ValueError("a confidence rumour is public")
    r = _int(p, "post_round", 1)
    post = {"round": r, "kind": "public_post", "post_id": f"p-r{r}-1", "author": p["author"],
            "text": p["text"]}
    return [post], [], {}


def _stablecoin_depeg(p: Mapping[str, Any]) -> tuple[list, list, dict]:
    flow_id = f"{p['asset'].lower()}-redemption-1"
    expected_h = _int(p, "expected_h", 1)
    flow = {"account": "treasury/operating", "flow_id": flow_id,
            "amount": {"minor": _int(p, "pending_in_minor", 1), "currency": "USD"},
            "expected_h": expected_h, "kind": f"{p['asset']} redemption at par"}
    delay = {"round": _due_round(expected_h), "kind": "delay_receipt", "flow_id": flow_id,
             "delay_h": _int(p, "settle_delay_h", 1), "id": f"delay-{flow_id}"}
    market = _prices(f"{p['asset']}/USD", p["asset"].lower(), _rates(p, "price_path"),
                     _int(p, "path_from_round", 1))
    return [delay], market, {"pending_in": [flow]}


def _borrower_silence(p: Mapping[str, Any]) -> tuple[list, list, dict]:
    borrower, r, stops = p["borrower"], _int(p, "from_round", 1), p["stops"]
    if not isinstance(stops, list) or not stops or not set(stops) <= {"repay", "messages"}:
        raise ValueError(f"a silent borrower stops repay, messages or both, not {stops!r}")
    said = []
    if "repay" in stops:
        said.append(f"{borrower}'s scheduled repayment did not arrive")
    if "messages" in stops:
        said.append(f"{borrower} does not answer calls or messages")
    note = {"round": r, "kind": "message", "id": f"silence-{borrower}-r{r}", "to": "lender",
            "text": " and ".join(said) + "."}
    return [note], [], {}


def _redemption_spike(p: Mapping[str, Any]) -> tuple[list, list, dict]:
    before, after = _int(p, "grows_from_minor", 1), _int(p, "grows_to_minor", 1)
    if after <= before:
        raise ValueError("a redemption spike grows the obligation")
    r, due_h = _int(p, "at_round", 1), _int(p, "due_h", 1)
    if due_h <= r * ROUND_HOURS:
        raise ValueError(f"the grown redemption is due after round {r} adds it, not at {due_h} h")
    standing = {"obligation_id": "redemption-1", "entity": "lender", "account": "lender/operating",
                "amount": {"minor": before, "currency": "USD"}, "due_h": due_h,
                "kind": "redemption"}
    grown = {"round": r, "kind": "obligation", "obligation_id": "redemption-1-spike",
             "account": "lender/operating", "amount_minor": after - before, "due_h": due_h,
             "kind_of": "redemption"}
    notice = {"round": r, "kind": "message", "id": f"redemption-notice-r{r}", "to": "lender",
              "text": f"Redemption requests grew from {before} to {after} USD minor units, due "
                      f"at t={due_h} h."}
    return [notice], [grown], {"obligations": [standing]}


def _fx_gap(p: Mapping[str, Any]) -> tuple[list, list, dict]:
    currency = p["currency"]
    if currency != "EUR":
        raise ValueError(f"the FX gap's path is EUR/USD; its invoice is in EUR, not {currency!r}")
    account = f"treasury/{currency.lower()}"
    zero = {"minor": 0, "currency": currency}
    holding = {"id": account, "entity": "treasury", "currency": currency,
               "observability": "known", "as_of_h": 0,
               "buckets": {"settled": zero, "reserved": zero, "pledged": zero,
                           "pending_in": [], "pending_out": []}}
    invoice = {"obligation_id": f"supplier-{currency.lower()}-1", "entity": "treasury",
               "account": account, "amount": {"minor": _int(p, "amount_minor", 1),
                                              "currency": currency},
               "due_h": _int(p, "due_h", 1), "kind": "supplier invoice"}
    market = _prices(f"{currency}/USD", f"{currency.lower()}usd", _rates(p, "eurusd_path"),
                     _int(p, "path_from_round", 1))
    return [], market, {"accounts": [holding], "obligations": [invoice]}


BUILDERS = {
    "delayed-receipt": _delayed_receipt,
    "confidence-rumour": _confidence_rumour,
    "stablecoin-depeg": _stablecoin_depeg,
    "borrower-silence": _borrower_silence,
    "redemption-spike": _redemption_spike,
    "fx-gap": _fx_gap,
}

def load_family(family_id: str, seed: int | None = None,
                params: Mapping[str, Any] | None = None, *,
                directory: str | Path = FAMILIES_DIR) -> Family:
    """A family with its file's parameters, overridden by ``params``, on ``seed`` (the file's
    when None). ``family_id`` may be the C6 spelling (``delayed_receipt``)."""
    family_id = family_id.replace("_", "-")
    if family_id not in BUILDERS:
        raise ValueError(f"unknown scenario family {family_id!r}; one of {list(FAMILY_IDS)}")
    raw = json.loads((Path(directory) / f"{family_id}.json").read_text(encoding="utf-8"))
    unknown = set(params or {}) - set(raw["params"])
    if unknown:
        raise ValueError(f"family {family_id} has no parameters {sorted(unknown)}")
    merged = {**raw["params"], **(params or {})}
    seed = raw["seed"] if seed is None else seed
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError(f"a seed is an integer, not {seed!r}")
    events, market, overlay = BUILDERS[family_id](merged)
    script = raw["script"]
    if family_id == "borrower-silence":
        talking = [e for e in script if e.get("actor_id") == merged["borrower"]
                   and e["round"] >= merged["from_round"] and _breaks_silence(e, merged["stops"])]
        if talking:
            raise ValueError(f"{merged['borrower']} acts after it fell silent: {talking}")
    return Family(family_id, seed, raw["starts_round"], raw["rounds"], merged, events, market,
                  overlay, script, [tuple(c) for c in raw["cleared"]], raw.get("refused", {}),
                  scripted=merged == raw["params"])


def _breaks_silence(entry: Mapping[str, Any], stops: list[str]) -> bool:
    """A silent borrower that stopped messages takes nothing but ``no_action`` and says nothing;
    one that stopped repaying only never repays."""
    calls = [c["name"] for c in entry.get("tool_calls") or []]
    if "messages" in stops:
        return "content" in entry or any(name != "no_action" for name in calls)
    return "repay" in calls


def build_world(family: Family, *, model: ModelFactory | None = None, workdir: str | Path,
                branch_id: str = "base", world: DemoWorld | None = None) -> World:
    """The demo world hit by ``family``, on its seed. ``model`` defaults to the family's scripted
    plan; a live run passes its own factory."""
    world = world or load_world()
    if model is None:
        plan = family.plan()
        model = lambda actor_id, w: plan.model(actor_id, lambda: w.clock.round)
    return World(f"{world.world_id}-{family.id}", branch_id, family.snapshot(world.snapshot),
                 world.actors, model=model, workdir=workdir, scenario=family.events,
                 seed=family.seed, epoch=world.epoch, coordinator=family.coordinator())

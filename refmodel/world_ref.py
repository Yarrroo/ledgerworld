"""Executable reference model of the coupled round (system brief §7.2, agent-world HANDOFF).

Oracle for T08, stdlib only. It is not the product: no OASIS, no camel, no SQLAlchemy.
Each upstream store is a plain component of `World` so that the round's capture/restore
contract can be checked exactly:

    ledger            -> World.ledger            (accounts, obligations, pools, journals)
    OASIS SQLite      -> World.oasis             (posts, prices, outbox, time_step)
    actor memory      -> World.memory
    both clocks       -> World.clock + World.oasis["time_step"]
    RNG               -> World.rng
    event cursor      -> World.event_cursor
    pending C2        -> World.pending_c2 (+ World.c2_delivered log)
    intent queue      -> World.queue
    transcript cursor -> World.transcript (+ World.intents, World.requests: the cause records)

Money is integer minor units, USD only. Times are simulated hours; round r runs at t = 4r.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random

ROUND_HOURS = 4
HORIZON_HOURS = 72
CURRENCY = "USD"
# Priority classes (actors.json): 0 mandatory/venue · 1 treasury, lender · 2 borrowers · 3 public.
PRIORITY = {"payroll": 0, "venue": 0, "treasury": 1, "lender": 1,
            "borrower-b": 2, "borrower-c": 2, "market-maker": 3, "feed": 3}


class RoundFailed(Exception):
    """An unhandled failure in steps 1-10; the world was restored to the round-start capture."""


class WorldUnusable(Exception):
    """Quiescence could not be established after an abort; this instance refuses every retry."""


class StaleWriter(Exception):
    """A writer from an aborted round tried to write after restoration began."""


class AdmissionClosed(Exception):
    """New round work was started after the round's admission closed."""


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def is_minor(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


# ---------------------------------------------------------------- ledger

def new_ledger() -> dict:
    return {"accounts": {}, "obligations": [], "pools": {}, "floors": {}, "journals": [], "journal_seq": 0}


def account(ledger: dict, name: str) -> dict:
    return ledger["accounts"].setdefault(
        name, {"settled": 0, "reserved": 0, "pledged": 0, "pending_in": [], "pending_out": []})


def ledger_hash(ledger: dict) -> str:
    return sha(ledger)


def _counted_in(acct: dict, t: float) -> int:
    return sum(p["amount"] for p in acct["pending_in"]
               if not p.get("arrived") and not p.get("overdue") and p["expected_h"] <= t)


def spendable(ledger: dict, name: str, t: float) -> int:
    """S = settled - reserved - pledged - Σ pending_out + Σ pending_in expected ≤ t (§5)."""
    a = account(ledger, name)
    return (a["settled"] - a["reserved"] - a["pledged"]
            - sum(p["amount"] for p in a["pending_out"]) + _counted_in(a, t))


def projected(ledger: dict, name: str, t: float) -> int:
    """P = settled + Σ pending_in ≤ t - Σ pending_out - Σ unsettled obligations due ≤ t (§5)."""
    a = account(ledger, name)
    due = sum(o["amount"] for o in ledger["obligations"]
              if o["account"] == name and not o["settled"] and o["due_h"] <= t)
    return a["settled"] + _counted_in(a, t) - sum(p["amount"] for p in a["pending_out"]) - due


def floor_headroom(ledger: dict, name: str, t_now: float) -> int:
    """min over t in [now, horizon] of P(t) - floor; P only changes at event times."""
    a = account(ledger, name)
    times = {t_now} | {p["expected_h"] for p in a["pending_in"] if t_now < p["expected_h"] <= HORIZON_HOURS}
    times |= {o["due_h"] for o in ledger["obligations"]
              if o["account"] == name and t_now < o["due_h"] <= HORIZON_HOURS}
    floor = ledger["floors"].get(name, 0)
    return min(projected(ledger, name, t) for t in times) - floor


def k_p(ledger: dict, pool: str) -> int:
    """K_p = settled (all pool accounts) - committed undrawn - pledged - pool obligations - pool floor."""
    p = ledger["pools"][pool]
    names = [n for n in ledger["accounts"] if n.startswith(pool + "/")]
    settled = sum(ledger["accounts"][n]["settled"] for n in names)
    pledged = sum(ledger["accounts"][n]["pledged"] for n in names)
    undrawn = sum(c["amount"] for c in p["committed_undrawn"])
    due = sum(o["amount"] for o in ledger["obligations"]
              if o["account"] in names and not o["settled"] and o["due_h"] <= HORIZON_HOURS)
    return settled - undrawn - pledged - due - p["floor"]


def post_journal(ledger: dict, postings: list, kind: str, intent_id: str | None = None,
                 round_: int | None = None) -> dict:
    """A double-entry journal: Σ deltas = 0, all integer minor units; commits whole."""
    if any(not is_minor(d) for _, d in postings) or sum(d for _, d in postings) != 0:
        raise ValueError(f"unbalanced or non-integer journal: {postings}")
    for name, delta in postings:
        account(ledger, name)["settled"] += delta
    ledger["journal_seq"] += 1
    j = {"seq": ledger["journal_seq"], "kind": kind, "intent_id": intent_id, "round": round_,
         "postings": [list(p) for p in postings]}
    ledger["journals"].append(j)
    return j


# ---------------------------------------------------------------- intents and clearing

def sort_key(intent: dict) -> tuple:
    return (intent["priority_class"], intent["sim_minute"], intent["actor_id"], intent["intent_id"])


def drain(queue: list) -> list:
    """IntentQueue.drain: empties the queue and returns intents in clearing order."""
    out = sorted(queue, key=sort_key)
    queue.clear()
    return out


def _amount(params: dict):
    """(minor, currency) from either money shape; a malformed amount yields (None, None)."""
    if "amount" in params:
        if not isinstance(params["amount"], dict):
            return None, None
        return params["amount"].get("minor"), params["amount"].get("currency")
    if "amount_minor" in params:
        return params["amount_minor"], params.get("currency")
    return None, None


REQUIRED = {"pay": ("amount", "to"), "request_advance": ("amount", "from"), "accept": ("request",),
            "disburse": ("request", "amount", "from_account"), "no_action": ()}


def validate(intent: dict, mandates: dict) -> str | None:
    """Step 6: mandate, amount, required fields. Returns a rejection reason or None.
    The amount is checked before field presence: round-rollback's invalid intent has no `to`
    and must be rejected as `amount_not_integer_minor`."""
    if intent["actor_id"] not in mandates:
        return "unknown_actor"
    if intent["type"] not in mandates[intent["actor_id"]]:
        return "outside_mandate"
    if intent["type"] not in REQUIRED:
        return "unsupported_type"
    prm = intent["params"]
    if not isinstance(prm, dict):
        return "malformed_params"
    minor, currency = _amount(prm)
    if minor is not None or "amount" in prm:
        if not is_minor(minor):
            return "amount_not_integer_minor"
        if minor <= 0:
            return "amount_not_positive"
        if currency != CURRENCY:
            return "currency_mismatch"
    for field in REQUIRED[intent["type"]]:
        if (minor is None) if field == "amount" else (field not in prm):
            return "missing_field"
        if field != "amount" and not isinstance(prm[field], str):
            return "malformed_field"
    return None


def operating(actor_id: str) -> str:
    return f"{actor_id}/operating"


def clear(ledger: dict, requests: dict, intent: dict, t: float, round_: int) -> dict:
    """Step 7 for one validated intent. Returns its C2 result; writes at most one journal."""
    typ, prm, actor = intent["type"], intent["params"], intent["actor_id"]
    res = {"intent_id": intent["intent_id"], "actor_id": actor, "status": "accepted"}
    minor, _ = _amount(prm)

    def reject(reason, **extra):
        res.update(status="rejected", reason=reason, **extra)
        return res

    if typ == "no_action":
        return res
    if typ == "pay":
        src = operating(actor)
        s = spendable(ledger, src, t)
        if minor > s:
            return reject("insufficient_spendable", spendable_minor=s)
        h = floor_headroom(ledger, src, t)
        if minor > h:
            return reject("reserve_floor", headroom_minor=h)
        j = post_journal(ledger, [(src, -minor), (f"ext/{prm['to']}", minor)], "pay", intent["intent_id"], round_)
        res["journal_seq"] = j["seq"]
        return res
    if typ == "request_advance":
        rid = f"req:{actor}:r{round_}"
        if rid in requests:
            return reject("duplicate_request")
        requests[rid] = {"id": rid, "borrower": actor, "lender": prm["from"], "amount": minor,
                         "origin_intent": intent["intent_id"], "round": round_, "status": "open"}
        res["request"] = rid
        return res
    req = requests.get(prm.get("request"))
    if typ in ("accept", "disburse") and (req is None or req["lender"] != actor):
        return reject("unknown_request")
    if typ == "accept":
        if req["status"] != "open":
            return reject("request_not_open")
        req["status"] = "accepted"
        return res
    if typ == "disburse":
        if req["status"] != "accepted":
            return reject("request_not_accepted")
        if minor != req["amount"]:
            return reject("amount_differs_from_request")
        src = prm["from_account"]
        if not src.startswith(actor + "/"):
            return reject("not_own_account")
        if actor not in ledger["pools"]:
            return reject("no_pool")
        cap = k_p(ledger, actor)
        if minor > cap:
            return reject("capacity", K_p=cap)
        s = spendable(ledger, src, t)
        if minor > s:
            return reject("insufficient_spendable", spendable_minor=s)
        j = post_journal(ledger, [(src, -minor), (operating(req["borrower"]), minor)],
                         "disburse", intent["intent_id"], round_)
        req["status"] = "disbursed"
        res["journal_seq"] = j["seq"]
        return res
    return reject("unsupported_type")


def clear_all(ledger: dict, requests: dict, intents: list, mandates: dict, t: float, round_: int) -> list:
    """Steps 6-7: validate then clear, in the order given (the caller passes drain() output)."""
    out = []
    for it in intents:
        reason = validate(it, mandates)
        if reason:
            out.append({"intent_id": it["intent_id"], "actor_id": it["actor_id"],
                        "status": "rejected", "reason": reason})
        else:
            out.append(clear(ledger, requests, it, t, round_))
    return out


# ---------------------------------------------------------------- scripted model

class ScriptedModel:
    """Plan entries match on (actor_id, round, when_seen ⊆ seen), never on call order."""

    def __init__(self, plan: list):
        self.entries = [e for e in plan if not e.get("default")]
        self.default = next((e for e in plan if e.get("default")), None)

    def respond(self, actor_id: str, round_: int, seen: set):
        for e in self.entries:
            if e["actor_id"] == actor_id and e["round"] == round_ and set(e.get("when_seen", [])) <= seen:
                return copy.deepcopy(e["tool_calls"]), list(e.get("when_seen", []))
        if self.default is None:
            raise LookupError(f"no plan entry for {actor_id} r{round_}")
        return copy.deepcopy(self.default["tool_calls"]), []


# ---------------------------------------------------------------- world

CAPTURED = ("ledger", "oasis", "memory", "clock", "event_cursor", "pending_c2", "c2_delivered",
            "queue", "transcript", "intents", "requests", "events_delivered")


class RoundWriter:
    """The only write handle a round's actor tasks hold. Restoration bumps the world epoch,
    so a handle from the failed attempt can never write into the restored world."""

    def __init__(self, world: "World"):
        self.world, self.epoch = world, world.epoch

    def _check(self):
        if self.world.epoch != self.epoch:
            self.world.stale_write_attempts += 1
            raise StaleWriter("write from an aborted round")

    def post(self, post: dict):
        self._check()
        self.world.oasis["posts"].append(post)

    def remember(self, actor_id: str, entry: dict):
        self._check()
        self.world.memory.setdefault(actor_id, []).append(entry)

    def queue(self, intent: dict):
        self._check()
        self.world.queue.append(intent)

    def spawn(self, coro):
        try:
            self._check()
        except StaleWriter:
            coro.close()
            raise
        if not self.world.admission_open:
            coro.close()
            raise AdmissionClosed()
        task = asyncio.ensure_future(coro)
        self.world.round_tasks.append(task)
        return task


class World:
    def __init__(self, world_id: str, branch: str, ledger: dict, actors: list, plan: list,
                 scheduled_events: list = (), seed: int = 0):
        self.world_id, self.branch = world_id, branch
        self.actors = actors                               # actors.json rows
        self.mandates = {a["actor_id"]: a["tools"] for a in actors}
        self.model = ScriptedModel(plan)
        self.events = sorted((e for e in scheduled_events if e.get("branch", branch) == branch),
                             key=lambda e: e["round"])
        self.ledger = ledger
        self.oasis = {"posts": [], "prices": [], "outbox": [], "time_step": 0}
        self.memory: dict = {}
        self.clock = {"round": -1, "next_round": 0}
        self.rng = random.Random(seed)
        self.event_cursor = 0
        self.pending_c2: list = []
        self.c2_delivered: list = []
        self.queue: list = []
        self.transcript: list = []
        self.intents: dict = {}      # intent_id -> intent with evidence_ids (cause records)
        self.requests: dict = {}
        self.events_delivered: list = []
        # Not captured: lifecycle and diagnostics stay outside committed actor history.
        self.epoch = 0
        self.admission_open = True
        self.unusable = False
        self.round_tasks: list = []
        self.stale_write_attempts = 0
        self.lifecycle: list = []
        self.diagnostics: list = []
        self.hooks: dict = {}         # point name -> fn(world); test fault injection
        self.actor_hooks: dict = {}   # actor_id -> async fn(world, writer, actor_id)
        self.quiesce_timeout = 1.0    # detection bound only; never used to order events

    # -- capture / restore
    def capture(self) -> dict:
        cap = {k: copy.deepcopy(getattr(self, k)) for k in CAPTURED}
        cap["rng"] = self.rng.getstate()
        return cap

    def restore(self, cap: dict):
        for k in CAPTURED:
            setattr(self, k, copy.deepcopy(cap[k]))
        self.rng.setstate(cap["rng"])

    def fork_from(self, cap: dict) -> "World":
        """A fresh instance from a capture (the clean control)."""
        w = World(self.world_id, self.branch, None, self.actors, [], self.events, 0)
        w.model, w.events = self.model, self.events
        w.restore(cap)
        return w

    def _hook(self, point: str):
        fn = self.hooks.get(point)
        if fn:
            fn(self)

    @property
    def llm_actors(self):
        return [a["actor_id"] for a in self.actors if a.get("llm")]

    # -- step 4
    def observe(self, actor_id: str, round_: int, t: float):
        own = {n: {"settled": a["settled"], "reserved": a["reserved"], "spendable": spendable(self.ledger, n, t)}
               for n, a in sorted(self.ledger["accounts"].items()) if n.startswith(actor_id + "/")}
        msgs = [r["id"] for r in self.requests.values()
                if r["lender"] == actor_id and r["round"] < round_ and r["status"] == "open"]
        c2 = [c for c in self.pending_c2 if c["actor_id"] == actor_id]
        posts = [p for p in self.oasis["posts"] if p["round"] <= round_]
        obs = {"actor": actor_id, "round": round_, "t_hours": t, "accounts": own, "messages": sorted(msgs),
               "c2": c2, "posts": posts, "prices": [p for p in self.oasis["prices"] if p["round"] == round_],
               "memory": self.memory.get(actor_id, [])}
        return obs, sha(obs), {p["id"] for p in posts} | set(msgs)

    # -- step 5, one actor
    async def _actor_step(self, writer: RoundWriter, actor_id: str, round_: int, obs_hash: str, seen: set):
        calls, evidence = self.model.respond(actor_id, round_, seen)
        writer.remember(actor_id, {"round": round_, "obs_hash": obs_hash, "tool_calls": calls})
        for n, call in enumerate(calls, 1):
            writer.queue({"intent_id": f"i-r{round_}-{actor_id}-{n}", "actor_id": actor_id,
                          "priority_class": PRIORITY[actor_id], "sim_minute": round_ * ROUND_HOURS * 60,
                          "type": call["name"], "params": call["args"], "evidence_ids": evidence})
        hook = self.actor_hooks.get(actor_id)
        if hook:
            await hook(self, writer, actor_id)
        return calls

    # -- the round
    async def run_round(self) -> dict:
        if self.unusable:
            raise WorldUnusable("quiescence was not proved; this instance cannot retry")
        cap = self.capture()                                   # capture precedes step 1
        self.round_tasks = []
        self.admission_open = True
        try:
            return await self._steps()
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            await self._abort(cap, status, exc)
            if not isinstance(exc, Exception):                 # cancel, SystemExit, KeyboardInterrupt
                raise
            raise RoundFailed(status) from exc

    async def _abort(self, cap: dict, status: str, exc: BaseException):
        rnd = cap["clock"]["next_round"]
        self.admission_open = False                            # 1 close admission
        self.lifecycle.append(("admission_closed", rnd))
        for task in self.round_tasks:                          # 2 cancel and join, children included
            task.cancel()
        try:                                                   # admission is closed: the set cannot grow
            if self.round_tasks:
                await asyncio.wait(self.round_tasks, timeout=self.quiesce_timeout)
        except asyncio.CancelledError:                         # cancelled again mid-abort: nothing proved
            self.unusable = True
            self.diagnostics.append({"round": rnd, "status": "unusable", "error": "cancelled during abort"})
            raise
        live = [t for t in self.round_tasks if not t.done()]
        self.lifecycle.append(("joined", rnd, len(live)))
        if live:                                               # 3 quiescence unproved
            self.unusable = True
            self.diagnostics.append({"round": rnd, "status": "unusable", "error": repr(exc)})
            raise WorldUnusable("round-owned tasks survived cancellation") from exc
        self.lifecycle.append(("restore_begin", rnd))
        self.epoch += 1                                        # every old writer is now stale
        self.restore(cap)                                      # 4 restore every component
        self.lifecycle.append(("restore_end", rnd))
        self.round_tasks = []
        self.admission_open = True                             # 5 retry allowed after restoration
        self.diagnostics.append({"round": rnd, "status": status, "error": repr(exc)})

    @staticmethod
    async def _join(tasks: list):
        """Wait until every task (the list may grow) is done; the first failure or
        self-cancellation of one is raised at once, so the abort can stop the rest."""
        while True:
            for task in tasks:
                if task.done() and task.cancelled():
                    raise RuntimeError("a round-owned task was cancelled from inside the round")
                if task.done() and task.exception():
                    raise task.exception()
            live = [t for t in tasks if not t.done()]
            if not live:
                return
            await asyncio.wait(live, return_when=asyncio.FIRST_EXCEPTION)

    async def _steps(self) -> dict:
        # 1 advance the clock
        r = self.clock["next_round"]
        self.clock["round"] = r
        t = r * ROUND_HOURS
        # 2 deliver scheduled external events due now; mark undelivered arrivals overdue
        while self.event_cursor < len(self.events) and self.events[self.event_cursor]["round"] <= r:
            ev = self.events[self.event_cursor]
            self.event_cursor += 1
            self.events_delivered.append(ev.get("post_id") or ev.get("id"))
            if ev["kind"] == "public_post":
                self.oasis["outbox"].append({"id": ev["post_id"], "author": ev["author"], "text": ev["text"], "round": r})
            elif ev["kind"] == "synthetic":
                self.oasis["prices"].append({"round": r, "px": ev["px"], "source": ev["id"]})
            self._hook("after_event")
        for name, a in self.ledger["accounts"].items():
            for p in a["pending_in"]:
                if p["expected_h"] <= t and not p.get("arrived") and p.get("arrive_h", p["expected_h"]) > t:
                    p["overdue"] = True
        self._hook("before_observations")
        # 3 publish public posts (market-maker price from the seeded RNG)
        self.oasis["posts"].extend(self.oasis["outbox"])
        self.oasis["outbox"] = []
        self.oasis["prices"].append({"round": r, "px": 10000 + self.rng.randint(-100, 100), "source": "market-maker"})
        # 4 observations
        obs = {a: self.observe(a, r, t) for a in self.llm_actors}
        self.c2_delivered.extend(self.pending_c2)
        self.pending_c2 = []
        # 5 agents propose intents, concurrently
        writer = RoundWriter(self)
        tasks = [writer.spawn(self._actor_step(writer, a, r, obs[a][1], obs[a][2])) for a in self.llm_actors]
        # wait, not gather: a cancelled gather waits on its children, so one actor that refuses
        # to stop would hold the coordinator before _abort could cancel, join and detect it.
        await self._join(tasks)
        calls = [task.result() for task in tasks]
        await self._join(self.round_tasks)                     # round-owned children finish in-round
        self.oasis["time_step"] += 1
        if self.oasis["time_step"] != r + 1:
            raise RuntimeError("OASIS clock drifted from the world clock")
        # 6-7 validate and clear in deterministic order
        self._hook("before_validate")
        intents = drain(self.queue)
        for it in intents:
            self.intents[it["intent_id"]] = it
        c2 = clear_all(self.ledger, self.requests, intents, self.mandates, t, r)
        # 8 mandatory settlements: due obligations, then arrivals
        settle = []
        for o in self.ledger["obligations"]:
            if not o["settled"] and o["due_h"] <= t:
                acct = account(self.ledger, o["account"])
                if o.get("reserved"):
                    acct["reserved"] -= o["amount"]
                settle.append(post_journal(self.ledger, [(o["account"], -o["amount"]), (o["to"], o["amount"])],
                                           "settlement", None, r))
                o["settled"] = True
                self._hook("after_settlement_journal")
        for name, a in sorted(self.ledger["accounts"].items()):
            for p in a["pending_in"]:
                if not p.get("arrived") and p.get("arrive_h", p["expected_h"]) <= t:
                    settle.append(post_journal(self.ledger, [(name, p["amount"]), (f"ext/{p['source']}", -p["amount"])],
                                               "arrival", None, r))
                    p["arrived"], p["overdue"] = True, False
                    self._hook("after_settlement_journal")
        # 9 C2 results go back to actors (seen next round)
        self.pending_c2.extend(c2)
        # 10 commit and append the transcript
        self._hook("before_transcript")
        journal_ids = sorted([c["journal_seq"] for c in c2 if "journal_seq" in c] + [j["seq"] for j in settle])
        entry = {"round": r, "observations": {a: obs[a][1] for a in obs},
                 "tool_calls": dict(zip(self.llm_actors, calls)),
                 "intents": [i["intent_id"] for i in intents], "c2": c2, "journal_ids": journal_ids}
        self.transcript.append(entry)
        self.clock["next_round"] = r + 1
        self.epoch += 1                                        # durable: this round's writers retire
        self.diagnostics.append({"round": r, "status": "committed"})
        return entry

    def run(self, rounds: int) -> list:
        async def go():
            return [await self.run_round() for _ in range(rounds)]
        return asyncio.run(go())

    # -- cause chain: journal <- intent <- request <- intent <- post
    def trace(self, journal_seq: int) -> list:
        j = next(x for x in self.ledger["journals"] if x["seq"] == journal_seq)
        if j["intent_id"] is None:                             # mandatory settlement or arrival
            return [f"journal {j['seq']} ({j['kind']})"]
        chain = [f"journal of {j['intent_id']}"]

        def follow(intent_id):
            chain.append(intent_id)
            for ev in self.intents[intent_id]["evidence_ids"]:
                chain.append(ev)
                if ev in self.requests:
                    follow(self.requests[ev]["origin_intent"])

        follow(j["intent_id"])
        return chain

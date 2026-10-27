"""Executable reference model of branches, replay and the six scenario families.

An oracle for T09 (branches and replay) and T10 (scenario families), written before them and
checked against the agent-world fixtures, which it reads and never edits. Standard library
only. The world is a toy: eight actors of `actors.json`, the LF-1 treasury and the
coupled-chain lender, cleared by a deterministic coordinator in the round order of system
brief 7.2. It is a model of the rules, not of OASIS or camel: the "OASIS SQLite file" is an
in-memory SQLite database copied by its SQL dump, the model is a `ScriptedModel`, and memory
is an in-process store that enforces namespaces like the T06 fake.

Money is integer minor units throughout; prices are integers in 1e-4 (10000 = 1.0000).
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import random
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"
LEDGER_FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/ledger/fixtures"

ROUND_HOURS = 4
HORIZON_H = 72
PRICE_ONE = 10000  # 1.0000 in 1e-4 units

# Actor -> the account it books to, and the account prefix it owns.
OPERATING = {
    "treasury": "borrower-a/operating",
    "lender": "lender/operating",
    "borrower-b": "borrower-b/operating",
    "borrower-c": "borrower-c/operating",
    "venue": "exchange-venue/operating",
}
OWNER_PREFIX = {a: acc.split("/")[0] + "/" for a, acc in OPERATING.items()}
FINANCIAL_TYPES = {"request_advance", "offer", "accept", "disburse", "repay", "convert",
                   "pay", "release", "defer"}

# The nine items `branch-isolation.json` says a checkpoint contains -> the Checkpoint field.
CHECKPOINT_ITEMS = {
    "ledger state": "ledger_state",
    "world state (OASIS SQLite file copy)": "sqlite_copy",
    "immutable actor memory records and namespace id": ("immutable_memory_records", "memory_ns"),
    "world and OASIS clocks": "clocks",
    "RNG state": "rng_state",
    "scheduled-event cursor": "event_cursor",
    "pending C2 deliveries": "pending_c2",
    "empty committed-boundary intent queue": "empty_queue",
    "transcript cursor": "transcript_cursor",
}


class NamespaceViolation(Exception):
    """A memory read or write outside the caller's own namespace."""


class ScriptMiss(Exception):
    """A model call that matches no plan entry and the plan has no default."""


class ReplayDivergence(Exception):
    """A replayed round observed something other than what the transcript recorded."""


@functools.cache
def _fixture_text(path: Path) -> str:
    return path.read_text()


def load_fixture(name: str, base: Path = FIXTURES) -> dict:
    """A fresh parse of a fixture (read once from disk); callers may mutate what they get."""
    return json.loads(_fixture_text(base / name))


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(obj) -> str:
    return hashlib.sha256(obj if isinstance(obj, bytes) else canonical(obj)).hexdigest()


def namespace(world_id: str, branch_id: str) -> str:
    return f"world/{world_id}/branch/{branch_id}"


# ---------------------------------------------------------------- memory


@dataclass(frozen=True)
class MemoryRecord:
    ns: str
    actor_id: str
    key: str
    value: str
    round: int
    seq: int


class MemoryStore:
    """One store shared by every branch of a world, like hosted graph memory. Records are
    immutable; every call names the caller's namespace and may touch nothing else."""

    def __init__(self):
        self._records: list[MemoryRecord] = []

    def write(self, caller_ns: str, ns: str, actor_id: str, key: str, value: str, round_: int):
        if ns != caller_ns:
            raise NamespaceViolation(f"{caller_ns} wrote {ns}")
        rec = MemoryRecord(ns, actor_id, key, value, round_, len(self._records))
        self._records.append(rec)
        return rec

    def records(self, caller_ns: str, ns: str) -> tuple[MemoryRecord, ...]:
        if ns != caller_ns:
            raise NamespaceViolation(f"{caller_ns} read {ns}")
        return tuple(r for r in self._records if r.ns == ns)


class MemoryClient:
    """A branch's handle on the store, bound to its namespace."""

    def __init__(self, store: MemoryStore, ns: str):
        self.store, self.ns = store, ns

    def write(self, actor_id, key, value, round_):
        return self.store.write(self.ns, self.ns, actor_id, key, value, round_)

    def records(self, ns: str | None = None):
        return self.store.records(self.ns, ns or self.ns)

    def read(self, actor_id: str, key: str, ns: str | None = None):
        hits = [r for r in self.records(ns) if r.actor_id == actor_id and r.key == key]
        return hits[-1].value if hits else None

    def view(self, actor_id: str) -> dict:
        return {r.key: r.value for r in self.records() if r.actor_id == actor_id}


# ---------------------------------------------------------------- model


class ScriptedModel:
    """Answers from a plan keyed on (actor, round, what the actor saw), never call order."""

    def __init__(self, plan: list[dict], strict: bool = False):
        self.entries = [e for e in plan if not e.get("default")]
        defaults = [e for e in plan if e.get("default")]
        self.default = None if strict or not defaults else defaults[0]
        self.prompts: list[tuple[str, int, str]] = []

    @classmethod
    def from_transcript(cls, entries: list[dict]) -> "ScriptedModel":
        plan = []
        for e in entries:
            for actor_id, calls in e["tool_calls"].items():
                plan.append({"actor_id": actor_id, "round": e["round"],
                             "when_seen": e["evidence"].get(actor_id, []),
                             "tool_calls": copy.deepcopy(calls)})
        return cls(plan, strict=True)

    def respond(self, actor_id: str, round_: int, seen: set[str], obs_hash: str):
        self.prompts.append((actor_id, round_, obs_hash))
        hits = [e for e in self.entries if e["actor_id"] == actor_id and e["round"] == round_
                and set(e.get("when_seen", [])) <= seen]
        if len(hits) > 1:
            raise ScriptMiss(f"ambiguous plan for {actor_id} r{round_}")
        if hits:
            return copy.deepcopy(hits[0]["tool_calls"]), list(hits[0].get("when_seen", []))
        if self.default is None:
            raise ScriptMiss(f"no plan entry for {actor_id} r{round_}")
        return copy.deepcopy(self.default["tool_calls"]), []


# ---------------------------------------------------------------- agents and queue


class IntentQueue:
    def __init__(self):
        self._items: list[dict] = []

    def put(self, intent: dict):
        self._items.append(intent)

    def drain(self) -> list[dict]:
        # n is the call's position in the actor's response; sorting the id string would put
        # i-r1-x-10 before i-r1-x-2
        items = sorted(self._items, key=lambda i: (i["priority_class"], i["sim_minute"],
                                                    i["actor_id"], i["n"]))
        self._items = []
        return items

    def __len__(self):
        return len(self._items)


class FinanceAgent:
    """Rebuilt from its persona on every fork; its tools close over its branch's queue."""

    def __init__(self, persona: dict, queue: IntentQueue, branch_id: str):
        self.persona = persona
        self.actor_id = persona["actor_id"]
        self.queue = queue
        self.tools = {name: self._tool(name, branch_id) for name in persona["tools"]}

    def _tool(self, name, branch_id):
        queue = self.queue
        actor_id, prio = self.persona["actor_id"], self.persona["priority_class"]

        def call(round_: int, n: int, args: dict, evidence_ids: list, obs_hash: str):
            intent = {"intent_id": f"i-r{round_}-{actor_id}-{n}", "branch_id": branch_id,
                      "round": round_, "actor_id": actor_id, "type": name, "params": args,
                      "evidence_ids": list(evidence_ids), "obs_hash": obs_hash,
                      "priority_class": prio, "sim_minute": round_ * ROUND_HOURS * 60, "n": n}
            queue.put(intent)
            return f"queued {intent['intent_id']}"
        return call


# ---------------------------------------------------------------- world


def roster() -> list[dict]:
    return load_fixture("actors.json")["actors"]


def validate_c5(snap: dict) -> None:
    """Structural C5 check: the keys of system brief 8 and integer money in every bucket."""
    for k in ("snapshot_id", "as_of", "entities", "accounts", "obligations", "contracts",
              "exposures"):
        if k not in snap:
            raise ValueError(f"C5: missing {k}")
    ents = {e["entity_id"] for e in snap["entities"]}
    for a in snap["accounts"]:
        for k in ("id", "entity", "currency", "buckets"):
            if k not in a:
                raise ValueError(f"C5: account missing {k}")
        if a["entity"] not in ents:
            raise ValueError(f"C5: account {a['id']} names unknown entity {a['entity']}")
        for b in ("settled", "reserved", "pledged"):
            if not isinstance(a["buckets"].get(b, 0), int):
                raise ValueError(f"C5: {a['id']}.{b} is not integer minor units")
        for f in a["buckets"].get("pending_in", []) + a["buckets"].get("pending_out", []):
            if not isinstance(f["amount"], int):
                raise ValueError(f"C5: flow {f['flow_id']} is not integer minor units")


def toy_snapshot() -> dict:
    """LF-1's treasury (unchanged) plus the coupled-chain lender pool and two borrowers, as C5."""
    lf1 = load_fixture("lf1-treasury.json", LEDGER_FIXTURES)["snapshot"]
    chain = load_fixture("coupled-chain.json")["lender_before"]
    snap = copy.deepcopy(lf1)
    snap["snapshot_id"] = "toy-lf1-lf2"
    snap["entities"] += [
        {"entity_id": "lender", "name": "Harbour Pool (synthetic)", "kind": "lender"},
        {"entity_id": "borrower-b", "name": "Borrower B (synthetic)", "kind": "borrower"},
        {"entity_id": "borrower-c", "name": "Borrower C (synthetic)", "kind": "borrower"},
    ]
    extra = [(acc_id, "lender", b["settled"]) for acc_id, b in chain["accounts"].items()]
    extra += [("borrower-b/operating", "borrower-b", 400000),
              ("borrower-c/operating", "borrower-c", 250000)]
    for acc_id, ent, settled in extra:
        snap["accounts"].append({"id": acc_id, "entity": ent, "currency": "USD",
                                 "buckets": {"settled": settled, "reserved": 0, "pledged": 0,
                                             "unknown": None, "pending_in": [], "pending_out": []}})
    snap["contracts"] = [
        {"contract_id": "line-b", "kind": "committed_line", "lender": "lender",
         "borrower": "borrower-b", "undrawn": u["amount"]}
        for u in chain["committed_undrawn"]
    ] + [{"contract_id": "pool-floor", "kind": "pool_floor", "entity": "lender",
          "amount": chain["pool_floor"]}]
    return snap


def ledger_from_c5(snap: dict) -> dict:
    validate_c5(snap)
    accounts, flows, flows_out, obligations = {}, [], [], []
    for a in snap["accounts"]:
        b = a["buckets"]
        accounts[a["id"]] = {"entity": a["entity"], "currency": a["currency"],
                             "settled": b["settled"], "reserved": b.get("reserved", 0),
                             "pledged": b.get("pledged", 0), "unknown": False,
                             "floor": a.get("floor_minor", 0)}
        for f in b.get("pending_in", []):
            flows.append({"flow_id": f["flow_id"], "account": a["id"], "amount": f["amount"],
                          "currency": a["currency"], "expected_h": f["expected_h"],
                          "arrival_h": f["expected_h"], "status": "expected"})
        for f in b.get("pending_out", []):
            flows_out.append({"flow_id": f["flow_id"], "account": a["id"], "amount": f["amount"],
                              "due_h": f.get("due_h", f.get("expected_h")), "status": "open"})
    for o in snap["obligations"]:
        obligations.append({**o, "status": "open"})
    committed = [c for c in snap["contracts"] if c["kind"] == "committed_line"]
    floor = next((c["amount"] for c in snap["contracts"] if c["kind"] == "pool_floor"), 0)
    return {"accounts": accounts, "flows": flows, "flows_out": flows_out,
            "obligations": obligations,
            "committed_undrawn": {c["contract_id"]: {"lender": c["lender"],
                                                     "borrower": c["borrower"],
                                                     "amount": c["undrawn"]} for c in committed},
            "pool_floor": floor, "pool_obligations": {}, "facilities": {}, "requests": {},
            "loans": {}, "intents": {}, "journals": [], "unpaid": []}


def new_account(entity: str, currency: str, settled: int = 0) -> dict:
    """A ledger account with nothing reserved, pledged or unknown."""
    return {"entity": entity, "currency": currency, "settled": settled, "reserved": 0,
            "pledged": 0, "unknown": False, "floor": 0}


def arrives_by(flow: dict, t: int) -> bool:
    """A pending_in still outstanding whose arrival falls at or before t."""
    return flow["status"] in ("expected", "overdue") and flow["arrival_h"] <= t


def k_p(ledger: dict) -> int:
    """Lender usable capacity: settled (known) - committed undrawn - pledged - pool
    obligations due within the horizon - pool floor (system brief 6, LF-2)."""
    accs = [a for i, a in ledger["accounts"].items() if i.startswith("lender/")]
    settled = sum(a["settled"] for a in accs if not a["unknown"])
    pledged = sum(a["pledged"] for a in accs)
    committed = sum(c["amount"] for c in ledger["committed_undrawn"].values())
    due = sum(o["amount"] for o in ledger["pool_obligations"].values()
              if o["status"] == "open" and o["due_h"] <= HORIZON_H)
    return settled - committed - pledged - due - ledger["pool_floor"]


def projected_cash(ledger: dict, account: str, t: int) -> int:
    """LF-1 P(t) on one account: settled + arrivals by t - pending_out and obligations due by t."""
    a = ledger["accounts"][account]
    arrivals = sum(f["amount"] for f in ledger["flows"]
                   if f["account"] == account and arrives_by(f, t))
    out = sum(f["amount"] for f in ledger["flows_out"] if f["account"] == account
              and f["status"] == "open" and f["due_h"] <= t)
    due = sum(o["amount"] for o in ledger["obligations"] if o["account"] == account
              and o["status"] == "open" and o["due_h"] <= t)
    return a["settled"] + arrivals - out - due


def spendable(ledger: dict, account: str) -> int:
    """LF-1 S(now) without arrivals: a committed outflow is spoken for whatever its due time."""
    a = ledger["accounts"][account]
    out = sum(f["amount"] for f in ledger["flows_out"]
              if f["account"] == account and f["status"] == "open")
    return a["settled"] - a["reserved"] - a["pledged"] - out


@dataclass(frozen=True)
class Checkpoint:
    world_id: str
    parent: str
    after_round: int
    ledger_state: bytes
    sqlite_copy: bytes
    immutable_memory_records: tuple
    memory_ns: str
    clocks: tuple
    rng_state: tuple
    event_cursor: int
    pending_c2: bytes
    empty_queue: tuple
    transcript_cursor: int
    transcript_prefix: bytes
    events: bytes
    silenced: tuple

    def hashes(self) -> dict:
        return {"ledger": sha(self.ledger_state), "sqlite": sha(self.sqlite_copy),
                "memory": sha([asdict(r) for r in self.immutable_memory_records])}


@dataclass
class RoundResult:
    round: int
    cleared: list
    journals: list
    transcript_entry: dict
    k_p: int
    replay: bool


class World:
    def __init__(self, world_id: str, branch_id: str, ledger: dict, events: list[dict],
                 model: ScriptedModel, store: MemoryStore, seed: int, replay: bool = False,
                 memory_writes: list[dict] | None = None, sqlite_dump: str | None = None,
                 start_round: int = 0):
        self.world_id, self.branch_id, self.replay = world_id, branch_id, replay
        self.ledger = ledger
        self.events = sorted(events, key=lambda e: e["round"])
        self.event_cursor = 0
        self.model = model
        self.memory = MemoryClient(store, namespace(world_id, branch_id))
        self.rng = random.Random(seed)
        self.round = self.oasis_time_step = start_round
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(sqlite_dump or (
            "CREATE TABLE post(post_id TEXT PRIMARY KEY, round INT, author TEXT, text TEXT,"
            " audience TEXT, to_actor TEXT);"
            "CREATE TABLE price(price_id TEXT PRIMARY KEY, round INT, symbol TEXT, value INT);"))
        self.queue = IntentQueue()
        self.agents = {p["actor_id"]: FinanceAgent(p, self.queue, branch_id) for p in roster()}
        self.pending_c2: list[dict] = []
        self.transcript: list[dict] = []
        self.silenced: set[str] = set()
        self.memory_writes = list(memory_writes or [])
        self.results: list[RoundResult] = []
        self._journal_seq = 0

    # -- state views

    def sqlite_bytes(self) -> bytes:
        return "\n".join(self.db.iterdump()).encode()

    def ledger_hash(self) -> str:
        return sha(self.ledger)

    def api(self, what: str) -> dict:
        """An API-shaped response; every one carries the replay label."""
        body = {"ledger": self.ledger, "transcript": self.transcript,
                "k_p": k_p(self.ledger)}[what]
        return {"world_id": self.world_id, "branch_id": self.branch_id, "replay": self.replay,
                "data": copy.deepcopy(body)}

    # -- the round, system brief 7.2

    def run(self, rounds: int) -> list[RoundResult]:
        return [self.run_round() for _ in range(rounds)]

    def run_round(self) -> RoundResult:
        if self.queue:
            raise RuntimeError("round started with a non-empty queue")
        # 1. advance the clock
        self.round += 1
        r, t = self.round, self.round * ROUND_HOURS
        delivered = {"events": [], "c2": []}
        # 2. deliver scheduled events due now; mark overdue arrivals
        posts = []
        while self.event_cursor < len(self.events) and self.events[self.event_cursor]["round"] <= r:
            ev = self.events[self.event_cursor]
            self.event_cursor += 1
            delivered["events"].append(ev["event_id"])
            posts += self._apply_event(ev, r)
        for f in self.ledger["flows"]:
            if f["status"] == "expected" and f["expected_h"] <= t < f["arrival_h"]:
                f["status"] = "overdue"
        # 3. publish posts and prices (the market-maker draws its index from the seeded RNG)
        posts.append(("price", {"price_id": f"price:IDX:r{r}", "symbol": "IDX",
                                "value": PRICE_ONE + self.rng.randint(-50, 50)}))
        for kind, row in posts:
            if kind == "post":
                self.db.execute("INSERT INTO post VALUES(?,?,?,?,?,?)",
                                (row["post_id"], r, row["author"], row["text"],
                                 row.get("audience", "public"), row.get("to")))
            else:
                self.db.execute("INSERT INTO price VALUES(?,?,?,?)",
                                (row["price_id"], r, row["symbol"], row["value"]))
        # 4. observations (C2 of last round is delivered here, once)
        inbox = {}
        for c2 in self.pending_c2:
            inbox.setdefault(c2["to"], []).append(c2)
            delivered["c2"].append(c2["intent_id"])
        self.pending_c2 = []
        observations, evidence_seen = {}, {}
        callers = [a for a in self.agents.values()
                   if a.persona["llm"] and a.actor_id not in self.silenced]
        for a in callers:
            obs, seen = self._observe(a, t, inbox.get(a.actor_id, []))
            observations[a.actor_id] = sha(obs)
            evidence_seen[a.actor_id] = seen
        # 5. agents propose; tools only queue
        tool_calls, evidence = {}, {}
        for a in sorted(callers, key=lambda a: a.actor_id):
            calls, ev_ids = self.model.respond(a.actor_id, r, evidence_seen[a.actor_id],
                                               observations[a.actor_id])
            tool_calls[a.actor_id], evidence[a.actor_id] = calls, ev_ids
            for n, call in enumerate(calls, 1):
                if call["name"] not in a.tools:
                    raise ValueError(f"{a.actor_id} has no tool {call['name']}")
                a.tools[call["name"]](r, n, call["args"], ev_ids, observations[a.actor_id])
        mem = [w for w in self.memory_writes if w["round"] == r]
        for w in mem:
            self.memory.write(w["actor_id"], w["key"], w["value"], r)
        # 6-7. validate and clear in deterministic order
        cleared, journals = [], []
        for intent in self.queue.drain():
            status, reason, journal = self._clear(intent, r, t)
            # the ledger keeps each intent's evidence, so a trace survives a fork
            self.ledger["intents"][intent["intent_id"]] = list(intent["evidence_ids"])
            c2 = {"intent_id": intent["intent_id"], "status": status, "round": r,
                  "journal_id": journal["journal_id"] if journal else None}
            if reason:
                c2["reason"] = reason
            cleared.append({**c2, "type": intent["type"], "actor_id": intent["actor_id"],
                            "evidence_ids": intent["evidence_ids"]})
            if journal:
                journals.append(journal)
            # 9. C2 returns to the actor next round
            self.pending_c2.append({**c2, "to": intent["actor_id"]})
        # 8. mandatory settlements
        journals += self._settle(r, t)
        self.ledger["journals"] += journals
        # 10. commit and append the transcript
        self.oasis_time_step += 1
        if self.oasis_time_step != self.round:
            raise RuntimeError("OASIS clock drifted from the world clock")
        entry = {"round": r, "observations": observations, "tool_calls": tool_calls,
                 "evidence": evidence, "intents": [c["intent_id"] for c in cleared],
                 "c2": [{k: c[k] for k in ("intent_id", "status", "journal_id")} for c in cleared],
                 "journal_ids": [j["journal_id"] for j in journals], "memory": mem,
                 "delivered": delivered}
        self.transcript.append(entry)
        res = RoundResult(r, cleared, journals, entry, k_p(self.ledger), self.replay)
        self.results.append(res)
        return res

    # -- helpers

    def _apply_event(self, ev: dict, r: int) -> list:
        kind, out = ev["kind"], []
        L = self.ledger
        if kind == "public_post":
            out.append(("post", {"post_id": ev["post_id"], "author": ev["author"],
                                 "text": ev["text"], "audience": "public"}))
        elif kind == "price":
            out.append(("price", {"price_id": f"price:{ev['symbol']}:r{r}",
                                  "symbol": ev["symbol"], "value": ev["value"]}))
        elif kind == "notice":
            out.append(("post", {"post_id": ev["notice_id"], "author": "scenario",
                                 "text": ev["text"], "audience": "direct", "to": ev["to"]}))
        elif kind == "silence":
            self.silenced.add(ev["actor_id"])
        elif kind == "grow_pool_obligation":
            L["pool_obligations"][ev["obligation_id"]]["amount"] = ev["to_minor"]
            out.append(("post", {"post_id": ev["notice_id"], "author": "scenario",
                                 "text": ev["text"], "audience": "direct", "to": "lender"}))
        else:
            raise ValueError(f"unknown event kind {kind}")
        return out

    def _observe(self, agent: FinanceAgent, t: int, c2s: list) -> tuple[dict, set]:
        sees, aid = set(agent.persona["sees"]), agent.actor_id
        L, r = self.ledger, self.round
        obs: dict = {"actor_id": aid, "t_h": t}
        seen: set[str] = set()
        if "own_accounts" in sees:
            prefix = OWNER_PREFIX.get(aid, "\0")
            obs["own_accounts"] = {i: {k: a[k] for k in ("currency", "settled", "reserved",
                                                          "pledged", "unknown")}
                                   for i, a in L["accounts"].items() if i.startswith(prefix)}
            mine = [f for f in L["flows"] if f["account"].startswith(prefix)]
            obs["own_flows"] = [{k: f[k] for k in ("flow_id", "amount", "currency",
                                                   "expected_h", "status")} for f in mine]
            seen |= {f"overdue:{f['flow_id']}" for f in mine if f["status"] == "overdue"}
        if "own_contracts" in sees:
            reqs = {k: v for k, v in L["requests"].items() if aid in (v["from"], v["to"])}
            facs = {k: v for k, v in L["facilities"].items() if aid in (v["lender"], v["to"])}
            loans = {k: v for k, v in L["loans"].items() if aid in (v["lender"], v["borrower"])}
            obs["own_contracts"] = {"requests": reqs, "facilities": facs, "loans": loans}
            seen |= set(reqs) | set(facs) | set(loans)
            seen |= {u["notice_id"] for u in L["unpaid"]
                     if aid in (u["lender"], u["borrower"]) and u["round"] < r}
        if "messages_to_me" in sees:
            rows = self.db.execute("SELECT post_id, text FROM post WHERE audience='direct' AND"
                                   " to_actor=? AND round<=? ORDER BY post_id", (aid, r)).fetchall()
            obs["messages_to_me"] = {"c2": c2s, "notices": rows}
            seen |= {f"c2:{c['intent_id']}" for c in c2s} | {p for p, _ in rows}
        if "public_posts" in sees:
            rows = self.db.execute("SELECT post_id, author, text FROM post WHERE"
                                   " audience='public' AND round<=? ORDER BY round, post_id",
                                   (r,)).fetchall()
            obs["public_posts"] = rows
            seen |= {p for p, _, _ in rows}
        if "public_prices" in sees:
            rows = self.db.execute("SELECT price_id, symbol, value FROM price WHERE round<=?"
                                   " ORDER BY round, price_id", (r,)).fetchall()
            obs["public_prices"] = rows
            seen |= {p for p, _, _ in rows}
        if "memory" in sees:
            obs["memory"] = self.memory.view(aid)
        return obs, seen

    def _journal(self, r: int, intent_id: str | None, kind: str, postings: list, **extra):
        self._journal_seq += 1
        return {"journal_id": f"j-r{r}-{self._journal_seq}", "round": r, "intent_id": intent_id,
                "kind": kind, "postings": postings, **extra}

    def _post(self, postings: list):
        for p in postings:
            self.ledger["accounts"][p["account"]]["settled"] += p["amount"]

    def _price(self, symbol: str, r: int) -> int | None:
        row = self.db.execute("SELECT value FROM price WHERE symbol=? AND round<=? ORDER BY"
                              " round DESC LIMIT 1", (symbol, r)).fetchone()
        return row[0] if row else None

    def _book(self, r: int, intent: dict, kind: str, postings: list, **extra):
        self._post(postings)
        return "accepted", None, self._journal(r, intent["intent_id"], kind, postings, **extra)

    def _clear(self, intent: dict, r: int, t: int):
        """-> (status, reason, journal). Step 6 runs first: the type must be in the actor's
        mandate and every amount a positive integer; a bad intent is rejected, never repaired."""
        L, typ, p, aid = self.ledger, intent["type"], intent["params"], intent["actor_id"]
        agent = self.agents.get(aid)
        if agent is None or typ not in agent.persona["tools"]:
            return "rejected", "outside_mandate", None
        if any(isinstance(v, float) for v in p.values()):
            return "rejected", "non_integer_amount", None
        amt = p.get("amount_minor", p.get("buy_amount_minor"))
        if amt is not None and (type(amt) is not int or amt <= 0):
            return "rejected", "non_positive_amount", None
        if typ in ("no_action", "defer"):
            return "accepted", None, None
        if typ == "request_advance":
            fac = next((k for k, f in L["facilities"].items()
                        if f["to"] == aid and f["state"] == "offered"), None)
            if fac:  # an offered facility clears through lending.disburse; arrives next boundary
                f = L["facilities"][fac]
                f["state"] = "drawn"
                L["flows"].append({"flow_id": f"adv-{fac}", "account": OPERATING[aid],
                                   "amount": amt, "currency": "USD",
                                   "expected_h": t + ROUND_HOURS, "arrival_h": t + ROUND_HOURS,
                                   "status": "expected"})
                return self._book(r, intent, "disburse",
                                  [{"account": OPERATING[f["lender"]], "amount": -amt}])
            L["requests"][f"req:{aid}:r{r}"] = {
                "from": aid, "to": p["from"], "amount": amt, "currency": p["currency"],
                "status": "open", "intent_id": intent["intent_id"],
                "evidence_ids": intent["evidence_ids"]}
            return "accepted", None, None
        if typ == "accept":
            req = L["requests"].get(p["request"])
            if not req or req["to"] != aid or req["status"] != "open":
                return "rejected", "no_open_request", None
            req["status"] = "accepted"
            return "accepted", None, None
        if typ == "disburse":
            req = L["requests"].get(p["request"])
            if not req or req["to"] != aid or req["status"] != "accepted" or req["amount"] != amt:
                return "rejected", "request_not_accepted", None
            if not p["from_account"].startswith(OWNER_PREFIX[aid]):
                return "rejected", "not_own_account", None
            cap = k_p(L)
            if amt > cap:
                return "rejected", f"K_p = {cap}", None
            req["status"] = "disbursed"
            return self._book(r, intent, "disburse",
                              [{"account": p["from_account"], "amount": -amt},
                               {"account": OPERATING[req["from"]], "amount": amt}])
        if typ == "offer":
            L["facilities"][f"fac-{p['to']}-r{r}"] = {"lender": aid, "to": p["to"],
                                                      "amount": amt, "state": "offered"}
            return "accepted", None, None
        if typ == "release":
            fid = p["facility"]
            fac, line = L["facilities"].get(fid), L["committed_undrawn"].get(fid)
            if fac and fac["lender"] == aid and fac["state"] == "offered":
                fac["state"] = "withdrawn"
                return "accepted", None, None
            if line and line["lender"] == aid:
                del L["committed_undrawn"][fid]
                return "accepted", None, None
            return "rejected", "nothing_to_release", None
        if typ == "repay":
            loan = L["loans"].get(p["loan"])
            due = next((d for d in loan["due"] if d["status"] == "due"), None) if loan else None
            if not loan or loan["borrower"] != aid or due is None or amt != due["amount"]:
                return "rejected", "not_a_due_installment", None
            if spendable(L, OPERATING[aid]) < amt:
                return "rejected", "insufficient_spendable", None
            loan["outstanding"] -= amt
            due["status"], due["paid"] = "paid", amt
            return self._book(r, intent, "repay",
                              [{"account": OPERATING[aid], "amount": -amt},
                               {"account": OPERATING[loan["lender"]], "amount": amt}])
        if typ == "pay":
            if spendable(L, OPERATING[aid]) < amt:
                return "rejected", "insufficient_spendable", None
            return self._book(r, intent, "pay", [{"account": OPERATING[aid], "amount": -amt}])
        if typ == "convert":  # quote at the current public price, then the conversion
            sym = f"{p['buy_currency']}{p['sell_currency']}"
            rate = self._price(sym, r)
            if rate is None:
                return "rejected", "no_quote", None
            sell = -(-amt * rate // PRICE_ONE)  # ceil: never undershoot
            src = OPERATING[aid]
            dst = next((i for i, a in L["accounts"].items()
                        if i.startswith(OWNER_PREFIX[aid]) and a["currency"] == p["buy_currency"]),
                       None)
            if dst is None:
                return "rejected", "no_account", None
            if spendable(L, src) < sell:
                return "rejected", "insufficient_spendable", None
            return self._book(r, intent, "convert",
                              [{"account": src, "amount": -sell}, {"account": dst, "amount": amt}],
                              quote={"symbol": sym, "rate_e4": rate})
        return "rejected", f"unsupported:{typ}", None

    def _settle(self, r: int, t: int) -> list:
        L, out = self.ledger, []
        for f in L["flows"]:
            if not arrives_by(f, t):
                continue
            extra = {"flow_id": f["flow_id"]}
            if f["currency"] == "USD":
                usd = f["amount"]
            else:  # a foreign pending_in is valued only now, at the settled rate (floor)
                rate = self._price(f"{f['currency']}USD", r)
                if rate is None:  # no settled rate: its value is unknown and adds nothing
                    f["status"] = "unknown"
                    continue
                usd = f["amount"] * rate // PRICE_ONE
                extra.update(amount_in=f["amount"], currency_in=f["currency"], rate_e4=rate,
                             loss=f["amount"] - usd)
            f["status"] = "settled"
            post = [{"account": f["account"], "amount": usd}]
            self._post(post)
            out.append(self._journal(r, None, "arrival", post, **extra))
        for f in L["flows_out"]:
            if f["status"] == "open" and f["due_h"] <= t:
                f["status"] = "settled"
                post = [{"account": f["account"], "amount": -f["amount"]}]
                self._post(post)
                out.append(self._journal(r, None, "pending_out", post, flow_id=f["flow_id"]))
        for o in L["obligations"]:
            if o["status"] == "open" and o["due_h"] <= t:
                a = L["accounts"][o["account"]]
                if o.get("reservation_id"):
                    a["reserved"] = max(0, a["reserved"] - o["amount"])
                post = [{"account": o["account"], "amount": -o["amount"]}]
                self._post(post)
                o["status"] = "settled"
                out.append(self._journal(r, None, "obligation", post,
                                         obligation_id=o["obligation_id"]))
        for lid, loan in L["loans"].items():
            for d in loan["due"]:
                if d["status"] == "due" and d["due_h"] <= t:
                    d["status"], d["paid"] = "unpaid", None  # unpaid, never a zero payment
                    L["unpaid"].append({"notice_id": f"unpaid:{lid}:{d['due_h']}", "round": r,
                                        "lender": loan["lender"], "borrower": loan["borrower"],
                                        "amount_due": d["amount"]})
        return out


# ---------------------------------------------------------------- branches


def checkpoint(world: World) -> Checkpoint:
    """A committed-boundary capture: every item `branch-isolation.json` lists."""
    if len(world.queue):
        raise RuntimeError("checkpoint off a committed boundary: queue not empty")
    return Checkpoint(
        world_id=world.world_id, parent=world.branch_id, after_round=world.round,
        ledger_state=canonical(world.ledger), sqlite_copy=world.sqlite_bytes(),
        immutable_memory_records=world.memory.records(), memory_ns=world.memory.ns,
        clocks=(world.round, world.oasis_time_step), rng_state=world.rng.getstate(),
        event_cursor=world.event_cursor, pending_c2=canonical(world.pending_c2),
        empty_queue=(), transcript_cursor=len(world.transcript),
        transcript_prefix=canonical(world.transcript), events=canonical(world.events),
        silenced=tuple(sorted(world.silenced)))


def fork(cp: Checkpoint, branch_id: str, model: ScriptedModel, store: MemoryStore,
         memory_writes: list[dict] | None = None, replay: bool = False) -> World:
    """Rebuild a world from a checkpoint. Agents are rebuilt from personas (never cloned) and
    bound to the new queue; pinned memory records are copied into the new namespace; the
    ledger and the SQLite file are copies, so the parent is never written."""
    w = World(cp.world_id, branch_id, json.loads(cp.ledger_state), json.loads(cp.events),
              model, store, seed=0, replay=replay, memory_writes=memory_writes,
              sqlite_dump=cp.sqlite_copy.decode())
    for rec in cp.immutable_memory_records:
        w.memory.write(rec.actor_id, rec.key, rec.value, rec.round)
    w.round, w.oasis_time_step = cp.clocks
    w.rng.setstate(cp.rng_state)
    w.event_cursor = cp.event_cursor
    w.pending_c2 = json.loads(cp.pending_c2)
    w.transcript = json.loads(cp.transcript_prefix)
    w.silenced = set(cp.silenced)
    w._journal_seq = sum(len(e["journal_ids"]) for e in w.transcript)
    return w


def replay(branch: World, cp: Checkpoint) -> World:
    """Re-run `branch` from `cp` with no live model: a strict ScriptedModel built from the
    branch's own transcript. Uses its own memory store so it never writes the live namespace.
    Raises ReplayDivergence if any round observes something the transcript did not record."""
    entries = branch.transcript[cp.transcript_cursor:]
    model = ScriptedModel.from_transcript(entries)
    mem = [m for e in entries for m in e["memory"]]
    w = fork(cp, branch.branch_id, model, MemoryStore(), memory_writes=mem, replay=True)
    for e in entries:
        res = w.run_round()
        if res.transcript_entry["observations"] != e["observations"]:
            raise ReplayDivergence(f"round {e['round']} observations differ")
    return w


def trace(world: World, journal_id: str) -> list[str]:
    """Follow a journal back through intents, requests and evidence to its first cause. Reads
    only the ledger, so a chain that began before a fork is followed into the parent's part."""
    j = next(j for j in world.ledger["journals"] if j["journal_id"] == journal_id)
    if j["intent_id"] is None:  # a mandatory settlement has no intent behind it
        return [f"journal {journal_id} ({j['kind']})"]
    evidence, requests = world.ledger["intents"], world.ledger["requests"]
    out, frontier, seen = [f"journal of {j['intent_id']}"], [j["intent_id"]], set()
    while frontier:
        node = frontier.pop()
        if node in seen:
            continue
        seen.add(node)
        out.append(node)
        if node in evidence:
            frontier += evidence[node]
        elif node in requests:
            frontier.append(requests[node]["intent_id"])
    return out


# ---------------------------------------------------------------- the coupled-chain world


def chain_events() -> list[dict]:
    ch = load_fixture("coupled-chain.json")
    return [{"event_id": e["post_id"], **e} for e in ch["scheduled_events"]
            if e.get("branch") == "shock"]


def main_world(store: MemoryStore, seed: int = 7) -> World:
    """The parent `main` of `branch-isolation.json`: the shock world on the coupled-chain plan,
    with one toy memory record before the checkpoint so the pinned record set is not empty."""
    plan = load_fixture("coupled-chain.json")["plan"]
    bi = load_fixture("branch-isolation.json")
    return World(bi["world_id"], bi["parent"], ledger_from_c5(toy_snapshot()), chain_events(),
                 ScriptedModel(plan), store, seed,
                 memory_writes=[{"round": 2, "actor_id": "borrower-c", "key": "note",
                                 "value": "watching the venue"}])


def branch_plan(fork_spec: dict) -> list[dict]:
    plan = load_fixture("coupled-chain.json")["plan"]
    if fork_spec["branch_id"] == "no-action":
        return [e for e in plan if e.get("default")]
    return plan


# ---------------------------------------------------------------- the six scenario families


def price_events(symbol: str, path: list[float], start: int) -> list[dict]:
    """A public price path as scheduled events, one per round from `start`, in 1e-4 units."""
    return [{"event_id": f"px-{i}", "round": start + i, "kind": "price", "symbol": symbol,
             "value": round(px * PRICE_ONE)} for i, px in enumerate(path)]


def _family_world(fam: dict) -> tuple[dict, list[dict], list[dict]]:
    """The toy ledger, the family's shock as data-driven scheduled events, and the
    ScriptedModel plan that answers it."""
    fid, p, start = fam["id"], fam["params"], fam["starts_round"]
    ledger = ledger_from_c5(toy_snapshot())
    events: list[dict] = []
    plan: list[dict] = [{"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}]
    if fid == "delayed-receipt":
        f = next(f for f in ledger["flows"] if f["flow_id"] == "rcv-1")
        f["arrival_h"] = f["expected_h"] + p["delay_h"]
        plan += [
            {"actor_id": "treasury", "round": start, "when_seen": ["overdue:rcv-1"],
             "tool_calls": [{"name": "request_advance", "args": {
                 "amount_minor": 1000000, "currency": "USD", "from": "lender",
                 "reason": "receivable overdue"}}]},
            {"actor_id": "lender", "round": start + 1, "when_seen": [f"req:treasury:r{start}"],
             "tool_calls": [{"name": "accept", "args": {"request": f"req:treasury:r{start}"}},
                            {"name": "disburse", "args": {
                                "request": f"req:treasury:r{start}", "amount_minor": 1000000,
                                "currency": "USD", "from_account": "lender/operating"}}]}]
    elif fid == "confidence-rumour":
        events += [{"event_id": "p-r3-1", "round": p["post_round"], "kind": "public_post",
                    "post_id": "p-r3-1", "author": "feed", "text": p["post"]}]
        plan = load_fixture("coupled-chain.json")["plan"]
    elif fid == "stablecoin-depeg":
        ledger["accounts"]["borrower-a/usdc-in"] = new_account("borrower-a", "USD")
        start_h = start * ROUND_HOURS
        ledger["flows"].append({"flow_id": "usdc-1", "account": "borrower-a/usdc-in",
                                "amount": p["pending_in_minor"], "currency": p["asset"],
                                "expected_h": start_h,
                                "arrival_h": start_h + p["settle_delay_h"], "status": "expected"})
        events += price_events(f"{p['asset']}USD", p["price_path"], start)
        plan.append({"actor_id": "treasury", "round": start + 1,
                     "when_seen": [f"price:{p['asset']}USD:r{start + 1}"],
                     "tool_calls": [{"name": "defer", "args": {"what": "usdc-1 conversion",
                                                                "until_h": start_h + p["settle_delay_h"]}}]})
    elif fid == "borrower-silence":
        b, due_h = p["borrower"], start * ROUND_HOURS
        ledger["loans"]["loan-b"] = {"lender": "lender", "borrower": b, "outstanding": 1080000,
                                     "due": [{"due_h": due_h, "amount": 360000, "status": "due"}]}
        events.append({"event_id": "silence", "round": p["from_round"], "kind": "silence",
                       "actor_id": b})
        plan += [
            {"actor_id": b, "round": start, "tool_calls": [
                {"name": "repay", "args": {"loan": "loan-b", "amount_minor": 360000,
                                           "currency": "USD"}}]},
            {"actor_id": "lender", "round": start + 1, "when_seen": [f"unpaid:loan-b:{due_h}"],
             "tool_calls": [{"name": "release", "args": {"facility": "line-b"}}]}]
    elif fid == "redemption-spike":
        ledger["pool_obligations"]["redemption-1"] = {"amount": p["grows_from_minor"],
                                                      "due_h": 60, "status": "open"}
        ledger["facilities"]["fac-c"] = {"lender": "lender", "to": "borrower-c",
                                         "amount": 500000, "state": "offered"}
        events.append({"event_id": "spike", "round": p["at_round"],
                       "kind": "grow_pool_obligation", "obligation_id": "redemption-1",
                       "to_minor": p["grows_to_minor"], "notice_id": "evt:redemption-spike",
                       "text": "lender redemption grows"})
        plan.append({"actor_id": "lender", "round": p["at_round"],
                     "when_seen": ["evt:redemption-spike"],
                     "tool_calls": [{"name": "release", "args": {"facility": "fac-c"}}]})
    elif fid == "fx-gap":
        ledger["accounts"]["borrower-a/eur"] = new_account("borrower-a", "EUR")
        ledger["obligations"].append({"obligation_id": "eur-invoice", "account": "borrower-a/eur",
                                      "amount": 1000000, "due_h": 36, "kind": "supplier",
                                      "status": "open"})
        events += price_events("EURUSD", p["eurusd_path"], start)
        plan.append({"actor_id": "treasury", "round": start + 1,
                     "when_seen": [f"price:EURUSD:r{start + 1}"],
                     "tool_calls": [{"name": "convert", "args": {
                         "sell_currency": "USD", "buy_currency": "EUR",
                         "buy_amount_minor": 1000000}}]})
    else:
        raise ValueError(f"unknown family {fid}")
    return ledger, events, plan


def run_family(fam: dict, rounds: int = 3, seed: int | None = None) -> World:
    """Run one family for `rounds` rounds on ScriptedModel from the round it starts in."""
    ledger, events, plan = _family_world(fam)
    w = World(f"fam-{fam['id']}", "base", ledger, events, ScriptedModel(plan), MemoryStore(),
              fam["seed"] if seed is None else seed, start_round=fam["starts_round"] - 1)
    w.run(rounds)
    return w


def cleared_financial(world: World) -> list[dict]:
    return [c for res in world.results for c in res.cleared
            if c["status"] == "accepted" and c["type"] in FINANCIAL_TYPES]

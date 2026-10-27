"""Checks the branch/replay/families reference model against the agent-world fixtures.

Run: python -m unittest discover -s refmodel -p test_branch_ref.py
Every fixture is loaded unchanged; the module fails if any fixture file's bytes change.
"""

import hashlib
import unittest

import branch_ref as br

FIXTURE_FILES = [br.FIXTURES / n for n in ("branch-isolation.json", "scenario-families.json",
                                           "coupled-chain.json", "actors.json")]
FIXTURE_FILES.append(br.LEDGER_FIXTURES / "lf1-treasury.json")
_BEFORE = {}


def setUpModule():
    for f in FIXTURE_FILES:
        _BEFORE[f] = hashlib.sha256(f.read_bytes()).hexdigest()


def tearDownModule():
    for f, h in _BEFORE.items():
        if hashlib.sha256(f.read_bytes()).hexdigest() != h:
            raise AssertionError(f"fixture changed: {f}")


BI = br.load_fixture("branch-isolation.json")
SF = br.load_fixture("scenario-families.json")
CC = br.load_fixture("coupled-chain.json")


def run_forks(store=None):
    """main to round 3, checkpoint, then each fork of the fixture to round 6."""
    store = store or br.MemoryStore()
    parent = br.main_world(store)
    parent.run(BI["checkpoint"]["after_round"])
    cp = br.checkpoint(parent)
    forks = {}
    for spec in BI["forks"]:
        writes = [w for w in BI["memory_writes"] if w["branch_id"] == spec["branch_id"]]
        w = br.fork(cp, spec["branch_id"], br.ScriptedModel(br.branch_plan(spec)), store, writes)
        w.run(6 - cp.after_round)
        forks[spec["branch_id"]] = w
    return store, parent, cp, forks


class CheckpointAndFork(unittest.TestCase):
    def test_checkpoint_holds_every_listed_item(self):
        _, parent, cp, _ = run_forks()
        self.assertEqual(set(br.CHECKPOINT_ITEMS), set(BI["checkpoint"]["contains"]))
        for item, fields in br.CHECKPOINT_ITEMS.items():
            for f in (fields if isinstance(fields, tuple) else (fields,)):
                self.assertTrue(hasattr(cp, f), item)
        self.assertEqual(cp.after_round, 3)
        self.assertEqual(cp.clocks, (3, 3))
        self.assertEqual(cp.empty_queue, ())
        self.assertTrue(cp.immutable_memory_records, "pinned memory must not be empty")
        self.assertTrue(cp.pending_c2 != b"[]", "round-3 C2 are pending at the boundary")
        self.assertEqual(cp.memory_ns, "world/w1/branch/main")

    def test_fork_rebuilds_agents_bound_to_its_own_queue(self):
        _, _, _, forks = run_forks()
        a, b = forks["no-action"], forks["integrated"]
        for w in (a, b):
            for aid, agent in w.agents.items():
                self.assertIsInstance(agent, br.FinanceAgent)
                persona = next(p for p in br.roster() if p["actor_id"] == aid)
                self.assertEqual(sorted(agent.tools), sorted(persona["tools"]))
                self.assertIs(agent.queue, w.queue)
        self.assertIsNot(a.queue, b.queue)
        a.agents["lender"].tools["no_action"](9, 1, {}, [], "h")
        self.assertEqual((len(a.queue), len(b.queue)), (1, 0))
        a.queue.drain()

    def test_sibling_read_raises_namespace_violation(self):
        exp = BI["expect"]["sibling_read"]
        _, _, _, forks = run_forks()
        self.assertEqual(exp["result"], "raises NamespaceViolation")
        with self.assertRaises(br.NamespaceViolation):
            forks[exp["from"]].memory.read("borrower-c", "note", ns=exp["namespace"])
        with self.assertRaises(br.NamespaceViolation):
            forks[exp["from"]].memory.store.write(
                forks[exp["from"]].memory.ns, exp["namespace"], "borrower-c", "note", "x", 4)

    def test_own_read(self):
        exp = BI["expect"]["own_read"]
        _, _, _, forks = run_forks()
        self.assertEqual(forks[exp["branch_id"]].memory.read("borrower-c", exp["key"]),
                         exp["value"])
        self.assertEqual(forks["no-action"].memory.read("borrower-c", "note"), "waited")

    def test_checkpoint_memory_immutable(self):
        store = br.MemoryStore()
        parent = br.main_world(store)
        parent.run(3)
        cp = br.checkpoint(parent)
        parent.memory.write("borrower-c", "note", "written after the checkpoint", 4)
        late = br.fork(cp, "late", br.ScriptedModel(br.branch_plan({"branch_id": "no-action"})),
                       store)
        self.assertEqual(late.memory.read("borrower-c", "note"), "watching the venue")
        self.assertEqual(len(late.memory.records()), len(cp.immutable_memory_records))

    def test_checkpoint_continuation_delivers_once_with_matching_observations(self):
        store = br.MemoryStore()
        parent = br.main_world(store)
        parent.run(3)
        cp = br.checkpoint(parent)
        pending = [c["intent_id"] for c in br.json.loads(cp.pending_c2)]
        f = br.fork(cp, "integrated", br.ScriptedModel(CC["plan"]), store)
        f.run(3)
        parent.run(3)  # the clean continuation from the same capture
        self.assertEqual(f.transcript[3]["observations"], parent.transcript[3]["observations"])
        for w in (f, parent):
            events = [e for x in w.transcript for e in x["delivered"]["events"]]
            c2 = [c for x in w.transcript for c in x["delivered"]["c2"]]
            self.assertEqual(events.count("p-r3-1"), 1)
            self.assertEqual(len(c2), len(set(c2)))
            for iid in pending:
                self.assertEqual(c2.count(iid), 1)
            self.assertEqual(w.transcript[3]["delivered"]["c2"], pending)

    def test_parent_unchanged(self):
        _, parent, cp, forks = run_forks()
        self.assertTrue(all(w.round == 6 for w in forks.values()))
        h = cp.hashes()
        self.assertEqual(parent.ledger_hash(), h["ledger"])
        self.assertEqual(br.sha(parent.sqlite_bytes()), h["sqlite"])
        self.assertEqual(parent.memory.records(), cp.immutable_memory_records)
        self.assertEqual(parent.round, 3)

    def test_branch_ledgers_differ_k_p_round_5(self):
        _, _, _, forks = run_forks()
        k = {b: next(r.k_p for r in w.results if r.round == 5) for b, w in forks.items()}
        self.assertEqual(k, {"no-action": 4200000, "integrated": 3000000})
        self.assertEqual(CC["lender_before"]["K_p"], 4200000)

    def test_integrated_branch_reproduces_coupled_chain(self):
        _, _, _, forks = run_forks()
        w, exp = forks["integrated"], CC["expect"]["shock"]
        by_round = {r.round: r for r in w.results}
        r4 = [c for c in by_round[4].cleared if c["actor_id"] == "borrower-c"][0]
        self.assertEqual((r4["intent_id"], r4["type"], r4["evidence_ids"], r4["status"],
                          r4["journal_id"]),
                         (exp["round_4"]["intent"], exp["round_4"]["type"],
                          exp["round_4"]["evidence_ids"], exp["round_4"]["c2_status"], None))
        r5 = [c for c in by_round[5].cleared if c["actor_id"] == "lender"]
        self.assertEqual([c["intent_id"] for c in r5], exp["round_5"]["intents"])
        self.assertTrue(all(c["status"] == "accepted" for c in r5))
        self.assertEqual(len(by_round[5].journals), exp["round_5"]["journals"])
        accts = w.ledger["accounts"]
        for acc, v in exp["lender_after"].items():
            self.assertEqual(accts[acc]["settled"], v["settled"])
        self.assertEqual(accts["borrower-c/operating"]["settled"] - 250000,
                         exp["borrower_c_after"]["borrower-c/operating"]["settled_increase"])
        self.assertEqual(br.k_p(w.ledger), exp["K_p_after"])
        self.assertEqual(br.trace(w, by_round[5].journals[0]["journal_id"]), exp["trace"])
        self.assertTrue(all(len(x["observations"]) <= 6 for x in w.transcript))


class Replay(unittest.TestCase):
    def test_replay_identity(self):
        _, _, cp, forks = run_forks()
        live = forks["integrated"]
        rep = br.replay(live, cp)
        self.assertIsNone(rep.model.default, "replay model has no default: nothing improvised")
        self.assertEqual(len(rep.model.prompts), len(live.model.prompts))
        self.assertEqual(br.canonical(rep.ledger["journals"]), br.canonical(live.ledger["journals"]))
        self.assertEqual(rep.ledger_hash(), live.ledger_hash())
        self.assertEqual(br.sha(rep.sqlite_bytes()), br.sha(live.sqlite_bytes()))
        self.assertEqual(rep.memory.read("borrower-c", "note"), "asked for 12,000.00")

    def test_replay_detects_divergence(self):
        _, _, cp, forks = run_forks()
        live = forks["integrated"]
        live.transcript[3]["observations"]["lender"] = "0" * 64
        with self.assertRaises(br.ReplayDivergence):
            br.replay(live, cp)

    def test_replay_label(self):
        _, _, cp, forks = run_forks()
        live = forks["integrated"]
        rep = br.replay(live, cp)
        for what in ("ledger", "transcript", "k_p"):
            self.assertIs(rep.api(what)["replay"], True)
            self.assertIs(live.api(what)["replay"], False)
        self.assertTrue(all(r.replay for r in rep.results))
        self.assertFalse(any(r.replay for r in live.results))


def family(fid):
    return next(f for f in SF["families"] if f["id"] == fid)


class ScenarioFamilies(unittest.TestCase):
    def check_family(self, fid, want_types, want_actor):
        fam = family(fid)
        w = br.run_family(fam, SF["expect_all"]["rounds_each"])
        self.assertEqual([r.round for r in w.results],
                         [fam["starts_round"] + i for i in range(SF["expect_all"]["rounds_each"])])
        got = br.cleared_financial(w)
        self.assertGreaterEqual(len(got), SF["expect_all"]["min_cleared_financial_actions_each"])
        self.assertTrue(any(c["type"] in want_types and c["actor_id"] == want_actor for c in got),
                        f"{fid}: {fam['expect_cleared']} not cleared; got {got}")
        again = br.run_family(fam, SF["expect_all"]["rounds_each"])
        self.assertEqual(br.canonical(w.ledger["journals"]), br.canonical(again.ledger["journals"]))
        self.assertEqual(w.transcript, again.transcript)
        return w

    def test_world_validates_against_c5(self):
        self.assertEqual(SF["expect_all"]["world_validates_against"], "C5")
        br.validate_c5(br.toy_snapshot())
        bad = br.toy_snapshot()
        bad["accounts"][0]["buckets"]["settled"] = 1.5
        with self.assertRaises(ValueError):
            br.validate_c5(bad)

    def test_six_families_with_seeds(self):
        self.assertEqual(len(SF["families"]), SF["expect_all"]["families"])
        self.assertEqual(len({f["seed"] for f in SF["families"]}), 6)
        for f in SF["families"]:
            br._family_world(f)  # every family loads as data

    def test_delayed_receipt(self):
        fam = family("delayed-receipt")
        ledger, _, _ = br._family_world(fam)
        p40 = br.projected_cash(ledger, "borrower-a/operating", 40)
        floor = ledger["accounts"]["borrower-a/operating"]["floor"]
        self.assertEqual((p40, floor, floor - p40), (2000000, 3000000, 1000000))
        w = self.check_family("delayed-receipt", {"request_advance", "defer"}, "treasury")
        # the lender's answer is LF-1's integrated plan: the floor holds at 30,000.00
        self.assertEqual(br.projected_cash(w.ledger, "borrower-a/operating", 40), 3000000)

    def test_confidence_rumour(self):
        w = self.check_family("confidence-rumour", {"request_advance"}, "borrower-c")
        self.assertEqual(br.k_p(w.ledger), CC["expect"]["shock"]["K_p_after"])

    def test_stablecoin_depeg(self):
        w = self.check_family("stablecoin-depeg", {"convert", "defer"}, "treasury")
        self.assertFalse([j for j in w.ledger["journals"] if j.get("flow_id") == "usdc-1"],
                         "no loss is booked before the pending_in settles")
        w.run(10 - w.round)  # settles at t = 16 + 24 = 40, round 10
        j = [j for j in w.ledger["journals"] if j.get("flow_id") == "usdc-1"]
        self.assertEqual(len(j), 1)
        self.assertEqual((j[0]["rate_e4"], j[0]["postings"][0]["amount"], j[0]["loss"]),
                         (9800, 1470000, 30000))

    def test_borrower_silence(self):
        w = self.check_family("borrower-silence", {"release", "offer"}, "lender")
        due = w.ledger["loans"]["loan-b"]["due"][0]
        self.assertEqual((due["status"], due["paid"], due["amount"]), ("unpaid", None, 360000))
        self.assertFalse([j for j in w.ledger["journals"] if j["kind"] == "repay"])
        self.assertFalse(any(p["amount"] == 0 for j in w.ledger["journals"] for p in j["postings"]))
        self.assertTrue(all("borrower-b" not in x["observations"] for x in w.transcript))

    def test_redemption_spike(self):
        fam = family("redemption-spike")
        ledger, _, _ = br._family_world(fam)
        before = br.k_p(ledger)
        w = self.check_family("redemption-spike", {"release"}, "lender")
        rise = fam["params"]["grows_to_minor"] - fam["params"]["grows_from_minor"]
        self.assertEqual(before - br.k_p(w.ledger), rise)
        self.assertEqual(w.ledger["facilities"]["fac-c"]["state"], "withdrawn")

    def test_fx_gap(self):
        w = self.check_family("fx-gap", {"convert", "defer"}, "treasury")
        j = [j for j in w.ledger["journals"] if j["kind"] == "convert"][0]
        self.assertEqual(j["quote"], {"symbol": "EURUSD", "rate_e4": 11100})
        self.assertEqual([p["amount"] for p in j["postings"]], [-1110000, 1000000])


if __name__ == "__main__":
    unittest.main()

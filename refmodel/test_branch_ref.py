"""Checks the branch/replay/families reference model against the agent-world fixtures.

Run: python -m unittest discover -s refmodel -p test_branch_ref.py
Every fixture is loaded unchanged; the module fails if any fixture file's bytes change.
"""

import json
import unittest

import branch_ref as br

FIXTURE_FILES = [br.FIXTURES / n for n in ("branch-isolation.json", "scenario-families.json",
                                           "coupled-chain.json", "actors.json")]
FIXTURE_FILES.append(br.LEDGER_FIXTURES / "lf1-treasury.json")
_BEFORE = {}


def setUpModule():
    for f in FIXTURE_FILES:
        _BEFORE[f] = br.sha(f.read_bytes())


def tearDownModule():
    for f, h in _BEFORE.items():
        if br.sha(f.read_bytes()) != h:
            raise AssertionError(f"fixture changed: {f}")


BI = br.load_fixture("branch-isolation.json")
SF = br.load_fixture("scenario-families.json")
CC = br.load_fixture("coupled-chain.json")


def parent_at_checkpoint(store):
    """`main` run to the fixture's checkpoint round, and the checkpoint."""
    parent = br.main_world(store)
    parent.run(BI["checkpoint"]["after_round"])
    return parent, br.checkpoint(parent)


def run_forks(store=None):
    """main to round 3, checkpoint, then each fork of the fixture to round 6."""
    store = store or br.MemoryStore()
    parent, cp = parent_at_checkpoint(store)
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
        personas = {p["actor_id"]: p for p in br.roster()}
        for w in (a, b):
            for aid, agent in w.agents.items():
                self.assertIsInstance(agent, br.FinanceAgent)
                persona = personas[aid]
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
        parent, cp = parent_at_checkpoint(store)
        parent.memory.write("borrower-c", "note", "written after the checkpoint", 4)
        late = br.fork(cp, "late", br.ScriptedModel(br.branch_plan({"branch_id": "no-action"})),
                       store)
        self.assertEqual(late.memory.read("borrower-c", "note"), "watching the venue")
        self.assertEqual(len(late.memory.records()), len(cp.immutable_memory_records))

    def test_checkpoint_continuation_delivers_once_with_matching_observations(self):
        store = br.MemoryStore()
        parent, cp = parent_at_checkpoint(store)
        pending = [c["intent_id"] for c in json.loads(cp.pending_c2)]
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
        fam, n = family(fid), SF["expect_all"]["rounds_each"]
        w = br.run_family(fam, n)
        self.assertEqual([r.round for r in w.results],
                         [fam["starts_round"] + i for i in range(n)])
        got = br.cleared_financial(w)
        self.assertGreaterEqual(len(got), SF["expect_all"]["min_cleared_financial_actions_each"])
        self.assertTrue(any(c["type"] in want_types and c["actor_id"] == want_actor for c in got),
                        f"{fid}: {fam['expect_cleared']} not cleared; got {got}")
        again = br.run_family(fam, n)
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


def toy_world(events=()):
    return br.World("t", "b", br.ledger_from_c5(br.toy_snapshot()), list(events),
                    br.ScriptedModel(CC["plan"][-1:]), br.MemoryStore(), 1)


def intent(aid, typ, params, n=1, r=1):
    return {"intent_id": f"i-r{r}-{aid}-{n}", "branch_id": "b", "round": r, "actor_id": aid,
            "type": typ, "params": params, "evidence_ids": [], "obs_hash": "h",
            "priority_class": 1, "sim_minute": 0, "n": n}


class Validation(unittest.TestCase):
    """Step 6 of the round: mandate, authority and amounts are checked before clearing."""

    def test_disburse_only_from_the_lenders_own_account(self):
        w = toy_world()
        w.ledger["requests"]["req:borrower-c:r1"] = {
            "from": "borrower-c", "to": "lender", "amount": 100000, "currency": "USD",
            "status": "accepted", "intent_id": "i-r1-borrower-c-1", "evidence_ids": []}
        before = w.ledger["accounts"]["borrower-b/operating"]["settled"]
        st, _, _ = w._clear(intent("lender", "disburse", {
            "request": "req:borrower-c:r1", "amount_minor": 100000, "currency": "USD",
            "from_account": "borrower-b/operating"}), 1, 4)
        self.assertEqual(st, "rejected")
        self.assertEqual(w.ledger["accounts"]["borrower-b/operating"]["settled"], before)

    def test_non_positive_amount_rejected(self):
        w = toy_world()
        for amt in (-5000000, 0):
            st, reason, _ = w._clear(intent("treasury", "pay", {"amount_minor": amt}), 1, 4)
            self.assertEqual((st, reason), ("rejected", "non_positive_amount"))
        self.assertEqual(w.ledger["accounts"]["borrower-a/operating"]["settled"], 7000000)

    def test_repay_only_by_the_borrower_and_in_full(self):
        w = toy_world()
        w.ledger["loans"]["loan-b"] = {"lender": "lender", "borrower": "borrower-b",
                                       "outstanding": 1080000,
                                       "due": [{"due_h": 24, "amount": 360000, "status": "due"}]}
        st, _, _ = w._clear(intent("borrower-c", "repay", {"loan": "loan-b", "amount_minor": 360000}), 1, 4)
        self.assertEqual(st, "rejected")
        st, _, _ = w._clear(intent("borrower-b", "repay", {"loan": "loan-b", "amount_minor": 1}), 1, 4)
        self.assertEqual(st, "rejected")
        self.assertEqual(w.ledger["loans"]["loan-b"]["due"][0]["status"], "due")
        st, _, _ = w._clear(intent("borrower-b", "repay", {"loan": "loan-b", "amount_minor": 360000}), 1, 4)
        self.assertEqual(st, "accepted")

    def test_release_outside_mandate_rejected(self):
        w = toy_world()
        before = br.k_p(w.ledger)
        st, reason, _ = w._clear(intent("borrower-b", "release", {"facility": "line-b"}), 1, 4)
        self.assertEqual((st, reason), ("rejected", "outside_mandate"))
        self.assertEqual(br.k_p(w.ledger), before)

    def test_convert_without_a_target_account_is_rejected_not_raised(self):
        w = toy_world()
        w.db.execute("INSERT INTO price VALUES('price:GBPUSD:r1', 1, 'GBPUSD', 12700)")
        st, reason, _ = w._clear(intent("treasury", "convert", {
            "sell_currency": "USD", "buy_currency": "GBP", "buy_amount_minor": 1000}), 1, 4)
        self.assertEqual((st, reason), ("rejected", "no_account"))

    def test_clearing_order_numeric_within_an_actor(self):
        q = br.IntentQueue()
        for n in range(11, 0, -1):
            q.put(intent("lender", "no_action", {}, n=n))
        self.assertEqual([i["intent_id"] for i in q.drain()],
                         [f"i-r1-lender-{n}" for n in range(1, 12)])


class ValidationRound2(unittest.TestCase):
    def accepted_request(self, w, amount=100000):
        w.ledger["requests"]["req:borrower-c:r1"] = {
            "from": "borrower-c", "to": "lender", "amount": amount, "currency": "USD",
            "status": "accepted", "intent_id": "i-r1-borrower-c-1", "evidence_ids": []}

    def test_disburse_from_a_missing_or_short_account_is_rejected(self):
        w = toy_world()
        self.accepted_request(w)
        st, _, _ = w._clear(intent("lender", "disburse", {
            "request": "req:borrower-c:r1", "amount_minor": 100000, "currency": "USD",
            "from_account": "lender/typo"}), 1, 4)
        self.assertEqual(st, "rejected")
        self.accepted_request(w, 2000000)  # lender/venue holds 1,500,000
        st, reason, _ = w._clear(intent("lender", "disburse", {
            "request": "req:borrower-c:r1", "amount_minor": 2000000, "currency": "USD",
            "from_account": "lender/venue"}), 1, 4)
        self.assertEqual((st, reason), ("rejected", "insufficient_spendable"))

    def test_missing_amount_is_rejected(self):
        w = toy_world()
        for aid, typ, params in (("treasury", "pay", {}), ("lender", "offer", {"to": "borrower-c"}),
                                 ("borrower-c", "request_advance",
                                  {"currency": "USD", "from": "lender"})):
            st, reason, _ = w._clear(intent(aid, typ, params), 1, 4)
            self.assertEqual((st, reason), ("rejected", "missing_amount"), typ)

    def test_two_requests_in_one_response_keep_both(self):
        w = toy_world()
        for n in (1, 2):
            w._clear(intent("treasury", "request_advance", {
                "amount_minor": 1000 * n, "currency": "USD", "from": "lender"}, n=n), 1, 4)
        self.assertEqual({k: v["amount"] for k, v in w.ledger["requests"].items()},
                         {"req:treasury:r1": 1000, "req:treasury:r1-2": 2000})

    def test_lender_pending_out_lowers_k_p(self):
        snap = br.toy_snapshot()
        lender = next(a for a in snap["accounts"] if a["id"] == "lender/operating")
        lender["buckets"]["pending_out"] = [{"flow_id": "po-l", "amount": 800000, "due_h": 60}]
        self.assertEqual(br.k_p(br.ledger_from_c5(snap)), 4200000 - 800000)

    def test_c5_rejects_untimed_pending_out_and_lenderless_line(self):
        snap = br.toy_snapshot()
        snap["accounts"][0]["buckets"]["pending_out"] = [{"flow_id": "po-1", "amount": 5}]
        with self.assertRaises(ValueError):
            br.validate_c5(snap)
        snap = br.toy_snapshot()
        del snap["contracts"][0]["lender"]
        with self.assertRaises(ValueError):
            br.validate_c5(snap)

    def test_unpriced_arrival_settles_once_a_rate_appears(self):
        w = toy_world([{"event_id": "px", "round": 2, "kind": "price", "symbol": "USDCUSD",
                        "value": 9900}])
        w.ledger["accounts"]["borrower-a/usdc-in"] = br.new_account("borrower-a", "USD")
        w.ledger["flows"].append({"flow_id": "usdc-x", "account": "borrower-a/usdc-in",
                                  "amount": 1000, "currency": "USDC", "expected_h": 4,
                                  "arrival_h": 4, "status": "expected"})
        w.run(2)
        self.assertEqual(w.ledger["accounts"]["borrower-a/usdc-in"]["settled"], 990)

    def test_observation_shows_own_pending_out(self):
        snap = br.toy_snapshot()
        snap["accounts"][0]["buckets"]["pending_out"] = [
            {"flow_id": "po-1", "amount": 600000, "due_h": 60}]
        w = br.World("t", "b", br.ledger_from_c5(snap), [],
                     br.ScriptedModel(CC["plan"][-1:]), br.MemoryStore(), 1)
        w.round = 1
        obs, _ = w._observe(w.agents["treasury"], 4, [])
        self.assertEqual([f["flow_id"] for f in obs["own_flows_out"]], ["po-1"])


class LedgerAndTrace(unittest.TestCase):
    def test_pending_out_counts_in_projection_and_spendability(self):
        snap = br.toy_snapshot()
        snap["accounts"][0]["buckets"]["pending_out"] = [
            {"flow_id": "po-1", "amount": 2000000, "due_h": 20}]
        ledger = br.ledger_from_c5(snap)
        self.assertEqual(br.projected_cash(ledger, "borrower-a/operating", 20), 7000000)
        self.assertEqual(br.spendable(ledger, "borrower-a/operating"), 0)

    def test_foreign_arrival_without_a_price_is_unknown_not_a_crash(self):
        w = toy_world()
        w.ledger["accounts"]["borrower-a/usdc-in"] = br.new_account("borrower-a", "USD")
        w.ledger["flows"].append({"flow_id": "usdc-x", "account": "borrower-a/usdc-in",
                                  "amount": 1000, "currency": "USDC", "expected_h": 4,
                                  "arrival_h": 4, "status": "expected"})
        w.run(1)
        flow = next(f for f in w.ledger["flows"] if f["flow_id"] == "usdc-x")
        self.assertEqual(flow["status"], "unknown")
        self.assertEqual(w.ledger["accounts"]["borrower-a/usdc-in"]["settled"], 0)

    def test_trace_crosses_a_fork(self):
        store = br.MemoryStore()
        _, cp = parent_at_checkpoint(store)
        f1 = br.fork(cp, "integrated", br.ScriptedModel(CC["plan"]), store)
        f1.run(1)  # round 4: borrower-c asks
        f2 = br.fork(br.checkpoint(f1), "integrated-2", br.ScriptedModel(CC["plan"]), store)
        res = f2.run(1)[0]  # round 5: the lender disburses
        self.assertEqual(br.trace(f2, res.journals[0]["journal_id"]),
                         CC["expect"]["shock"]["trace"])

    def test_trace_of_a_settlement_journal(self):
        w = toy_world()
        w.run(3)  # rcv-1 arrives at t=12
        j = next(j for j in w.ledger["journals"] if j.get("flow_id") == "rcv-1")
        self.assertEqual(br.trace(w, j["journal_id"]), [f"journal {j['journal_id']} (arrival)"])


if __name__ == "__main__":
    unittest.main()

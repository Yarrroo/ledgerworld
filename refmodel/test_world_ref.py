"""Reference-model checks against the agent-world fixtures, loaded unchanged from prp/.

Run: python -m unittest discover -s refmodel -p test_world_ref.py
"""

import asyncio
import json
import unittest
from pathlib import Path

import world_ref as wr

FIX = Path(__file__).resolve().parent.parent / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


ACTORS = load("actors")["actors"]
MANDATES = {a["actor_id"]: a["tools"] for a in ACTORS}
CASH, FLOOR, PAYROLL = 7_000_000, 3_000_000, 5_000_000   # LF-1, system brief §6, USD minor units


def lf1_ledger(shock: bool) -> dict:
    """LF-1 treasury at t=0 (§6); the shock delays the 20,000.00 receivable by 240 h."""
    led = wr.new_ledger()
    acct = wr.account(led, "treasury/operating")
    acct["settled"], acct["reserved"] = CASH, PAYROLL
    receivable = {"id": "receivable", "amount": 2_000_000, "expected_h": 12, "source": "customer"}
    if shock:
        receivable["arrive_h"] = 12 + 240
    acct["pending_in"] = [receivable, {"id": "withdrawal", "amount": 1_500_000, "expected_h": 48, "source": "venue"}]
    led["floors"]["treasury/operating"] = FLOOR
    led["obligations"].append({"id": "payroll", "account": "treasury/operating", "amount": PAYROLL,
                               "due_h": 40, "reserved": True, "to": "payroll/operating", "settled": False})
    return led


class Clearing(unittest.TestCase):
    """clearing-order.json: any arrival permutation gives one cleared order, one C2 set, one ledger."""

    fx = load("clearing-order")

    def ledger(self):
        led = lf1_ledger(shock=False)
        for name, b in self.fx["ledger_before"].items():
            a = wr.account(led, name)
            a["settled"] = b["settled"]
            a["reserved"] = b.get("reserved", 0)
        tre = led["accounts"]["treasury/operating"]
        expected = {(p["amount"], p["expected_h"]) for p in self.fx["ledger_before"]["treasury/operating"]["pending_in"]}
        self.assertEqual({(p["amount"], p["expected_h"]) for p in tre["pending_in"]}, expected)
        return led

    def run_order(self, order, sort=True, floor=True):
        by_id = {i["intent_id"]: i for i in self.fx["intents"]}
        queue = [dict(by_id[i]) for i in order]
        intents = wr.drain(queue) if sort else queue
        led = self.ledger()
        if not floor:
            led["floors"].clear()
        c2 = wr.clear_all(led, {}, intents, MANDATES, 0, 0)
        return [i["intent_id"] for i in intents], c2, led

    def test_spendable_now(self):
        led = self.ledger()
        for name, s in self.fx["spendable_now"].items():
            self.assertEqual(wr.spendable(led, name, 0), s)

    def test_every_arrival_order(self):
        exp = self.fx["expect"]
        seen = set()
        for order in self.fx["arrival_orders"]:
            with self.subTest(order=order):
                cleared, c2, led = self.run_order(order)
                self.assertEqual(cleared, exp["cleared_order"])
                results = {c["intent_id"]: {k: v for k, v in c.items() if k not in ("intent_id", "actor_id")} for c in c2}
                self.assertEqual(results, exp["results"])
                for name, b in exp["ledger_after"].items():
                    for bucket, v in b.items():
                        self.assertEqual(led["accounts"][name][bucket], v, f"{name}.{bucket}")
                self.assertEqual([j["intent_id"] for j in led["journals"]],
                                 [i for i in exp["cleared_order"] if exp["results"][i]["status"] == "accepted"])
                seen.add(wr.ledger_hash(led))
        self.assertEqual(len(seen), 1, "same_for_every_arrival_order")

    def test_unsorted_coordinator_fails(self):
        """expect.note: without the sort, arrival order 1 accepts 15,000.00 and rejects 10,000.00.
        FINDINGS W1: that holds only with the §5 reserve-floor check off. With it on, the floor
        rejects 15,000.00 in either order, and the unsorted run still fails the fixture on the reason."""
        _, c2, _ = self.run_order(self.fx["arrival_orders"][0], sort=False, floor=False)
        st = {c["intent_id"]: c["status"] for c in c2}
        self.assertEqual((st["i-r0-treasury-2"], st["i-r0-treasury-1"]), ("accepted", "rejected"))
        _, c2, _ = self.run_order(self.fx["arrival_orders"][0], sort=False)
        res = {c["intent_id"]: c for c in c2}
        self.assertEqual((res["i-r0-treasury-2"]["status"], res["i-r0-treasury-2"]["reason"]), ("rejected", "reserve_floor"))
        self.assertEqual(res["i-r0-treasury-1"]["status"], "accepted")
        self.assertNotEqual(res["i-r0-treasury-2"].get("reason"), self.fx["expect"]["results"]["i-r0-treasury-2"]["reason"])

    def test_floor_binds_at_equality(self):
        """After the accepted 10,000.00 the LF-1 floor is met exactly: P(40) = 30,000.00."""
        _, _, led = self.run_order(self.fx["arrival_orders"][0])
        self.assertEqual(wr.projected(led, "treasury/operating", 40), FLOOR)
        self.assertEqual(wr.floor_headroom(led, "treasury/operating", 0), 0)

    def test_priority_classes_match_actors(self):
        self.assertEqual({a["actor_id"]: a["priority_class"] for a in ACTORS}, wr.PRIORITY)

    def test_intent_id_tiebreak_is_lexicographic(self):
        """FINDINGS W4: string sort puts tool call 10 before tool call 2 of the same response."""
        a = {"priority_class": 1, "sim_minute": 0, "actor_id": "lender", "intent_id": "i-r5-lender-2"}
        b = dict(a, intent_id="i-r5-lender-10")
        self.assertEqual([i["intent_id"] for i in wr.drain([a, b])], ["i-r5-lender-10", "i-r5-lender-2"])


class CoupledChain(unittest.TestCase):
    """coupled-chain.json: rumour r3 -> request r4 -> disbursal r5 -> K_p falls; control unchanged."""

    fx = load("coupled-chain")

    def world(self, branch, actors=ACTORS):
        led = wr.new_ledger()
        for name, b in self.fx["lender_before"]["accounts"].items():
            wr.account(led, name)["settled"] = b["settled"]
        wr.account(led, "borrower-c/operating")["settled"] = 400_000
        led["pools"]["lender"] = {"committed_undrawn": [dict(c) for c in self.fx["lender_before"]["committed_undrawn"]],
                                  "floor": self.fx["lender_before"]["pool_floor"]}
        return wr.World("w-coupled", branch, led, actors, self.fx["plan"], self.fx["scheduled_events"], seed=7)

    def run_branch(self, branch, actors=ACTORS):
        w = self.world(branch, actors)
        self.assertEqual(wr.k_p(w.ledger, "lender"), self.fx["lender_before"]["K_p"])
        w.run(6)                                   # rounds 0..5
        return w

    def test_round_hours(self):
        self.assertEqual(self.fx["round_hours"], wr.ROUND_HOURS)

    def test_shock_branch(self):
        exp = self.fx["expect"]["shock"]
        w = self.run_branch("shock")
        r4, r5 = w.transcript[4], w.transcript[5]
        e4 = exp["round_4"]
        self.assertIn(e4["intent"], r4["intents"])
        self.assertEqual(w.intents[e4["intent"]]["type"], e4["type"])
        self.assertEqual(w.intents[e4["intent"]]["evidence_ids"], e4["evidence_ids"])
        c4 = next(c for c in r4["c2"] if c["intent_id"] == e4["intent"])
        self.assertEqual(c4["status"], e4["c2_status"])
        self.assertEqual(c4.get("journal_seq"), e4["journal"])
        self.assertEqual(r4["journal_ids"], [])
        e5 = exp["round_5"]
        self.assertEqual([i for i in r5["intents"] if i.startswith("i-r5-lender")], e5["intents"])
        for iid in e5["intents"]:
            self.assertEqual(w.intents[iid]["evidence_ids"], e5["evidence_ids"])
            self.assertEqual(next(c for c in r5["c2"] if c["intent_id"] == iid)["status"], e5["c2_status"])
        self.assertEqual(len(r5["journal_ids"]), e5["journals"])
        for name, b in exp["lender_after"].items():
            self.assertEqual(w.ledger["accounts"][name]["settled"], b["settled"])
        self.assertEqual(w.ledger["accounts"]["borrower-c/operating"]["settled"] - 400_000,
                         exp["borrower_c_after"]["borrower-c/operating"]["settled_increase"])
        self.assertEqual(wr.k_p(w.ledger, "lender"), exp["K_p_after"])
        self.assertEqual(w.trace(r5["journal_ids"][0]), exp["trace"])

    def test_control_branch(self):
        exp = self.fx["expect"]["control"]
        w = self.run_branch("control")
        for rk, actor_of in (("round_4", exp["round_4"]), ("round_5", exp["round_5"])):
            r = w.transcript[int(rk[-1])]
            for actor, tool in actor_of.items():
                self.assertEqual([c["name"] for c in r["tool_calls"][actor]], [tool])
        self.assertEqual(wr.k_p(w.ledger, "lender"), exp["K_p_after"])
        self.assertEqual(w.ledger["journals"], [])

    def test_answer_order_does_not_matter(self):
        """env.step answers in any order; the plan keys on what was seen, so transcripts are identical."""
        a = self.run_branch("shock")
        b = self.run_branch("shock", list(reversed(ACTORS)))
        self.assertEqual(wr.sha(a.transcript), wr.sha(b.transcript))
        self.assertEqual(wr.ledger_hash(a.ledger), wr.ledger_hash(b.ledger))

    def test_trap_committed_draw_cannot_move_capacity(self):
        w = self.world("control")
        led = w.ledger
        line = led["pools"]["lender"]["committed_undrawn"][0]
        wr.post_journal(led, [("lender/operating", -line["amount"]), (wr.operating(line["to"]), line["amount"])], "draw")
        line["amount"] = 0
        self.assertEqual(wr.k_p(led, "lender"), self.fx["lender_before"]["K_p"])

    def test_scripted_model_without_default_raises(self):
        m = wr.ScriptedModel([e for e in self.fx["plan"] if not e.get("default")])
        with self.assertRaises(LookupError):
            m.respond("borrower-c", 4, set())


class RoundRollback(unittest.TestCase):
    """round-rollback.json: LF-1 shock branch, round 10 (t=40 h), payroll due as a mandatory settlement."""

    fx = load("round-rollback")
    PLAN = [{"actor_id": "borrower-b", "round": 10,
             "tool_calls": [{"name": "pay", "args": {"amount_minor": 100_000, "currency": "USD", "to": "supplier-2"}}]},
            {"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}]
    EVENTS = [{"round": 10, "kind": "synthetic", "id": "ev-r10-px", "px": 9_900},
              {"round": 10, "kind": "public_post", "post_id": "p-r10-1", "author": "feed", "text": "Payroll day."}]

    def at_round_10(self):
        led = lf1_ledger(shock=True)
        wr.account(led, "borrower-b/operating")["settled"] = 900_000
        w = wr.World("w-lf1", "shock", led, ACTORS, self.PLAN, self.EVENTS, seed=11)
        w.run(10)                                  # rounds 0..9 commit
        self.assertEqual(w.transcript[-1]["round"], 9)
        return w

    def control(self, w, cap):
        c = w.fork_from(cap)
        asyncio.run(c.run_round())
        return c

    def test_world_matches_fixture(self):
        self.assertEqual(self.fx["world"].split(":")[0], "LF-1, shock branch, round 10 (t=40h)")
        self.assertEqual(10 * wr.ROUND_HOURS, 40)
        self.assertEqual(set(self.fx["failed_round_expect"]["applies_to"]) | {"invalid-intent"},
                         {c["id"] for c in self.fx["cases"]})

    def assert_failed_round(self, case, w, cap, status):
        exp = self.fx["expect"][case]
        self.assertEqual(w.diagnostics[-1]["status"], exp["round_status"])
        self.assertEqual(status, exp["round_status"])
        self.assertEqual(wr.ledger_hash(w.ledger), wr.ledger_hash(cap["ledger"]), "ledger_hash")
        self.assertEqual(w.transcript[-1]["round"], 9, "transcript_rounds ends at round 9")
        self.assertFalse(any(c["intent_id"].startswith("i-r10-") for c in w.pending_c2 + w.c2_delivered), "c2_delivered")
        self.assertEqual(w.capture(), cap, "all_captured_state_equals_round_start")
        self.assertFalse(any(d.get("round") == 10 for e in w.memory.values() for d in e), "no failed-round memory")

    def assert_retry_equals_control(self, w, cap):
        control = self.control(w, cap)
        asyncio.run(w.run_round())
        a, b = w.transcript[-1], control.transcript[-1]
        self.assertEqual(a["observations"], b["observations"], "observation hashes")
        self.assertEqual(a["intents"], b["intents"], "intent ids")
        self.assertEqual(a["c2"], b["c2"], "C2 deliveries")
        self.assertEqual(w.pending_c2, control.pending_c2)
        self.assertEqual(w.ledger["journals"], control.ledger["journals"], "journals")
        self.assertEqual(wr.ledger_hash(w.ledger), wr.ledger_hash(control.ledger), "final ledger hash")
        self.assertEqual(wr.sha(w.transcript), wr.sha(control.transcript), "committed transcript")
        # no duplicates: event delivery, mandatory settlement, public post, memory entry, C2 delivery
        self.assertEqual(w.events_delivered.count("p-r10-1"), 1)
        self.assertEqual([j["kind"] for j in w.ledger["journals"]].count("settlement"), 1)
        self.assertEqual([p["id"] for p in w.oasis["posts"]].count("p-r10-1"), 1)
        self.assertEqual(w.memory, control.memory)
        self.assertEqual(w.capture(), control.capture())
        self.assertEqual(w.ledger["accounts"]["payroll/operating"]["settled"], PAYROLL)

    def run_fault(self, case, hooks):
        w = self.at_round_10()
        cap = w.capture()
        w.hooks = hooks
        with self.assertRaises(wr.RoundFailed):
            asyncio.run(w.run_round())
        self.assert_failed_round(case, w, cap, "failed")
        w.hooks = {}
        self.assert_retry_equals_control(w, cap)

    def test_fault_in_events(self):
        def boom(w):
            self.assertGreater(w.event_cursor, 0)          # the due event advanced the cursor and changed state
            self.assertTrue(w.oasis["prices"] and w.oasis["prices"][-1]["source"] == "ev-r10-px")
            raise RuntimeError("fault-in-events")
        self.run_fault("fault-in-events", {"after_event": boom})

    def test_fault_in_settlement(self):
        def boom(w):
            self.assertEqual(w.ledger["journals"][-1]["kind"], "settlement")
            raise RuntimeError("fault-in-settlement")
        self.run_fault("fault-in-settlement", {"after_settlement_journal": boom})

    def test_fault_in_commit(self):
        def boom(w):
            self.assertTrue(any(j["round"] == 10 for j in w.ledger["journals"]))
            raise RuntimeError("fault-in-commit")
        self.run_fault("fault-in-commit", {"before_transcript": boom})

    def sibling(self, w, reached, barrier, stash, stubborn=None):
        """borrower-b writes a provisional post, memory entry and intent, then pauses on a barrier;
        cancelled, it makes one last provisional write before it terminates."""
        async def child():
            try:
                await barrier.wait()
            finally:
                w.lifecycle.append(("child_done",))

        async def hook(world, writer, actor):
            writer.post({"id": "p-r10-provisional", "author": actor, "text": "provisional", "round": 10})
            writer.remember(actor, {"round": 10, "provisional": True})
            writer.queue({"intent_id": "i-r10-borrower-b-9", "actor_id": actor, "priority_class": 2,
                          "sim_minute": 2400, "type": "no_action", "params": {}, "evidence_ids": []})
            writer.spawn(child())
            stash["writer"] = writer
            reached.set()
            w.lifecycle.append(("sibling_at_barrier",))
            try:
                await barrier.wait()
            except asyncio.CancelledError:
                writer.remember(actor, {"round": 10, "cleanup": True})
                writer.queue({"intent_id": "i-r10-borrower-b-10", "actor_id": actor, "priority_class": 2,
                              "sim_minute": 2400, "type": "no_action", "params": {}, "evidence_ids": []})
                w.lifecycle.append(("sibling_cleanup_write",))
                if stubborn is not None:
                    await stubborn.wait()               # refuses to stop: quiescence unproved
                raise
            finally:
                w.lifecycle.append(("sibling_done",))
        return hook

    def assert_writers_gone(self, w, cap, barrier, stash):
        names = [e[0] for e in w.lifecycle]
        begin = names.index("restore_begin")
        for done in ("sibling_cleanup_write", "sibling_done", "child_done"):
            self.assertLess(names.index(done), begin, f"{done} precedes restoration")
        self.assertEqual([e for e in w.lifecycle if e[0] == "joined"][-1][2], 0, "round_owned_tasks_at_restore")
        barrier.set()                                    # release every test barrier after the abort
        with self.assertRaises(wr.StaleWriter):
            stash["writer"].remember("borrower-b", {"round": 10, "late": True})
        self.assertEqual(w.stale_write_attempts, 1)
        self.assertEqual(w.capture(), cap, "writes_after_restore = 0; cleanup writes removed")

    def test_fault_in_agent_step(self):
        w = self.at_round_10()
        cap = w.capture()

        async def go():
            reached, barrier, stash = asyncio.Event(), asyncio.Event(), {}
            w.actor_hooks["borrower-b"] = self.sibling(w, reached, barrier, stash)

            async def fail(world, writer, actor):
                await reached.wait()
                raise RuntimeError("fault-in-agent-step")
            w.actor_hooks["treasury"] = fail
            with self.assertRaises(wr.RoundFailed):
                await w.run_round()
            self.assert_writers_gone(w, cap, barrier, stash)
        asyncio.run(go())
        self.assert_failed_round("fault-in-agent-step", w, cap, "failed")
        w.actor_hooks = {}
        self.assert_retry_equals_control(w, cap)

    def test_cancel_in_agent_step(self):
        w = self.at_round_10()
        cap = w.capture()

        async def go():
            reached, barrier, stash = asyncio.Event(), asyncio.Event(), {}
            w.actor_hooks["borrower-b"] = self.sibling(w, reached, barrier, stash)
            coord = asyncio.ensure_future(w.run_round())
            await reached.wait()
            coord.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await coord
            self.assert_writers_gone(w, cap, barrier, stash)
        asyncio.run(go())
        self.assert_failed_round("cancel-in-agent-step", w, cap, "cancelled")
        w.actor_hooks = {}
        self.assert_retry_equals_control(w, cap)

    def test_unproved_quiescence_refuses_retry(self):
        w = self.at_round_10()
        w.quiesce_timeout = 0.05                         # detection bound; ordering is by barriers

        async def go():
            reached, barrier, stubborn, stash = asyncio.Event(), asyncio.Event(), asyncio.Event(), {}
            w.actor_hooks["borrower-b"] = self.sibling(w, reached, barrier, stash, stubborn)

            async def fail(world, writer, actor):
                await reached.wait()
                raise RuntimeError("actor fault")
            w.actor_hooks["treasury"] = fail
            with self.assertRaises(wr.WorldUnusable):
                await w.run_round()
            self.assertTrue(w.unusable)
            with self.assertRaises(wr.WorldUnusable):
                await w.run_round()
            stubborn.set()
            barrier.set()
            await asyncio.gather(*w.round_tasks, return_exceptions=True)
        asyncio.run(go())

    def test_invalid_intent(self):
        exp = self.fx["expect"]["invalid-intent"]
        inj = next(c for c in self.fx["cases"] if c["id"] == "invalid-intent")["inject"]
        w = self.at_round_10()
        intent = dict(inj["intent"], intent_id="i-r10-treasury-inj", priority_class=1, sim_minute=2400,
                      evidence_ids=[])
        w.hooks = {"before_validate": lambda world: world.queue.append(intent)}
        entry = asyncio.run(w.run_round())
        self.assertEqual(w.diagnostics[-1]["status"], exp["round_status"])
        c2 = next(c for c in entry["c2"] if c["intent_id"] == "i-r10-treasury-inj")
        self.assertEqual({k: c2[k] for k in exp["c2"]}, exp["c2"])
        self.assertTrue(exp["payroll_settled"])
        self.assertTrue(w.ledger["obligations"][0]["settled"])
        self.assertEqual(w.ledger["accounts"]["payroll/operating"]["settled"], PAYROLL)
        # LF-1 shock at t=40: receivable overdue, payroll paid from 70,000.00 -> 20,000.00 settled
        tre = w.ledger["accounts"]["treasury/operating"]
        self.assertEqual((tre["settled"], tre["reserved"]), (CASH - PAYROLL, 0))
        self.assertTrue(tre["pending_in"][0]["overdue"])
        self.assertEqual(wr.projected(w.ledger, "treasury/operating", 40) - FLOOR, -1_000_000)


if __name__ == "__main__":
    unittest.main()

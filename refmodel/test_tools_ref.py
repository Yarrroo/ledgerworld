"""Oracle tests for the tool boundary; each loads its agent-world fixture unchanged from prp/.

Run: python -m unittest discover -s refmodel -p test_tools_ref.py
"""

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tools_ref as ref  # noqa: E402

FIXTURES = (Path(__file__).resolve().parents[1] / "prp" / "2026-10-20-ledgerworld" / "design"
            / "modules" / "agent-world" / "fixtures")


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


ACTORS = load("actors")
BY_ID = {a["actor_id"]: a for a in ACTORS["actors"]}


class ObservationScope(unittest.TestCase):
    fx = load("observation-scope")

    def build(self, items):
        return ref.build_observation(BY_ID[self.fx["actor_id"]], items, self.fx["round"], self.fx["sim_time_h"])

    def test_included_exactly(self):
        _, _, evidence = self.build(self.fx["world_items"])
        self.assertEqual(sorted(evidence), sorted(self.fx["expect"]["included"]))

    def test_each_excluded_item(self):
        _, _, evidence = self.build(self.fx["world_items"])
        for item_id, why in self.fx["expect"]["excluded"].items():
            with self.subTest(item=item_id, why=why):
                self.assertNotIn(item_id, evidence)

    def test_every_item_classified(self):
        exp = self.fx["expect"]
        ids = {i["id"] for i in self.fx["world_items"]}
        self.assertEqual(ids, set(exp["included"]) | set(exp["excluded"]))

    def test_obs_hash_stable(self):
        _, h1, _ = self.build(self.fx["world_items"])
        _, h2, _ = self.build(list(reversed(self.fx["world_items"])))
        self.assertEqual(h1, h2)
        self.assertRegex(h1, r"^[0-9a-f]{64}$")

    def test_adding_excluded_items_changes_nothing(self):
        excluded = set(self.fx["expect"]["excluded"])
        only_included = [i for i in self.fx["world_items"] if i["id"] not in excluded]
        obs_a, h_a, _ = self.build(only_included)
        obs_b, h_b, _ = self.build(self.fx["world_items"])
        self.assertEqual((obs_a, h_a), (obs_b, h_b))

    def test_obs_hash_is_sha256_of_canonical_json(self):
        obs, h, _ = self.build(self.fx["world_items"])
        text = ref.canonical_json(obs)
        self.assertNotIn(" ", text)
        self.assertEqual(h, hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(obs["t"], "2026-01-01T16:00:00Z")

    def test_item_times_are_iso_in_hash_input(self):
        obs, _, _ = self.build(self.fx["world_items"])
        for item in obs["items"]:
            self.assertNotIn("visible_from_h", item)
            self.assertRegex(item["visible_from"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_duplicate_ids_do_not_make_hash_order_dependent(self):
        a = {"id": "acct:borrower-c/operating", "kind": "account", "owner": "borrower-c", "balance_minor": 1}
        b = dict(a, balance_minor=2)
        self.assertEqual(self.build([a, b])[1], self.build([b, a])[1])

    def test_due_scheduled_event_only_reaches_its_addressee(self):
        unaddressed = {"id": "sched:receipt-delay@16h", "kind": "scheduled_event", "visible_from_h": 16}
        addressed = dict(unaddressed, id="sched:call@16h", to="borrower-c")
        other = dict(unaddressed, id="sched:treasury@16h", to="treasury")
        _, _, evidence = self.build([unaddressed, addressed, other])
        self.assertEqual(evidence, ["sched:call@16h"])

    def test_float_refused_in_canonical_json(self):
        with self.assertRaises(ValueError):
            ref.canonical_json({"amount_minor": 1.5})


class MalformedOutput(unittest.TestCase):
    fx = load("malformed-output")
    actor = BY_ID["borrower-c"]

    def run_case(self, case):
        prompts = []

        def ask_repair(prompt):
            prompts.append(prompt)
            return case["repair"]

        out = ref.guard_model_output(self.actor, case["first"], ask_repair, 4, "h" * 64, ["p-r3-1"])
        return out, prompts

    def test_cases(self):
        for case in self.fx["cases"]:
            with self.subTest(case=case["id"]):
                exp = case["expect"]
                out, prompts = self.run_case(case)
                self.assertEqual(out["intent"]["type"], exp["intent_type"])
                self.assertEqual(out["repair_attempts"], exp["repair_attempts"])
                self.assertEqual(out["alert"], exp["alert"])
                if "alert_reason" in exp:
                    self.assertEqual(out["alert_reason"], exp["alert_reason"])
                if "posted_amount_minor" in exp:
                    amount = out["intent"]["params"]["amount_minor"]
                    self.assertIs(type(amount), int)
                    self.assertEqual(amount, exp["posted_amount_minor"])
                self.assertLessEqual(len(prompts), self.fx["expect_all"]["max_repair_attempts"])

    def test_repair_prompt_names_the_schema_error(self):
        for case in self.fx["cases"]:
            with self.subTest(case=case["id"]):
                out, prompts = self.run_case(case)
                self.assertEqual(len(prompts), 1)
                self.assertIn("refused", prompts[0])
                self.assertIn(out["repair_prompt"], prompts)
        float_case = next(c for c in self.fx["cases"] if c["id"] == "float-never-reaches-ledger")
        out, prompts = self.run_case(float_case)
        self.assertIn("'amount_minor' must be int, got float", prompts[0])

    def test_no_float_in_any_intent(self):
        for case in self.fx["cases"]:
            with self.subTest(case=case["id"]):
                out, _ = self.run_case(case)
                ref.canonical_json(out["intent"])  # raises on a float

    def test_valid_first_call_needs_no_repair(self):
        def never(_):
            raise AssertionError("repair asked for a valid call")

        call = self.fx["cases"][0]["repair"]
        out = ref.guard_model_output(self.actor, call, never, 4, "h" * 64, [])
        self.assertEqual((out["repair_attempts"], out["alert"]), (0, False))
        self.assertEqual(out["intent"]["intent_id"], "i-r4-borrower-c-1")

    def test_failed_repair_call_becomes_no_action(self):
        def boom(_):
            raise TimeoutError("model timed out")

        out = ref.guard_model_output(self.actor, self.fx["cases"][0]["first"], boom, 4, "h" * 64, [])
        self.assertEqual((out["intent"]["type"], out["alert"], out["alert_reason"]),
                         ("no_action", True, "repair_call_failed"))

    def test_never_raises_on_garbage(self):
        for garbage in (None, "text", [], {"name": None}, {"name": "pay"}, {"name": "pay", "args": "x"}):
            with self.subTest(garbage=garbage):
                out = ref.guard_model_output(self.actor, garbage, lambda _: garbage, 4, "h" * 64, [])
                self.assertEqual((out["intent"]["type"], out["alert"]), ("no_action", True))


class ActorTools(unittest.TestCase):
    def test_roster_counts(self):
        exp = ACTORS["expect"]
        llm = [a for a in ACTORS["actors"] if a["llm"]]
        self.assertEqual(len(ACTORS["actors"]), 8)
        self.assertEqual(len(llm), exp["llm_actors"])
        self.assertEqual(len(ACTORS["actors"]) - len(llm), exp["rule_actors"])
        self.assertEqual(len(llm), exp["calls_per_round_max"])
        rounds = ACTORS["horizon_hours"] // ACTORS["round_hours"]
        self.assertEqual(rounds, exp["rounds"])
        self.assertEqual(rounds * len(llm), exp["calls_per_branch_max"])

    def test_every_listed_tool_has_a_schema(self):
        for actor in ACTORS["actors"]:
            for tool in actor["tools"]:
                with self.subTest(actor=actor["actor_id"], tool=tool):
                    self.assertIn(tool, ref.TOOL_SCHEMAS)

    def test_tools_outside_the_list_refused(self):
        for actor in ACTORS["actors"]:
            for tool in ref.TOOL_SCHEMAS:
                if tool in actor["tools"]:
                    continue
                with self.subTest(actor=actor["actor_id"], tool=tool):
                    with self.assertRaises(ref.ToolRefusal) as cm:
                        ref.gate_tool_call(actor, {"name": tool, "args": {}})
                    self.assertEqual(cm.exception.reason, "tool_not_in_mandate")

    def test_rule_actors_have_no_tools(self):
        for actor in ACTORS["actors"]:
            if not actor["llm"]:
                self.assertEqual(actor["tools"], [])

    def test_no_action_open_to_every_llm_actor(self):
        for actor in ACTORS["actors"]:
            if actor["llm"]:
                self.assertEqual(ref.gate_tool_call(actor, {"name": "no_action", "args": {}}), {})

    def test_scope_kinds_known(self):
        for actor in ACTORS["actors"]:
            for scope in actor["sees"]:
                self.assertIn(scope, ref.SCOPE_RULES)

    def test_feed_cannot_see_private_items(self):
        items = load("observation-scope")["world_items"]
        _, _, evidence = ref.build_observation(BY_ID["feed"], items, 4, 16)
        self.assertEqual(sorted(evidence), ["p-r3-1", "price:USDC-USD@16h"])

    def test_rule_actor_without_scope_sees_nothing(self):
        items = load("observation-scope")["world_items"]
        _, _, evidence = ref.build_observation(BY_ID["market-maker"], items, 4, 16)
        self.assertEqual(evidence, [])

    def test_bad_currency_and_empty_target_refused(self):
        for args in ({"amount_minor": 100, "currency": "dollars", "to": "payroll"},
                     {"amount_minor": 100, "currency": "USD", "to": ""}):
            with self.subTest(args=args):
                with self.assertRaises(ref.ToolRefusal) as cm:
                    ref.gate_tool_call(BY_ID["borrower-c"], {"name": "pay", "args": args})
                self.assertEqual(cm.exception.reason, "malformed_tool_args")

    def test_targetless_calls_refused(self):
        for actor, call in (("lender", {"name": "accept", "args": {}}),
                            ("lender", {"name": "release", "args": {}}),
                            ("treasury", {"name": "defer", "args": {}})):
            with self.subTest(call=call):
                with self.assertRaises(ref.ToolRefusal):
                    ref.gate_tool_call(BY_ID[actor], call)
        self.assertEqual(ref.gate_tool_call(BY_ID["lender"], {"name": "accept", "args": {"intent_id": "i-r4-borrower-c-1"}}),
                         {"intent_id": "i-r4-borrower-c-1"})

    def test_mandated_tool_without_schema_named_as_such(self):
        actor = dict(BY_ID["treasury"], tools=["hedge"])
        with self.assertRaises(ref.ToolRefusal) as cm:
            ref.gate_tool_call(actor, {"name": "hedge", "args": {}})
        self.assertEqual(cm.exception.reason, "tool_schema_missing")

    def test_bool_is_not_money(self):
        with self.assertRaises(ref.ToolRefusal):
            ref.gate_tool_call(BY_ID["borrower-c"], {"name": "pay", "args": {
                "amount_minor": True, "currency": "USD", "to": "payroll"}})


if __name__ == "__main__":
    unittest.main()

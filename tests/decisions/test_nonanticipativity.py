"""Clairvoyant policies are rejected; honest ones pass (g1 `clairvoyant_policy_rejected`, T32).

The tree is the fixture's: LF-1 from its C5 snapshot, forked into three scenarios that differ
only in when the receivable rcv-1 arrives. The round coordinator's observability rules (T08) are
written here by hand, as the leaves' versions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.decisions.nonanticipativity import (
    NEVER,
    AnticipationViolation,
    Leaf,
    PolicyView,
    ScenarioTree,
    guarded_decide,
    observable_histories,
    paired_history_check,
    snapshot_world,
)
from app.finance.schemas import Snapshot

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (ROOT / "prp/2026-10-20-ledgerworld/design/modules/decisions/fixtures/nonanticipativity.json")
    .read_text(encoding="utf-8"))
LF1 = Snapshot.model_validate(json.loads(
    (ROOT / "contracts/examples/c5_snapshot/valid-lf1.json").read_text(encoding="utf-8"))["instance"])
POLICIES = {p["id"]: p for p in FIXTURE["policies"]}
ACCOUNT = "accounts[borrower-a/operating]"
RCV = f"{ACCOUNT}.pending_in[rcv-1]"
ROUNDS = 5  # t = 0..16 h: one round past the checkpoint, where s-short and s-late part


def lf1_tree(*, with_post: bool = False) -> ScenarioTree:
    base = snapshot_world(LF1)
    settled = base[f"{ACCOUNT}.settled"].versions[0][1]
    amount = base[f"{RCV}.amount"].versions[0][1]["minor"]
    scenarios = {}
    for sid, flows in FIXTURE["tree"].items():
        if not sid.startswith("s-"):
            continue
        rcv = flows["rcv-1"]
        expected_h, arrives_h = rcv["expected_h"], rcv["arrives_h"]
        status = Leaf.at(0, "expected")
        if arrives_h > expected_h:  # not delivered in step 2 of the round at t: overdue
            status = status.then(expected_h, "overdue")
        world = dict(base)
        world[f"{RCV}.status"] = status.then(arrives_h, "arrived")
        world[f"{RCV}.arrived_h"] = Leaf.at(arrives_h, arrives_h)
        world[f"{ACCOUNT}.settled"] = Leaf.at(0, settled).then(
            arrives_h, {**settled, "minor": settled["minor"] + amount})
        world["scenario.params.delay_h"] = Leaf.never()
        if with_post:
            world["public.posts[p-r3-1]"] = Leaf.at(12, {"author": "public-feed", "round": 3})
        scenarios[sid] = world
    return ScenarioTree(scenarios, ROUNDS)


ADVANCE = {"type": "request_advance", "facility": "adv-a", "amount_minor": 1000000}


def integrated(view: PolicyView) -> list:
    """Draws the advance in the round the receivable shows overdue, reading only the view."""
    if view.get(f"{RCV}.status") == "overdue" and view.get(f"{RCV}.expected_h") == view.t_h:
        return [dict(ADVANCE)]
    return []


def reader(spec: dict, seen: dict | None = None):
    """A policy that does the fixture's reads at their rounds and decides nothing."""
    def decide(view: PolicyView) -> list:
        for read in spec["reads"]:
            if read["round"] == view.round:
                value = view.get(read["path"])
                if seen is not None:
                    seen[read["path"]] = value
        return []
    return decide


def side_channel_by_call_order(tree: ScenarioTree):
    """Closes over the scenarios; knows which one it is in from how often it has been called."""
    order, calls = list(tree.scenarios), []

    def decide(view: PolicyView) -> list:
        scenario = order[len(calls) // tree.rounds]
        calls.append(scenario)
        return [dict(ADVANCE)] if view.round == 0 and scenario == "s-late" else []
    return decide


def side_channel_through_the_store(view: PolicyView) -> list:
    """Reaches the true arrival through the view's private store, never through `get`."""
    arrives_h = view._leaves[f"{RCV}.arrived_h"].versions[0][0]
    return [dict(ADVANCE)] if view.round == 0 and arrives_h > 200 else []


def test_the_lf1_snapshot_is_a_world_observable_from_t0():
    world = snapshot_world(LF1)
    assert world[f"{RCV}.expected_h"] == Leaf.at(0, 12)
    assert world[f"{RCV}.status"] == Leaf.at(0, "expected")
    assert world[f"{RCV}.amount"] == Leaf.at(0, {"minor": 2000000, "currency": "USD"})
    assert world[f"{ACCOUNT}.as_of_h"] == Leaf.at(0, 0)
    assert world["obligations[payroll-1].due_h"] == Leaf.at(0, 40)
    assert world["entities[borrower-a].escalation"] == Leaf.at(0, "treasury operator")
    assert world["exposures[venue-1].shared_with"] == Leaf.at(0, ["lender"])
    assert all(leaf.available_at_h == 0 for leaf in world.values())


def test_the_tree_shares_the_fixtures_histories():
    hashes = observable_histories(lf1_tree())
    for pair, through in FIXTURE["tree"]["identical_history_through_round"].items():
        a, b = pair.split("|")
        assert hashes[a][: through + 1] == hashes[b][: through + 1], pair
        assert hashes[a][through + 1] != hashes[b][through + 1], pair


def test_honest_policies_are_accepted():
    tree = lf1_tree()
    decisions = paired_history_check(integrated, tree)
    for sid, by_round in POLICIES["integrated"]["decisions"].items():
        for r, actions in by_round.items():
            assert decisions[sid][int(r)].actions == actions, (sid, r)
    assert decisions["s-late"][3].evidence_ids == (f"{RCV}.status", f"{RCV}.expected_h")
    assert all(d.actions == [] for d in decisions["s-late"][4:] + decisions["s-short"][4:])

    for pid in ("reads-expectation", "reads-overdue"):
        spec = POLICIES[pid]
        assert spec["expect"] == {"accepted": True}
        decisions = paired_history_check(reader(spec), tree)
        for read in spec["reads"]:
            for sid, world in tree.scenarios.items():
                seen = {}
                guarded_decide(reader(spec, seen), world, read["round"])
                if "value_in" in read:
                    assert seen[read["path"]] == read["value_in"][sid], (pid, sid)
                assert decisions[sid][read["round"]].evidence_ids == (read["path"],)


@pytest.mark.parametrize("pid", ["peek-arrival", "peek-params", "peek-post"])
def test_a_policy_reading_the_future_is_rejected_with_the_path(pid):
    spec = POLICIES[pid]
    expect = spec["expect"]
    tree = lf1_tree(with_post=bool(spec.get("world_adds")))
    (read,) = spec["reads"]
    for sid, world in tree.scenarios.items():
        with pytest.raises(AnticipationViolation) as caught:
            guarded_decide(reader(spec), world, read["round"])
        available = expect["available_at_h"]
        assert expect["rejected"] == "AnticipationViolation"
        assert caught.value.path == expect["path"]
        assert caught.value.read_at_h == expect["read_at_h"]
        assert caught.value.available_at_h == (
            available[sid] if isinstance(available, dict) else available)
    with pytest.raises(AnticipationViolation) as caught:
        paired_history_check(reader(spec), tree)
    assert caught.value.path == expect["path"] and caught.value.node is None


@pytest.mark.parametrize("make", [side_channel_by_call_order,
                                  lambda tree: side_channel_through_the_store],
                         ids=["call-order", "private-store"])
def test_a_side_channel_policy_is_caught_by_the_paired_history_check(make):
    spec = POLICIES["side-channel"]
    tree = lf1_tree()
    for sid, by_round in spec["decisions"].items():  # the view guard alone sees nothing wrong
        for r, actions in by_round.items():
            decision = guarded_decide(side_channel_through_the_store, tree.scenarios[sid], int(r))
            assert (decision.actions, decision.evidence_ids) == (actions, ())
    with pytest.raises(AnticipationViolation) as caught:
        paired_history_check(make(tree), tree)
    assert caught.value.path == spec["expect"]["path"] is None
    assert caught.value.node == spec["expect"]["node"]
    assert caught.value.reason == spec["expect"]["reason"]


def test_a_swallowed_early_read_still_rejects():
    def hedger(view: PolicyView) -> list:
        try:
            view.get(f"{RCV}.arrived_h")
        except AnticipationViolation:
            return [dict(ADVANCE)]  # it learned the receipt has not arrived; it must not keep that
        return []

    def raiser(view: PolicyView) -> list:
        try:
            view.get("scenario.params.delay_h")
        except AnticipationViolation:
            raise RuntimeError("covering the read") from None
        return []

    tree = lf1_tree()
    for policy, path, available in ((hedger, f"{RCV}.arrived_h", 252),
                                    (raiser, "scenario.params.delay_h", NEVER)):
        with pytest.raises(AnticipationViolation) as caught:
            paired_history_check(policy, tree)
        assert (caught.value.path, caught.value.available_at_h) == (path, available)


def test_the_view_shows_nothing_early_and_hands_out_copies():
    world = lf1_tree(with_post=True).scenarios["s-short"]
    early, late = PolicyView(world, 2), PolicyView(world, 4)
    assert "public.posts[p-r3-1]" not in early.paths("public")
    assert late.paths("public") == ["public.posts[p-r3-1]"]
    assert f"{RCV}.arrived_h" not in early.paths(RCV)
    assert early.paths("scenario") == [] and late.paths("scenario") == []
    assert early.paths("accounts[borrower-a") == []  # a prefix never matches mid-id
    assert early.get(f"{ACCOUNT}.settled")["minor"] == 7000000
    assert late.get(f"{ACCOUNT}.settled")["minor"] == 9000000
    assert late.get(f"{RCV}.status") == "arrived"
    late.get(f"{RCV}.amount")["minor"] = 1
    assert late.get(f"{RCV}.amount")["minor"] == 2000000
    with pytest.raises(TypeError):
        late._leaves["scenario.params.delay_h"] = Leaf.at(0, 4)
    with pytest.raises(KeyError):
        early.get("accounts[nobody].settled")
    assert early.obs_hash() != late.obs_hash()


def test_every_honest_policy_passes_and_every_clairvoyant_one_is_named():
    accepted, rejected = 0, []
    for spec in FIXTURE["policies"]:
        tree = lf1_tree(with_post=bool(spec.get("world_adds")))
        policy = {"integrated": integrated,
                  "side-channel": side_channel_by_call_order(tree)}.get(spec["id"], reader(spec))
        try:
            paired_history_check(policy, tree)
            accepted += 1
            assert spec["kind"] == "honest", spec["id"]
        except AnticipationViolation as violation:
            assert spec["kind"] == "clairvoyant", spec["id"]
            assert violation.path is not None or violation.node is not None
            rejected.append(spec["id"])
    assert accepted == FIXTURE["expect_all"]["honest_accepted"]
    assert len(rejected) == FIXTURE["expect_all"]["clairvoyant_rejected"]


def test_a_policy_that_moves_the_views_clock_is_caught():
    def time_traveller(view: PolicyView) -> list:
        view._round = 100  # the read below is then "on time", and the view's hash changes
        arrives_h = view.get(f"{RCV}.arrived_h")
        return [dict(ADVANCE)] if arrives_h > 200 and view.get(f"{RCV}.expected_h") == 12 else []

    tree = lf1_tree()
    assert guarded_decide(time_traveller, tree.scenarios["s-late"], 0).obs_hash == (
        observable_histories(tree)["s-late"][0])
    with pytest.raises(AnticipationViolation) as caught:
        paired_history_check(time_traveller, tree)
    assert caught.value.node == {"round": 0, "scenarios": ["s-late", "s-short"]}


def test_a_policy_that_erases_its_violation_is_caught_by_the_pair():
    def eraser(view: PolicyView) -> list:
        try:
            view.get(f"{RCV}.arrived_h")
        except AnticipationViolation as violation:
            view._violations.clear()  # hides the read from the view guard...
            if violation.available_at_h > 200:  # ...and acts on what the rejection revealed
                return [dict(ADVANCE)]
        return []

    with pytest.raises(AnticipationViolation) as caught:
        paired_history_check(eraser, lf1_tree())
    assert caught.value.node == {"round": 0, "scenarios": ["s-late", "s-short"]}


def test_a_policy_must_return_a_list_of_actions():
    world = lf1_tree().scenarios["s-late"]
    with pytest.raises(TypeError, match="list"):
        guarded_decide(lambda view: dict(ADVANCE), world, 0)


def test_a_snapshot_cannot_hold_an_account_observed_after_it():
    data = LF1.model_dump(mode="json")
    data["accounts"][0]["as_of"] = "2026-01-05T02:00:00Z"
    with pytest.raises(ValueError, match="after the snapshot"):
        snapshot_world(Snapshot.model_validate(data))

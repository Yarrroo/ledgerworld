"""Reverse stress on LF-1 + LF-2 under the integrated policy (T21; decisions HANDOFF).

``reverse-stress.json`` is read unchanged: seven families on two baselines (no shock, and the
demo shock: rcv-1 delayed 240 h), their breaking sizes, ``size_bps``, the not-applicable and
live-only families, the failure paths by hour, the search label and the cohort apart. The
search runs on the rules-replay world; every found point is confirmed in one fresh branch of the
coupled world (real OASIS platform, ``ScriptedModel``), the same world ``test_policies`` builds,
checkpointed at round 0. The fixture's failure-path events are prose; the tests hold the rounds
they happen in, and the numbers through ``settled_by_h``.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import json
import re
from pathlib import Path

import pytest
from app.decisions.candidates import Integrated
from app.decisions.reverse_stress import (
    COHORT,
    LABEL,
    Baseline,
    FreshBranch,
    Reaction,
    SearchFamily,
    _staged,
    borrower_silence,
    confidence_rumour,
    delayed_receipt,
    fx_gap,
    lender_redemption,
    obligation_growth,
    replay_world,
    reverse_stress,
    stablecoin_depeg,
)
from app.finance.schemas import Snapshot
from app.simulation.branches import checkpoint
from app.simulation.coordinator import Coordinator
from app.simulation.world import World, import_oasis
from app.testing.scripted_model import ScriptedPlan
from oasis_finance.observation import iso_utc

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "prp/2026-10-20-ledgerworld/design/modules"
FIXTURE = json.loads((DESIGN / "decisions/fixtures/reverse-stress.json").read_text())
COUPLED = json.loads((DESIGN / "agent-world/fixtures/coupled-chain.json").read_text())
ACTOR_SPECS = {a["actor_id"]: a for a in
               json.loads((DESIGN / "agent-world/fixtures/actors.json").read_text())["actors"]}
ACTORS = ["treasury", "lender", "borrower-b", "borrower-c", "feed", "payroll", "market-maker"]
BASELINES = {b["id"]: b for b in FIXTURE["baselines"]}
TERMS = {"adv-a": {"arrive_by_h": 18}}  # LF-1: the advance is eligible when it lands by t = 18
SEED = 101
T0 = iso_utc(0)


def usd(minor: int) -> dict:
    return {"minor": minor, "currency": "USD"}


# ------------------------------------------------------------------------------ the world

def account(account_id: str, settled: int, *, reserved: int = 0, floor: int | None = None,
            pending_in: list | None = None, venue: str | None = None) -> dict:
    acc = {"id": account_id, "entity": account_id.split("/")[0], "currency": "USD",
           "observability": "known", "as_of": T0,
           "buckets": {"settled": usd(settled), "reserved": usd(reserved), "pledged": usd(0),
                       "pending_in": pending_in or [], "pending_out": []}}
    if floor is not None:
        acc["floor"] = usd(floor)
    if venue is not None:
        acc["venue"] = venue
    return acc


def lf_snapshot() -> Snapshot:
    """LF-1's treasury beside the coupled-chain lender pool (LF-2) and its borrowers, adv-a
    offered to the treasury, at round 0."""
    before = COUPLED["lender_before"]
    (line,) = before["committed_undrawn"]
    return Snapshot.model_validate({
        "snapshot_id": "snap-reverse-stress", "as_of": T0,
        "entities": [
            {"entity_id": "treasury", "name": "Borrower A treasury (synthetic)",
             "kind": "treasury", "escalation": "treasury operator"},
            {"entity_id": "lender", "name": "Lender pool (synthetic)", "kind": "lender pool"},
            {"entity_id": "borrower-b", "name": "Borrower B (synthetic)", "kind": "borrower"},
            {"entity_id": "borrower-c", "name": "Borrower C (synthetic)", "kind": "borrower"}],
        "accounts": [
            account("treasury/operating", 7_000_000, reserved=5_000_000, floor=3_000_000,
                    pending_in=[{"flow_id": "rcv-1", "amount": usd(2_000_000),
                                 "expected_at": iso_utc(12), "kind": "receivable"},
                                {"flow_id": "wd-1", "amount": usd(1_500_000),
                                 "expected_at": iso_utc(48), "kind": "exchange_withdrawal"}]),
            account("lender/operating", before["accounts"]["lender/operating"]["settled"],
                    reserved=line["amount"]),
            account("lender/venue", before["accounts"]["lender/venue"]["settled"],
                    venue="exchange-venue"),
            account("borrower-b/operating", 900_000),
            account("borrower-c/operating", 400_000)],
        "obligations": [{"obligation_id": "payroll-1", "entity": "treasury",
                         "account": "treasury/operating", "amount": usd(5_000_000),
                         "due_at": iso_utc(40), "kind": "payroll",
                         "reservation_id": "res-payroll-1"}],
        "contracts": [
            {"contract_id": "line-b", "lender": "lender", "borrower": line["to"],
             "state": "active", "kind": "committed_line", "limit": usd(line["amount"]),
             "drawn": usd(0), "reservation_id": "line-b:undrawn",
             "reserved_on": "lender/operating"},
            {"contract_id": "adv-a", "lender": "lender", "borrower": "treasury",
             "state": "offered", "kind": "revenue_advance", "principal": usd(1_000_000),
             "fee_bps": 800, "repay_share_bps": 1500}],
        "exposures": [], "pools": [{"entity": "lender", "floor": usd(before["pool_floor"])}],
    })


SNAPSHOT = lf_snapshot()
SHOCKS = {"no-shock": (),  # the demo shock is policy-comparison's s1
          "demo-shock": ({"round": 3, "kind": "delay_receipt", "flow_id": "rcv-1",
                          "delay_h": 240},)}


def families() -> list[SearchFamily]:
    """The fixture's seven families, in its order, with its ranges and scales; the timing in
    each one's ``size`` text (announced at round 2, due t = 24, 24 h late) is spelled here."""
    spec = {f["id"]: f for f in FIXTURE["families"]}

    def rs(fid: str) -> dict:
        return {"range_": tuple(spec[fid]["range"]), "scale": spec[fid]["scale"]}

    built = [delayed_receipt("rcv-1", **rs("delayed-receipt")),
             obligation_growth("payroll-1", announce_round=2, **rs("obligation-growth")),
             lender_redemption("lender/operating", announce_round=2, due_h=24,
                               **rs("lender-redemption")),
             stablecoin_depeg("wd-1", settle_delay_h=24, **rs("stablecoin-depeg")),
             borrower_silence("borrower-b", to="lender", **rs("borrower-silence")),
             fx_gap(), confidence_rumour()]
    assert [f.id for f in built] == list(spec)
    return built


def baseline(bid: str, branch: FreshBranch | None = None, **kw) -> Baseline:
    return Baseline(bid, SNAPSHOT, SNAPSHOT.as_of, "lender", shock=SHOCKS[bid], terms=TERMS,
                    branch=branch, **{"horizon_h": 72, **kw})


def plan_model(plan: ScriptedPlan):
    return lambda actor_id, world: plan.model(actor_id, lambda: world.clock.round)


async def searched(tmp: Path, bid: str) -> dict:
    base_dir = tmp / "base"
    base_dir.mkdir()
    base = World("reverse-stress", "base", SNAPSHOT.model_dump(mode="json"),
                 [ACTOR_SPECS[a] for a in ACTORS],
                 model=plan_model(ScriptedPlan(copy.deepcopy(COUPLED["plan"][-1:]))),
                 workdir=base_dir, seed=SEED, coordinator=Coordinator())
    async with base:
        cp = checkpoint(base)
    work = tmp / "branches"
    work.mkdir()
    fresh = FreshBranch(cp, plan_model(ScriptedPlan(copy.deepcopy(COUPLED["plan"]))), work)
    return await reverse_stress(Integrated(), baseline(bid, fresh), families())


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return {bid: asyncio.run(searched(tmp_path_factory.mktemp(bid), bid)) for bid in BASELINES}


# -------------------------------------------------------------------------- the fixture

CASES = [(bid, fid) for bid, b in BASELINES.items() for fid in b["expect"]["results"]]


@pytest.mark.parametrize(("bid", "fid"), CASES, ids=[f"{b}-{f}" for b, f in CASES])
def test_each_family_on_each_baseline(results, bid, fid):
    expect = BASELINES[bid]["expect"]["results"][fid]
    got = results[bid]["results"][fid]
    for key, want in expect.items():
        if key != "note":
            assert got[key] == want, key
    assert got["label"] == LABEL
    if got["breaks"]:
        assert got["confirmed"] is True and got["matches_replay"] is True
        assert got["branch_id"].startswith(COHORT) and got["replay"] is False
        assert got["non_monotone"] is False and got["reactions_frozen"] is False


@pytest.mark.parametrize("bid", list(BASELINES))
def test_the_smallest_shock_and_the_sensitivity_table(results, bid):
    expect = BASELINES[bid]["expect"]
    got = results[bid]
    assert got["smallest"] == expect["smallest"]
    assert len(got["sensitivity_table"]) == expect.get("sensitivity_table_rows",
                                                       len(FIXTURE["families"]))
    assert [r["family"] for r in got["sensitivity_table"]] == [
        f["id"] for f in FIXTURE["families"]]
    for row in got["sensitivity_table"]:
        r = got["results"][row["family"]]
        assert row["status"] == r.get("status", "breaks" if r["breaks"] else "holds")
        assert row["size_bps"] == r.get("size_bps")


def rounds_of(events: list) -> set[int]:
    return {int(re.match(r"r(\d+)", e if isinstance(e, str) else e["text"]).group(1))
            for e in events}


@pytest.mark.parametrize("bid", list(BASELINES))
def test_the_failure_path(results, bid):
    expect = BASELINES[bid]["expect"]["failure_path"]
    path = results[bid]["failure_path"]
    for hour, settled in expect["settled_by_h"].items():
        assert path["settled_by_h"][int(hour)] == settled, hour
    assert path["breach_h"] == expect["breach_h"]
    assert path["confirmed"] is expect["confirmed"]
    assert rounds_of(path["events"]) == rounds_of(expect["events"])
    smallest = results[bid]["results"][path["family"]]
    branch = smallest["branch_settled"]  # the fresh branch's realised ledger, hour by hour
    assert {h: branch[h] for h in (40, 48)} == {h: path["settled_by_h"][h] for h in (40, 48)}


def walk(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{path}.{k}", k, v
            yield from walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for n, v in enumerate(value):
            yield from walk(v, f"{path}[{n}]")


def test_a_search_never_a_forecast_and_its_cohort_apart(results):
    expect = FIXTURE["expect_all"]
    for got in results.values():
        assert not [p for p, k, _ in walk(got) if "probab" in str(k).lower()]
        assert got["label"] == expect["label_on_every_result"] == LABEL
        assert got["cohort"] == expect["cohort"] == COHORT
        assert all(r["label"] == LABEL for r in got["results"].values())
        assert all(r["label"] == LABEL for r in got["sensitivity_table"])
        assert got["failure_path"]["label"] == LABEL
        assert not {"ranking", "selected", "policies", "plan_for_now"} & set(got)
    assert expect["mixed_into_policy_comparison"] is False
    source = (ROOT / "backend/app/decisions/reverse_stress.py").read_text(encoding="utf-8")
    imported = {a.name for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.ImportFrom) for a in node.names}
    assert "rank" not in imported and "decide" not in imported  # nothing here ranks


def test_a_rejected_draw_is_not_retried_in_the_search(results):
    path = replay_world(Integrated(), baseline("demo-shock"),
                        lender_redemption("lender/operating", announce_round=2, due_h=24,
                                          range_=(0, 1), scale=1).events(3_200_001))
    assert [a["type"] for a in path.actions] == ["request_advance"]
    assert any("rejected, K_p = 9,999.99" in e["text"] for e in path.events)


# -------------------------------------------------------------- the search, on its own

def banded(breaks_at) -> SearchFamily:
    """A family that grows payroll past the floor only at the sizes ``breaks_at`` accepts."""
    grow = obligation_growth("payroll-1", announce_round=2, range_=(0, 1), scale=1)
    return SearchFamily("banded", (0, 14), 14,
                        events=lambda size: grow.events(2_000_001) if breaks_at(size) else [])


def search(family: SearchFamily, **kw) -> dict:
    return asyncio.run(reverse_stress(Integrated(), baseline("no-shock", **kw), [family],
                                      confirm=False))["results"][family.id]


def test_a_grid_point_below_the_bisection_is_the_answer_and_flagged():
    # breaks at 2 and from 9: the bisection over [0, 14] lands on 9; the grid saw 2 break
    got = search(banded(lambda s: s == 2 or s >= 9))
    assert (got["breaking_size"], got["non_monotone"]) == (2, True)


def test_a_break_that_closes_again_inside_the_range_is_flagged():
    got = search(banded(lambda s: 5 <= s <= 8))
    assert (got["breaking_size"], got["non_monotone"]) == (5, True)
    assert search(banded(lambda s: s >= 5))["non_monotone"] is False


def test_an_unmatched_recorded_reaction_falls_back_to_no_action():
    # the lender's recorded draw for borrower-c, made having seen nothing new
    draw = Reaction(5, "lender", frozenset(), pool_minor=-1_200_000, what="disburses to c")
    kw = {"reactions": (draw,)}
    redemption = lender_redemption("lender/operating", announce_round=2, due_h=24,
                                   range_=(0, 6_000_000), scale=4_200_000)
    growth = obligation_growth("payroll-1", announce_round=2, range_=(0, 5_000_000),
                               scale=5_000_000)
    assert search(redemption, **kw)["reactions_frozen"] is True  # the lender saw the notice
    assert search(growth, **kw)["reactions_frozen"] is False
    replayed = replay_world(Integrated(), baseline("no-shock", **kw))
    assert any("disburses to c (replayed)" in e["text"] for e in replayed.events)
    frozen = replay_world(Integrated(), baseline("no-shock", **kw), redemption.events(1))
    assert frozen.reactions_frozen and any("no_action" in e["text"] for e in frozen.events)


def test_a_silent_borrower_drops_its_own_reactions_without_freezing():
    repay = Reaction(6, "borrower-b", frozenset(), pool_minor=100_000, what="repays")
    silent = borrower_silence("borrower-b", to="lender", range_=(1, 18), scale=18)
    path = replay_world(Integrated(), baseline("no-shock", reactions=(repay,)),
                        silent.events(4))
    assert not path.reactions_frozen
    assert not any("repays" in e["text"] for e in path.events)


def test_a_shock_the_round_world_cannot_stage_is_not_staged_differently():
    b = baseline("no-shock")
    part = delayed_receipt("rcv-1", range_=(0, 2_000_000), scale=2_000_000)
    assert _staged(b, part.events(1_000_000)) is None
    world, market = _staged(b, part.events(2_000_000))
    assert world == [{"round": 3, "kind": "delay_receipt", "flow_id": "rcv-1", "delay_h": 72}]
    assert market == []
    depeg = stablecoin_depeg("wd-1", settle_delay_h=24, range_=(0, 10_000), scale=10_000)
    assert _staged(b, depeg.events(100)) is None


def test_confirming_needs_a_fresh_branch():
    with pytest.raises(ValueError, match="fresh branch"):
        asyncio.run(reverse_stress(Integrated(), baseline("no-shock"), families()))


def test_a_confirming_branch_id_fits_the_ledgers_branch_column():
    from app.decisions.reverse_stress import _confirm_run_id
    from app.finance.models import branch_meta

    width = branch_meta.c.branch_id.type.length
    family = lender_redemption("lender/operating", announce_round=2, due_h=24,
                               range_=(0, 1), scale=1)
    for bid in ("demo-shock", "a-baseline-whose-name-runs-long-on-purpose"):
        run_id = _confirm_run_id(Baseline(bid, SNAPSHOT, SNAPSHOT.as_of, "lender"), family,
                                 Integrated())
        assert run_id.startswith(COHORT)
        assert len(f"{run_id}-confirm-{Integrated().id}") <= width
    short = _confirm_run_id(baseline("demo-shock"), family, Integrated())
    assert short == f"{COHORT}-demo-shock-lender-redemption"


# ------------------------------------------------------------------------ vet round 1

def test_a_descending_familys_bps_grow_with_its_severity():
    early = SearchFamily("silence-like", (1, 18), 18, descending=True,
                         events=banded(lambda s: True).events)
    assert early.size_bps(1) > early.size_bps(17) and early.size_bps(18) == 0
    got = search(SearchFamily("silence-like", (1, 18), 18, descending=True,
                              events=lambda r: banded(lambda s: True).events(1) if r <= 4
                              else []))
    assert (got["breaking_size"], got["size_bps"]) == (4, 14 * 10_000 // 18)


class Asks:
    """A policy that asks for ``amount`` on adv-a once, at round 1."""

    id = "asks"

    def __init__(self, amount: int):
        self.amount = amount

    def decide(self, view):
        if view.round != 1:
            return []
        view.get("facilities[adv-a]")
        return [{"type": "request_advance", "facility": "adv-a", "amount_minor": self.amount}]


def test_a_draw_that_differs_from_the_offer_is_rejected_as_the_round_world_does():
    path = replay_world(Asks(600_000), baseline("no-shock"))
    assert path.settled[8] == 7_000_000  # nothing arrived
    assert any("rejected, amount_differs_from_offer" in e["text"] for e in path.events)
    assert replay_world(Asks(1_000_000), baseline("no-shock")).settled[8] == 8_000_000


def test_a_facility_of_another_lender_is_refused_rather_than_cleared_on_this_pool():
    snap = SNAPSHOT.model_dump(mode="json")
    snap["entities"].append({"entity_id": "lender-2", "name": "Lender 2 (synthetic)",
                             "kind": "lender pool"})
    snap["contracts"][1]["lender"] = "lender-2"
    snap["pools"].append({"entity": "lender-2", "floor": usd(0)})
    snap["accounts"].append(account("lender-2/operating", 5_000_000))
    b = Baseline("other", Snapshot.model_validate(snap), SNAPSHOT.as_of, "lender",
                 terms=TERMS)
    with pytest.raises(ValueError, match="K_p of lender only; adv-a is lent by lender-2"):
        replay_world(Asks(1_000_000), b)


def test_a_flow_already_overdue_at_the_snapshot_is_still_shocked():
    snap = SNAPSHOT.model_dump(mode="json")
    snap["as_of"] = snap["accounts"][0]["as_of"] = iso_utc(12)
    b = Baseline("late", Snapshot.model_validate(snap), SNAPSHOT.as_of, "lender", terms=TERMS)
    path = replay_world(Integrated(), b, delayed_receipt(
        "rcv-1", range_=(0, 2_000_000), scale=2_000_000).events(2_000_000))
    assert any("slips past the horizon" in e["text"] for e in path.events)
    assert path.settled[16] == 7_000_000  # rcv-1 never landed


def test_an_obligation_due_after_the_last_round_is_not_counted_unmet():
    late = SearchFamily("late", (0, 1), 1, events=lambda size: [
        {"round": 2, "kind": "obligation", "obligation_id": "late-1",
         "account": "treasury/operating", "amount_minor": 1, "due_h": 73}])
    path = replay_world(Integrated(), baseline("no-shock", horizon_h=74), late.events(1))
    assert path.obligations_unmet == 0 and not path.breaks

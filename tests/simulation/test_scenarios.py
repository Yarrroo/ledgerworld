"""The demo world and its six scenario families (T10).

The world is checked against C5 (JSON Schema and pydantic), against ``actors.json`` unchanged and
against LF-1 and LF-2. Each family runs on a real OASIS platform with its ``ScriptedModel`` plan
through ``Coordinator.run_round`` up to the third round from the one it starts in, and must clear
at least one financial action in those rounds; a second run on the same seed must give the same
journals. ``scenario-families.json``'s ``expect_all`` block is asserted unchanged.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from app.finance import ledger
from app.finance.lending import capacity
from app.finance.schemas import ScenarioSpec, Snapshot
from app.finance.spendability import floor_check, projected_cash
from app.finance.store import LedgerStore
from app.simulation.clock import HORIZON_ROUNDS, ROUND_HOURS
from app.simulation.scenarios import (
    FAMILY_IDS,
    build_world,
    load_family,
    load_world,
)
from app.simulation.world import World, import_oasis
from jsonschema import Draft202012Validator

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/agent-world/fixtures"
ACTORS = json.loads((FIXTURES / "actors.json").read_text())
FAMILIES = json.loads((FIXTURES / "scenario-families.json").read_text())
COUPLED = json.loads((FIXTURES / "coupled-chain.json").read_text())
LF1 = json.loads((ROOT / "fixtures/lf1_treasury.json").read_text())
LF2 = json.loads((ROOT / "fixtures/lf2_lender.json").read_text())
C5 = json.loads((ROOT / "contracts/c5_snapshot.schema.json").read_text())
WORLD_RAW = json.loads((ROOT / "scenarios/world.json").read_text())
FINANCIAL = {"request_advance", "accept", "offer", "disburse", "release", "pay", "pledge",
             "repay", "convert", "defer"}


def c5_errors(snapshot: dict) -> list[str]:
    check = Draft202012Validator(C5, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [f"{list(e.absolute_path)}: {e.message}" for e in check.iter_errors(snapshot)]


def h(world: World, hours: int):
    return world.clock.epoch + timedelta(hours=hours)


# ------------------------------------------------------------------------------- the world


def test_the_world_validates_against_c5_and_so_does_every_family_snapshot():
    assert c5_errors(WORLD_RAW["snapshot"]) == []
    world = load_world()
    assert world.snapshot == Snapshot.model_validate(WORLD_RAW["snapshot"])
    for family_id in FAMILY_IDS:
        snap = load_family(family_id).snapshot(world.snapshot)
        assert c5_errors(snap.model_dump(mode="json", exclude_none=True)) == [], family_id


def test_the_world_has_the_eight_fixture_actors_all_synthetic():
    world = load_world()
    assert WORLD_RAW["synthetic"] is ACTORS["synthetic"] is True
    assert world.actors == ACTORS["actors"]  # the fixture, unchanged
    assert (WORLD_RAW["round_hours"], WORLD_RAW["horizon_hours"]) == \
        (ACTORS["round_hours"], ACTORS["horizon_hours"]) == (ROUND_HOURS, 72)
    expect = ACTORS["expect"]
    llm = [a for a in world.actors if a["llm"]]
    assert len(world.actors) == 8
    assert (len(llm), len(world.actors) - len(llm)) == (expect["llm_actors"],
                                                         expect["rule_actors"])
    assert (len(llm), HORIZON_ROUNDS) == (expect["calls_per_round_max"], expect["rounds"])
    assert len(llm) * HORIZON_ROUNDS == expect["calls_per_branch_max"]
    entities = {e.entity_id: e for e in world.snapshot.entities}
    assert set(entities) == {a["actor_id"] for a in world.actors}
    assert all(e.synthetic and "(synthetic)" in e.name for e in entities.values())
    kinds = {a["actor_id"]: entities[a["actor_id"]].kind for a in world.actors}
    assert (kinds["treasury"], kinds["lender"], kinds["venue"]) == \
        ("treasury", "lender pool", "venue")
    assert [a for a, k in kinds.items() if k == "borrower"] == ["borrower-b", "borrower-c"]
    # A family's model-actor scope is the World's: the ledger entity is the actor id.
    assert all(a.entity == a.id.split("/")[0] for a in world.snapshot.accounts)


def test_the_world_ledger_is_lf1_and_lf2():
    """The treasury reproduces LF-1's no-shock path and the pool LF-2's K_p (system brief §6)."""
    world = load_world()
    store = LedgerStore("sqlite://")
    ledger.from_snapshot(store, world.snapshot)
    want = LF1["expected"]["no_shock"]
    view = store.view("treasury/operating")
    for t, p in want["P"].items():
        assert projected_cash(view, world.epoch + timedelta(hours=int(t))) == p, t
    check = floor_check(view, world.epoch)
    assert (check.feasible, check.min_p) == (True, want["min_P"]["value"])
    k_p = capacity(store, "lender", world.epoch).K_p
    assert k_p == COUPLED["lender_before"]["K_p"] == LF2["expected"]["K_p_before"]["value"]


# ---------------------------------------------------------------------------- the families


def test_the_six_families_are_the_fixtures():
    expect = FAMILIES["expect_all"]
    by_id = {f["id"]: f for f in FAMILIES["families"]}
    assert list(by_id) == list(FAMILY_IDS) and len(FAMILY_IDS) == expect["families"]
    assert sorted(p.name for p in (ROOT / "scenarios/families").glob("*.json")) == \
        sorted(f"{i}.json" for i in FAMILY_IDS)
    for family_id in FAMILY_IDS:
        family, fx = load_family(family_id), by_id[family_id]
        assert (family.seed, family.starts_round, family.rounds) == \
            (fx["seed"], fx["starts_round"], expect["rounds_each"])
        raw = json.loads((ROOT / f"scenarios/families/{family_id}.json").read_text())
        assert raw["expect_cleared"] == fx["expect_cleared"]
        assert family.cleared  # what the plan clears in the family's rounds
        # The C6 spelling of a family loads the same family.
        spec = ScenarioSpec(family=family_id.replace("-", "_"), seed=fx["seed"], params={})
        assert load_family(spec.family, spec.seed, spec.params) == family
    p = {f: load_family(f).params for f in FAMILY_IDS}
    fp = {f: by_id[f]["params"] for f in FAMILY_IDS}
    assert p["delayed-receipt"]["delay_h"] == fp["delayed-receipt"]["delay_h"]
    assert (p["confidence-rumour"]["post_round"], p["confidence-rumour"]["audience"]) == \
        (fp["confidence-rumour"]["post_round"], fp["confidence-rumour"]["audience"])
    depeg = p["stablecoin-depeg"]
    assert (depeg["asset"], depeg["pending_in_minor"], depeg["settle_delay_h"]) == \
        tuple(fp["stablecoin-depeg"][k] for k in ("asset", "pending_in_minor", "settle_delay_h"))
    assert [round(float(r) * 100) for r in depeg["price_path"]] == \
        [round(r * 100) for r in fp["stablecoin-depeg"]["price_path"]]
    assert {k: p["borrower-silence"][k] for k in fp["borrower-silence"]} == \
        fp["borrower-silence"]
    assert {k: p["redemption-spike"][k] for k in ("grows_from_minor", "grows_to_minor",
                                                  "at_round")} == \
        {k: fp["redemption-spike"][k] for k in ("grows_from_minor", "grows_to_minor",
                                                "at_round")}
    assert [round(float(r) * 100) for r in p["fx-gap"]["eurusd_path"]] == \
        [round(r * 100) for r in fp["fx-gap"]["eurusd_path"]]
    assert (p["fx-gap"]["currency"], p["fx-gap"]["amount_minor"], p["fx-gap"]["due_h"]) == \
        ("EUR", 1_000_000, 36)


def test_a_family_is_parameterised_and_refuses_what_it_cannot_run():
    late = load_family("delayed-receipt", params={"delay_h": 12, "at_round": 2})
    assert late.events == [{"round": 2, "kind": "delay_receipt", "flow_id": "receivable-1",
                            "delay_h": 12, "id": "delay-receivable-1"}]
    assert load_family("delayed-receipt", seed=7).seed == 7
    spike = load_family("redemption-spike", params={"grows_to_minor": 900_000})
    assert spike.market[0]["amount_minor"] == 400_000
    depeg = load_family("stablecoin-depeg", params={"price_path": ["0.99", "0.90"]})
    assert [(m["round"], m["rate"]) for m in depeg.market] == [(3, "0.99"), (4, "0.90")]
    with pytest.raises(ValueError, match="unknown scenario family"):
        load_family("bank-run")
    with pytest.raises(ValueError, match="no parameters"):
        load_family("fx-gap", params={"leverage": 3})
    with pytest.raises(ValueError, match="decimal strings"):
        load_family("fx-gap", params={"eurusd_path": [1.08, 1.11]})  # a float never enters
    with pytest.raises(ValueError, match="integer"):
        load_family("stablecoin-depeg", params={"pending_in_minor": 1500000.0})
    with pytest.raises(ValueError, match="grows"):
        load_family("redemption-spike", params={"grows_to_minor": 400_000})
    with pytest.raises(TypeError, match="seed"):
        load_family("fx-gap", seed="106")


def test_a_silent_borrower_never_acts_in_its_family():
    family = load_family("borrower-silence")
    assert not [e for e in family.script if e.get("actor_id") == "borrower-b"]
    with pytest.raises(ValueError, match="acts after it fell silent"):
        load_family("borrower-silence", params={"borrower": "borrower-c"},
                    directory=_with_script(family, "borrower-c"))


def _with_script(family, talker: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="families-"))
    raw = json.loads((ROOT / "scenarios/families/borrower-silence.json").read_text())
    raw["script"].append({"actor_id": talker, "round": family.params["from_round"] + 1,
                          "tool_calls": [{"name": "pay", "args": {
                              "to": "lender", "amount_minor": 100, "currency": "USD"}}]})
    (directory / "borrower-silence.json").write_text(json.dumps(raw))
    return directory


# --------------------------------------------------------------------- running each family

_RUNS: dict[tuple[str, int], dict] = {}


def run_family(family_id: str, attempt: int, tmp_path_factory) -> dict:
    """Run a family up to its last round, once per attempt; what the tests read of it."""
    key = (family_id, attempt)
    if key not in _RUNS:
        family = load_family(family_id)
        workdir = tmp_path_factory.mktemp(f"{family_id}-{attempt}")
        world = build_world(family, workdir=workdir)
        _RUNS[key] = asyncio.run(_run(world, family))
    return _RUNS[key]


async def _run(world: World, family) -> dict:
    out: dict = {"rounds": [], "probes": {}}
    async with world:
        for _ in range(family.last_round):
            result = await world.coordinator.run_round(world)
            out["rounds"].append(result)
            now = world.clock.now
            view = world.store.view("treasury/operating")
            out["probes"][result.round] = {
                "K_p": capacity(world.store, "lender", now).K_p,
                "P40": projected_cash(view, h(world, 40)),
                "floor": floor_check(view, now),
            }
    dump = world.store.dump()
    out["journals"] = {"journals": dump["journals"], "postings": dump["postings"]}
    return out


def window(run: dict, family) -> list:
    return [c for r in run["rounds"] if r.round >= family.starts_round for c in r.records]


@pytest.mark.parametrize("family_id", FAMILY_IDS)
def test_each_family_runs_three_rounds_and_clears_a_financial_action(family_id,
                                                                      tmp_path_factory):
    family = load_family(family_id)
    run = run_family(family_id, 0, tmp_path_factory)
    assert [r.round for r in run["rounds"]][-FAMILIES["expect_all"]["rounds_each"]:] == \
        list(range(family.starts_round, family.last_round + 1))
    records = window(run, family)
    cleared = [(c.actor_id, c.type) for c in records
               if c.type in FINANCIAL and c.c2.status == "accepted"]
    assert len(cleared) >= FAMILIES["expect_all"]["min_cleared_financial_actions_each"]
    assert sorted(set(cleared)) == sorted(set(family.cleared))
    refused = {c.type: c.c2.reason for c in records if c.c2.status == "rejected"}
    assert refused == family.refused
    probes = run["probes"]
    match family_id:
        case "delayed-receipt":
            # LF-1's shock: P(t=40) after payroll = 20,000.00 < floor 30,000.00, short 10,000.00.
            shocked = probes[family.params["at_round"]]["floor"]
            assert probes[family.params["at_round"]]["P40"] == 2_000_000
            assert (shocked.feasible, shocked.short_minor) == (False, 1_000_000)
            # The disbursed advance is in transit: the floor holds again, exactly (LF-1 plan).
            after = probes[family.last_round]["floor"]
            assert (after.feasible, after.min_p) == (True, 3_000_000)
        case "confidence-rumour":
            expect = COUPLED["expect"]["shock"]
            assert probes[family.last_round]["K_p"] == expect["K_p_after"]
            assert any(j["journal_id"] == "j:i-r5-lender-2" for j in run["journals"]["journals"])
        case "redemption-spike":
            r = family.params["at_round"]
            increase = family.params["grows_to_minor"] - family.params["grows_from_minor"]
            assert probes[r - 1]["K_p"] - probes[r]["K_p"] == increase
            assert probes[r - 1]["K_p"] == 4_200_000 - family.params["grows_from_minor"]
        case "borrower-silence":
            silent = [c for r in run["rounds"] for c in r.records
                      if c.actor_id == family.params["borrower"]
                      and r.round >= family.params["from_round"]]
            assert silent and {c.type for c in silent} == {"no_action"}
        case "stablecoin-depeg" | "fx-gap":
            # The family's prices reached the treasury as public prices, as decimal strings.
            seen = [i for i in run["rounds"][-1].transcript_entry["evidence"]["treasury"]
                    if i.startswith("px-")]
            assert len(seen) == len([m for m in family.market
                                     if m["round"] <= family.last_round])


@pytest.mark.parametrize("family_id", FAMILY_IDS)
def test_the_same_seed_gives_the_same_journals(family_id, tmp_path_factory):
    first = run_family(family_id, 0, tmp_path_factory)
    second = run_family(family_id, 1, tmp_path_factory)
    assert FAMILIES["expect_all"]["same_seed_same_journals"] is True
    assert first["journals"]["journals"]  # there is something to compare
    assert first["journals"] == second["journals"]
    assert [r.transcript_entry["c2"] for r in first["rounds"]] == \
        [r.transcript_entry["c2"] for r in second["rounds"]]

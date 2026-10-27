"""Fixtures LF-1 and LF-2: valid C5 snapshots whose expected numbers add up by hand (T03).

The arithmetic here is a pencil, not the ledger: it re-derives every expected number from the
snapshot with the formulas of system brief §5 and §6 and never imports the finance engine.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

import pytest
from app.finance.schemas import Snapshot
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
DESIGN = ROOT / "prp/2026-10-20-ledgerworld/design/modules/ledger/fixtures"
EXAMPLES = ROOT / "contracts/examples/c5_snapshot"
NAMES = {"lf1_treasury": "lf1-treasury", "lf2_lender": "lf2-lender"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def fixture(name: str) -> dict:
    return load(FIXTURES / f"{name}.json")


@cache
def c5() -> Draft202012Validator:
    schema = load(ROOT / "contracts/c5_snapshot.schema.json")
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def hours(fx: dict, iso: str) -> float:
    return (at(iso) - at(fx["t0"])) / timedelta(hours=1)


def usd(minor: int) -> str:
    """The hand notation of the fixtures: 4000000 -> '40,000'."""
    return f"{minor // 100:,}" + (f".{minor % 100:02d}" if minor % 100 else "")


def snapshots(name: str) -> list[tuple[str, dict]]:
    fx = fixture(name)
    return [("snapshot", fx["snapshot"])] + [
        (f"stressed.{k}", s) for k, s in fx.get("stressed", {}).items()
    ]


# ---------------------------------------------------------------------- shape and provenance

@pytest.mark.parametrize("name", NAMES)
def test_snapshots_are_valid_c5(name):
    for where, snap in snapshots(name):
        errors = [e.message for e in c5().iter_errors(snap)]
        assert errors == [], f"{name} {where}: {errors}"
        assert Snapshot.model_validate(snap).model_dump(mode="json", exclude_unset=True) == snap


@pytest.mark.parametrize("name", NAMES)
def test_expected_block_is_the_design_fixture_unchanged(name):
    design = load(DESIGN / f"{NAMES[name]}.json")
    assert fixture(name)["expected"] == design["expected"]
    assert fixture(name)["definitions"] == design["definitions"]


def test_snapshots_are_the_c5_examples():
    assert fixture("lf1_treasury")["snapshot"] == load(EXAMPLES / "valid-lf1.json")["instance"]
    lf2 = fixture("lf2_lender")
    assert lf2["snapshot"] == load(EXAMPLES / "valid-lf2.json")["instance"]
    frozen = load(EXAMPLES / "valid-lf2-venue-freeze.json")["instance"]
    assert lf2["stressed"]["venue_freeze"] == frozen


def test_lf1_snapshot_carries_the_design_numbers():
    fx, design = fixture("lf1_treasury"), load(DESIGN / "lf1-treasury.json")
    (acct,), (want,) = fx["snapshot"]["accounts"], design["snapshot"]["accounts"]
    buckets, wanted = acct["buckets"], want["buckets"]
    assert acct["floor"]["minor"] == want["floor_minor"]
    for bucket in ("settled", "reserved", "pledged"):
        assert buckets[bucket]["minor"] == wanted[bucket]
    flows = {f["flow_id"]: f for f in buckets["pending_in"]}
    for w in wanted["pending_in"]:
        assert flows[w["flow_id"]]["amount"]["minor"] == w["amount"]
        assert hours(fx, flows[w["flow_id"]]["expected_at"]) == w["expected_h"]
    (ob,), (wob,) = fx["snapshot"]["obligations"], design["snapshot"]["obligations"]
    assert (ob["amount"]["minor"], hours(fx, ob["due_at"])) == (wob["amount"], wob["due_h"])
    assert ob["reservation_id"] == wob["reservation_id"]


def test_lf2_snapshot_carries_the_design_numbers():
    fx, design = fixture("lf2_lender"), load(DESIGN / "lf2-lender.json")
    accounts = {a["id"]: a["buckets"] for a in fx["snapshot"]["accounts"]}
    for want in design["snapshot"]["accounts"]:
        for bucket in ("settled", "reserved", "pledged"):
            assert accounts[want["id"]][bucket]["minor"] == want["buckets"][bucket]
    (pool,) = fx["snapshot"]["pools"]
    assert pool["floor"]["minor"] == design["snapshot"]["pool"]["floor_minor"]
    contracts = {c["contract_id"]: c for c in fx["snapshot"]["contracts"]}
    line, adv = contracts["line-b"], contracts["adv-a"]
    assert line["limit"]["minor"] == 1000000 and line["drawn"]["minor"] == 0
    assert (adv["principal"]["minor"], adv["fee_bps"], adv["repay_share_bps"]) == (
        1000000, 800, 1500)


def test_the_venue_couples_the_two_worlds():
    """The 15,000 LF-1 expects from the venue is the 15,000 LF-2 holds there."""
    lf1, lf2 = fixture("lf1_treasury")["snapshot"], fixture("lf2_lender")["snapshot"]
    (x1,), (x2,) = lf1["exposures"], lf2["exposures"]
    assert x1["venue"] == x2["venue"]
    assert "lender" in x1["shared_with"] and "borrower-a" in x2["shared_with"]
    withdrawal = next(f for a in lf1["accounts"] for f in a["buckets"]["pending_in"]
                      if f["flow_id"] == x1["flow_id"])
    venue = next(a for a in lf2["accounts"] if a["id"] == x2["account"])
    assert withdrawal["amount"]["minor"] == venue["buckets"]["settled"]["minor"] == 1500000


# ------------------------------------------------------------------------- LF-1 by hand

def treasury(delay_h: int = 0, extra_in: list[tuple[int, int]] = ()):
    """S(t), P(t) and the floor of LF-1's one account, with rcv-1 delayed and inflows added."""
    fx = fixture("lf1_treasury")
    snap = fx["snapshot"]
    (acct,) = snap["accounts"]
    b = acct["buckets"]
    ins = [(hours(fx, f["expected_at"]) + (delay_h if f["kind"] == "receivable" else 0),
            f["amount"]["minor"]) for f in b["pending_in"]]
    ins += list(extra_in)
    outs = [(hours(fx, f["expected_at"]), f["amount"]["minor"]) for f in b["pending_out"]]
    dues = [(hours(fx, o["due_at"]), o["amount"]["minor"]) for o in snap["obligations"]]
    settled, reserved, pledged = (b[k]["minor"] for k in ("settled", "reserved", "pledged"))

    def S(t):
        return (settled - reserved - pledged - sum(a for _, a in outs)
                + sum(a for h, a in ins if h <= t))

    def P(t):
        return (settled + sum(a for h, a in ins if h <= t) - sum(a for h, a in outs if h <= t)
                - sum(a for h, a in dues if h <= t))

    return S, P, acct["floor"]["minor"]


def min_p(P):
    horizon = fixture("lf1_treasury")["horizon_h"]
    value, at_h = min((P(t), t) for t in range(horizon + 1))
    return {"value": value, "at_h": at_h}


def test_lf1_no_shock():
    want = fixture("lf1_treasury")["expected"]["no_shock"]
    S, P, floor = treasury()
    assert {h: S(int(h)) for h in want["S"]} == want["S"]
    assert {h: P(int(h)) for h in want["P"]} == want["P"]
    assert min_p(P) == want["min_P"]
    assert want["headroom_0"] == max(0, min_p(P)["value"] - floor) == 1000000
    assert want["feasible"] is (min_p(P)["value"] >= floor)
    assert usd(want["min_P"]["value"]) in want["hand"]


def test_lf1_receipt_delayed_240h_breaches_the_floor():
    want = fixture("lf1_treasury")["expected"]["shock_receipt_delayed_240h"]
    _, P, floor = treasury(delay_h=240)
    assert {h: P(int(h)) for h in want["P"]} == want["P"]
    assert min_p(P) == want["min_P"]
    assert want["feasible"] is (min_p(P)["value"] >= floor) is False
    breach = want["breach"]
    assert breach["at_h"] == want["min_P"]["at_h"]
    assert breach["short_minor"] == floor - min_p(P)["value"] == 1000000
    assert f"{usd(floor)}.00" in breach["binding"]
    assert usd(breach["short_minor"]) in want["hand"]


def test_lf1_integrated_plan_keeps_the_floor_exactly():
    want = fixture("lf1_treasury")["expected"]["integrated_plan"]
    (advance,) = want["actions"]
    assert advance["arrives_h"] <= advance["deadline_h"]
    _, P, floor = treasury(delay_h=240, extra_in=[(advance["arrives_h"], advance["amount"])])
    assert {h: P(int(h)) for h in want["P"]} == want["P"]
    assert min_p(P) == want["min_P"]
    assert want["min_P"]["value"] == floor
    assert want["feasible"] is (min_p(P)["value"] >= floor) is True
    # the advance is exactly the shortfall of the shock: no more borrowed than needed
    shock = fixture("lf1_treasury")["expected"]["shock_receipt_delayed_240h"]
    assert advance["amount"] == shock["breach"]["short_minor"]


def test_lf1_rejections():
    expected = fixture("lf1_treasury")["expected"]
    cases = {c["id"]: c for c in expected["rejections"]}
    S, P, floor = treasury()
    headroom = expected["no_shock"]["headroom_0"]

    def verdict(amount):
        if amount > S(0):
            return "insufficient_spendable"
        if amount > headroom:
            return "breaks_floor"
        return "accepted"

    big = cases["pay-80k"]
    assert big["S_0"] == S(0) == expected["no_shock"]["S"]["0"]
    assert verdict(big["intent"]["amount"]) == big["reason"] and big["status"] == "rejected"
    mid = cases["pay-20k-breaks-floor"]
    assert verdict(mid["intent"]["amount"]) == mid["reason"] and mid["status"] == "rejected"
    assert P(40) - mid["intent"]["amount"] < floor
    small = cases["pay-10k-keeps-floor"]
    assert verdict(small["intent"]["amount"]) == small["status"] == "accepted"
    assert P(40) - small["intent"]["amount"] == floor

    pledge = cases["double-pledge"]
    first, second = pledge["intents"]
    assert first["collateral_ref"] == second["collateral_ref"]
    assert first["amount"] <= S(0)
    assert pledge["status"] == ["accepted", "rejected"] and pledge["reason"] == "already_pledged"

    idle = cases["inaction-keeps-obligation"]
    (payroll,) = fixture("lf1_treasury")["snapshot"]["obligations"]
    assert idle["intent"]["type"] == "no_action" and payroll["obligation_id"] in idle["expect"]
    assert payroll.get("mandatory", True) and payroll.get("state", "open") == "open"
    (acct,) = fixture("lf1_treasury")["snapshot"]["accounts"]
    assert acct["buckets"]["reserved"]["minor"] == payroll["amount"]["minor"]


# ------------------------------------------------------------------------- LF-2 by hand

def capacity(snap: dict) -> tuple[int, str, dict]:
    """K_p of the pool, its authority and its parts: §6's formula, read off one snapshot."""
    (pool,) = snap["pools"]
    accounts = [a for a in snap["accounts"] if a["entity"] == pool["entity"]]
    known = [a for a in accounts if a["observability"] == "known"]
    lines = [c for c in snap["contracts"]
             if c["kind"] == "committed_line" and c["lender"] == pool["entity"]]
    parts = {
        "settled_known": sum(a["buckets"]["settled"]["minor"] for a in known),
        "committed_undrawn": sum(c["limit"]["minor"] - c["drawn"]["minor"] for c in lines),
        "pledged": sum(a["buckets"]["pledged"]["minor"] for a in accounts),
        "obligations": sum(o["amount"]["minor"] for o in snap["obligations"]
                           if o["entity"] == pool["entity"]),
        "floor": pool["floor"]["minor"],
    }
    k_p = parts["settled_known"] - sum(v for k, v in parts.items() if k != "settled_known")
    return k_p, "full" if len(known) == len(accounts) else "reduced", parts


def test_lf2_capacity_before_and_under_the_venue_freeze():
    fx = fixture("lf2_lender")
    want = fx["expected"]
    k_p, authority, parts = capacity(fx["snapshot"])
    assert parts == {"settled_known": 6000000, "committed_undrawn": 1000000, "pledged": 0,
                     "obligations": 0, "floor": 800000}
    assert (k_p, authority) == (want["K_p_before"]["value"], "full")
    assert usd(k_p) in want["K_p_before"]["hand"]

    stress = want["stress_venue_freeze"]
    frozen = fx["stressed"]["venue_freeze"]
    venue = next(a for a in frozen["accounts"] if a["id"] == "lender/venue")
    assert venue["observability"] == stress["lender/venue"] == "unknown"
    assert venue["buckets"]["settled"] is None  # unknown, not zero
    k_p, authority, parts = capacity(frozen)
    assert parts["settled_known"] == 4500000
    assert (k_p, authority) == (stress["K_p"], stress["authority"])
    assert usd(k_p) in stress["hand"]
    # the freeze removes exactly the venue's 15,000 and nothing else
    assert want["K_p_before"]["value"] - stress["K_p"] == 1500000


def test_lf2_committed_line_is_the_operating_reservation():
    snap = fixture("lf2_lender")["snapshot"]
    line = next(c for c in snap["contracts"] if c["kind"] == "committed_line")
    held = next(a for a in snap["accounts"] if a["id"] == line["reserved_on"])
    assert held["buckets"]["reserved"]["minor"] == line["limit"]["minor"] - line["drawn"]["minor"]


def test_lf2_draws_against_capacity():
    fx = fixture("lf2_lender")
    want = fx["expected"]
    stressed = want["draw_30k_under_stress"]
    k_p, _, _ = capacity(fx["stressed"]["venue_freeze"])
    assert stressed["K_p_minor"] == k_p < 3000000
    assert (stressed["status"], stressed["reason"]) == ("rejected", "beyond_capacity")
    assert stressed["binding"] == f"K_p = {usd(k_p)}.00"

    calm = want["draw_30k_no_stress"]
    k_p, _, _ = capacity(fx["snapshot"])
    assert calm["status"] == "accepted" and calm["K_p_after"] == k_p - 3000000

    line = want["committed_line_draw"]
    after = json.loads(json.dumps(fx["snapshot"]))
    drawn = next(c for c in after["contracts"] if c["contract_id"] == "line-b")
    drawn["drawn"]["minor"] += line["amount"]
    operating = next(a for a in after["accounts"] if a["id"] == drawn["reserved_on"])
    operating["buckets"]["settled"]["minor"] -= line["amount"]
    assert line["borrower"] == drawn["borrower"]
    assert capacity(after)[0] == line["K_p_after"] == k_p


def test_lf2_advance_and_repayment_from_observed_revenue():
    fx = fixture("lf2_lender")
    adv = next(c for c in fx["snapshot"]["contracts"] if c["kind"] == "revenue_advance")
    want = fx["expected"]["advance"]
    disburse = want["disburse"]
    assert disburse["principal"] == adv["principal"]["minor"]
    assert disburse["fee"] == adv["principal"]["minor"] * adv["fee_bps"] // 10000 == 80000
    assert disburse["owed"] == disburse["principal"] + disburse["fee"]
    assert disburse["K_p_after"] == capacity(fx["snapshot"])[0] - disburse["principal"]

    outstanding = disburse["owed"]
    for week in ("week_1", "week_2_forecast_only", "week_3", "week_4"):
        case = want[week]
        revenue = case["observed_revenue"]  # forecast revenue is never read
        due = 0 if revenue is None else revenue * adv["repay_share_bps"] // 10000
        repayment = min(due, outstanding)
        outstanding -= repayment
        assert (case["repayment"], case["outstanding"]) == (repayment, outstanding), week
    assert outstanding == 0
    assert want["week_3"]["observed_revenue"] * adv["repay_share_bps"] % 10000  # rounded down
    assert want["week_4"]["observed_revenue"] * adv["repay_share_bps"] // 10000 > \
        want["week_4"]["repayment"]  # capped

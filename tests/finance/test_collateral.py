"""The collateral facility's borrowing base (T21), read from the decisions design's
``collateral.json`` unchanged: haircuts rounded down, one pass of obligor then type limits on the
pre-limit total, unknown, stale and pledged lots adding nothing, draws within and beyond the base,
the double pledge refused by the ledger, and no wiring to execution.
"""

from __future__ import annotations

import ast
import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.finance.collateral import borrowing_base, draw, pledge_lot
from app.finance.models import Journal, Posting
from app.finance.schemas import LegKind
from app.finance.store import LedgerStore

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
FIXTURE = json.loads((ROOT / "prp/2026-10-20-ledgerworld/design/modules/decisions/fixtures"
                      / "collateral.json").read_text())
CASES = {c["id"]: c for c in FIXTURE["cases"]}


def lots_for(case: dict) -> list[dict]:
    """The fixture's lots with a case's ``change`` (``lots[<id>].<field>``) applied."""
    if "lots_only" in case:
        return copy.deepcopy(case["lots_only"])
    lots = copy.deepcopy(FIXTURE["lots"])
    for key, value in case.get("change", {}).items():
        lot_id, attr = re.fullmatch(r"lots\[(\w+)\]\.(\w+)", key).groups()
        (lot,) = [lot for lot in lots if lot["lot_id"] == lot_id]
        lot[attr] = value
    return lots


def base_of(case: dict):
    return borrowing_base(lots_for(case), case.get("limits", FIXTURE["limits"]), FIXTURE["now"],
                          eligible_types=FIXTURE["eligible_types"])


BASE_CASES = [c for c in CASES.values() if "pre_limit" in c["expect"]
              or "borrowing_base" in c["expect"]]


@pytest.mark.parametrize("case", BASE_CASES, ids=[c["id"] for c in BASE_CASES])
def test_the_borrowing_base(case):
    got = base_of(case).as_dict()
    for key, want in case["expect"].items():
        if key != "hand":
            assert got[key] == want, key


def test_the_stale_threshold_is_the_ledgers():
    assert FIXTURE["stale_after_h"] == 6
    lot = dict(FIXTURE["lots"][0], as_of="2026-01-05T06:00:00Z")  # exactly 6 h old: still fresh
    assert borrowing_base([lot], {}, FIXTURE["now"]).excluded == {}


@pytest.mark.parametrize("case_id", ["draw-beyond-base", "draw-within-base"])
def test_a_draw_is_checked_against_the_base(case_id):
    case = CASES[case_id]
    assert draw(base_of(CASES["base"]), case["draw"]["amount"]) == case["expect"]


def test_a_draw_counts_what_is_already_drawn():
    base = base_of(CASES["base"])
    assert draw(base, 1, drawn_minor=base.borrowing_base)["status"] == "rejected"
    with pytest.raises(ValueError):
        draw(base, 0)


def test_a_bad_lot_is_refused_rather_than_guessed():
    lot = dict(FIXTURE["lots"][0], haircut_bps=10_001)
    with pytest.raises(ValueError, match="haircut"):
        borrowing_base([lot], {}, FIXTURE["now"])
    with pytest.raises(ValueError, match="twice"):
        borrowing_base([FIXTURE["lots"][0]] * 2, {}, FIXTURE["now"])


def test_a_lot_pledged_to_this_facility_counts_and_to_another_does_not():
    lot = dict(FIXTURE["lots"][5])  # L6, pledged to another-facility
    assert borrowing_base([lot], {}, FIXTURE["now"]).excluded == {"L6": "already_pledged"}
    mine = borrowing_base([lot], {}, FIXTURE["now"], facility="another-facility")
    assert mine.after_haircut == {"L6": 400_000}


def test_the_same_lot_is_never_pledged_twice():
    case = CASES["pledge-twice"]
    store = LedgerStore("sqlite://")
    t0 = datetime.fromisoformat(FIXTURE["now"]).astimezone(UTC)
    store.add_entity("borrower-b", "Borrower B (synthetic)", "borrower")
    store.open_account("borrower-b/operating", "borrower-b", "USD", as_of=t0)
    store.open_account("borrower-b/opening", "borrower-b", "USD", kind="external", as_of=t0)
    store.apply(Journal("open:borrower-b", (Posting("borrower-b/operating", 10_000_000),
                                            Posting("borrower-b/opening", -10_000_000))))
    lots = {lot["lot_id"]: lot for lot in FIXTURE["lots"]}
    results = [pledge_lot(store, "borrower-b/operating", lots[p["lot_id"]], p["facility"])
               for p in case["pledge"]]
    assert [r["status"] for r in results] == case["expect"]["status"]
    assert results[1]["reason"] == case["expect"]["reason"]
    active = [p for p in store.rows("pledges") if p["state"] == "active"]
    assert [(p["collateral_ref"], p["facility_id"]) for p in active] == [("L1", "col-1")]


def imports_of(path: Path) -> set[str]:
    """Every module ``path`` imports, relative imports resolved against its package."""
    package = path.relative_to(BACKEND.parent).with_suffix("").parts[:-1]
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = list(package[:len(package) - node.level + 1]) if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            out |= {module, *(f"{module}.{a.name}" for a in node.names)}
    return out


def test_collateral_is_not_wired_to_execution():
    expect = CASES["not-wired-to-execution"]["expect"]
    wired = [p for d in ("execution", "connectors", "api") for p in (BACKEND / d).rglob("*.py")
             if "app.finance.collateral" in imports_of(p)]
    assert len(wired) == expect["imports"]
    routes = [p for p in (BACKEND / "api").rglob("*.py")
              if "collateral" in p.read_text(encoding="utf-8")]
    assert routes == []
    leg_kinds = [k for k in LegKind.__args__ if "collateral" in k]
    assert len(leg_kinds) == expect["leg_kinds_with_collateral"]
    # the scanner resolves relative imports: it sees the decisions module's own lending import
    assert "app.finance.lending" in imports_of(BACKEND / "decisions/candidates.py")


# ------------------------------------------------------------------------ vet round 1

def test_an_obligors_cut_is_shared_across_its_types_exactly():
    """X holds three types of 10 and is cut by 2; the cut is shared 1, 1, 0 in lot order, so
    type a keeps 9 and sits exactly at its 9 % limit: no second cut."""
    def lot(lot_id, kind, obligor, value):
        return {"lot_id": lot_id, "type": kind, "obligor": obligor, "value": value,
                "haircut_bps": 0, "as_of": FIXTURE["now"]}
    lots = [lot("a1", "a", "x", 10), lot("b1", "b", "x", 10), lot("c1", "c", "x", 10),
            lot("d1", "d", "y1", 23), lot("d2", "d", "y2", 23), lot("d3", "d", "y3", 24)]
    base = borrowing_base(lots, {"per_obligor_bps": 2800, "per_type_bps": {"a": 900}},
                          FIXTURE["now"], eligible_types=("a", "b", "c", "d"))
    assert (base.pre_limit, base.obligor_cut, base.type_cut) == (100, {"x": 2}, {})
    assert base.borrowing_base == 98


def test_a_lot_of_unknown_value_is_refused_a_pledge_not_raised():
    store = LedgerStore("sqlite://")
    lot = dict(FIXTURE["lots"][2], value=None)  # L3 under the venue freeze
    assert pledge_lot(store, "borrower-b/operating", lot, "col-1") == {
        "status": "rejected", "reason": "unknown"}


def test_a_draw_on_a_reduced_base_says_so():
    frozen = base_of(CASES["venue-freeze"])
    assert draw(frozen, 1)["authority"] == "reduced"
    assert "authority" not in draw(base_of(CASES["base"]), 1)

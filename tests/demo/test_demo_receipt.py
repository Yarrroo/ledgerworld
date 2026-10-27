"""The demo receipt checker against the execution module's demo-receipt fixture (T42, ahead of T23).

The fixture is loaded unchanged. Its invalid cases are patches on the valid fake receipt; two
patch values are descriptions rather than values ("before started_at", "<the setup funding's
provider id>"), and `DESCRIBED` resolves each, once per patch, into the receipt it describes.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from checks import demo_receipt
from checks.goals import g3

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/demo-receipt.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))
INVALID = {case["id"]: case for case in CASES["invalid"]}

SETUP_FUNDING = {
    "kind": "wallet_funding",
    "label": "sandbox wallet funding (setup, not part of the plan)",
    "provider_id": "sbx-dep-setup-1",
    "amount": "60000.00",
}


def valid_fake() -> dict:
    receipt = copy.deepcopy(CASES["valid_fake"])
    del receipt["expect"]
    return receipt


def with_setup_funding(receipt: dict) -> str:
    """Lists the setup funding once and returns its provider id."""
    if SETUP_FUNDING not in receipt["setup"]:
        receipt["setup"].append(dict(SETUP_FUNDING))
    return SETUP_FUNDING["provider_id"]


def before_started_at(receipt: dict) -> str:
    """A run start (kept when the receipt has one) and a moment one minute before it."""
    receipt.setdefault("started_at", "2026-11-06T10:00:00Z")
    started = datetime.fromisoformat(receipt["started_at"])
    return (started - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")


# The fixture's patch values that describe a receipt instead of being a value.
DESCRIBED = {
    "before started_at": before_started_at,
    "<the setup funding's provider id>": with_setup_funding,
}


def patched(case: dict, receipt: dict | None = None) -> dict:
    receipt = valid_fake() if receipt is None else receipt
    for path, value in case["patch"].items():
        if isinstance(value, str) and value in DESCRIBED:
            value = DESCRIBED[value](receipt)
        *parents, leaf = path.split(".")
        targets = [receipt]
        for part in parents:
            if part == "*":
                targets = [child for target in targets for child in target.values()]
            else:
                targets = [target[part] for target in targets]
        for target in targets:
            target[leaf] = value
    return receipt


def live_sandbox() -> dict:
    receipt = valid_fake()
    receipt["mode"] = "sandbox"
    receipt["started_at"] = "2026-11-06T10:00:00Z"
    receipt["checkpoints"]["fresh_branch"]["created_at"] = "2026-11-06T10:00:05Z"
    for checkpoint in receipt["checkpoints"].values():
        checkpoint["mode"] = "sandbox"
    return receipt


def test_fixture_shape_matches_the_checker():
    shape = CASES["shape"]
    assert set(shape) == set(demo_receipt.RUN_FIELDS)
    assert shape["beats"] == demo_receipt.BEATS
    assert set(shape["setup"][0]) == set(demo_receipt.SETUP_FIELDS)
    assert set(shape["checkpoints"]) == set(demo_receipt.CHECKPOINTS)
    for name, fields in shape["checkpoints"].items():
        assert set(fields) <= set(demo_receipt.CHECKPOINT_FIELDS[name])


def test_valid_fake_receipt_passes_and_counts_zero_live():
    expect = CASES["valid_fake"]["expect"]
    receipt = valid_fake()
    assert expect["demo_receipt"] == "ok"
    assert demo_receipt.check(receipt) == []
    assert demo_receipt.check(receipt, require_live=True) == [expect["require_live"]["refused"]]
    assert demo_receipt.live_checkpoints(receipt) == expect["live_checkpoints"] == 0


@pytest.mark.parametrize("case_id", sorted(INVALID))
def test_invalid_receipt_is_refused_with_its_reason(case_id):
    case = INVALID[case_id]
    receipt = patched(case)
    reasons = demo_receipt.check(receipt, require_live=case.get("require_live", False))
    assert reasons == [case["expect"]["refused"]]
    if "live_checkpoints" in case["expect"]:
        assert demo_receipt.live_checkpoints(receipt) == case["expect"]["live_checkpoints"]


def test_sandbox_receipt_with_provider_ids_counts_three_live():
    receipt = live_sandbox()
    assert demo_receipt.check(receipt, require_live=True) == []
    assert demo_receipt.live_checkpoints(receipt) == 3


def test_timestamp_with_an_offset_is_the_same_instant():
    receipt = live_sandbox()
    receipt["started_at"] = "2026-11-06T14:00:00+04:00"
    assert demo_receipt.check(receipt, require_live=True) == []
    assert demo_receipt.live_checkpoints(receipt) == 3


def test_mode_b_label_needs_simulation_not_one_exact_string():
    receipt = live_sandbox()
    receipt["checkpoints"]["advance_reconciled"]["label"] = "advance inflow (simulation, Mode B)"
    assert demo_receipt.check(receipt, require_live=True) == []


def g3_cases() -> list[tuple[str, dict]]:
    """Well-shaped receipts with both timestamps: the live one, each fixture case on it, edges.

    Without a timestamp the two part on purpose: the fixture counts the branch (its
    live-missing-provider-id case expects 2 on the timestamp-less fake), g3 does not.
    """
    cases = [("live", live_sandbox())]
    cases += [(case_id, patched(case, live_sandbox())) for case_id, case in INVALID.items()]
    receipt = live_sandbox()
    receipt["started_at"] = "2026-11-06T14:00:00+04:00"
    cases.append(("offset-started-at", receipt))
    receipt = live_sandbox()
    receipt["checkpoints"]["advance_reconciled"]["label"] = "advance inflow (simulation, Mode B)"
    cases.append(("mode-b-other-label", receipt))
    receipt = live_sandbox()
    receipt["checkpoints"]["fresh_branch"]["created_at"] = "2026-11-06T11:00:00+02:00"
    cases.append(("offset-created-before-run", receipt))
    receipt = live_sandbox()
    receipt["connected"] = True
    receipt["checkpoints"]["advance_reconciled"]["label"] = "advance (connected-account transfer)"
    cases.append(("mode-a-advance", receipt))
    receipt = live_sandbox()
    receipt["checkpoints"]["advance_reconciled"]["status"] = "PENDING"
    cases.append(("advance-pending", receipt))
    return cases


@pytest.mark.parametrize(("case_id", "receipt"), g3_cases(), ids=[c[0] for c in g3_cases()])
def test_checker_and_g3_kpi_count_the_same_live_checkpoints(case_id, receipt):
    assert demo_receipt.live_checkpoints(receipt) == g3.count(receipt), case_id


def test_setup_movement_is_listed_apart_and_never_counts():
    receipt = patched(INVALID["setup-counted"], live_sandbox())
    assert demo_receipt.check(receipt, require_live=True) == [
        "a setup movement is not a checkpoint"
    ]
    assert demo_receipt.live_checkpoints(receipt) == 2


def test_setup_with_its_own_id_is_fine():
    receipt = live_sandbox()
    with_setup_funding(receipt)
    assert demo_receipt.check(receipt, require_live=True) == []
    assert demo_receipt.live_checkpoints(receipt) == 3


def test_unhashable_provider_id_is_a_shape_refusal_not_a_crash():
    receipt = live_sandbox()
    receipt["checkpoints"]["advance_reconciled"]["provider_id"] = ["x"]
    with_setup_funding(receipt)
    receipt["setup"][0]["provider_id"] = {"a": 1}
    reasons, live = demo_receipt.assess(receipt, require_live=True)
    assert "shape: checkpoints.advance_reconciled.provider_id is not str?" in reasons
    assert "shape: setup[0].provider_id is not str?" in reasons
    assert live == 0


def test_run_level_refusal_leaves_no_live_checkpoint():
    receipt = live_sandbox()
    receipt["incidents_open"] = 1
    assert demo_receipt.check(receipt, require_live=True) == ["open incident"]
    assert demo_receipt.live_checkpoints(receipt) == 0


def test_a_broken_checkpoint_does_not_hide_the_others():
    receipt = patched(INVALID["cached-branch"])
    del receipt["checkpoints"]["payout_reconciled"]
    reasons = demo_receipt.check(receipt)
    assert "shape: checkpoints.payout_reconciled is not an object" in reasons
    assert "branch not fresh" in reasons


def test_checkpoints_not_an_object_is_refused_once():
    receipt = valid_fake()
    receipt["checkpoints"] = None
    assert demo_receipt.assess(receipt, require_live=True) == (
        ["shape: receipt.checkpoints is not dict"],
        0,
    )


def test_both_legs_reusing_the_setup_id_is_one_reason():
    receipt = live_sandbox()
    setup_id = with_setup_funding(receipt)
    for leg in ("advance_reconciled", "payout_reconciled"):
        receipt["checkpoints"][leg]["provider_id"] = setup_id
    assert demo_receipt.check(receipt) == ["a setup movement is not a checkpoint"]
    assert demo_receipt.live_checkpoints(receipt) == 1


def test_require_live_counts_every_fake_checkpoint_even_a_broken_one():
    receipt = valid_fake()
    del receipt["checkpoints"]["payout_reconciled"]["journal_id"]
    reasons = demo_receipt.check(receipt, require_live=True)
    assert "mode fake on 3 checkpoints" in reasons


def test_missing_field_is_a_shape_refusal():
    receipt = valid_fake()
    del receipt["checkpoints"]["payout_reconciled"]["journal_id"]
    assert "shape: checkpoints.payout_reconciled.journal_id missing" in demo_receipt.check(receipt)


@pytest.mark.parametrize(
    ("argv", "code", "live"),
    [([], 0, 0), (["--require-live"], 1, 0)],
)
def test_cli_on_the_fake_receipt(tmp_path, capsys, argv, code, live):
    path = tmp_path / "fake.json"
    path.write_text(json.dumps(valid_fake()), encoding="utf-8")
    assert demo_receipt.main([str(path), *argv, "--json"]) == code
    assert json.loads(capsys.readouterr().out)["live_checkpoints"] == live


def test_cli_require_live_passes_only_at_three(tmp_path, capsys):
    path = tmp_path / "live.json"
    path.write_text(json.dumps(live_sandbox()), encoding="utf-8")
    assert demo_receipt.main([str(path), "--require-live"]) == 0
    assert "live checkpoints 3/3" in capsys.readouterr().out


def test_cli_missing_receipt_counts_zero(tmp_path, capsys):
    assert demo_receipt.main([str(tmp_path / "live.json"), "--require-live", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False and result["live_checkpoints"] == 0


def test_cli_null_receipt_is_not_an_object(tmp_path, capsys):
    path = tmp_path / "null.json"
    path.write_text("null", encoding="utf-8")
    assert demo_receipt.main([str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["refused"] == ["shape: receipt is not an object"]


def test_cli_bad_usage():
    assert demo_receipt.main([]) == 2
    assert demo_receipt.main(["a.json", "--bogus"]) == 2

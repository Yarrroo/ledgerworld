"""The demo receipt checker against the execution module's demo-receipt fixture (T42, ahead of T23).

The fixture is loaded unchanged. Its invalid cases are patches on the valid fake receipt; two
patch values are descriptions rather than values ("before started_at", "<the setup funding's
provider id>"), and `materialise` turns each into the concrete receipt it describes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from checks import demo_receipt

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/demo-receipt.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))
INVALID = {case["id"]: case for case in CASES["invalid"]}

STARTED_AT = "2026-11-06T10:00:00Z"
SETUP_PROVIDER_ID = "sbx-dep-setup-1"


def valid_fake() -> dict:
    receipt = copy.deepcopy(CASES["valid_fake"])
    del receipt["expect"]
    return receipt


def materialise(receipt: dict, value: object) -> object:
    if value == "before started_at":
        receipt["started_at"] = STARTED_AT
        return "2026-11-06T09:59:00Z"
    if value == "<the setup funding's provider id>":
        receipt["setup"].append(
            {
                "kind": "wallet_funding",
                "label": "sandbox wallet funding (setup, not part of the plan)",
                "provider_id": SETUP_PROVIDER_ID,
                "amount": "60000.00",
            }
        )
        return SETUP_PROVIDER_ID
    return value


def patched(case: dict, receipt: dict | None = None) -> dict:
    receipt = valid_fake() if receipt is None else receipt
    for path, value in case["patch"].items():
        *parents, leaf = path.split(".")
        targets = [receipt]
        for part in parents:
            if part == "*":
                targets = [child for target in targets for child in target.values()]
            else:
                targets = [target[part] for target in targets]
        for target in targets:
            target[leaf] = materialise(receipt, value)
    return receipt


def live_sandbox() -> dict:
    receipt = valid_fake()
    receipt["mode"] = "sandbox"
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


def test_setup_movement_is_listed_apart_and_never_counts():
    receipt = patched(INVALID["setup-counted"], live_sandbox())
    assert demo_receipt.check(receipt, require_live=True) == [
        "a setup movement is not a checkpoint"
    ]
    assert demo_receipt.live_checkpoints(receipt) == 2


def test_setup_with_its_own_id_is_fine():
    receipt = live_sandbox()
    materialise(receipt, "<the setup funding's provider id>")
    assert demo_receipt.check(receipt, require_live=True) == []
    assert demo_receipt.live_checkpoints(receipt) == 3


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


def test_cli_bad_usage():
    assert demo_receipt.main([]) == 2
    assert demo_receipt.main(["a.json", "--bogus"]) == 2

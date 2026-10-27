"""The fake demo end to end (T23): one run of `app.demo.run`, its story and its receipt.

The run is the one `scripts/demo.sh --mode fake` makes: the simulation in its own process on the
confidence-rumour family's `ScriptedModel`, the gateway on the connector's fake provider. It runs
once per module with an Airwallex variable set to a sentinel, so the test can show the sentinel
reaches neither the simulation process nor the receipt. The receipt is judged by
`checks/demo_receipt.py`, whose own cases come from the execution design's `demo-receipt.json`.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from app.demo import run

from checks import demo_receipt

SENTINEL = "sentinel-not-a-key-7f3c"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo") / "fake.json"
    with pytest.MonkeyPatch.context() as env:
        env.setenv("AIRWALLEX_API_KEY", SENTINEL)
        env.setenv("LEDGERWORLD_DEMO_TOKEN", SENTINEL)
        code = run.main(["--mode", "fake", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    return code, json.loads(text), text


def test_the_fake_demo_writes_a_receipt_the_checker_accepts(demo):
    code, receipt, _ = demo
    assert code == 0 and "failed" not in receipt
    assert demo_receipt.check(receipt) == []
    assert demo_receipt.live_checkpoints(receipt) == 0
    assert demo_receipt.check(receipt, require_live=True) == ["mode fake on 3 checkpoints"]
    assert (receipt["mode"], receipt["model"], receipt["connected"]) == ("fake", "scripted", False)
    assert receipt["beats"] == run.BEATS and receipt["setup"] == []


def test_the_branch_is_new_and_simulated_in_this_run(demo):
    _, receipt, _ = demo
    branch = receipt["checkpoints"]["fresh_branch"]
    assert branch["branch_id"] == f"{receipt['run_id']}-shock-integrated"
    assert branch["cached"] is False and branch["rounds"] == 16 and branch["model_calls"] > 0
    assert datetime.fromisoformat(receipt["started_at"]) <= datetime.fromisoformat(
        branch["created_at"]) <= datetime.fromisoformat(receipt["finished_at"])
    assert branch["parent_snapshot_id"] == receipt["story"]["state"]["snapshot_id"]


def test_the_shock_forks_three_policies_and_the_integrated_one_holds(demo):
    _, receipt, _ = demo
    story = receipt["story"]
    assert [e["kind"] for e in story["shock"]["events"]] == ["delay_receipt", "public_post"]
    fork = story["fork"]
    assert {p["id"]: p["feasible"] for p in fork["policies"]} == {
        "no-action": False, "fixed-reserve": False, "integrated": True}
    assert fork["selected"] == "integrated" and fork["status"] == "selected"
    assert {p["treasury_model_calls"] for p in fork["policies"]} == {0}
    # The rumour's borrower draw and the treasury's advance both come out of the pool.
    integrated = next(p for p in fork["policies"] if p["id"] == "integrated")
    assert story["state"]["lender_K_p"] == 4_200_000
    assert min(integrated["lender_K_p_by_round"].values()) == 4_200_000 - 1_200_000 - 1_000_000
    # Break: the policies that did not hold, each 10,000.00 under the floor at payroll.
    assert [(b["policy"], b["floor"]["at_h"], b["floor"]["short_minor"])
            for b in story["break"]] == [("no-action", 40, 1_000_000),
                                         ("fixed-reserve", 40, 1_000_000)]


def test_the_plan_is_bound_on_the_observed_snapshot_and_both_legs_reconcile(demo):
    _, receipt, _ = demo
    execute = receipt["story"]["execute"]
    assert execute["observed_snapshot_id"] == "obs-demo-r3" and execute["leg_mode"] == "B"
    advance, payout = execute["approval"]["legs"]
    assert (advance["kind"], advance["amount"], advance["facility_id"]) == (
        "advance", {"minor": 1_000_000, "currency": "USD"}, "adv-a")
    assert (payout["kind"], payout["amount"], payout["funded_by"], payout["after"]) == (
        "payout", {"minor": 5_000_000, "currency": "USD"}, "reservation:payroll-hold", [1])
    legs = receipt["checkpoints"]
    plan_hash = execute["approval"]["plan_hash"]
    assert legs["advance_reconciled"]["request_id"] == f"{plan_hash[:12]}-1-advance"
    assert legs["advance_reconciled"]["journal_id"] == "j-adv-a-disburse"
    assert "simulation" in legs["advance_reconciled"]["label"]  # Mode B says so
    assert (legs["payout_reconciled"]["status"], legs["payout_reconciled"]["reconciled"]) == (
        "PAID", True)
    assert receipt["incidents_open"] == 0


def test_the_story_is_told_beat_by_beat(demo, capsys):
    # The module fixture ran before this test's capture; tell the simulation's beats again.
    _, receipt, _ = demo
    run.tell({k: receipt["story"][k] for k in ("state", "world", "shock", "fork", "break")})
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("]")[0] for line in lines] == [
        f"[{n}/7 {beat}" for n, beat in enumerate(run.BEATS[:5], 1)]
    assert "lender K_p 42,000.00" in lines[0] and "10,000.00 under the floor" in lines[4]


def test_no_credential_reaches_the_simulation_or_the_receipt(demo):
    _, _, text = demo
    assert SENTINEL not in text
    env = run.sim_env({"AIRWALLEX_API_KEY": SENTINEL, "AIRWALLEX_MODE": "sandbox",
                       "LEDGERWORLD_DEMO_TOKEN": SENTINEL, "LLM_MODEL_NAME": "m"})
    assert env["LEDGERWORLD_ROLE"] == "sim" and env["LLM_MODEL_NAME"] == "m"
    assert not [k for k in env if k.startswith("AIRWALLEX_") or k == "LEDGERWORLD_DEMO_TOKEN"]
    assert env["PYTHONPATH"].split(":")[0] == str(run.SOURCES[0])


def test_a_sandbox_run_without_its_beneficiary_fails_with_a_receipt_that_says_so(tmp_path):
    out = tmp_path / "live.json"
    assert run.main(["--mode", "sandbox", "--out", str(out)]) == 1
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert "--beneficiary" in receipt["failed"] and receipt["checkpoints"] == {}
    assert demo_receipt.check(receipt, require_live=True)


def test_sandbox_options_are_refused_in_fake_mode(tmp_path):
    with pytest.raises(SystemExit) as caught:
        run.main(["--mode", "fake", "--out", str(tmp_path / "x.json"), "--beneficiary", "b"])
    assert caught.value.code == 2


class _Client:
    def __init__(self):
        self.moves = []

    def simulate_transition(self, transfer_id, status):
        self.moves.append(status)


@pytest.mark.parametrize(("status", "moves"), [
    ("SCHEDULED", ["PROCESSING", "SENT", "PAID"]), ("SENT", ["PAID"]), ("PAID", [])])
def test_a_payout_is_walked_on_from_the_status_it_shows(status, moves):
    client = _Client()
    run.pay(client, type("Leg", (), {"provider_status": status, "provider_id": "t-1"})())
    assert client.moves == moves

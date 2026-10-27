"""The fake demo end to end (T23): one run of `app.demo.run`, its story and its receipt.

The run is the one `scripts/demo.sh --mode fake` makes: the simulation in its own process on the
confidence-rumour family's `ScriptedModel`, the gateway on the connector's fake provider. It runs
once per module with an Airwallex variable set to a sentinel, so the test can show the sentinel
reaches neither the simulation process nor the receipt. The receipt is judged by
`checks/demo_receipt.py`, whose own cases come from the execution design's `demo-receipt.json`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from app.connectors.airwallex.errors import AirwallexError
from app.connectors.airwallex.fake import CONNECTED_ACCOUNT
from app.demo import run
from app.execution.approval import bind
from app.finance.schemas import Money
from app.simulation.scenarios import load_world

from checks import demo_receipt

SENTINEL = "sentinel-not-a-key-7f3c"
# The names a credential travels under; never written beside a value in this file.
KEY, TOKEN = "AIRWALLEX_API_KEY", "LEDGERWORLD_DEMO_TOKEN"


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
    assert execute["observed_snapshot_id"] == f"obs-demo-r3-{receipt['run_id']}"
    assert execute["leg_mode"] == "B"
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


def sim_of(receipt: dict) -> dict:
    """The simulation's output, as the receipt carries it."""
    branch = {k: v for k, v in receipt["checkpoints"]["fresh_branch"].items() if k != "mode"}
    return {**{k: receipt["story"][k] for k in ("state", "world", "shock", "fork", "break")},
            "model": receipt["model"], "fresh_branch": branch}


def test_the_story_is_told_beat_by_beat(demo, capsys):
    # The module fixture ran before this test's capture; tell its seven beats again.
    _, receipt, _ = demo
    run.tell(sim_of(receipt))
    legs = [dict(receipt["checkpoints"][f"{kind}_reconciled"], kind=kind)
            for kind in ("advance", "payout")]
    run.tell_execution({"story": receipt["story"]["execute"], "setup": [], "legs": legs,
                        "incidents_open": 0}, "fake")
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("]")[0] for line in lines] == [
        f"[{n}/7 {beat}" for n, beat in enumerate(run.BEATS, 1)]
    assert "lender K_p 42,000.00" in lines[0] and "10,000.00 under the floor" in lines[4]
    assert "payout PAID" in lines[6]


def test_a_policy_that_misses_an_obligation_says_so_not_a_zero_breach():
    entry = {"policy": "fixed-reserve",
             "floor": {"min_cash": 3_000_000, "at_h": 40, "short_minor": 0, "breach_h": None},
             "obligations": [{"id": "payroll-1", "due_h": 40, "amount_minor": 5_000_000,
                              "met": False, "short_minor": 200_000}]}
    assert run.failure_of(entry) == "fixed-reserve: payroll-1 unmet at t=40 h, short 2,000.00"


def test_an_obligation_overdue_at_the_checkpoint_says_where_its_shortfall_was_read():
    entry = {"policy": "fixed-reserve",
             "floor": {"min_cash": 3_000_000, "at_h": 40, "short_minor": 0, "breach_h": None},
             "obligations": [{"id": "fee-0", "due_h": 4, "amount_minor": 500_000, "met": False,
                              "short_minor": 200_000, "overdue_h": 12}]}
    assert run.failure_of(entry) == ("fixed-reserve: fee-0 unmet at t=4 h, overdue at the "
                                     "checkpoint (read at t=12 h), short 2,000.00")


def test_no_credential_reaches_the_simulation_or_the_receipt(demo):
    _, _, text = demo
    assert SENTINEL not in text
    env = run.sim_env({KEY: SENTINEL, "AIRWALLEX_MODE": "sandbox", TOKEN: SENTINEL,
                       "LLM_MODEL_NAME": "m"})
    assert env["LEDGERWORLD_ROLE"] == "sim" and env["LLM_MODEL_NAME"] == "m"
    assert not [k for k in env if k.startswith("AIRWALLEX_") or k == "LEDGERWORLD_DEMO_TOKEN"]
    assert env["PYTHONPATH"].split(":")[0] == str(run.SOURCES[0])


def test_a_dotenv_cannot_put_the_credential_back_in_the_simulation(tmp_path):
    """The app loads `.env` with override on import; in the sim child that load is disabled."""
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"AIRWALLEX_API_KEY={SENTINEL}\nLEDGERWORLD_ROLE=\n", encoding="utf-8")
    probe = ("import os, sys; from dotenv import load_dotenv; load_dotenv(sys.argv[1], "
             "override=True); print(os.environ.get('AIRWALLEX_API_KEY'), "
             "os.environ['LEDGERWORLD_ROLE'])")
    out = subprocess.run([sys.executable, "-c", probe, str(dotenv)], env=run.sim_env({}),
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["None", "sim"]


def test_the_child_scrubs_what_reached_its_environment_on_import(monkeypatch):
    import os
    monkeypatch.setattr(os, "environ", dict(os.environ))  # isolate() clears; keep the session's
    monkeypatch.setenv("AIRWALLEX_API_KEY", SENTINEL)
    monkeypatch.setenv("LEDGERWORLD_DEMO_TOKEN", SENTINEL)
    monkeypatch.setenv("LEDGERWORLD_ROLE", "")
    run.isolate()
    assert "AIRWALLEX_API_KEY" not in os.environ and "LEDGERWORLD_DEMO_TOKEN" not in os.environ
    assert os.environ["LEDGERWORLD_ROLE"] == "sim"


def test_every_run_binds_new_request_ids():
    world = load_world()
    a, b = (run.observed_snapshot(world, run_id) for run_id in ("demo-1-aaaa", "demo-1-bbbb"))
    assert a.snapshot_id != b.snapshot_id
    plan = {"entity": "treasury", "account": "treasury/operating", "legs": [
        {"index": 1, "kind": "payout", "amount": {"minor": 100, "currency": "USD"},
         "source": "treasury/operating", "counterparty": "ben-payroll-1"}]}
    hashes = {bind(plan, snap, "x", "fake", now=snap.as_of).plan_hash for snap in (a, b)}
    assert len(hashes) == 2


def test_a_foreign_object_on_the_provider_is_not_this_runs_incident():
    """The sandbox account holds earlier runs' transfers; this run's fresh ledger owns none."""
    client, leg_mode = run.connect("fake", None)
    client.create_transfer("earlier-run-2-payout", beneficiary_id=run.FAKE_BENEFICIARY,
                           amount=Money(minor=100, currency="USD"))
    done = run.execute("integrated", "fake", client=client, leg_mode=leg_mode,
                       run_id="demo-x-0000", beneficiary=run.FAKE_BENEFICIARY,
                       connected_account=None, into={})
    assert done["incidents_open"] == 0
    assert [(leg["kind"], leg["state"]) for leg in done["legs"]] == [
        ("advance", "settled"), ("payout", "settled")]


def test_mode_a_with_a_lost_advance_answer_still_ends_paid():
    """Mode A: the advance's create answer is lost; the gateway adopts it by request id, the
    payout follows it, and the demo walks the payout to PAID. (The fake settles the adopted
    advance inside `execute`, so this does not reach the case the leg loop re-reads for: a
    sandbox advance still processing when `execute` returns.)"""
    client, _ = run.connect("fake", None)
    fake = client.transport
    fake.connected = True
    fake.balances[CONNECTED_ACCOUNT] = {"USD": 10_000_000}
    fake.arm("timeout_after_accept")
    done = run.execute("integrated", "fake", client=client, leg_mode="A", run_id="demo-y-0000",
                       beneficiary=run.FAKE_BENEFICIARY, connected_account=CONNECTED_ACCOUNT,
                       into={})
    assert [(leg["kind"], leg["state"], leg["status"]) for leg in done["legs"]] == [
        ("advance", "settled", "SETTLED"), ("payout", "settled", "PAID")]


def test_a_step_that_fails_after_money_moved_keeps_what_moved_in_the_receipt(
        demo, monkeypatch, tmp_path):
    def refused(*a):
        raise AirwallexError("transition refused")

    monkeypatch.setattr(run, "run_simulation", lambda *a: sim_of(demo[1]))
    monkeypatch.setattr(run, "pay", refused)
    out = tmp_path / "r.json"
    assert run.main(["--mode", "fake", "--out", str(out)]) == 1
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["failed"] == "AirwallexError: transition refused"
    assert receipt["checkpoints"]["advance_reconciled"]["status"] == "SETTLED"
    assert receipt["checkpoints"]["payout_reconciled"]["provider_id"]  # sent, not paid
    assert receipt["story"]["execute"]["approval"]["legs"]


def test_a_bad_scripted_plan_still_writes_a_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BASE_URL", "scripted://no-such-plan")
    out = tmp_path / "live.json"
    assert run.main(["--mode", "sandbox", "--out", str(out)]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["model"] == "scripted"


def canned(monkeypatch, receipt: dict, execute) -> None:
    monkeypatch.setattr(run, "run_simulation", lambda *a: sim_of(receipt))
    monkeypatch.setattr(run, "execute", execute)


def test_any_failure_still_writes_a_receipt_that_names_it(demo, monkeypatch, tmp_path):
    def refused(*a, **k):
        raise AirwallexError("auth_fail: credentials refused")

    canned(monkeypatch, demo[1], refused)
    out = tmp_path / "r.json"
    assert run.main(["--mode", "fake", "--out", str(out)]) == 1
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["failed"] == "AirwallexError: auth_fail: credentials refused"
    assert "advance_reconciled" not in receipt["checkpoints"]
    assert demo_receipt.check(receipt)


def test_every_leg_must_settle_not_only_the_last_of_its_kind(demo, monkeypatch, tmp_path):
    receipt = demo[1]
    payout = dict(receipt["checkpoints"]["payout_reconciled"], kind="payout", state="settled")
    stuck = dict(payout, leg_id="x-2-payout", status="SCHEDULED", state="submitted",
                 reconciled=False)
    advance = dict(receipt["checkpoints"]["advance_reconciled"], kind="advance",
                   state="settled")
    done = {"connected": False, "setup": [], "legs": [advance, stuck, payout],
            "incidents_open": 0, "story": receipt["story"]["execute"]}
    canned(monkeypatch, receipt, lambda *a, into, **k: into.update(done))
    out = tmp_path / "r.json"
    assert run.main(["--mode", "fake", "--out", str(out)]) == 1
    assert "x-2-payout" in json.loads(out.read_text(encoding="utf-8"))["failed"]


def test_a_sandbox_run_is_refused_before_it_simulates(monkeypatch, tmp_path):
    monkeypatch.delenv("AIRWALLEX_MODE", raising=False)

    def never(*a):
        raise AssertionError("the simulation ran before the provider was reached")

    monkeypatch.setattr(run, "run_simulation", never)
    out = tmp_path / "live.json"
    assert run.main(["--mode", "sandbox", "--out", str(out), "--beneficiary", "b"]) == 1
    assert "AIRWALLEX_MODE=sandbox" in json.loads(out.read_text(encoding="utf-8"))["failed"]


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
    def __init__(self, held=None):
        self.moves, self.deposits, self.held = [], [], held or {}

    def simulate_transition(self, transfer_id, status):
        self.moves.append(status)

    def balances(self):
        return [SimpleNamespace(currency=c, available=Money(minor=m, currency=c))
                for c, m in self.held.items()]

    def global_accounts(self):
        return [{"id": "ga-eur", "currency": "EUR"}, {"id": "ga-usd", "currency": "USD"}]

    def simulate_deposit(self, *, amount, global_account_id, reference):
        self.deposits.append((amount.currency, amount.minor, global_account_id, reference))
        return SimpleNamespace(provider_id=f"dep-{amount.currency}")

    def wait_for_deposit(self, provider_id):
        self.moves.append(provider_id)
        return SimpleNamespace(provider_id=provider_id, status="SETTLED")


@pytest.mark.parametrize(("status", "moves"), [
    ("SCHEDULED", ["PROCESSING", "SENT", "PAID"]), ("SENT", ["PAID"]), ("PAID", []),
    ("FAILED", []), ("CANCELLED", [])])
def test_a_payout_is_walked_on_from_the_status_it_shows(status, moves):
    client = _Client()
    run.pay(client, "t-1", status)
    assert client.moves == moves


def test_the_wallet_is_funded_per_currency_and_listed_as_setup():
    client = _Client({"USD": 2_000_000})
    legs = [{"kind": "payout", "amount": {"minor": 5_000_000, "currency": "USD"}},
            {"kind": "payout", "amount": {"minor": 300_000, "currency": "EUR"}},
            {"kind": "advance", "amount": {"minor": 1_000_000, "currency": "USD"}}]
    setup = run.fund_wallet(client, {"legs": legs})
    assert client.deposits == [("EUR", 300_000, "ga-eur", run.SETUP_LABEL),
                               ("USD", 3_000_000, "ga-usd", run.SETUP_LABEL)]
    assert [(s["provider_id"], s["amount"]) for s in setup] == [
        ("dep-EUR", "3000.00"), ("dep-USD", "30000.00")]
    assert all(s["label"] == run.SETUP_LABEL for s in setup)
    assert client.moves == ["dep-EUR", "dep-USD"]

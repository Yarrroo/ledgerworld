"""Sandbox demo model selection stays independent of the provider and needs no live model key."""

import json

import pytest
from app.demo import run
from app.simulation.scenarios import load_family
from app.testing.scripted_model import ScriptedPlan

from checks import demo_receipt


def test_sandbox_demo_runs_the_family_script_without_a_live_model_key(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BASE_URL", "scripted://family")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL_NAME", raising=False)
    client, leg_mode = run.connect("fake", None)
    connections = []

    def connect(mode, connected_account):
        connections.append((mode, connected_account))
        return client, leg_mode

    monkeypatch.setattr(run, "connect", connect)
    out = tmp_path / "sandbox.json"
    assert run.main(["--mode", "sandbox", "--out", str(out),
                     "--beneficiary", run.FAKE_BENEFICIARY]) == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert connections == [("sandbox", None)]
    assert "failed" not in receipt
    assert (receipt["mode"], receipt["model"]) == ("sandbox", "scripted")
    assert demo_receipt.check(receipt, require_live=True) == []
    branch = receipt["checkpoints"]["fresh_branch"]
    assert branch["cached"] is False and branch["model_calls"] > 0
    assert receipt["story"]["fork"]["selected"] == "integrated"
    integrated = next(p for p in receipt["story"]["fork"]["policies"]
                      if p["id"] == "integrated")
    assert min(integrated["lender_K_p_by_round"].values()) == 2_000_000
    for name in ("advance_reconciled", "payout_reconciled"):
        assert receipt["checkpoints"][name]["reconciled"] is True


@pytest.mark.parametrize("source", ["family", "configured"])
def test_demo_family_alias_selects_the_rumour_plan(monkeypatch, source):
    monkeypatch.setenv("LLM_BASE_URL", "scripted://family")
    assert run.scripted_plan(source).entries == load_family(run.RUMOUR).plan().entries
    assert run.model_kind(source) == "scripted"


def test_configured_named_plan_still_loads(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "scripted://coupled-chain")
    assert run.scripted_plan("configured").entries == ScriptedPlan.from_url(
        "scripted://coupled-chain").entries


def test_configured_live_model_still_requires_its_key(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://model.example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "demo-model")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert run.scripted_plan("configured") is None
    assert run.model_kind("configured") == "live"
    with pytest.raises(run.DemoFailed, match="a live model needs LLM_API_KEY"):
        run.model_factory("configured")

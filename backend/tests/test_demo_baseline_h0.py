"""With a prepared demo, Overview, Treasury and Lending tell the story from the demo world's h0:
the observed snapshot at the world's epoch (settled 70,000, spendable 20,000, the receivable
+20,000 at h12, payroll -50,000 at h40, the low point 40,000 holding the floor), not the
prepared run's own observation at h12. Simulation reads the run's own snapshot."""
from __future__ import annotations

import json
from pathlib import Path

from app.api.v1 import register
from app.api.v1.services import Services
from app.finance.ledger import pay
from app.jobs.runner import new_run
from app.simulation.scenarios import load_world
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT / "contracts/examples/c6_api/valid-overview-demo-baseline.json")
                      .read_text(encoding="utf-8"))["instance"]
WORLD = load_world()
H0 = "2026-01-01T00:00:00Z"
RUN = "demo-h0"


def money(minor: int) -> dict:
    return {"minor": minor, "currency": "USD"}


def prepared() -> Services:
    """The app on the demo world, a prepared run named, and its clock long past h0."""
    services = Services.build(WORLD.snapshot, epoch=WORLD.epoch, mode="fake", token=None,
                              clock=lambda: WORLD.epoch.replace(day=4))
    services.jobs.put("run", RUN, new_run(RUN, WORLD.snapshot.snapshot_id, WORLD.snapshot.as_of))
    services.prepare_demo(RUN)
    return services


def test_overview_is_the_demo_worlds_h0_baseline():
    http = register(Flask(__name__), prepared()).test_client()
    body = http.get("/api/v1/overview").get_json()
    assert body["demo"] == {"run_id": RUN, "execution_id": None}
    assert body["snapshot_id"] == WORLD.snapshot.snapshot_id
    assert body["as_of"] == H0
    assert body["cash"] == {**money(7_000_000), "status": "known", "as_of": H0}
    assert body["spendable"]["minor"] == 2_000_000
    [payroll] = body["upcoming_outflows"]
    assert (payroll["amount"], payroll["due_at"]) == (money(5_000_000), "2026-01-02T16:00:00Z")
    assert body["coverage"]["min_projected"]["minor"] == 4_000_000
    assert body["coverage"]["headroom"]["minor"] >= 0
    receipts = [e for p in body["outlook"] for e in p["events"] if e["direction"] == "in"]
    assert [(e["amount"], e["kind"]) for e in receipts][:1] == [(money(2_000_000), "receivable")]
    # the recorded baseline the UX check serves is this answer, run and scenario aside
    assert {**body, "demo": BASELINE["demo"], "scenario": BASELINE.get("scenario")} == BASELINE


def test_treasury_and_lending_read_the_same_h0_snapshot():
    http = register(Flask(__name__), prepared()).test_client()
    treasury = http.get("/api/v1/treasury").get_json()
    lending = http.get("/api/v1/lending").get_json()
    for body in (treasury, lending):
        assert (body["snapshot_id"], body["as_of"]) == (WORLD.snapshot.snapshot_id, H0)
    operating = next(a for a in treasury["accounts"] if a["id"] == "treasury/operating")
    assert operating["buckets"]["settled"] == money(7_000_000)
    assert operating["spendable"]["minor"] == 2_000_000


def test_the_baseline_is_not_the_ledger_the_execution_moved():
    services = prepared()
    pay(services.store, "treasury/operating", 1_000_000, to_account="lender/operating",
        now=WORLD.epoch, journal_id="moved")
    body = register(Flask(__name__), services).test_client().get("/api/v1/overview").get_json()
    assert body["cash"]["minor"] == 7_000_000


def test_simulation_keeps_the_runs_own_snapshot():
    http = register(Flask(__name__), prepared()).test_client()
    run = http.get(f"/api/v1/runs/{RUN}").get_json()
    assert run["run_id"] == RUN and run["snapshot_id"] == WORLD.snapshot.snapshot_id

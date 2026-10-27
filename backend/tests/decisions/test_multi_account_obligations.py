"""An obligation on a treasury account other than the operating one is never dropped.

The treasury holds a USD operating account and a EUR account; a EUR invoice is owed on the EUR
account, more than that account holds. The observed snapshot, the branch observation, the
projection, the conversion a policy plans and the branch's realised feasibility all carry it
with its account and currency, so no policy that misses it is selected; a position that cannot
be priced is refused rather than read as nothing to do.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime
from pathlib import Path

import pytest
from app.decisions.candidates import (
    ALL,
    FixedReserve,
    Integrated,
    UnpricedPosition,
    evaluate,
    plan_for_now,
    project,
    snapshot_observation,
    view_world,
)
from app.decisions.nonanticipativity import PolicyView
from app.decisions.objective import rank
from app.finance.schemas import Snapshot
from app.simulation.branches import checkpoint
from app.simulation.coordinator import Coordinator
from app.simulation.world import World, import_oasis
from app.testing.scripted_model import ScriptedPlan
from oasis_finance.observation import iso_utc

import_oasis()  # once, from a temporary directory: importing oasis writes ./log

T0 = datetime.fromisoformat(iso_utc(0))  # the snapshots' epoch
USD_ACCOUNT, EUR_ACCOUNT = "treasury/operating", "treasury/eur"
EURUSD = "1.08"


def money(minor: int, currency: str) -> dict:
    return {"minor": minor, "currency": currency}


def cash(account_id: str, currency: str, settled: int, floor: int | None = None) -> dict:
    acc = {"id": account_id, "entity": "treasury", "currency": currency,
           "observability": "known", "as_of": iso_utc(0),
           "buckets": {"settled": money(settled, currency), "reserved": money(0, currency),
                       "pledged": money(0, currency), "pending_in": [], "pending_out": []}}
    if floor is not None:
        acc["floor"] = money(floor, currency)
    return acc


def snapshot(*, invoice_due_h: int) -> dict:
    """70,000.00 USD on a 30,000.00 floor; 1,000.00 EUR held against a 4,000.00 EUR invoice."""
    return {
        "snapshot_id": "snap-multi-account", "as_of": iso_utc(0),
        "entities": [{"entity_id": "treasury", "name": "Treasury (synthetic)", "kind": "treasury",
                      "escalation": "treasury operator"}],
        "accounts": [cash(USD_ACCOUNT, "USD", 7_000_000, floor=3_000_000),
                     cash(EUR_ACCOUNT, "EUR", 100_000)],
        "obligations": [{"obligation_id": "inv-eur", "entity": "treasury",
                         "account": EUR_ACCOUNT, "amount": money(400_000, "EUR"),
                         "due_at": iso_utc(invoice_due_h), "kind": "invoice"}],
        "contracts": [], "exposures": [], "pools": [],
    }


# ------------------------------------------------------------- the observed snapshot

def observed(**kw) -> Snapshot:
    return Snapshot.model_validate(snapshot(**kw))


def test_the_observation_carries_the_obligation_on_the_other_account():
    obs = snapshot_observation(observed(invoice_due_h=4), epoch=T0)
    assert obs["account"] == USD_ACCOUNT
    assert [(o["id"], o["account"], o["currency"], o["amount"]) for o in obs["obligations"]] == [
        ("inv-eur", EUR_ACCOUNT, "EUR", 400_000)]
    assert obs["holdings"] == [{"id": EUR_ACCOUNT, "currency": "EUR", "settled": 100_000}]


def test_the_projection_funds_what_the_other_account_cannot_pay():
    obs = snapshot_observation(observed(invoice_due_h=4), epoch=T0, prices={"EUR/USD": EURUSD})
    # 3,000.00 EUR uncovered at 1.08, rounded up: 3,240.00 USD out of 70,000.00 at t=4
    assert project(obs).min_minor == 7_000_000 - 324_000
    with pytest.raises(UnpricedPosition, match="no EUR/USD price for inv-eur"):
        project(snapshot_observation(observed(invoice_due_h=4), epoch=T0))


def test_integrated_converts_the_uncovered_part_into_the_account_that_owes_it():
    obs = snapshot_observation(observed(invoice_due_h=4), epoch=T0, prices={"EUR/USD": EURUSD})
    proposal = Integrated().propose(PolicyView(view_world(obs), 0))
    assert proposal.actions == [{"type": "convert", "buy": money(300_000, "EUR"),
                                 "sell_currency": "USD", "for_obligation": "inv-eur",
                                 "to_account": EUR_ACCOUNT}]
    plan = plan_for_now(Integrated(), observed(invoice_due_h=4), epoch=T0, beneficiaries={},
                        prices={"EUR/USD": EURUSD})
    assert plan["legs"] == [{"index": 1, "kind": "fx", "amount": money(324_000, "USD"),
                             "source": USD_ACCOUNT, "counterparty": EUR_ACCOUNT,
                             "to_currency": "EUR"}]


def test_an_unpriced_position_is_refused_not_read_as_nothing_to_do():
    obs = snapshot_observation(observed(invoice_due_h=4), epoch=T0)
    for policy in (Integrated(), FixedReserve()):
        proposal = policy.propose(PolicyView(view_world(obs), 0))
        assert (proposal.actions, proposal.reason) == ([], "unpriced_obligation")
        assert proposal.detail == "no EUR/USD price for inv-eur"
    with pytest.raises(ValueError, match="unpriced_obligation"):
        plan_for_now(Integrated(), observed(invoice_due_h=4), epoch=T0, beneficiaries={})


def test_a_holding_that_covers_its_own_obligation_needs_nothing_from_home():
    snap = snapshot(invoice_due_h=4)
    snap["accounts"][1]["buckets"]["settled"] = money(500_000, "EUR")
    obs = snapshot_observation(Snapshot.model_validate(snap), epoch=T0)  # no price needed
    assert project(obs).min_minor == 7_000_000
    assert Integrated().propose(PolicyView(view_world(obs), 0)).actions == []


# ------------------------------------------------------------------- the branches

CP_ROUND, HORIZON_H = 2, 24
TREASURY = {"actor_id": "treasury", "kind": "treasury", "entity": "treasury",
            "priority_class": 1, "role": "treasury"}


def plan_model(plan: ScriptedPlan):
    return lambda actor_id, world: plan.model(actor_id, lambda: world.clock.round)


async def compare(tmp: Path):
    idle = [{"default": True, "tool_calls": [{"name": "no_action", "args": {}}]}]
    base_dir = tmp / "base"
    base_dir.mkdir()
    base = World("multi-account", "base", snapshot(invoice_due_h=20), [TREASURY],
                 model=plan_model(ScriptedPlan(copy.deepcopy(idle))), workdir=base_dir,
                 seed=7, coordinator=Coordinator())
    async with base:
        await base.run(CP_ROUND)
        cp = checkpoint(base)
    work = tmp / "branches"
    work.mkdir()
    evaluations = await evaluate("run-ma", cp, {"s1": []}, ALL,
                                 model=plan_model(ScriptedPlan(copy.deepcopy(idle))),
                                 workdir=work, horizon_h=HORIZON_H)
    return evaluations


@pytest.fixture(scope="module")
def evaluations(tmp_path_factory):
    return asyncio.run(compare(tmp_path_factory.mktemp("multi-account")))


def test_every_branch_is_judged_on_the_eur_invoice(evaluations):
    assert len(evaluations) == len(ALL)
    for e in evaluations:
        (inv,) = [o for o in e.feasibility.obligations if o.id == "inv-eur"]
        assert (inv.met, inv.due_h, inv.short_minor) == (False, 20, 300_000)
        assert (inv.account, inv.currency) == (EUR_ACCOUNT, "EUR")
        assert inv.as_dict()["currency"] == "EUR"
        assert not e.feasibility.feasible


def test_no_policy_that_misses_the_invoice_is_selected(evaluations):
    result = rank(evaluations, order=[p.id for p in ALL], escalate_to="treasury operator")
    assert (result.status, result.selected) == ("all_infeasible", None)
    earliest = result.escalation["earliest_unmet"]
    assert {k: earliest[k] for k in ("id", "account", "currency", "short_minor")} == {
        "id": "inv-eur", "account": EUR_ACCOUNT, "currency": "EUR", "short_minor": 300_000}
    assert result.escalation["binding"] == (
        "free cash 1,000.00 EUR at t=20 < inv-eur 4,000.00 EUR; no reservation is touched")


# ------------------------------------------------------------------------ vet round 1

def test_a_holdings_committed_outflow_is_not_free_to_pay_another_obligation():
    """1,000.00 EUR held, 800.00 of it already committed to a flow: 200.00 is free, so 3,800.00
    of the 4,000.00 invoice is the home account's to fund."""
    snap = snapshot(invoice_due_h=4)
    snap["accounts"][1]["buckets"]["pending_out"] = [
        {"flow_id": "out:inv-0", "amount": money(80_000, "EUR"),
         "expected_at": iso_utc(8), "kind": "invoice"}]
    obs = snapshot_observation(Snapshot.model_validate(snap), epoch=T0,
                               prices={"EUR/USD": EURUSD})
    assert obs["holdings"] == [{"id": EUR_ACCOUNT, "currency": "EUR", "settled": 20_000}]
    (convert,) = Integrated().propose(PolicyView(view_world(obs), 0)).actions
    assert convert["buy"] == money(380_000, "EUR")


def test_the_replay_world_refuses_only_a_debt_it_cannot_hold():
    from app.decisions.reverse_stress import replayable

    owes_eur = snapshot_observation(observed(invoice_due_h=4), epoch=T0)
    assert not replayable(owes_eur)
    idle = snapshot(invoice_due_h=4)
    idle["obligations"] = []  # a second account with nothing owed on it: replayable as before
    assert replayable(snapshot_observation(Snapshot.model_validate(idle), epoch=T0))


def test_the_demo_names_the_currency_of_a_foreign_shortfall():
    from app.demo.run import failure_of

    entry = {"policy": "integrated", "floor": {"short_minor": 0},
             "obligations": [{"id": "inv-eur", "due_h": 20, "short_minor": 300_000,
                              "account": EUR_ACCOUNT, "currency": "EUR"}]}
    assert failure_of(entry) == "integrated: inv-eur unmet at t=20 h, short 3,000.00 EUR"

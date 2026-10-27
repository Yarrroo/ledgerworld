"""Approval binding (C3) against design/modules/execution/fixtures/approval-binding.json.

The fixture is loaded unchanged. Its legs are flat (`amount`, `currency`); C3 carries Money, so
`c3_leg` reshapes them. A change without `rehash` alters what is presented and keeps the stored
approval; with `rehash` the changed plan is bound afresh. The binding-level codes are tested
here; the ledger-backed cases run through the gateway's preflight in `test_gateway.py`, and the
token check is carried, skipped, until the approvals route lands.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from app.execution.approval import OK, TTL, Refusal, bind, request_id, verify
from app.finance.schemas import BoundApproval

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/approval-binding.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
EXAMPLES = ROOT / "contracts/examples"
BASE = DATA["base"]
CASES = {case["id"]: case for case in DATA["cases"]}
LEG_TERM = re.compile(r"^legs\[(\d+)\]\.(\w+)$")

ALTERED = ["amount-altered", "counterparty-altered", "leg-added"]
BINDING = {"ok", *ALTERED, "expired", "mode-mismatch", "branch-snapshot", "snapshot-moved",
           "replayed-approval"}
LEDGER = ["unowned-source", "beneficiary-not-allowlisted", "stale-balance", "breaks-floor",
          "reservation-mismatch"]
ROUTE = {"no-token"}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def c3_leg(leg: dict) -> dict:
    """A fixture leg in C3's shape: the flat amount and currency become Money."""
    shaped = {k: v for k, v in leg.items() if k not in ("amount", "currency")}
    return shaped | {"amount": {"minor": leg["amount"], "currency": leg["currency"]}}


def plan_of(terms: dict) -> dict:
    return {"entity": terms["entity"], "account": terms["account"],
            "legs": [c3_leg(leg) for leg in terms["legs"]]}


def bind_terms(terms: dict) -> BoundApproval:
    return bind(plan_of(terms), terms["snapshot_id"], terms["approver"], terms["mode"],
                now=at(DATA["now"]), approval_id=terms["approval_id"])


@dataclass
class Setup:
    stored: BoundApproval
    presented: dict
    now: datetime
    current: str
    gateway_mode: str

    def verify(self, used: tuple[str, ...] = ()):
        return verify(self.stored, self.presented, self.now, self.current, self.gateway_mode,
                      used=used)


def setup(case_id: str) -> Setup:
    """The stored approval and what is presented, after the case's change."""
    change = CASES[case_id]["change"] or {}
    terms = copy.deepcopy(BASE)
    env = {"now": DATA["now"], "current_observed_snapshot_id": DATA["current_observed_snapshot_id"],
           "gateway_mode": BASE["mode"]}
    for key, value in change.items():
        if match := LEG_TERM.match(key):
            terms["legs"][int(match[1])][match[2]] = value
        elif key == "legs[+]":
            terms["legs"].append(value)
        elif key == "snapshot_id":
            terms["snapshot_id"] = value
        elif key in env:
            env[key] = value
        elif key not in ("rehash", "execute_twice"):
            raise KeyError(f"{case_id}: {key} is not a binding-level change")
    stored = bind_terms(terms if change.get("rehash") else BASE)
    presented = stored.model_dump(mode="json") | {
        "legs": plan_of(terms)["legs"], "snapshot_id": terms["snapshot_id"]}
    return Setup(stored, presented, at(env["now"]), env["current_observed_snapshot_id"],
                 env["gateway_mode"])


def refused(verdict, code: str) -> None:
    assert isinstance(verdict, Refusal), verdict
    assert verdict.code == code, verdict


def test_every_fixture_case_is_carried():
    assert set(CASES) == BINDING | set(LEDGER) | ROUTE


def test_bind_reproduces_the_fixture_approval_and_its_canonical_hash():
    approval = bind_terms(BASE)
    terms = {"entity": BASE["entity"], "account": BASE["account"],
             "legs": plan_of(BASE)["legs"], "snapshot_id": BASE["snapshot_id"],
             "mode": BASE["mode"]}
    canonical = json.dumps(terms, sort_keys=True, separators=(",", ":"))
    assert approval.plan_hash == hashlib.sha256(canonical.encode()).hexdigest()
    assert approval.expires_at == at(BASE["expires_at"]) == at(DATA["now"]) + TTL
    expected = {k: v for k, v in BASE.items() if k != "legs"} | {
        "legs": plan_of(BASE)["legs"], "plan_hash": approval.plan_hash}
    assert approval == BoundApproval.model_validate(expected)
    assert bind_terms(BASE).plan_hash == approval.plan_hash


def test_the_contract_examples_carry_the_bound_hash_and_request_ids():
    """C3's valid example is the fixture base; C4 and C6 name its legs by `request_id`."""
    example = json.loads((EXAMPLES / "c3_bound_approval/valid-lf1-integrated.json")
                         .read_text(encoding="utf-8"))["instance"]
    approval = BoundApproval.model_validate(example)
    assert approval.plan_hash == bind_terms(BASE).plan_hash
    assert verify(approval, example, at(DATA["now"]), approval.snapshot_id, approval.mode) is OK
    ids = {request_id(approval, leg) for leg in approval.legs}
    named = set()
    for path in [*EXAMPLES.glob("c4_provider_op/*.json"), EXAMPLES / "c6_api/valid-execution.json"]:
        named |= set(re.findall(r'"request_id": "([^"]+)"', path.read_text(encoding="utf-8")))
    assert named and named <= ids


def test_an_empty_approval_id_is_refused_not_replaced():
    with pytest.raises(ValueError):
        bind(plan_of(BASE), BASE["snapshot_id"], BASE["approver"], BASE["mode"],
             now=at(DATA["now"]), approval_id="")


def test_ok_approval_verifies_and_fixes_its_request_ids():
    case = CASES["ok"]
    run = setup("ok")
    assert run.verify() is OK
    ids = [request_id(run.stored, leg) for leg in run.stored.legs]
    expect = case["expect"]
    assert len(ids) == expect["legs_queued"]
    assert ids == [rid.replace("<plan_hash[:12]>", run.stored.plan_hash[:12])
                   for rid in expect["request_ids"]]


@pytest.mark.parametrize("case_id", ALTERED)
def test_altered_approval_refused(case_id):
    refused(setup(case_id).verify(), CASES[case_id]["expect"]["refused"])


@pytest.mark.parametrize("term, value", [
    ("expires_at", "2026-11-05T11:15:00Z"),
    ("approver", "someone-else"),
    ("approval_id", "apr-2"),
    ("plan_hash", "0" * 64),
])
def test_a_term_outside_the_hash_is_still_bound(term, value):
    run = setup("ok")
    run.presented[term] = value
    refused(run.verify(), "approval_altered")


def test_a_tampered_stored_approval_is_refused():
    run = setup("ok")
    legs = [leg.model_copy(update={"counterparty": "ben-other"}) for leg in run.stored.legs]
    run.stored = run.stored.model_copy(update={"legs": legs})
    run.presented = run.stored.model_dump(mode="json")
    refused(run.verify(), "approval_altered")


def test_expired_approval_refused_at_expires_at_exactly():
    run = setup("expired")
    refused(run.verify(), CASES["expired"]["expect"]["refused"])
    run.now -= timedelta(seconds=1)
    assert run.verify() is OK


def test_mode_mismatch_refused_both_ways():
    run = setup("mode-mismatch")
    refused(run.verify(), CASES["mode-mismatch"]["expect"]["refused"])
    sandbox = bind(plan_of(BASE), BASE["snapshot_id"], BASE["approver"], "sandbox",
                   now=at(DATA["now"]))
    refused(verify(sandbox, sandbox.model_dump(mode="json"), at(DATA["now"]),
                   BASE["snapshot_id"], "fake"), "mode_mismatch")


def test_branch_snapshot_refused():
    refused(setup("branch-snapshot").verify(), CASES["branch-snapshot"]["expect"]["refused"])
    with pytest.raises(ValueError, match="not_observed_snapshot"):
        bind(plan_of(BASE), "branch-integrated-r4", BASE["approver"], BASE["mode"],
             now=at(DATA["now"]))


def test_moved_snapshot_refused():
    refused(setup("snapshot-moved").verify(), CASES["snapshot-moved"]["expect"]["refused"])


def test_replayed_approval_refused():
    run = setup("replayed-approval")
    ids = [request_id(run.stored, leg) for leg in run.stored.legs]
    assert run.verify() is OK
    second = run.verify(used=(run.stored.approval_id,))
    refused(second, CASES["replayed-approval"]["expect"]["second"]["refused"])
    assert [request_id(bind_terms(BASE), leg) for leg in run.stored.legs] == ids


@pytest.mark.parametrize("value", [
    None,
    {"run_id": "run-1", "status": "selected", "selected": "integrated"},
    {"intent_id": "i-1", "status": "accepted", "round": 3},
])
def test_not_an_approval_refused(value):
    run = setup("ok")
    refused(verify(run.stored, value, run.now, run.current, run.gateway_mode), "not_an_approval")
    refused(verify(value, run.presented, run.now, run.current, run.gateway_mode),
            "not_an_approval")
    unhashed = {k: v for k, v in run.presented.items() if k != "plan_hash"}
    refused(verify(run.stored, unhashed, run.now, run.current, run.gateway_mode),
            "not_an_approval")


@pytest.mark.skip(reason="lands with the API task: the token-guarded POST /api/v1/approvals")
def test_approval_route_needs_the_demo_token():
    assert CASES["no-token"]["expect"]["http"] == 401

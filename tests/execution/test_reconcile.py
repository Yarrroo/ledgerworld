"""Reconciliation and webhook ingestion against the execution design's fixtures, unchanged.

`reconciliation.json`: provider state becomes ledger journals only when a `GET` shows the
terminal status in the leg's own terms; every mismatch is an incident and the ledger is never
corrected to fit. Journals are checked posting by posting against the ledger module's
`advance-journals.json`. `webhooks.json`: the real HMAC values over the fixture body; a verified
event only triggers the `GET`, and is handled once. The world is the one `test_gateway.py`
builds: the observed LF-1 + LF-2 store on the fake provider.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from app.connectors.airwallex.client import leg_plan
from app.connectors.airwallex.errors import ProviderError
from app.execution import reconcile
from app.execution.gateway import Execution
from app.finance import lending
from app.finance.lending import capacity, observe_revenue
from app.finance.schemas import Money
from test_gateway import BASE, FIXTURES, NOW, ROOT, World, bind_terms, fund

RECON = json.loads((FIXTURES / "reconciliation.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in RECON["cases"]}
HOOKS = json.loads((FIXTURES / "webhooks.json").read_text(encoding="utf-8"))
HOOK_CASES = {case["id"]: case for case in HOOKS["cases"]}
JOURNALS = json.loads((ROOT / "prp/2026-10-20-ledgerworld/design/modules/ledger/fixtures"
                       "/advance-journals.json").read_text(encoding="utf-8"))["journals"]
SECRET = HOOKS["secret"]
RAW = HOOKS["raw_body"].encode()


def postings(world: World, journal_id: str) -> list[tuple[str, int]]:
    return sorted((p["account_id"], p["amount_minor"]) for p in world.store.rows("postings")
                  if p["journal_id"] == journal_id)


def fixture_postings(index: int) -> list[tuple[str, int]]:
    return sorted((p["account"], p["amount"]) for p in JOURNALS[index]["postings"])


def approval_with(approval_id: str, legs: list[dict]):
    return bind_terms(copy.deepcopy(BASE) | {"approval_id": approval_id, "legs": legs})


def leg_count(world: World) -> int:
    return len(world.store.rows("journals"))


# ------------------------------------------------------------------------------ the advance


def test_reconciliation_closes_the_advance():
    """LF-2's advance closed in Mode A: one journal, posting by posting, and K_p after it."""
    case = CASES["advance-mode-a"]
    world = World(leg_mode="A")
    done = world.execute(bind_terms(BASE))
    advance = done.legs[0]
    assert (advance.request_id, advance.amount_minor) == (
        case["leg"]["request_id"].replace("<h>", advance.request_id[:12]), case["leg"]["amount"])
    assert advance.provider_op == leg_plan("A")["advance"].op
    assert advance.state == "settled" and advance.reconciled is case["expect"]["reconciled"]
    assert advance.journal_id == "j-adv-a-disburse"
    assert advance.receipt_label == case["expect"]["receipt_label"]
    assert postings(world, advance.journal_id) == fixture_postings(0)
    assert capacity(world.store, "lender", NOW).K_p == case["expect"]["K_p_after"]
    obj = world.fake.objects["connected_account_transfers"][advance.provider_id]
    assert (obj["status"], str(obj["amount"]), obj["currency"]) == (
        case["provider"]["status"], case["provider"]["amount"], case["provider"]["currency"])
    flows = {f["flow_id"]: f["state"] for f in world.store.rows("expected_flows")}
    assert flows[advance.leg_id] == "settled"  # the pending_in it was until it landed


def test_advance_mode_b_is_the_same_journal_under_its_own_label():
    case = CASES["advance-mode-b"]
    world = World(leg_mode="B")
    advance = world.execute(bind_terms(BASE)).legs[0]
    assert advance.state == "settled" and advance.reconciled is case["expect"]["reconciled"]
    assert advance.journal_id == "j-adv-a-disburse"
    assert postings(world, advance.journal_id) == fixture_postings(0)
    assert advance.receipt_label == case["expect"]["receipt_label"]
    assert case["expect"]["never_label"] not in advance.receipt_label
    (deposit,) = world.fake.objects["deposits"].values()
    reference = case["provider"]["reference"].replace("<h>", advance.request_id[:12])
    assert deposit["reference"] == reference and deposit["amount"] == Decimal("10000.00")
    (journal,) = [j for j in world.store.rows("journals") if j["journal_id"] == advance.journal_id]
    assert journal["mode"] == "fake"
    world.gateway.mode = "sandbox"  # the receipt mode a sandbox Mode B run books under
    assert world.gateway._journal_mode() == "sandbox_simulation"


def test_an_amount_mismatch_is_an_incident_and_posts_nothing():
    case = CASES["amount-mismatch"]
    world = World(leg_mode="A")

    def short_change():  # the provider's object shows another amount than the leg's
        (obj,) = world.fake.objects["connected_account_transfers"].values()
        obj["amount"] = Decimal(case["provider"]["amount"])

    world.wire.after_create = short_change
    advance = world.execute(bind_terms(BASE)).legs[0]
    assert advance.state == "submitted" and not advance.reconciled
    assert advance.journal_id is None and world.journals(advance.leg_id) == []
    (incident,) = world.gateway.incidents(open_only=True)
    assert incident["kind"] == case["expect"]["incident"]["kind"]
    assert f"provider {case['expect']['incident']['provider']} USD" in incident["detail"]
    reconcile.sweep(world.gateway)
    assert len(world.gateway.incidents()) == 1 and world.journals(advance.leg_id) == []


# ---------------------------------------------------------------------------- the payout


def test_payout_paid_settles_its_reservation_and_meets_the_obligation():
    case = CASES["payout-paid"]
    world = World()
    payout = world.execute(bind_terms(BASE)).legs[1]
    assert payout.funded_by == case["leg"]["funded_by"]
    res = world.store.reservation("res-payroll-1")
    assert res.state == "committed"
    view = world.store.view("borrower-a/operating")
    assert [f.amount_minor for f in view.pending_out if f.flow_id == payout.leg_id] == [5_000_000]
    for status in case["provider"]["status_path"][1:]:
        world.pay(payout, [status])
        reconcile.sweep(world.gateway)
        payout = world.legs()[1]
        assert (payout.state == "settled") is (status == "PAID"), status
    assert payout.reconciled and payout.provider_status == "PAID"
    assert postings(world, payout.journal_id) == sorted(
        [("borrower-a/operating", -5_000_000), ("external/USD", 5_000_000)])
    assert world.store.reservation("res-payroll-1").state == "settled"
    (payroll,) = [o for o in world.store.rows("obligations") if o["obligation_id"] == "payroll-1"]
    assert payroll["state"] == "met"
    obj = world.fake.objects["transfers"][payout.provider_id]
    assert str(obj["transfer_amount"]) == case["provider"]["transfer_amount"]


def test_paid_then_failed_opens_an_incident_and_reopens_the_obligation():
    case = CASES["paid-then-failed"]
    world = World()
    world.execute(bind_terms(BASE))
    payout = world.legs()[1]
    world.pay(payout)
    reconcile.sweep(world.gateway)
    journals = leg_count(world)
    world.pay(payout, ["FAILED"])
    reconcile.sweep(world.gateway)
    world.fake.advance(10)  # FAILED → CANCELLED, the funds back in the wallet
    reconcile.sweep(world.gateway)
    payout = world.legs()[1]
    assert world.fake.objects["transfers"][payout.provider_id]["status"] == "CANCELLED"
    (incident,) = world.gateway.incidents(open_only=True)
    assert incident["kind"] == case["expect"]["incident"]["kind"]
    assert payout.state == "settled" and payout.reconciled is case["expect"]["reconciled"]
    assert leg_count(world) - journals == case["expect"]["journals_added"]
    (payroll,) = [o for o in world.store.rows("obligations") if o["obligation_id"] == "payroll-1"]
    assert payroll["state"] == "open"  # owed again; the reversal is the operator's to confirm


def test_a_currency_mismatch_is_an_incident_and_posts_nothing():
    case = CASES["currency-mismatch"]
    world = World()
    world.execute(bind_terms(BASE))
    payout = world.legs()[1]
    obj = world.fake.objects["transfers"][payout.provider_id]
    obj["transfer_currency"] = case["provider"]["currency"]
    world.pay(payout)
    reconcile.sweep(world.gateway)
    payout = world.legs()[1]
    assert payout.state == "submitted" and world.journals(payout.leg_id) == []
    (incident,) = world.gateway.incidents(open_only=True)
    assert incident["kind"] == case["expect"]["incident"]["kind"]


def test_an_orphan_provider_object_is_an_incident_never_adopted():
    case = CASES["orphan-provider-object"]
    world = World()
    world.execute(bind_terms(BASE))
    client = world.gateway.provider.client
    orphan = client.create_transfer(case["provider"]["request_id"], beneficiary_id="ben-payroll-1",
                                    amount=Money(minor=100, currency="USD"))
    for status in ("PROCESSING", "SENT", case["provider"]["status"]):
        client.simulate_transition(orphan.provider_id, status)
    journals = leg_count(world)
    done = reconcile.sweep(world.gateway)
    assert done.orphans == [orphan.provider_id]
    (incident,) = [i for i in world.gateway.incidents() if i["leg_id"] is None]
    assert (incident["kind"], incident["provider_id"]) == (
        case["expect"]["incident"]["kind"], orphan.provider_id)
    assert leg_count(world) == journals
    assert orphan.provider_id not in {leg.provider_id for leg in world.legs()}
    assert reconcile.sweep(world.gateway).orphans == []  # one open incident per object


# ----------------------------------------------------------------------- repayment and fx


def test_repayment_mode_b_is_ledger_only_and_labelled_simulated():
    case = CASES["repayment-mode-b"]
    world = World(leg_mode="B")
    lending.disburse(world.store, "adv-a", now=NOW, journal_id="j-adv-a-disburse")
    week_end = NOW - timedelta(hours=1)
    observe_revenue(world.store, "adv-a", week_end, 2_400_000, observed_at=week_end,
                    source="sales ledger")
    approval = approval_with("apr-repay", [
        {"index": 1, "kind": "repayment", "amount": case["leg"]["amount"], "currency": "USD",
         "source": "borrower-a/operating", "counterparty": "lender/operating",
         "facility_id": "adv-a"}])
    done = world.execute(approval)
    assert isinstance(done, Execution)
    (leg,) = done.legs
    states = [to for (to,) in world.gateway.conn.execute(
        "SELECT to_state FROM leg_events WHERE leg_id = ? ORDER BY event_seq", (leg.leg_id,))]
    assert states == case["expect"]["state_path"]
    assert leg.receipt_label == case["expect"]["receipt_label"]
    assert leg.provider_id is case["expect"]["provider_id"] and leg.ledger_only
    assert leg.reconciled is case["expect"]["reconciled"]
    # The ledger names the period's journal itself; its postings are advance-journals' week 1.
    assert postings(world, leg.journal_id) == fixture_postings(1)
    assert world.posts() == []


def test_fx_posts_one_journal_balanced_per_currency():
    case = CASES["fx-settled"]
    world = World()
    world.store.open_account("borrower-a/eur", "borrower-a", "EUR", as_of=NOW)
    fund(world.store, "borrower-a/operating", 5_000_000)
    # C3 binds the sell side; 11,100.00 USD buys the fixture's 10,000.00 EUR at 1.1100.
    approval = approval_with("apr-fx", [
        {"index": 1, "kind": "fx", "amount": 1_110_000, "currency": "USD",
         "source": "borrower-a/operating", "counterparty": "borrower-a/eur",
         "to_currency": "EUR"}])
    (leg,) = world.execute(approval).legs
    assert leg.state == "submitted"
    obj = world.fake.objects["conversions"][leg.provider_id]
    assert (str(obj["buy_amount"]), str(obj["sell_amount"]), str(obj["client_rate"])) == (
        case["provider"]["buy_amount"], case["provider"]["sell_amount"],
        case["provider"]["client_rate"])
    world.fake.settle_conversion(leg.provider_id)
    reconcile.sweep(world.gateway)
    (leg,) = world.legs("apr-fx")
    assert leg.state == "settled" and leg.reconciled is case["expect"]["reconciled"]
    assert postings(world, leg.journal_id) == sorted([
        ("borrower-a/operating", -1_110_000), ("external/USD", 1_110_000),
        ("external/EUR", -1_000_000), ("borrower-a/eur", 1_000_000)])


def test_the_sweep_drives_open_legs_and_stops_when_none_is_left():
    assert RECON["sweep"]["when"].startswith(f"every {reconcile.SWEEP_EVERY_S} s")
    world = World()
    world.execute(bind_terms(BASE))
    assert reconcile.open_legs(world.gateway) == [world.legs()[1].leg_id]
    world.pay(world.legs()[1])
    assert reconcile.sweep(world.gateway).executions == [BASE["approval_id"]]
    assert reconcile.open_legs(world.gateway) == []


# -------------------------------------------------------------------------------- webhooks


def sign(timestamp: str, body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).hexdigest()


def body_of(case: dict) -> bytes:
    if case.get("body") == "raw_body with PAID → FAILED":
        return HOOKS["raw_body"].replace('"PAID"', '"FAILED"').encode()
    if case.get("body") == "raw_body parsed and re-dumped with spaces":
        return json.dumps(json.loads(RAW)).encode()
    return RAW


def gets(world: World, provider_id: str) -> int:
    return sum(1 for r in world.fake.requests
               if r.method == "GET" and r.path.endswith(f"/{provider_id}"))


@pytest.fixture
def hooked():
    world = World()
    return world, reconcile.webhook_verifier(world.gateway, SECRET)


def test_the_fixture_signatures_are_real():
    ts = HOOK_CASES["valid"]["headers"]["x-timestamp"]
    assert sign(ts, RAW) == HOOK_CASES["valid"]["headers"]["x-signature"]
    altered = HOOK_CASES["altered-body-own-signature"]
    assert sign(ts, body_of(altered)) == altered["headers"]["x-signature"]
    assert sign(ts, RAW) != HOOK_CASES["wrong-secret"]["headers"]["x-signature"]


@pytest.mark.parametrize("case_id", ["valid", "wrong-secret", "body-altered",
                                     "altered-body-own-signature", "reserialised-body",
                                     "missing-headers"])
def test_webhook_cases(hooked, case_id):
    world, verifier = hooked
    case = HOOK_CASES[case_id]
    status = verifier.verify_and_ingest(case["headers"], body_of(case), HOOKS["now_ms"])
    assert status == case["expect"]["http"]
    assert gets(world, "t-0001") == (1 if case["expect"].get("action", "").startswith("GET")
                                     else 0)


def test_a_stale_webhook_is_refused(hooked):
    world, verifier = hooked
    case = HOOK_CASES["stale"]
    headers = {"x-timestamp": case["headers"]["x-timestamp"]}
    headers["x-signature"] = sign(headers["x-timestamp"], RAW)
    assert verifier.verify_and_ingest(headers, RAW, case["now_ms"]) == case["expect"]["http"]
    assert gets(world, "t-0001") == 0


def test_a_replayed_event_is_handled_once(hooked):
    world, verifier = hooked
    valid = HOOK_CASES["valid"]
    assert verifier.verify_and_ingest(valid["headers"], RAW, HOOKS["now_ms"]) == 200
    assert verifier.verify_and_ingest(valid["headers"], RAW, HOOKS["now_ms"]) == 200
    assert gets(world, "t-0001") == 1
    assert world.gateway.conn.execute("SELECT handled FROM webhook_events").fetchall() == [(1,)]


def hint(name: str, obj: dict, event_id: str) -> tuple[dict, bytes]:
    body = json.dumps({"id": event_id, "name": name, "data": {"object": obj}},
                      separators=(",", ":")).encode()
    ts = str(HOOKS["now_ms"])
    return {"x-timestamp": ts, "x-signature": sign(ts, body)}, body


def test_an_unknown_event_name_is_stored_and_ignored(hooked):
    world, verifier = hooked
    headers, body = hint("issuing.card.created", {"id": "card-1"}, "evt-card")
    assert verifier.verify_and_ingest(headers, body, HOOKS["now_ms"]) == 200
    assert world.gateway.conn.execute("SELECT name, handled FROM webhook_events").fetchall() == [
        ("issuing.card.created", 1)]
    assert gets(world, "card-1") == 0


def test_a_webhook_on_an_object_no_leg_owns_is_read_then_flagged(hooked):
    world, verifier = hooked
    client = world.gateway.provider.client
    orphan = client.create_transfer(HOOK_CASES["unknown-object"]["object_request_id"],
                                    beneficiary_id="ben-payroll-1",
                                    amount=Money(minor=100, currency="USD"))
    headers, body = hint("payout.transfer.paid", {"id": orphan.provider_id,
                                                  "request_id": orphan.request_id,
                                                  "status": "PAID"}, "evt-orphan")
    assert verifier.verify_and_ingest(headers, body, HOOKS["now_ms"]) == 200
    assert gets(world, orphan.provider_id) == 1
    (incident,) = world.gateway.incidents(open_only=True)
    assert (incident["kind"], incident["provider_id"]) == ("unknown_provider_object",
                                                           orphan.provider_id)


def test_a_paid_webhook_settles_nothing_until_the_get_shows_paid(hooked):
    world, verifier = hooked
    world.execute(bind_terms(BASE))
    payout = world.legs()[1]
    world.pay(payout, ["PROCESSING", "SENT"])
    headers, body = hint("payout.transfer.paid", {"id": payout.provider_id,
                                                  "request_id": payout.request_id,
                                                  "status": "PAID"}, "evt-early")
    assert verifier.verify_and_ingest(headers, body, HOOKS["now_ms"]) == 200
    assert world.legs()[1].state == "submitted"  # the GET said SENT; the event is only a hint
    world.pay(payout, ["PAID"])
    headers, body = hint("payout.transfer.paid", {"id": payout.provider_id,
                                                  "request_id": payout.request_id,
                                                  "status": "PAID"}, "evt-paid")
    assert verifier.verify_and_ingest(headers, body, HOOKS["now_ms"]) == 200
    payout = world.legs()[1]
    assert payout.state == "settled" and payout.reconciled
    assert gets(world, payout.provider_id) >= 2


def test_a_lookup_that_errors_leaves_the_event_retryable(hooked):
    world, verifier = hooked
    for _ in range(3):
        world.fake.respond_next(500, {"code": "internal_error", "message": "down"})
    headers, body = hint("payout.transfer.paid", {"id": "t-9", "status": "PAID"}, "evt-down")
    with pytest.raises(ProviderError):
        verifier.verify_and_ingest(headers, body, HOOKS["now_ms"])
    assert world.gateway.conn.execute("SELECT handled FROM webhook_events").fetchall() == [(0,)]
    assert verifier.verify_and_ingest(headers, body, HOOKS["now_ms"]) == 200  # 404: nothing moved

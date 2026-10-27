"""The Airwallex connector against its fake: the switch, hosts, lifecycles, idempotency, errors
and the leg plan, each asserted from the design's fixtures unchanged
(prp/2026-10-20-ledgerworld/design/modules/airwallex/fixtures/)."""

from __future__ import annotations

import ast
import json
import logging
import traceback
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache
from pathlib import Path

import pytest
from app.connectors.airwallex import fake as fake_module
from app.connectors.airwallex.client import (
    CONNECTED_PROBE_PATH,
    LEG_PLAN,
    AirwallexClient,
    client_from_env,
    provider_amount,
)
from app.connectors.airwallex.errors import (
    ConfigError,
    DuplicateRequest,
    HostRefused,
    OutcomeUnknown,
    ProviderError,
)
from app.connectors.airwallex.fake import CONNECTED_ACCOUNT, SCENARIOS, FakeClock, FakeTransport
from app.connectors.airwallex.live import LiveTransport
from app.connectors.airwallex.transport import (
    BANNERS,
    CREDENTIAL_VARS,
    Credentials,
    check_base_url,
    encode_body,
    select_transport,
)
from app.finance.schemas import Money
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/airwallex/fixtures"
PLACEHOLDER = "placeholder-not-a-key"


@cache
def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Sleeps(list):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


def make(scenario: str = "happy", *, times: int | None = 1, connected: bool = False):
    clock = FakeClock()
    transport = FakeTransport(scenario, clock=clock, connected=connected, times=times)
    client = AirwallexClient(transport, clock, api_version="2024-06-30", sleep=Sleeps())
    return transport, client


def usd(minor: int) -> Money:
    return Money(minor=minor, currency="USD")


def posts(transport: FakeTransport, path: str) -> list:
    return [r for r in transport.requests if r.method == "POST" and r.path == path]


def pay(client: AirwallexClient, request_id: str, minor: int = 100000):
    return client.create_transfer(request_id, beneficiary_id="ben-payroll-1", amount=usd(minor))


# --------------------------------------------------------------------- switch and hosts


def env_of(row: dict) -> dict[str, str]:
    return {k: PLACEHOLDER if v == "<set>" else v for k, v in row["env"].items()}


@pytest.mark.parametrize("row", fixture("switch-and-hosts")["switch"], ids=lambda r: r["id"])
def test_switch(row):
    env, expect = env_of(row), row["expect"]
    if "refused" in expect:
        with pytest.raises(ConfigError) as refused:
            select_transport(env)
        assert type(refused.value).__name__ == expect["refused"]
        for name in expect.get("message_names", []):
            assert name in str(refused.value)
        assert PLACEHOLDER not in str(refused.value)
        return
    transport = select_transport(env)
    kind = {"fake": FakeTransport, "live": LiveTransport}[expect["transport"]]
    assert isinstance(transport, kind)
    if "base_url" in expect:
        assert transport.base_url == expect["base_url"]
        transport.close()
    if "banner" in expect:
        assert BANNERS[transport.mode] == expect["banner"]


def test_sandbox_with_production_base_url_is_refused():
    env = {"AIRWALLEX_MODE": "sandbox", "AIRWALLEX_BASE_URL": "https://api.airwallex.com",
           **dict.fromkeys(CREDENTIAL_VARS, PLACEHOLDER)}
    with pytest.raises(HostRefused):
        select_transport(env)


@pytest.mark.parametrize("row", fixture("switch-and-hosts")["hosts"], ids=lambda r: r["base_url"])
def test_host_allowlist(row):
    creds = Credentials(PLACEHOLDER, PLACEHOLDER)
    if row["expect"] == "allowed":
        assert check_base_url(row["base_url"]) == row["base_url"]
        LiveTransport(row["base_url"], creds).close()
        return
    with pytest.raises(HostRefused):
        check_base_url(row["base_url"])
    with pytest.raises(HostRefused):
        LiveTransport(row["base_url"], creds)


def test_headers_on_every_call_and_login_only():
    transport, client = make()
    client.balances()
    pay(client, "leg-h-1")
    login, *calls = transport.requests
    assert login.path == "/api/v1/authentication/login"
    assert {"x-client-id", "x-api-key"} <= set(login.headers)
    assert "authorization" not in login.headers
    assert len(calls) == 2
    for call in calls:
        assert call.headers["authorization"].startswith("Bearer ")
        assert call.headers["x-api-version"] == "2024-06-30"
        assert call.headers["content-type"] == "application/json"
        assert not {"x-client-id", "x-api-key"} & set(call.headers)


def test_api_version_is_pinned_from_the_environment():
    client = client_from_env({"AIRWALLEX_API_VERSION": "2025-02-14"})
    client.balances()
    assert {r.headers["x-api-version"] for r in client.transport.requests} == {"2025-02-14"}
    assert client_from_env({}).api_version == fixture("canonical-requests")["api_version"]
    for bad in ("2023-01-01", "latest"):
        with pytest.raises(ConfigError, match="AIRWALLEX_API_VERSION"):
            client_from_env({"AIRWALLEX_API_VERSION": bad})


def test_token_renewal():
    token = fixture("switch-and-hosts")["token"]
    transport, client = make()
    logins = lambda: len(posts(transport, "/api/v1/authentication/login"))
    seen = 0
    for case in [c for c in token["cases"] if "now_s" in c]:
        transport.clock.now = case["now_s"]
        client.balances()
        assert logins() - seen == (1 if case["expect"] == "login" else 0), case
        seen = logins()
    assert token["lifetime_s"] - token["renew_before_s"] == 1740


def test_expired_token_relogs_once_and_repeats_the_same_request():
    transport, client = make()
    client.balances()
    transport.expire_tokens()
    pay(client, "leg-t-1")
    creates = posts(transport, "/api/v1/transfers/create")
    assert len(creates) == 2  # the 401, then the same request after one re-login
    assert {c.body["request_id"] for c in creates} == {"leg-t-1"}
    assert len(posts(transport, "/api/v1/authentication/login")) == 2
    assert transport.count("transfers", "leg-t-1") == 1


def test_a_second_401_is_auth_fail():
    transport, client = make()
    for _ in range(2):
        transport.respond_next(401, {"code": "credentials_expired", "message": "expired"})
    with pytest.raises(ProviderError) as failed:
        pay(client, "leg-t-2")
    assert (failed.value.code, failed.value.retryable, failed.value.outcome) == (
        "auth_fail", False, "rejected")
    assert transport.count("transfers", "leg-t-2") == 0


SENTINEL = "sentinel-key-value-0123456789"
SENTINEL_ID = "sentinel-client-id-987654"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_secrets_never_reach_a_message_log_or_trace(scenario, caplog):
    caplog.set_level(logging.DEBUG)
    transport, client = make(scenario, times=None)
    transport.credentials = Credentials(SENTINEL_ID, SENTINEL)
    texts = [repr(transport.credentials), repr(client), repr(transport)]
    for action in (client.balances, lambda: pay(client, "leg-s-1"),
                   lambda: client.simulate_deposit(amount=usd(100), global_account_id="ga-usd-1")):
        try:
            action()
        except Exception as error:  # noqa: BLE001 — every error's text is the probe
            texts += [str(error), repr(error), "".join(traceback.format_exception(error))]
    tokens = [t for t in transport._tokens]
    texts.append(caplog.text)
    for text in texts:
        for secret in (SENTINEL, SENTINEL_ID, *tokens):
            assert secret not in text


def test_config_error_names_variables_never_values():
    with pytest.raises(ConfigError) as refused:
        select_transport({"AIRWALLEX_MODE": "sandbox",
                          **dict.fromkeys(CREDENTIAL_VARS[:1], SENTINEL)})
    assert "AIRWALLEX_CLIENT_ID" in str(refused.value)
    assert SENTINEL not in str(refused.value)


# ---------------------------------------------------------------------------- lifecycles


def test_fake_start_state_is_the_fixture():
    start = fixture("fake-lifecycles")["start"]
    transport = FakeTransport()
    assert [{"currency": c, "available_minor": transport.available(c)}
            for c in ("USD", "EUR")] == start["balances"]
    assert transport.global_accounts == start["global_accounts"]
    assert list(transport.beneficiaries.values()) == start["beneficiaries"]


def test_transfer_statuses_and_edges_are_the_fixture():
    transfer = fixture("fake-lifecycles")["transfer"]
    assert fake_module.TRANSFER_EDGES == {tuple(e) for e in transfer["edges"]}
    assert {s for e in fake_module.TRANSFER_EDGES for s in e} == set(transfer["statuses"])


@pytest.mark.parametrize("path", fixture("fake-lifecycles")["transfer"]["paths"],
                         ids=lambda p: p["id"])
def test_transfer_lifecycle(path):
    transport, client = make()
    spec = path["create"]
    transfer = None
    for step in path["steps"]:
        do = step["do"]
        try:
            if do == "create":
                transfer = client.create_transfer(
                    spec["request_id"], beneficiary_id=spec["beneficiary_id"],
                    amount=Money(minor=spec["transfer_amount_minor"], currency=spec["currency"]))
            elif do.startswith("transition"):
                _, status, *rest = do.split()
                failure = rest[0].removeprefix("failure_type=") if rest else None
                client.simulate_transition(transfer.provider_id, status, failure_type=failure)
            elif do == "advance 5 s":
                transport.advance(5)
            assert "refused" not in step, step
        except ProviderError as refused:
            assert "refused" in step, step
            assert refused.http == step["refused"]["http"]
            if "code" in step["refused"]:
                assert refused.code == step["refused"]["code"]
        if transfer is not None and "status" in step:
            assert client.get_transfer(transfer.provider_id).status == step["status"]
        if "available_minor" in step:
            assert transport.available(spec["currency"]) == step["available_minor"]
    if "wire_amount" in path:
        create = posts(transport, "/api/v1/transfers/create")[0]
        assert create.body["transfer_amount"] == path["wire_amount"]


def test_conversion_paths():
    paths = {p["id"]: p for p in fixture("fake-lifecycles")["conversion"]["paths"]}

    cover = paths["eur-invoice-cover"]
    transport, client = make()
    q = cover["quote"]
    buy = Money(minor=q["buy_amount_minor"], currency=q["buy_currency"])
    quote = client.quote(sell_currency=q["sell_currency"], buy_currency=q["buy_currency"],
                         amount=buy)
    assert quote["client_rate"] == Decimal(q["fake_rate"])
    conv = client.create_conversion(cover["create"]["request_id"], sell_currency="USD",
                                    buy_currency="EUR", amount=buy, quote_id=quote["quote_id"])
    body = posts(transport, "/api/v1/conversions/create")[0].body
    assert body["buy_amount"] == cover["create"]["buy_amount"] and "sell_amount" not in body
    assert conv.amount == cover["create"]["sell_amount_expected"] and conv.currency == "USD"
    created, settled = cover["steps"]
    assert conv.status == created["status"]
    assert transport.available("USD") == created["USD_available_minor"]
    assert transport.available("EUR") == created["EUR_available_minor"]
    transport.settle_conversion(conv.provider_id)
    assert client.get_conversion(conv.provider_id).status == settled["status"]
    assert transport.available("EUR") == settled["EUR_available_minor"]

    cancel = paths["cancel-unsettled"]
    transport, client = make()
    spec = cancel["create"]
    conv = client.create_conversion(
        spec["request_id"], sell_currency=spec["sell_currency"],
        buy_currency=spec["buy_currency"], amount=usd(100000))
    assert posts(transport, "/api/v1/conversions/create")[0].body["sell_amount"] == "1000.00"
    assert conv.status == cancel["steps"][0]["status"]
    transport.cancel_conversion(conv.provider_id)
    assert client.find_conversion(spec["request_id"])[0].status == cancel["steps"][1]["status"]
    assert transport.available("USD") == cancel["steps"][1]["USD_available_minor"]


def test_deposit_simulation_sends_a_number_from_the_converter():
    sim = fixture("fake-lifecycles")["deposit_simulation"]
    transport, client = make()
    before = transport.available("USD")
    deposit = client.simulate_deposit(
        amount=usd(sim["from_minor"]), global_account_id=sim["body"]["global_account_id"],
        reference=sim["body"]["reference"])
    sent = posts(transport, sim["call"].split()[1])[0]
    assert json.loads(sent.wire, parse_float=Decimal) == json.loads(
        json.dumps(sim["body"]), parse_float=Decimal)
    assert '"amount":10000.00' in sent.wire
    assert isinstance(sent.body["amount"], Decimal)
    assert deposit.status == sim["expect"]["status"]
    assert transport.available("USD") - before == sim["expect"]["USD_available_minor_delta"]


# --------------------------------------------------------------------------- idempotency


def _movements(transport: FakeTransport, request_id: str, start: int, minor: int) -> int:
    count = transport.count("transfers", request_id)
    assert start - transport.available("USD") == count * minor  # one debit per stored transfer
    return count


def test_idempotency_cases_are_all_driven():
    assert {c["id"] for c in fixture("idempotency")["cases"]} == set(IDEMPOTENCY)


def _replay_after_settle(case):
    transport, client = make()
    first, replay = case["calls"]
    created = pay(client, first["request_id"], first["amount_minor"])
    assert created.status == first["result"]["status"]
    with pytest.raises(DuplicateRequest) as dup:
        pay(client, replay["request_id"], replay["amount_minor"])
    assert dup.value.code == replay["result"]["code"]
    found = client.find_transfer(first["request_id"])
    assert [f.provider_id for f in found] == [created.provider_id]
    assert len(found) == case["then"]["returns"]["count"]
    return transport, first["request_id"], first["amount_minor"]


def _replay_in_flight(case):
    transport, client = make()
    first, replay = case["calls"]
    transport.hold(first["request_id"])
    with pytest.raises(OutcomeUnknown):
        pay(client, first["request_id"], first["amount_minor"])
    with pytest.raises(DuplicateRequest) as dup:
        pay(client, replay["request_id"], replay["amount_minor"])
    assert dup.value.in_flight is True
    return transport, first["request_id"], first["amount_minor"]


def _replay_with_other_amount(case):
    transport, client = make()
    first, replay = case["calls"]
    pay(client, first["request_id"], first["amount_minor"])
    with pytest.raises(DuplicateRequest) as dup:
        pay(client, replay["request_id"], replay["amount_minor"])
    assert dup.value.code == replay["result"]["code"]
    return transport, first["request_id"], first["amount_minor"]


def _conversion_replay(case):
    transport, client = make()
    first, replay = case["calls"]
    conv = lambda: client.create_conversion(
        first["request_id"], sell_currency="USD", buy_currency="EUR", amount=usd(100000))
    assert conv().status == first["result"]["status"]
    with pytest.raises(DuplicateRequest) as dup:
        conv()
    assert dup.value.code == replay["result"]["code"]
    assert len(client.find_conversion(first["request_id"])) == case["then"]["returns"]["count"]
    assert transport.available("USD") == 10000000 - 100000


def _connected_transfer_replay(case):
    transport, client = make(connected=True)
    first, replay = case["calls"]
    move = lambda: client.connected_account_transfer(
        first["request_id"], amount=usd(1000000), destination=CONNECTED_ACCOUNT)
    move()
    with pytest.raises(DuplicateRequest) as dup:
        move()
    assert dup.value.code == replay["result"]["code"]
    assert dup.value.in_flight is case["client_raises"]["DuplicateRequest"]["in_flight"]
    assert transport.available("USD", CONNECTED_ACCOUNT) == 1000000


def _timeout_after_accept(case):
    transport, client = make(case["scenario"])
    call = case["calls"][0]
    with pytest.raises(OutcomeUnknown) as unknown:
        pay(client, call["request_id"], call["amount_minor"])
    assert unknown.value.request_id == call["request_id"]
    assert len(posts(transport, "/api/v1/transfers/create")) == 1  # never repeated
    found = client.find_transfer(call["request_id"])
    assert len(found) == case["then"]["returns"]["count"]
    assert found[0].status == case["then"]["returns"]["status"]
    return transport, call["request_id"], call["amount_minor"]


def _timeout_before_send(case):
    transport, client = make(case["scenario"])
    call = case["calls"][0]
    with pytest.raises(OutcomeUnknown):
        pay(client, call["request_id"], call["amount_minor"])
    assert len(client.find_transfer(call["request_id"])) == case["then"]["returns"]["count"]
    pay(client, call["request_id"], call["amount_minor"])  # the safe retry: the SAME id
    assert transport.count("transfers", call["request_id"]) == case["movements_after_retry"]
    return transport, call["request_id"], call["amount_minor"]


def _rate_limited_then_ok(case):
    transport, client = make(case["scenario"])
    request_id = case["calls"][0]["request_id"]
    pay(client, request_id)
    creates = posts(transport, "/api/v1/transfers/create")
    assert [c.body["request_id"] for c in creates] == [request_id] * len(case["calls"])
    assert len(client._sleep) == 1
    return transport, request_id, 100000


IDEMPOTENCY = {
    "replay-after-settle": _replay_after_settle,
    "replay-in-flight": _replay_in_flight,
    "replay-with-other-amount": _replay_with_other_amount,
    "conversion-replay": _conversion_replay,
    "connected-transfer-replay": _connected_transfer_replay,
    "timeout-after-accept": _timeout_after_accept,
    "timeout-before-send": _timeout_before_send,
    "rate-limited-then-ok": _rate_limited_then_ok,
}


@pytest.mark.parametrize("case", fixture("idempotency")["cases"], ids=lambda c: c["id"])
def test_idempotency(case):
    moved = IDEMPOTENCY[case["id"]](case)
    if moved is not None:
        transport, request_id, minor = moved
        expected = case.get("movements_after_retry", case.get("movements"))
        assert _movements(transport, request_id, 10000000, minor) == expected


OPS = st.lists(st.sampled_from(
    ["create", "hold", "release", "timeout_before_send", "timeout_after_accept"]), max_size=12)


@settings(max_examples=150, deadline=None)
@given(OPS)
def test_at_most_one_transfer_per_request_id(ops):
    transport, client = make()
    for op in ops:
        if op == "hold":
            transport.hold("leg-p")
        elif op == "release":
            transport.release("leg-p")
        else:
            if op != "create":
                transport.arm(op)
            try:
                pay(client, "leg-p")
            except (DuplicateRequest, OutcomeUnknown):
                pass
            transport.arm("happy")
        assert _movements(transport, "leg-p", 10000000, 100000) <= 1


# --------------------------------------------------------------------------------- errors


def _error_case(scenario):
    """Drive one errors.json scenario; return (raised error or None, transport)."""
    connected = scenario == "duplicate_old_spelling"
    arm = {"rate_limited": None, "server_error_on_get": None}
    fake_scenario = {"server_error_on_get": "server_error"}.get(scenario, scenario)
    if fake_scenario not in SCENARIOS:
        fake_scenario = "happy"
    transport, client = make(fake_scenario, times=arm.get(scenario, 1), connected=connected)
    try:
        if scenario in ("duplicate", "in_flight"):
            if scenario == "in_flight":
                transport.hold("leg-e")
            try:
                pay(client, "leg-e")
            except OutcomeUnknown:
                pass
            pay(client, "leg-e")
        elif scenario == "duplicate_old_spelling":
            for _ in range(2):
                client.connected_account_transfer("leg-e", amount=usd(100),
                                                  destination=CONNECTED_ACCOUNT)
        elif scenario == "token_expired":
            client.balances()
            transport.expire_tokens()
            pay(client, "leg-e")
        elif scenario == "server_error_on_get":
            client.balances()
        elif scenario == "unknown_code":
            transport.respond_next(400, {"code": "something_new", "message": "new"})
            pay(client, "leg-e")
        else:
            pay(client, "leg-e")
    except Exception as error:  # noqa: BLE001 — the raised class is what is asserted
        return error, transport, client
    return None, transport, client


@pytest.mark.parametrize("case", fixture("errors")["cases"], ids=lambda c: c["scenario"])
def test_error_classes(case):
    error, transport, client = _error_case(case["scenario"])
    creates = posts(transport, "/api/v1/transfers/create")
    klass = case["class"]
    if klass == "ok" or case.get("expect") == "re-login, then success":
        assert error is None
    elif klass == "rejected":
        assert isinstance(error, ProviderError) and not isinstance(error, DuplicateRequest)
        assert (error.code, error.http, error.retryable, error.outcome) == (
            case["code"], case["http"], False, "rejected")
    elif klass == "rejected_duplicate":
        assert isinstance(error, DuplicateRequest)
        assert error.in_flight is (case["http"] == 409)
        assert error.request_id == "leg-e"
        if "code" in case:
            assert error.code == case["code"]
    elif klass == "retried":
        assert isinstance(error, ProviderError) and error.retryable and error.outcome == "rejected"
        if "code" in case:
            assert error.code == case["code"]
        tried = creates if case["scenario"] == "rate_limited" else [
            r for r in transport.requests if r.path == "/api/v1/balances/current"]
        assert len(tried) == 3 and len(client._sleep) == 2
    elif klass == "retried_once":
        assert isinstance(error, ProviderError)
        assert (error.code, error.retryable) == ("auth_fail", False)
    elif klass == "unknown":
        assert isinstance(error, OutcomeUnknown) and error.request_id == "leg-e"
        assert len(creates) == 1  # a POST is never repeated after a timeout or a 5xx


def test_a_get_recovers_after_a_5xx():
    transport, client = make("server_error", times=2)
    assert {b.currency: b.available for b in client.balances()}["USD"] == usd(10000000)
    assert len([r for r in transport.requests if r.path == "/api/v1/balances/current"]) == 3


@pytest.mark.parametrize("amount", ["abc", "NaN", True])
def test_an_unreadable_provider_amount_is_unknown(amount):
    with pytest.raises(OutcomeUnknown):
        provider_amount(amount, "USD")


def test_no_float_in_any_body_the_client_builds():
    transport, client = make(connected=True)
    pay(client, "leg-f-1")
    client.quote(sell_currency="USD", buy_currency="EUR", amount=Money(minor=100, currency="EUR"))
    client.create_conversion("leg-f-2", sell_currency="USD", buy_currency="EUR", amount=usd(100))
    client.connected_account_transfer("leg-f-3", amount=usd(100), destination=CONNECTED_ACCOUNT)
    client.charge("leg-f-4", amount=usd(100), source=CONNECTED_ACCOUNT)
    client.simulate_deposit(amount=usd(100), global_account_id="ga-usd-1")

    def floats(value) -> bool:
        if isinstance(value, dict):
            return any(floats(v) for v in value.values())
        if isinstance(value, list):
            return any(floats(v) for v in value)
        return isinstance(value, float)

    assert not any(floats(r.body) for r in transport.requests)
    with pytest.raises(TypeError):
        encode_body({"amount": 1.5})
    with pytest.raises(ValueError):
        pay(client, "leg-f-5", 100.0)  # Money refuses a float before any body exists


# ---------------------------------------------------------------------------- leg mapping


@pytest.mark.parametrize("case", fixture("leg-mapping")["probe"]["cases"],
                         ids=lambda c: json.dumps(c["env"]) + json.dumps(c["probe"]))
def test_probe(case):
    setting = case["env"].get("AIRWALLEX_CONNECTED")
    probe = case["probe"]
    if isinstance(probe, dict):
        transport, client = make(connected=probe["http"] == 200)
        if probe["http"] in (404, 500):
            for _ in range(3):
                transport.respond_next(probe["http"], {"code": "x", "message": "probe"})
    else:
        transport, client = make()
    if case["mode"] == "refused":
        with pytest.raises(ConfigError, match=str(probe["http"])):
            client.probe_connected(setting)
        return
    if case["mode"] == "from the fake":
        for connected, mode in ((True, "A"), (False, "B")):
            client = client_from_env(case["env"], connected=connected)
            assert client.probe_connected(setting) == mode
        return
    assert client.probe_connected(setting) == case["mode"]
    probed = [r for r in transport.requests if r.path == CONNECTED_PROBE_PATH]
    assert bool(probed) == (probe != "not called")


@pytest.mark.parametrize("leg", fixture("leg-mapping")["legs"], ids=lambda leg: leg["kind"])
def test_leg_plan(leg):
    for mode in ("A", "B"):
        spec, planned = leg[f"mode_{mode}"], LEG_PLAN[mode][leg["kind"]]
        if spec["op"] == "same as A":
            spec = {**leg["mode_A"], **{k: v for k, v in spec.items() if k != "op"}}
        assert (planned.op, planned.label) == (spec["op"], spec["label"])
        assert planned.on_behalf_of == spec.get("header", "").startswith("x-on-behalf-of:")


def test_lf2_advance_on_the_wire_in_both_modes():
    lf2 = fixture("leg-mapping")["lf2_advance"]
    principal = usd(lf2["ledger_principal_minor"])
    leg_id, now = "0123456789ab-1-advance", datetime(2026, 10, 28, tzinfo=UTC)

    transport, client = make(connected=True)
    moved = client.connected_account_transfer(leg_id, amount=principal,
                                              destination=CONNECTED_ACCOUNT)
    sent = posts(transport, "/api/v1/connected_account_transfers/create")[0].body
    assert sent["amount"] == lf2["provider_amount"]
    receipt = moved.receipt(leg_kind="advance", label=LEG_PLAN["A"]["advance"].label,
                            mode=client.mode, observed_at=now)
    want = lf2["mode_A_receipt"]
    assert (receipt.label, receipt.amount, receipt.currency) == (
        want["label"], want["amount"], want["currency"])

    transport, client = make()
    before = transport.available("USD")
    deposit = client.simulate_deposit(amount=principal, global_account_id="ga-usd-1",
                                      reference=LEG_PLAN["B"]["advance"].label)
    receipt = deposit.receipt(leg_kind="advance", label=LEG_PLAN["B"]["advance"].label,
                              mode=client.mode, observed_at=now, request_id=leg_id)
    want = lf2["mode_B_receipt"]
    assert (receipt.label, receipt.amount, receipt.currency, receipt.status) == (
        want["label"], want["amount"], want["currency"], want["status"])
    # the principal only: the fee is a ledger journal, never a provider movement
    assert transport.available("USD") - before == lf2["ledger_principal_minor"]


# ---------------------------------------------------------------------------- the fence


def test_the_fake_loads_no_other_connector_module_on_import():
    """A simulation process may import the fake (the isolation fixture's `fake-allowed`);
    the static fence follows import-time imports, so the fake reaches the rest lazily."""
    tree = ast.parse(Path(fake_module.__file__).read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and "airwallex" not in (node.module or ""), node.module
        if isinstance(node, ast.Import):
            assert not any("airwallex" in a.name for a in node.names)

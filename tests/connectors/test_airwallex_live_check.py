"""checks/airwallex_live.py: the canonical contract pass, proven end to end on the fake.

The sandbox leg is never called here; `--require-key` is driven with the fake standing in for the
sandbox client, which exercises the same sequence and the diff offline."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.connectors.airwallex.client import AirwallexClient
from app.connectors.airwallex.fake import FakeTransport

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "checks" / "airwallex_live.py"
sys.path.insert(0, str(SCRIPT.parent))

import airwallex_live as live

KEY_VARS = ("AIRWALLEX_API_KEY", "AIRWALLEX_CLIENT_ID", "AIRWALLEX_BENEFICIARY_ID")


def _script(*args: str, **extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AIRWALLEX_")}
    env.update(extra)
    return subprocess.run([sys.executable, str(SCRIPT), *args], check=False, cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def _pass(transport: FakeTransport, run_id: str = "t1") -> live.ContractPass:
    return live.ContractPass(AirwallexClient(transport), run_id, live.FAKE_BENEFICIARY).run()


def test_fake_runs_every_check_and_exits_0() -> None:
    done = _script("--fake", "--run-id", "t1")
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert "14/14 PASS" in lines
    assert not [line for line in lines if line.startswith("FAIL")]
    assert any(line.startswith("PASS payout-to-paid transfer-")
               and line.endswith("· status PAID, USD moved -10000 minor") for line in lines)
    assert any(line.startswith("PASS advance deposit-") and "JSON number: accepted" in line
               for line in lines)


def test_require_key_without_a_key_exits_2_naming_the_variables() -> None:
    done = _script("--require-key")
    assert done.returncode == 2
    for name in KEY_VARS:
        assert name in done.stderr
    assert "PASS" not in done.stdout


def test_require_key_names_only_what_is_missing() -> None:
    done = _script("--require-key", AIRWALLEX_API_KEY="k-test", AIRWALLEX_CLIENT_ID="c-test")
    assert done.returncode == 2
    assert "AIRWALLEX_BENEFICIARY_ID" in done.stderr
    assert "AIRWALLEX_API_KEY" not in done.stderr
    assert "k-test" not in done.stderr + done.stdout


class AcceptsReplays(FakeTransport):
    """A provider double that answers a replayed request_id by moving money again."""

    def count(self, collection: str, request_id: str) -> int:
        return 0


def test_a_duplicate_request_id_moving_twice_fails_the_check() -> None:
    run = _pass(AcceptsReplays())
    failed = {c.name for c in run.checks if not c.ok}
    assert {"fx-conversion-replay", "payout-replay", "payout-lookup", "fx-conversion-lookup",
            "one-movement"} <= failed
    assert not run.ok
    replay = next(c for c in run.checks if c.name == "payout-replay")
    assert replay.provider_id and "a second transfer moved" in replay.detail
    assert next(c for c in run.checks if c.name == "one-movement").detail.startswith("2 transfer")


def test_mode_a_runs_the_connected_account_advance() -> None:
    run = _pass(FakeTransport(connected=True))
    assert run.ok, [c.line() for c in run.checks]
    assert run.mode == "A"
    advance = next(c for c in run.checks if c.name == "advance")
    assert advance.detail.startswith("mode A") and advance.provider_id


def test_a_failed_step_skips_what_depends_on_it() -> None:
    transport = FakeTransport()
    transport.beneficiaries.clear()
    run = _pass(transport)
    by_name = {c.name: c for c in run.checks}
    assert not by_name["payout"].ok
    assert by_name["payout-replay"].detail == "skipped: no transfer"
    assert by_name["fx-conversion"].ok and by_name["advance"].ok


def test_diff_fails_a_key_only_the_fake_returns_and_lists_one_only_the_sandbox_returns() -> None:
    fake = _pass(FakeTransport())
    sandbox = _pass(FakeTransport())
    assert live.diff(sandbox, fake) == ([], [])
    payout = next(c for c in sandbox.checks if c.name == "payout")
    payout.shape = live.Shape(payout.shape.http, payout.shape.keys - {"reference"} | {"fee"},
                              payout.shape.status)
    quote = next(c for c in sandbox.checks if c.name == "fx-conversion")
    quote.shape = live.Shape(quote.shape.http, quote.shape.keys, "SETTLED")
    failing, listed = live.diff(sandbox, fake)
    assert failing == ["fx-conversion: status sandbox SETTLED, fake SCHEDULED",
                       "payout: only the fake returns reference"]
    assert listed == ["payout: only the sandbox returns fee"]


def test_require_key_runs_sandbox_then_fake_and_diffs(monkeypatch, capsys) -> None:
    real = live.client_from_env

    def no_network(env, **options):
        assert env["AIRWALLEX_MODE"] in ("sandbox", "fake")
        return real({"AIRWALLEX_MODE": "fake"}, **options)

    monkeypatch.setattr(live, "client_from_env", no_network)
    env = {"AIRWALLEX_API_KEY": "k", "AIRWALLEX_CLIENT_ID": "c",
           "AIRWALLEX_BENEFICIARY_ID": live.FAKE_BENEFICIARY}
    assert live.main(["--require-key", "--run-id", "t2"], env) == 0
    out = capsys.readouterr().out
    assert "== sandbox" in out and "== fake" in out
    assert "== diff · 0 failing, 0 listed" in out


@pytest.mark.parametrize(("name", "value"), [
    ("AIRWALLEX_CONNECTED", "sometimes"),
    ("AIRWALLEX_API_VERSION", "2023-01-01"),
    ("AIRWALLEX_BASE_URL", "https://api.airwallex.com"),
])
def test_bad_configuration_exits_2(name: str, value: str, capsys) -> None:
    env = {"AIRWALLEX_API_KEY": "k", "AIRWALLEX_CLIENT_ID": "c",
           "AIRWALLEX_BENEFICIARY_ID": "b", name: value}
    assert live.main(["--require-key"], env) == 2
    assert "configuration refused" in capsys.readouterr().err


def test_a_status_only_one_side_carries_is_a_listed_key_not_a_failing_status() -> None:
    fake = _pass(FakeTransport())
    sandbox = _pass(FakeTransport())
    accounts = next(c for c in sandbox.checks if c.name == "global-accounts")
    accounts.shape = live.Shape(accounts.shape.http, accounts.shape.keys | {"status"}, "ACTIVE")
    assert live.diff(sandbox, fake) == ([], ["global-accounts: only the sandbox returns status"])


def test_the_connected_probe_answer_is_recorded_not_failed() -> None:
    fake = _pass(FakeTransport())
    sandbox = _pass(FakeTransport())
    probe = next(c for c in sandbox.checks if c.name == "connected-probe")
    probe.shape = live.Shape(404, frozenset({"code", "message"}), "resource_not_found")
    failing, listed = live.diff(sandbox, fake)
    assert failing == []
    assert listed == [("connected-probe: sandbox answered http 404 resource_not_found, "
                       "fake http 403 unauthorized")]


def test_an_unexpected_answer_shape_fails_its_check_and_the_pass_goes_on() -> None:
    class ListQuote(FakeTransport):
        def _quote(self, body):
            return [super()._quote(body)]

    run = _pass(ListQuote())
    by_name = {c.name: c for c in run.checks}
    assert not by_name["fx-quote"].ok and "AttributeError" in by_name["fx-quote"].detail
    assert len(run.checks) == 14 and by_name["payout-to-paid"].ok


class FailedAdvance(FakeTransport):
    def _new_connected_account_transfers(self, body, account):
        return {**super()._new_connected_account_transfers(body, account), "status": "FAILED"}


def test_a_failed_mode_a_advance_fails_the_check() -> None:
    run = _pass(FailedAdvance(connected=True))
    advance = next(c for c in run.checks if c.name == "advance")
    assert not advance.ok and "status FAILED" in advance.detail

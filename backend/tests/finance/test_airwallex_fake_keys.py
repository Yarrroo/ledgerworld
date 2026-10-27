"""The fake returns no key the sandbox does not (checks/airwallex_canon.json).

Sandbox run 4 (api_version 2024-09-27, Mode B) left two differences, both keys only the fake
returned: `trace_id` on the replayed conversion, and `created_at`, `global_account_id` and
`request_id` on the deposit create. Each canonical check of the fake is pinned to the key set,
HTTP status and status value the canon records, so a key added to the fake fails here until a
sandbox run shows it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "checks"))

import airwallex_live as live

CANON = json.loads((ROOT / "checks" / "airwallex_canon.json").read_text())


@pytest.fixture(scope="module")
def fake_pass() -> dict[str, live.Check]:
    run = live.ContractPass(live.fake_client({}), "keys", live.FAKE_BENEFICIARY).run()
    assert run.ok, [c.line() for c in run.checks if not c.ok]
    assert run.mode == CANON["mode"]
    return {c.name: c for c in run.checks}


def test_the_canon_names_every_diffed_check(fake_pass):
    shaped = {name for name, check in fake_pass.items() if check.shape is not None}
    assert set(CANON["checks"]) == shaped - live.RECORDED_ONLY


@pytest.mark.parametrize("name", sorted(CANON["checks"]))
def test_the_fake_answers_as_the_canon_records(fake_pass, name):
    want, got = CANON["checks"][name], fake_pass[name].shape
    assert (got.http, got.status, sorted(got.keys)) == (want["http"], want["status"],
                                                        want["keys"])


def test_a_replayed_conversion_carries_no_trace_id(fake_pass):
    assert "trace_id" not in fake_pass["fx-conversion-replay"].shape.keys


def test_a_deposit_create_carries_only_what_the_sandbox_returned(fake_pass):
    keys = fake_pass["advance"].shape.keys
    assert not keys & {"created_at", "global_account_id", "request_id"}


def test_the_deposit_list_still_finds_and_settles_the_created_deposit():
    client = live.fake_client({})
    usd = client.transport.global_accounts[0]["id"]
    deposit = client.simulate_deposit(amount=live.PAYOUT, global_account_id=usd,
                                      reference="keys-1")
    assert [d.provider_id for d in client.find_deposit("keys-1")] == [deposit.provider_id]
    assert client.wait_for_deposit(deposit.provider_id).status == "SETTLED"

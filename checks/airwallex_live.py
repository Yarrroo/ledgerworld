"""The Airwallex contract pass: the canonical requests run end to end, each a named check.

Usage: python checks/airwallex_live.py (--fake | --require-key) [--run-id ID]

The sequence is `canonical-requests.json` (design/modules/airwallex/fixtures/) driven through
`client_from_env` and the `AirwallexClient` methods only: login, balances, global accounts, the
connected-accounts probe, one FX quote and one conversion, the conversion replayed under the same
`request_id` (it must be rejected) and looked up (one), one payout, its replay and lookup, the
payout driven to `PAID` through the transition simulation, the advance leg of the probed mode
(Mode B: one simulated deposit into the USD Global Account and the balance read after it; Mode A:
one connected-account transfer), and a last count of one movement per `request_id`. Every check
prints PASS or FAIL with the provider id it touched.

- `--fake` runs the sequence on the fake transport. No credential is read.
- `--require-key` runs it on the sandbox (`AIRWALLEX_MODE` is forced to `sandbox`), then on the
  fake in the mode the sandbox probed, and diffs each answer's key set and status value. A
  status or HTTP difference, or a key the fake returns and the sandbox does not, fails the pass;
  a key only the sandbox returns is listed and does not. Without `AIRWALLEX_CLIENT_ID`,
  `AIRWALLEX_API_KEY` and `AIRWALLEX_BENEFICIARY_ID` (the sandbox test beneficiary) it exits 2
  naming the missing ones: it never fakes a pass. `AIRWALLEX_GLOBAL_ACCOUNT_ID` and
  `AIRWALLEX_CONNECTED_ACCOUNT_ID` pick those accounts when set.

Request ids are `canon-fx-<run>`, `canon-pay-<run>` and `canon-adv-<run>`, a fresh `<run>` per
invocation. Only key names, statuses, codes and provider ids are printed: never a value of an
answer, a token, a key or a bank detail. Exit 0 when every check passes, 1 on a failed check or a
failing difference, 2 on bad usage or configuration.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.connectors.airwallex.client import (
    LOGIN_PATH,
    PAYOUT_PATH,
    AirwallexClient,
    active_account,
    client_from_env,
    connected_setting,
    global_accounts_by_currency,
)
from app.connectors.airwallex.errors import (
    AirwallexError,
    ConfigError,
    DuplicateRequest,
    HostRefused,
)
from app.connectors.airwallex.fake import START
from app.connectors.airwallex.transport import CREDENTIAL_VARS
from app.finance.schemas import Money

BENEFICIARY_VAR = "AIRWALLEX_BENEFICIARY_ID"
GLOBAL_ACCOUNT_VAR = "AIRWALLEX_GLOBAL_ACCOUNT_ID"
CONNECTED_ACCOUNT_VAR = "AIRWALLEX_CONNECTED_ACCOUNT_ID"
REQUIRED_VARS = (*CREDENTIAL_VARS, BENEFICIARY_VAR)
FAKE_BENEFICIARY = START["beneficiaries"][0]["id"]

FX_BUY = Money(minor=1_000_000, currency="EUR")
PAYOUT = Money(minor=10_000, currency="USD")
ADVANCE = Money(minor=1_000_000, currency="USD")
TO_PAID = PAYOUT_PATH[1:]
# The probe path is assumed (canonical-requests.json): its answer is recorded, not diffed.
RECORDED_ONLY = frozenset({"connected-probe"})
# The minimum key sets of canonical-requests.json; both sides must carry them.
KEYS_MIN = {
    "login": {"token", "expires_at"},
    "balances": {"currency", "available_amount", "pending_amount"},
    "fx-quote": {"quote_id", "client_rate"},
    "payout": {"id", "request_id", "status"},
}


# ------------------------------------------------------------------------------ recording


@dataclass(frozen=True)
class Shape:
    """What a diff compares of one answer: its HTTP status, key names and status value."""

    http: int
    keys: frozenset[str]
    status: str | None


def shape_of(answer: Any) -> Shape:
    """Key names of an object, or of the items of a list; `status` (or the error `code`)."""
    body = answer.json
    items = body.get("items") if isinstance(body, dict) and "items" in body else body
    if isinstance(items, list):
        objects = [i for i in items if isinstance(i, dict)]
        keys = frozenset(k for i in objects for k in i)
        statuses = sorted({str(i["status"]) for i in objects if "status" in i})
        return Shape(answer.status, keys, ",".join(statuses) or None)
    if isinstance(body, dict):
        status = body.get("status", body.get("code"))
        return Shape(answer.status, frozenset(body), None if status is None else str(status))
    return Shape(answer.status, frozenset(), None)


class Recorder:
    """The client's transport, seen through: every answer is kept for its shape."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.answers: list[tuple[str, Any]] = []

    @property
    def mode(self) -> str:
        return self.inner.mode

    @property
    def credentials(self) -> Any:
        return self.inner.credentials

    def send(self, method: str, path: str, json: Any = None,
             headers: Mapping[str, str] | None = None) -> Any:
        answer = self.inner.send(method, path, json, headers)
        self.answers.append((path, answer))
        return answer

    def last(self, *, login: bool = False) -> Any | None:
        """The latest answer; a token renewal in between is skipped unless `login`."""
        for path, answer in reversed(self.answers):
            if login or path != LOGIN_PATH:
                return answer
        return None


# --------------------------------------------------------------------------------- checks


@dataclass
class Check:
    name: str
    ok: bool
    provider_id: str | None = None
    detail: str = ""
    shape: Shape | None = None

    def line(self) -> str:
        parts = ["PASS" if self.ok else "FAIL", self.name]
        if self.provider_id:
            parts.append(self.provider_id)
        if self.detail:
            parts.append(f"· {self.detail}")
        return " ".join(parts)


class Skipped(Exception):
    """A step whose input an earlier step failed to produce."""


@dataclass
class ContractPass:
    """The canonical sequence on one client; `run()` fills `checks` in order."""

    client: AirwallexClient
    run_id: str
    beneficiary_id: str
    setting: str = "auto"
    global_account_id: str | None = None
    connected_account_id: str | None = None
    checks: list[Check] = field(default_factory=list)
    mode: str | None = None
    state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.recorder = Recorder(self.client.transport)
        self.client.transport = self.recorder

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def run(self) -> ContractPass:
        steps: list[tuple[str, Callable[[], tuple[bool, str | None, str]]]] = [
            ("login", self.login),
            ("balances", self.balances),
            ("global-accounts", self.global_accounts),
            ("connected-probe", self.connected_probe),
            ("fx-quote", self.fx_quote),
            ("fx-conversion", self.fx_conversion),
            ("fx-conversion-replay", self.fx_conversion_replay),
            ("fx-conversion-lookup", self.fx_conversion_lookup),
            ("payout", self.payout),
            ("payout-replay", self.payout_replay),
            ("payout-lookup", self.payout_lookup),
            ("payout-to-paid", self.payout_to_paid),
            ("advance", self.advance),
            ("one-movement", self.one_movement),
        ]
        for name, step in steps:
            self._shape = None
            try:
                ok, provider_id, detail = step()
            except Skipped as missing:
                ok, provider_id, detail = False, None, f"skipped: no {missing}"
            # A failed check is reported and the pass goes on.
            except (AirwallexError, AttributeError, KeyError, TypeError, ValueError) as failed:
                ok, provider_id, detail = False, None, self._scrub(
                    f"{type(failed).__name__}: {failed}")
            self.checks.append(Check(name, ok, provider_id, detail, self._shape))
        return self

    # -------------------------------------------------------------------- helpers

    def _observe(self, *, login: bool = False) -> None:
        answer = self.recorder.last(login=login)
        self._shape = None if answer is None else shape_of(answer)

    def _need(self, key: str) -> Any:
        if key not in self.state:
            raise Skipped(key)
        return self.state[key]

    def _usd(self) -> int:
        return next((b.available.minor for b in self.client.balances() if b.currency == "USD"), 0)

    def _keys_min(self, name: str) -> str:
        missing = KEYS_MIN[name] - (self._shape.keys if self._shape else frozenset())
        return f"missing keys {', '.join(sorted(missing))}" if missing else ""

    def _scrub(self, text: str) -> str:
        creds = self.recorder.credentials
        for value in (creds.api_key, creds.client_id):
            if value:
                text = text.replace(value, "<hidden>")
        return text

    def _replay(self, create: Callable[[], Any], kind: str) -> tuple[bool, str | None, str]:
        try:
            second = create()
        except DuplicateRequest as rejected:
            self._observe()
            http = self._shape.http if self._shape else None
            state = "in flight" if rejected.in_flight else "already used"
            return True, None, f"rejected: http {http}, code {rejected.code}, {state}"
        self._observe()
        return False, second.provider_id, f"replay accepted: a second {kind} moved"

    def _lookup(self, found: list, first_key: str) -> tuple[bool, str | None, str]:
        self._observe()
        first = self._need(first_key)
        ids = [o.provider_id for o in found]
        ok = ids == [first.provider_id]
        return ok, ",".join(ids) or None, f"{len(ids)} found, first {first.provider_id}"

    # ---------------------------------------------------------------------- steps

    def login(self) -> tuple[bool, str | None, str]:
        self.client.login()
        self._observe(login=True)
        missing = self._keys_min("login")
        return not missing, None, missing or f"api_version {self.client.api_version}"

    def balances(self) -> tuple[bool, str | None, str]:
        found = self.client.balances()
        self._observe()
        currencies = ",".join(b.currency for b in found)
        missing = self._keys_min("balances")
        has_usd = any(b.currency == "USD" for b in found)
        return not missing and has_usd, None, missing or (
            currencies if has_usd else f"no USD balance in {currencies or 'none'}")

    def global_accounts(self) -> tuple[bool, str | None, str]:
        accounts = self.client.global_accounts()
        self._observe()
        # The account the gateway would take: the pinned one if it takes USD, else its pick.
        pinned = [a for a in accounts if isinstance(a, dict) and a.get("id") == self.global_account_id]
        wanted = global_accounts_by_currency(pinned if self.global_account_id else accounts)
        if "USD" not in wanted:
            return False, None, f"no USD global account among {len(accounts)}"
        self.state["global_account"] = wanted["USD"]
        return True, wanted["USD"], f"{len(accounts)} listed"

    def connected_probe(self) -> tuple[bool, str | None, str]:
        before = len(self.recorder.answers)
        self.mode = self.client.probe_connected(self.setting)
        if len(self.recorder.answers) > before:
            self._observe()
        listed = None
        if self.mode == "A" and self._shape is not None:
            listed = active_account(self.recorder.last().json)
        account = self.connected_account_id or listed
        if account:
            self.state["connected_account"] = account
        answer = f"http {self._shape.http}" if self._shape else "not probed"
        return True, account, f"mode {self.mode} (setting {self.setting}, {answer})"

    def fx_quote(self) -> tuple[bool, str | None, str]:
        quote = self.client.quote(sell_currency="USD", buy_currency="EUR", amount=FX_BUY)
        self._observe()
        quote_id = quote.get("quote_id") or quote.get("id")
        if quote_id:
            self.state["quote_id"] = quote_id
        missing = self._keys_min("fx-quote")
        return bool(quote_id) and not missing, quote_id, missing

    def _convert(self) -> Any:
        return self.client.create_conversion(
            f"canon-fx-{self.run_id}", sell_currency="USD", buy_currency="EUR", amount=FX_BUY,
            quote_id=self._need("quote_id"))

    def fx_conversion(self) -> tuple[bool, str | None, str]:
        conversion = self._convert()
        self._observe()
        self.state["conversion"] = conversion
        ok = conversion.status in ("SCHEDULED", "SETTLED")
        return ok, conversion.provider_id, f"status {conversion.status}"

    def fx_conversion_replay(self) -> tuple[bool, str | None, str]:
        self._need("conversion")
        return self._replay(self._convert, "conversion")

    def fx_conversion_lookup(self) -> tuple[bool, str | None, str]:
        self._need("conversion")
        return self._lookup(self.client.find_conversion(f"canon-fx-{self.run_id}"), "conversion")

    def _pay(self) -> Any:
        return self.client.create_transfer(
            f"canon-pay-{self.run_id}", beneficiary_id=self.beneficiary_id, amount=PAYOUT,
            reference="ledgerworld canon")

    def payout(self) -> tuple[bool, str | None, str]:
        self.state["usd_before_payout"] = self._usd()
        transfer = self._pay()
        self._observe()
        self.state["transfer"] = transfer
        missing = self._keys_min("payout")
        ok = transfer.status == "SCHEDULED" and not missing
        return ok, transfer.provider_id, missing or f"status {transfer.status}"

    def payout_replay(self) -> tuple[bool, str | None, str]:
        self._need("transfer")
        return self._replay(self._pay, "transfer")

    def payout_lookup(self) -> tuple[bool, str | None, str]:
        self._need("transfer")
        return self._lookup(self.client.find_transfer(f"canon-pay-{self.run_id}"), "transfer")

    def payout_to_paid(self) -> tuple[bool, str | None, str]:
        transfer = self._need("transfer")
        # The sandbox moves a payout on by itself; a step it already took is read back as made.
        try:
            for status in TO_PAID:
                self.client.simulate_transition(transfer.provider_id, status)
        except AirwallexError as failed:
            self._observe()
            return False, transfer.provider_id, self._scrub(
                f"to {status}: {type(failed).__name__}: {failed}")
        final = self.client.get_transfer(transfer.provider_id)
        self._observe()
        delta = self._usd() - self.state["usd_before_payout"]
        ok = final.status == "PAID" and delta == -PAYOUT.minor
        return ok, final.provider_id, f"status {final.status}, USD moved {delta} minor"

    def advance(self) -> tuple[bool, str | None, str]:
        if self.mode is None:
            raise Skipped("probed mode")
        if self.mode == "A":
            destination = self._need("connected_account")
            moved = self.client.connected_account_transfer(
                f"canon-adv-{self.run_id}", amount=ADVANCE, destination=destination)
            self._observe()
            ok = moved.status not in ("FAILED", "CANCELLED")
            return ok, moved.provider_id, f"mode A, status {moved.status}"
        before = self._usd()
        deposit = self.client.simulate_deposit(
            amount=ADVANCE, global_account_id=self._need("global_account"),
            reference=f"advance inflow (sandbox simulation) canon-{self.run_id}")
        self._observe()  # compare this create, not the final page of unrelated deposits
        deposit = self.client.wait_for_deposit(deposit.provider_id)
        delta = self._usd() - before
        ok = deposit.status == "SETTLED" and delta == ADVANCE.minor
        return ok, deposit.provider_id, (
            f"mode B, status {deposit.status}, USD moved {delta} minor, "
            "amount sent as a JSON number: accepted")

    def one_movement(self) -> tuple[bool, str | None, str]:
        transfers = self.client.find_transfer(f"canon-pay-{self.run_id}")
        conversions = self.client.find_conversion(f"canon-fx-{self.run_id}")
        ok = len(transfers) == 1 and len(conversions) == 1
        return ok, None, f"{len(transfers)} transfer, {len(conversions)} conversion"


# ----------------------------------------------------------------------------------- diff


def diff(sandbox: ContractPass, fake: ContractPass) -> tuple[list[str], list[str]]:
    """Failing differences and listed-only ones, per check both sides answered; the probe's
    answer is recorded, never failed (any refusal there means Mode B)."""
    failing, listed = [], []
    fakes = {c.name: c.shape for c in fake.checks}
    for check in sandbox.checks:
        real, double = check.shape, fakes.get(check.name)
        if real is None or double is None:
            continue
        if check.name in RECORDED_ONLY:
            if real != double:
                listed.append(f"{check.name}: sandbox answered http {real.http} {real.status}, "
                              f"fake http {double.http} {double.status}")
            continue
        if real.http != double.http:
            failing.append(f"{check.name}: http sandbox {real.http}, fake {double.http}")
        # A status only one side carries is a key difference, reported below.
        initial_deposit = (check.name == "advance" and sandbox.mode == fake.mode == "B"
                           and {real.status, double.status} <= {"PENDING", "SETTLED"})
        if None not in (real.status, double.status) and real.status != double.status \
                and not initial_deposit:
            failing.append(f"{check.name}: status sandbox {real.status}, fake {double.status}")
        if invented := sorted(double.keys - real.keys):
            failing.append(f"{check.name}: only the fake returns {', '.join(invented)}")
        if lacking := sorted(real.keys - double.keys):
            listed.append(f"{check.name}: only the sandbox returns {', '.join(lacking)}")
    return failing, listed


# ----------------------------------------------------------------------------------- main


def print_pass(title: str, run: ContractPass) -> None:
    print(f"== {title} · mode {run.client.mode} · api_version {run.client.api_version} "
          f"· run {run.run_id}")
    for check in run.checks:
        print(check.line())
    passed = sum(c.ok for c in run.checks)
    print(f"{passed}/{len(run.checks)} PASS")


def fake_client(env: Mapping[str, str], *, connected: bool = False) -> AirwallexClient:
    fake_env = {"AIRWALLEX_MODE": "fake"}
    if env.get("AIRWALLEX_API_VERSION"):
        fake_env["AIRWALLEX_API_VERSION"] = env["AIRWALLEX_API_VERSION"]
    return client_from_env(fake_env, connected=connected)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--fake", action="store_true", help="run on the fake transport")
    which.add_argument("--require-key", action="store_true",
                       help="run on the sandbox and diff against the fake")
    parser.add_argument("--run-id", help="the <run> in the request ids (default: fresh)")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    run_id = args.run_id or f"{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"

    try:
        if args.fake:
            run = ContractPass(fake_client(env), run_id, FAKE_BENEFICIARY).run()
            print_pass("fake", run)
            return 0 if run.ok else 1

        missing = [name for name in REQUIRED_VARS if not env.get(name, "").strip()]
        if missing:
            print(f"--require-key needs {', '.join(missing)}; no pass without them",
                  file=sys.stderr)
            return 2
        setting = connected_setting(env)
        sandbox = ContractPass(
            client_from_env({**env, "AIRWALLEX_MODE": "sandbox"}), run_id,
            env[BENEFICIARY_VAR].strip(), setting,
            env.get(GLOBAL_ACCOUNT_VAR, "").strip() or None,
            env.get(CONNECTED_ACCOUNT_VAR, "").strip() or None,
        ).run()
        fake = ContractPass(fake_client(env, connected=sandbox.mode == "A"), run_id,
                            FAKE_BENEFICIARY, setting).run()
    except (ConfigError, HostRefused) as refused:
        print(f"configuration refused: {refused}", file=sys.stderr)
        return 2

    print_pass("sandbox", sandbox)
    print_pass("fake", fake)
    failing, listed = diff(sandbox, fake)
    print(f"== diff · {len(failing)} failing, {len(listed)} listed")
    for line in failing:
        print(f"FAIL diff {line}")
    for line in listed:
        print(f"NOTE diff {line}")
    return 0 if sandbox.ok and fake.ok and not failing else 1


if __name__ == "__main__":
    sys.exit(main())

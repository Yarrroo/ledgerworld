# airwallex — the provider connector

Tasks: T12 (adapter: transports, fake sandbox, key switch) · T15 (sandbox arrives: live contract pass, fake corrections).
Read with `00-system.md` §10 and the research note `research/airwallex-sandbox-semantics.md` in the design. The connector is the only code that speaks the provider's protocol. It decides nothing about money: it builds requests from `Money`, sends them, and returns typed results. What to do with an unknown outcome is the gateway's job (execution module).

Three rules this module exists to keep:
- **A replayed `request_id` is rejected, not answered.** The provider returns `duplicate_request_id` (`request_id_duplicate` on connected-account transfers), or `409` while the first call is in flight. The fake behaves the same way. The original object is found by list-by-`request_id`.
- **The client never repeats a POST after a timeout or a 5xx.** That outcome is `OutcomeUnknown`. A `429` or a `401` is a rejection (nothing moved), so the client retries it itself with the same `request_id`.
- **The fake is the provider's double, not a convenience.** Every behaviour the gateway tests rely on is pinned in `fixtures/`, and T15 diffs the fake against the sandbox on the requests in `canonical-requests.json`.

## Interfaces

| Unit | File | Shape | Notes |
|---|---|---|---|
| `select_transport(env)` | `backend/app/connectors/airwallex/transport.py` | `→ FakeTransport \| LiveTransport` | `AIRWALLEX_MODE` = fake (default) \| sandbox. A key alone never flips the mode. `sandbox` without a key raises `ConfigError` naming the variables. (`switch-and-hosts.json`) |
| `Transport.send` | `transport.py` | `(method, path, json?, headers) → Response{status, json, headers}` | Raises `TransportTimeout(after_send: bool)`. The fake can raise either; the live transport reports `after_send=true` once the body has been written. |
| `LiveTransport` | `live.py` | httpx; base URL from `AIRWALLEX_BASE_URL` | Allowlist: the parsed host must equal `api.sandbox.airwallex.com` over https, or `HostRefused`. Never imported by a simulation process. Not exercised by merge-gate tests. |
| `FakeTransport(scenario, seed, clock, connected)` | `fake.py` | in-memory state: balances, global accounts, beneficiaries, quotes, conversions, transfers, deposits | Serves every path in `canonical-requests.json`, including the two simulation endpoints and list-by-`request_id`. Scenarios: `happy, timeout_after_accept, timeout_before_send, insufficient_funds, rate_limited, auth_fail, server_error, malformed_body`. A fixed FX rate per seed. |
| `AirwallexClient(transport, clock)` | `client.py` | `login · balances · global_accounts · probe_connected · quote · create_conversion · find_conversion · create_transfer · get_transfer · find_transfer · connected_account_transfer · charge · simulate_deposit · simulate_transition` | Amount arguments are `Money`. Wire amounts come from `to_provider_decimal` (ledger module); `simulate_deposit` sends the same decimal as a JSON number (`Decimal`, never float). Sends `x-api-version` from `AIRWALLEX_API_VERSION` (default `2024-09-27`). Token cached until expiry minus 60 s. |
| `leg_plan(mode)` | `client.py` | `mode A\|B → {advance, repayment, fx, payout} → operation + receipt label` | From `leg-mapping.json`. The mode is chosen once at start by `probe_connected()` under `AIRWALLEX_CONNECTED=auto\|on\|off` and exposed on `/api/v1/health`. |
| errors | `errors.py` | `ConfigError · HostRefused · ProviderError(code, http, retryable, outcome=rejected) · DuplicateRequest(request_id, in_flight) · OutcomeUnknown(request_id)` | A message never contains the key, the token or the webhook secret. Unknown 4xx codes stay verbatim. (`errors.json`) |
| contract pass | `checks/airwallex_live.py`, `checks/airwallex_canon.json`, `docs/airwallex-contract.md` | T15 | `--require-key`: run the canonical sequence on fake and sandbox and diff. The canon file is generated from `canonical-requests.json`. |

Webhook verification lives in the execution module (`webhooks.py`, owned by T13); the connector only exposes `get_transfer` and `find_*`, which reconciliation treats as the truth.

## Data

- The connector owns no tables. Provider ids, request ids and raw receipts are stored by the gateway's outbox (execution module), keyed by `leg_id`.
- `request_id` = the leg id: `<plan_hash[:12]>-<leg index>-<kind>`. It is deterministic, so a crash and restart reuse the same id. The same id is never reused for a different leg.
- Statuses used, for API version 2024-09-27:
  - transfer `SCHEDULED → PROCESSING → SENT → PAID`, with `OVERDUE`, `FAILED` (reachable even after `PAID`), `CANCELLATION_REQUESTED`, `CANCELLED`;
  - conversion `SCHEDULED → SETTLED`, with `OVERDUE`, `CANCELLED`.
  - Approval statuses are out of scope.
- Receipt shape (inside C4): `{provider_id, request_id, kind, status, amount (provider string), currency, label, mode, raw_keys[], observed_at}`. `label` comes from `leg_plan`.
- The fake's start state comes from the fixture (`fake-lifecycles.json` `start`). Its FX rate is per seed and documented as fake; a live rate never enters a test.
- The LF-2 advance moves the principal only (10,000.00). The 800.00 fee is a ledger journal and never a provider movement.

## Fixtures

| File | Drives | What it pins |
|---|---|---|
| `fixtures/switch-and-hosts.json` | T12 | 6 environment rows for the switch; 5 hosts (production, plain http and a suffix trick refused); headers; token renewal at 1,740 s; the secret-sentinel probe |
| `fixtures/fake-lifecycles.json` | T12 | transfer edges and 4 paths, including PAID → FAILED → CANCELLED with funds returned and a skipped transition refused; conversion 2 paths with balance effects; the deposit simulation's numeric amount |
| `fixtures/idempotency.json` | T12, T15 | 8 cases: replay after settle, in flight (409), same id with another amount, conversion replay, the old spelling, timeout after accept, timeout before send (retry with the same id), 429; a property test of at most one transfer per id |
| `fixtures/errors.json` | T12 | 13 scenarios mapped to ok / rejected / rejected_duplicate / retried / unknown, and three things that never happen |
| `fixtures/leg-mapping.json` | T12, T15 | the probe matrix (an unclear probe never selects Mode A; forcing A without it fails at start); the four legs in each mode with their receipt labels; the LF-2 advance on the wire |
| `fixtures/canonical-requests.json` | T15 | 14 requests in order, each marked docs or assumed, with the minimum key sets; replays rejected and found by lookup; one payout driven to PAID; the Mode B deposit; what the contract doc records |

## Failure modes

| Failure | Where it bites | Guard |
|---|---|---|
| The fake returns the original on a replayed id | gateway tests pass; the real gateway breaks on its first retry | the fake rejects; `idempotency.json` `replay-after-settle` |
| The client retries a POST after a timeout | a second transfer if the provider's dedupe window or id differs | `OutcomeUnknown`, never retried; `errors.json` `never` |
| A retry under a fresh id after a duplicate | money moves twice | `DuplicateRequest` carries the id; the gateway looks up, never re-mints |
| A key appearing flips to the live provider | an accidental real call from a dev box or test | the mode flips only on `AIRWALLEX_MODE=sandbox`; `key-without-mode` |
| A host check by substring | a request to a look-alike host carrying the token | parse the host and compare exactly; the suffix-trick row |
| `PAID` treated as final | the ledger settles a payout that later fails | reconciliation reads `GET`; `paid-then-failed` path |
| An unclear connected-account probe read as yes | the demo claims a lender disbursement that never happened | a 5xx probe → Mode B; Mode B labels on every receipt |
| A float in a body | a cent lost on the wire | `Money` in, converter out; `Decimal` for the simulation number |
| An unpinned API version | status names change under us (CANCELLATION_REQUESTED vanishes after 2025-06-30) | `x-api-version` on every call; the contract doc records it |
| The key in an exception or trace | a secret in a log or the demo recording | the sentinel probe in `switch-and-hosts.json` |
| An unknown error code mapped to a known one | a wrong retry decision | unknown 4xx stays verbatim, classed rejected |
| The canon run uses a real beneficiary's details in the contract doc | personal data in a public repo | ids only; `canonical-requests.json` `never` |

## Done-whens

- accept: uv run pytest -q tests/connectors/test_airwallex_fake.py — fixture: fixtures/switch-and-hosts.json
- accept: uv run pytest -q tests/connectors/test_airwallex_fake.py — fixture: fixtures/fake-lifecycles.json
- accept: uv run pytest -q tests/connectors/test_airwallex_fake.py — fixture: fixtures/idempotency.json
- accept: uv run pytest -q tests/connectors/test_airwallex_fake.py — fixture: fixtures/errors.json
- accept: uv run pytest -q tests/connectors/test_airwallex_fake.py — fixture: fixtures/leg-mapping.json
- accept: uv run python checks/airwallex_live.py --require-key — fixture: fixtures/canonical-requests.json

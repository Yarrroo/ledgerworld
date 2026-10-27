# A committed obligation paid after its deadline is unmet — Close-out
> Close-out (/dev-close). Source: cross-family review of T11 (policy comparison), finding on
> `feasibility.py:139-140` (assessment falls back to the final state when the obligation-named
> journal is absent).
> Date: 2026-10-27

## What shipped
- `_paid_round` (`backend/app/decisions/feasibility.py`) dates an obligation's payment by its own
  `settle:<obligation>` journal or, when a reservation backs it, by the settled flow's
  `settle:<flow>` journal, whichever is earliest. `assess` judges it met only when that journal
  falls in its due round or earlier.
- Root cause: an obligation whose reservation was committed before it fell due (a snapshot's
  committed `pending_out`, or any commit ahead of `settle_due`) is paid when its flow lands, under
  the flow's journal. The lookup searched only the obligation-named journal, found nothing, and
  fell back to `state == "met"`, which `settle_flow` sets however late the flow landed.
- The fallback to the ledger's state stays for an obligation whose payment no `settle:` journal
  names: met before the ledger opened (a snapshot), or settled under a journal id its caller
  chose (the execution gateway's `j-<leg>`).
- An unmet obligation's `short_minor` is clamped at 0: a late payment from cash that was there is
  unmet with nothing short, never a negative shortfall.
- Docs: the module docstring states the rule and the clamp.

## Verification
- Reproduced on 03b060c: an obligation due at t=12, paid through its committed reservation at
  t=20, assessed `met=True`.
- `tests/decisions/test_feasibility.py`: on-time (t=12) and late (t=20) committed-flow payments,
  the late one unmet with `short_minor 0` (failed before the fix); a payment under a caller-named
  journal falls back to the state (failed before the vet round-1 fix).
- `uv run pytest -q tests/decisions tests/api/test_api_v1.py tests/hunt/test_money_safety.py`:
  175 passed, 1 xfailed. ruff clean; `checks/no_secrets.py`, `checks/attribution.py` ok. The
  full gate is the landing train's.
- Vet: T2 (money flag cleared to an assessment read), 2 rounds, converged; 7 findings, 2 applied
  (1 proven by a test, 1 docstring), 5 recorded.

## Recorded, not changed
- An obligation reopened after its payout failed (`reconcile.reopen_failed_payouts`) keeps its
  journal; the gateway names it `j-<leg>`, so the state (`open`) decides and it reads unmet.
- Two queries per obligation in `assess`; obligations per branch are few, and `bounded_id`
  hashes in Python, so the flow lookup does not fold into one SQL statement.

## Follow-ups / known gaps
- `later` (the reservations backing later obligations) subtracts reservations already settled
  or released by the due round, which can overstate an unmet obligation's `short_minor`.
  Predates this change.
- Journals carry no link to the flow they settle, so the payment is found by journal name. A
  flow id on the journal (a schema change) would remove the name lookup and the fallback.
- The review report named on the card was not in this checkout; the finding was taken from the
  card's text.

# T05 · revenue-based advances and lender capacity — Close-out
> Close-out. Source: briefs/T05.md ← design/modules/ledger/HANDOFF.md ← 00-system.md §6.
> Date: 2026-10-27

## What shipped
- `backend/app/finance/contracts.py`: the contract terms as integer functions (`fee_minor`,
  `repayment_minor`, rounding down) and `register`/`load`, which turn each C5 contract into a
  `facilities` row plus a lender receivable `<pool>/loan:<id>`. Outstanding is that receivable's
  balance, never a column.
- `backend/app/finance/lending.py`: `capacity` (K_p and its five parts, authority), `check_draw`,
  `disburse` (whole principal, within K_p and the source account's S and floor headroom),
  `draw_line` (a committed line drawn from its hold, K_p unchanged), `observe_revenue` and
  `repay` (a share of observed revenue, capped at outstanding, once per period).
- Wiring: `ledger.from_snapshot` now registers every snapshot contract (one line).
- `tests/finance/test_lending.py`: LF-2 from `fixtures/lf2_lender.json` (42,000 → 27,000, the
  30,000 draw refused naming `K_p = 27,000.00`, the 30,000 draw accepted without stress, the
  committed-line draw, weeks 1–4) and `advance-journals.json` posting by posting.
- `checks/required.json`: g1 ids for `lf2_reproduction` and `draw_beyond_kp_rejected`.
- `design/modules/ledger/HANDOFF.md`: the three lending rows now state the signatures that
  shipped (store-first, `repay` by period, `draw_line`, `obligations_due` as a fifth part).

## Verification
- `uv run pytest -q tests/finance/test_lending.py`: 34 passed.
- `tests/finance tests/fixtures tests/contracts tests/test_skeleton.py checks/tests tests/execution
  tests/simulation`: 372 passed, 6 skipped (`pg`/`live`).
- ruff on new code, `checks/no_secrets.py`, `checks/attribution.py`: green.
- `checks/kpi.py g1 --print`: 50 at 09592d1, 62 here (10 of 16 g1 checks).
- Vet: T3 (money surface), 2 rounds, 0 open. Round 1 (`/code-review high`, `/simplify` inline,
  `/security-review`: none): 11 findings, 9 applied (6 correctness, each with a test that fails
  on 0098a40), 2 recorded. Round 2 (`/code-review medium` on the fixes): 10 findings, 6 applied
  (each with a test that fails on ea7ce32), 4 recorded. The recorded ones and why are under
  Follow-ups below.

## Docs updated
- Module docstrings carry the rules (K_p formula, committed vs discretionary, observed revenue
  only). HANDOFF rows as above. No README or CLAUDE.md change: no command or workflow changed.

## Follow-ups / known gaps
- K_p follows §6's formula, so a held reservation that is neither a line's hold nor an
  obligation (e.g. a snapshot's `<account>:reserved` remainder) is not subtracted. A disbursal
  is still gated on the source account's S, so no held unit moves; but a planner reading K_p
  sees more than is free. Changing the formula is the brief's call (§6 [DEFAULT]).
- Nothing calls `disburse`, `draw_line` or `repay` yet: the coordinator's clearing of the
  `disburse`/`repay` intents, `GET /api/v1/lending` (`schemas.Capacity`, `FacilityView`) and the
  gateway's advance leg are later tasks. `capacity` and the three writes are their entry points.
- A collateral facility registers its limit only; `advance_rate_bps` and `collateral_ref` are
  T21's (the `facilities` table has no column for them).
- `Mode` in `lending.py` repeats `Journal.mode`'s Literal; a shared alias belongs in
  `models.py`.
- `capacity` reads one receivable sum per active line (few per pool), and a draw's default id
  comes from the store's `_next_id` (a count per call).
- `contracts.py` uses the store's private `_naive` and `_sum`; public names for them belong in
  `store.py` (T04's file).
- A line hold smaller than the line's undrawn part (a short snapshot `reserved` bucket) is
  consumed by the first draw; the shortfall was never held, and K_p subtracts the full undrawn.

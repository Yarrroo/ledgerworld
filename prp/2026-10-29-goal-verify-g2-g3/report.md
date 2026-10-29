# Goal verification — g2 (the world is coupled) and g3 (it executes for real, sandbox)

Run 2026-10-29 on `6dd7657`, board item 147. Re-measures the 2026-10-28 pass
(`prp/2026-10-28-goal-verify-g2-g3/report.md`) on today's tree.

| goal | verdict | KPI reading | receipts |
|---|---|---|---|
| g2 | **verified** | `coupling_checks_pct` 100 / 100 | `python3 checks/kpi.py g2` → `g2 coupling_checks_pct 100`; `var/kpi/g2.xml` holds 246 testcases, 0 failed, errored or skipped, over the 8 required checks |
| g3 | **partial** | `demo_checkpoints_live` 3 / 3 | fresh sandbox run `demo-20261029T033816Z-9a3e` (`scripts/demo.sh --mode sandbox`, scripted agents, Mode B) → `checks/demo_receipt.py var/demo/live.json --require-live` → `ok · live checkpoints 3/3`; `python3 checks/kpi.py g3` → `3`; advance `27ef9051-…` SETTLED, payout `41aecb43-…` PAID, both reconciled, 0 incidents; the committed `docs/evidence/sandbox-receipt.json` still passes `--require-live` 3/3 |

The sandbox run walks the coupling claim end to end: the round-3 rumour post lowers the lender's
K_p (42,000 → 30,000 / 20,000), three sibling branches fork from round 2 (fresh, not cached, 16
rounds) and end apart — no-action and fixed-reserve breach the floor by 10,000.00 at t = 40 h,
integrated holds — and the approval executes only the integrated plan's two legs. The coupled path
is reachable from the app: `POST /api/v1/runs/<id>/fork`, `GET /decisions/<id>`,
`POST /approvals`, `POST /executions` (`backend/app/api/v1/routes.py`), called from
`frontend/src/views/Execution.vue` and `Lending.vue`.

## What the green readings hide (g3 gaps)

1. **The public deployment runs the fake provider.** `deploy/host.toml` sets
   `AIRWALLEX_MODE = "fake"`; README says "simulated provider until the sandbox keys land". The
   sandbox keys exist and drove today's run; arming the deploy is the owner's call. Until then g3
   holds for the command-line demo only.
2. **The sandbox demo needs a beneficiary id nobody stores.** `--mode sandbox` refuses without
   `--beneficiary`; the id is in no doc, `.env.example` or secret store, only in earlier session
   logs. Proposed fix: name `AIRWALLEX_BENEFICIARY_ID` in `.env.example` and let `demo.sh` read it.
3. **The KPI is machine-local.** g3 reads 0 in any fresh checkout: `var/demo/live.json` is
   untracked, so the reading is as fresh as the last sandbox run on the measuring machine.

## Not checked

- The public URL: not reachable from the verifying machine, so the deployed surface was not walked.
- The verdict write: recording it on the board is outside this checkout. The verdicts to record
  are the table above — g2 verified with its two receipts; g3 partial with gaps 1 and 2.

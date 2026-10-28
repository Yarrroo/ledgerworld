# Goal verification — g2 (the world is coupled) and g3 (it executes for real, sandbox)

Run 2026-10-28 on `236c85b`, board item 117.

| goal | KPI | reading | target | evidence |
|---|---|---|---|---|
| g2 | `coupling_checks_pct` | **100** | 100 | `python3 checks/kpi.py g2` → `g2 coupling_checks_pct 100`; the junit report holds 246 testcases, 246 passed, over the 8 required checks (tools 58 ids, shock 13, rollback 12, isolation 23, replay 11, six families 19, grounded report 37, read-only interview 8) |
| g3 | `demo_checkpoints_live` | **3** | 3 | fresh sandbox run `demo-20261028T035814Z-1c8b` (`scripts/demo.sh --mode sandbox`, scripted agents, Mode B): `checks/demo_receipt.py var/demo/live.json --require-live` → `ok · live checkpoints 3/3`; `python3 checks/kpi.py g3` → `3`. Advance `609be66f-…` SETTLED, payout `02302dfa-…` PAID, both reconciled, 0 incidents. The committed receipt `docs/evidence/sandbox-receipt.json` still passes `--require-live` 3/3 |

The same sandbox run walks the coupling claims end to end: the rumour post at round 3 lowers the
lender's K_p (45,000 → 30,000 / 20,000), the three sibling branches fork from round 2 and end
apart (two infeasible, the integrated plan feasible), and the approval executes only the
integrated plan's two legs.

## Gaps

1. **Fixed here.** `docs/airwallex-contract.md` said the 2026-10-27 receipt "stays in
   `var/demo/`", though it is committed as `docs/evidence/sandbox-receipt.json`. It now cites the
   file and records today's re-run; `checks/tests/test_sandbox_evidence.py` holds it.
2. **Open, not code.** The public deployment runs the fake provider (`deploy/host.toml`
   `AIRWALLEX_MODE = "fake"`), and README says "simulated provider until the sandbox keys land".
   The keys exist (both sandbox runs used them); arming the deploy with them is the owner's call.
   Until then g3 holds for the command-line demo only, which the docs already say.
3. **Not checked.** The public URL is not reachable from the verifying pane, so the deployed
   surface was not walked.
4. **By design.** g3 reads 0 in any fresh checkout: its receipt `var/demo/live.json` is
   untracked. The reading is only as fresh as the last sandbox run on the measuring machine.

`pocket-pm goal verify` is owner-only from a worker pane; record g2 and g3 from this file.

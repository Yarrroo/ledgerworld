# Fixtures LF-1 and LF-2 — the money truth

Two small synthetic worlds every money test checks against. Each file is a C5 snapshot
(`contracts/c5_snapshot.schema.json`) plus an `expected` block; LF-2 also carries the same snapshot
under the venue freeze in `stressed.venue_freeze`. Amounts in the files are USD minor units
(`7000000` = 70,000.00); below they are written in dollars. `t` is simulated hours from
`t0 = 2026-01-05T00:00Z`, horizon 72 h. `tests/fixtures/test_fixture_data.py` re-derives every
number below from the snapshot without the ledger engine.

- **S(t)** spendability = settled − reserved − pledged − Σ all pending_out + Σ pending_in arriving ≤ t
- **P(t)** projected cash = settled + Σ pending_in arriving ≤ t − Σ pending_out due ≤ t − Σ obligations due ≤ t
- The reserve floor is checked on **P** over the horizon; headroom(now) = min P(t) − floor.

## LF-1 · treasury (`lf1_treasury.json`, borrower-a)

Settled 70,000 · reserved 50,000 (the payroll hold) · floor 30,000 · receivable 20,000 at t=12 ·
venue withdrawal 15,000 at t=48 · payroll 50,000 due t=40.

| | line by line | result |
|---|---|---|
| S(0) | 70,000 − 50,000 | 20,000 |
| S(12) = S(40) | 20,000 + 20,000 | 40,000 |
| S(48) = S(72) | 40,000 + 15,000 | 55,000 |
| P(0) = P(11) | 70,000 | 70,000 |
| P(12) = P(39) | 70,000 + 20,000 | 90,000 |
| P(40) | 90,000 − 50,000 (withdrawal lands after the deadline, not counted) | 40,000 |
| P(48) = P(72) | 40,000 + 15,000 | 55,000 |
| min P, headroom(0) | 40,000 at t=40; 40,000 − 30,000 | 10,000 → **feasible** |

**Shock: receivable delayed 240 h** (arrives t=252, past the horizon)

| | line by line | result |
|---|---|---|
| P(0) = P(12) | 70,000 | 70,000 |
| P(40) | 70,000 − 50,000 | 20,000 |
| P(48) | 20,000 + 15,000 | 35,000 |
| breach | 30,000 − 20,000 at t=40 | **short 10,000** |

**Integrated plan: advance 10,000 arriving t=16 (deadline t=18)** on the shocked world

| | line by line | result |
|---|---|---|
| P(16) | 70,000 + 10,000 | 80,000 |
| P(40) | 80,000 − 50,000 = 30,000 = floor (kept: the floor holds when ≥) | **feasible** |
| P(48) | 30,000 + 15,000 | 45,000 |

**Rejections at t=0** (S(0) = 20,000, headroom(0) = 10,000)

| intent | check | verdict |
|---|---|---|
| pay 80,000 | 80,000 > S(0) 20,000 | rejected `insufficient_spendable` |
| pay 20,000 | ≤ S(0), but P(40) = 40,000 − 20,000 = 20,000 < 30,000 | rejected `breaks_floor` |
| pay 10,000 | P(40) = 40,000 − 10,000 = 30,000 = floor | accepted |
| pledge 5,000 of `lot-1` twice | same `collateral_ref` | 1st accepted, 2nd rejected `already_pledged` |
| no action | payroll-1 stays open to t=40, then settles from its reservation | never removed |

## LF-2 · lender pool (`lf2_lender.json`)

Operating 45,000 (of which 10,000 reserved for line-b) · venue 15,000 · line-b to borrower-b:
limit 10,000, drawn 0 · pool floor 8,000 · no pool obligations · advance adv-a to borrower-a:
principal 10,000, fee 800 bps, repayment 1,500 bps of observed weekly revenue.

K_p = settled of known accounts − committed undrawn − pledged − pool obligations − floor

| | line by line | result |
|---|---|---|
| K_p before | (45,000 + 15,000) − 10,000 − 0 − 0 − 8,000 | **42,000** |
| K_p under venue freeze | 45,000 − 10,000 − 0 − 0 − 8,000 (venue `unknown`, not zero; authority reduced) | **27,000** |
| draw 30,000 under stress | 30,000 > 27,000 | rejected `beyond_capacity`, binding `K_p = 27,000.00` |
| draw 30,000, no stress | 42,000 − 30,000 | accepted, K_p 12,000 |
| line-b draw 10,000 | settled −10,000 and undrawn −10,000 together | K_p stays 42,000 |

**Advance and repayment** (repayment = ⌊revenue × 15 %⌋, capped at outstanding)

| step | line by line | repayment | outstanding |
|---|---|---|---|
| disburse | fee 10,000 × 8 % = 800; owed 10,000 + 800; K_p 42,000 − 10,000 = 32,000 | — | 10,800 |
| week 1 | observed 24,000 × 15 % | 3,600 | 7,200 |
| week 2 | forecast 30,000, nothing observed → 0 (forecast is never used) | 0 | 7,200 |
| week 3 | observed 3,333.33 × 15 % = 499.9995 → 499.99 (rounded down) | 499.99 | 6,700.01 |
| week 4 | observed 100,000 × 15 % = 15,000, capped at outstanding | 6,700.01 | 0 |

## Coupling

LF-1's 15,000 withdrawal (`wd-1`) and LF-2's 15,000 venue account sit at the same
`exchange-venue` (exposure `venue-1` in both): one venue freeze reaches both worlds.

## Sources

The `expected` and `definitions` blocks are copied unchanged from the ledger design fixtures
(`prp/2026-10-20-ledgerworld/design/modules/ledger/fixtures/lf1-treasury.json`,
`lf2-lender.json`); the snapshots equal the C5 examples `contracts/examples/c5_snapshot/valid-lf1.json`,
`valid-lf2.json` and `valid-lf2-venue-freeze.json`. The tests fail if either drifts.

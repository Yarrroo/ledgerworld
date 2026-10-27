# Branch / replay / scenario-family reference model — findings

`refmodel/branch_ref.py` (stdlib only), checked by `python -m unittest discover -s refmodel -p test_branch_ref.py`
(30 tests, green). Fixtures `branch-isolation.json`, `scenario-families.json`, `coupled-chain.json`,
`actors.json`, `lf1-treasury.json` are read unchanged (the suite fails if their bytes change).

## Reproduced

| Expectation | Value |
|---|---|
| checkpoint after round 3 holds all 9 listed items | yes; clocks (3, 3), queue empty, round-3 C2 pending |
| sibling read / write of `world/w1/branch/no-action` from `integrated` | raises `NamespaceViolation` |
| own read, `integrated` | `asked for 12,000.00` |
| parent record written after the checkpoint, read by a new fork | not visible (pinned records) |
| fork vs clean continuation | same round-4 observation hashes; `p-r3-1` and each round-3 C2 delivered once |
| parent after both forks reach round 6 | ledger, SQLite and memory hashes equal the checkpoint |
| K_p at round 5 | no-action 4,200,000 · integrated 3,000,000 |
| coupled chain in `integrated` | intents, evidence, lender 3,300,000 / 1,500,000, five-link trace as fixture |
| replay of `integrated` (strict ScriptedModel from transcript) | journals byte-identical, same ledger and SQLite hash, `replay=true` everywhere |
| delayed-receipt | P(40) 2,000,000, breach 1,000,000; after the advance P(40) 3,000,000 = floor (LF-1 integrated plan) |
| confidence-rumour | borrower-c `request_advance` r4, K_p 3,000,000 |
| stablecoin-depeg | `defer`; no loss before settlement; settles r10 at 0.98: 1,470,000, loss 30,000 |
| borrower-silence | lender `release` of line-b; installment `unpaid`, paid `None`, no zero posting |
| redemption-spike | lender `release` of an offer; K_p 3,700,000 → 2,200,000 (−1,500,000) |
| fx-gap | `convert` quoted at 1.1100: −1,110,000 USD, +1,000,000 EUR |
| every family | ≥1 cleared financial action in 3 rounds; same seed → same journals and transcript |

Mutation check: dropping RNG restore, pending-C2 restore, the event cursor, pinned memory, or the
namespace guard each turns the suite red.

## Mismatches and gaps (severity · confidence)

1. **Transcript cannot replay memory** (medium · high). The HANDOFF transcript row has no actor
   memory writes; memory is in every observation, so a replay from that schema alone diverges at the
   first round after a write. The model records `memory` per entry. T09 needs the same field.
2. **No namespace for a replay** (medium · high). `world/<id>/branch/<id>` has no slot for a replay of
   an existing branch; replaying into the live namespace duplicates its records. The model replays
   into its own store.
3. **fx-gap conversion breaks the LF-1 floor rule** (medium · high). At 1.11, buying 1,000,000 EUR costs
   1,110,000 USD > headroom(0) 1,000,000; under LF-1's discretionary-outflow rule it clears as
   `breaks_floor` (P(40) 2,890,000 < 3,000,000), since the EUR obligation is not in USD P. The
   cross-currency floor rule is unspecified; the model checks only S for `convert`.
4. **Offers vs K_p** (medium · medium). HANDOFF says the lender "committed when it offered", but the
   LF-2 K_p subtracts only committed undrawn lines. The model does not count offers; if T10 does,
   redemption-spike's "K_p falls by the increase" is confounded by the release.
5. **Families need state the fixture omits** (low · high). borrower-silence needs a repayment schedule
   (model: 360,000 due t=24); redemption-spike needs a due time (model: t=60, inside the horizon) and
   an existing offer; delayed-receipt's advance needs an offered facility or a lender accept+disburse.
6. **Depeg price path** (low · high). Four prices for three rounds; mapping unstated. Model: price i at
   `starts_round + i`, last held. Settlement (t=40) lies outside the 3-round window, so the
   booking rule is only observable on a longer run. Rounding at the settled rate is unstated (model:
   floor).
7. **Lender naming** (low · high). `actors.json` entity `lender-pool`; account ids use `lender/`.
8. **Clearing order sorts the id string** (medium · high). HANDOFF `IntentQueue.drain` sorts on
   `(…, actor_id, intent_id)`; as a string `i-r5-lender-10` sorts before `i-r5-lender-2`, so an
   actor with 10+ calls clears out of order (a disburse ahead of its accept). Sort on the call
   index `n`, as the model does.
9. **Step 6 must check authority, not only schema** (medium · high). The model rejects, before
   clearing: a type outside the actor's mandate, a non-positive amount, a disburse from an
   account the lender does not own, a repay by anyone but the borrower or of less than the due
   installment, and a release by anyone but the facility's lender. Each has a test. A foreign
   `pending_in` with no settled rate becomes `unknown`, never a crash mid-round; `pending_out`
   counts in P(t) and S.

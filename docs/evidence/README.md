# Evidence

## `sandbox-receipt.json`

The receipt of one command-line demo run against the Airwallex sandbox, committed verbatim as
`scripts/demo.sh` wrote it. It is never re-run or edited here.

| | |
|---|---|
| run | `demo-20261027T190757Z-9674`, 2026-10-27 19:07:57Z to 19:08:23Z |
| provider | Airwallex sandbox (`mode: sandbox`), API version `2024-09-27` |
| connected accounts | off (`connected: false`), so **Mode B**: the advance is a sandbox deposit simulation labelled *advance inflow (sandbox simulation)*, not a lender disbursement |
| model | `scripted` — the actors' choices are wired, not a live model's |
| checkpoints | fresh branch, advance reconciled (`SETTLED`), payout reconciled (`PAID`): 3/3 live |
| open incidents | 0 |

Each money checkpoint carries its `request_id`, the provider's id and the journal entry it
reconciled into. It is the command-line demo store's run, not a run of the public API deployment,
and it proves no live-model choice.

Validate it:

```bash
uv run python checks/demo_receipt.py docs/evidence/sandbox-receipt.json --require-live
```

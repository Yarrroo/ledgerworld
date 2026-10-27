# LedgerWorld walkthrough

> Recording plan, not a recording or a claim that the following shots already happened.
> Target duration: 4:35, below the 4:40 production limit and the event's five-minute limit.

## Recording prerequisites

During preparation, capture the initial approval and execution before naming that execution as the
prepared demo. Save its actual run, approval, snapshot and execution IDs with this footage. Then
prepare the associated run/execution in the public API store and verify the read-only judge path.
Approval is one-shot for that plan and observed snapshot: repeating it returns `409 already_approved`;
repeating execution returns `409 approval_used`. A fresh simulation fork does not reset either.
The Execute beat uses the labelled earlier capture, not a second approval of the prepared plan.
The command-line demo's private store is not that prepared run. If the prepared run is absent or
every policy is infeasible, stop recording; do not force a selection just for the video.

Keep synthetic data and provider/model labels visible. Use an operator-only token outside the
capture area for POSTs. Do not film environment files, headers containing credentials or a token
entry. Reserve enough time and model budget for a genuinely fresh branch during the take. If it
cannot finish, record that limitation rather than cutting a replay into a purported live shot.

The opening minute visits Overview → Live Simulation → Decisions → Execution (preview), then
returns to the branch. The full execution happens in the Execute beat. Pause the narration for
necessary UI navigation; the final edit must preserve ordering, labels and waiting-time disclosures.

## 00:00-00:15 State

**Shot:** Overview with the mode banner, `as_of`, snapshot, cash buckets and next obligation. Name
the prepared `run_id` and associated execution, or show unavailable and stop the success take.

**Voice:** “This is synthetic treasury cash. Settled, pending and reserved are different buckets.
We rehearse a shock before a bounded approval can spend anything.”

## 00:15-00:25 World

**Shot:** Open Live Simulation. Select one actor and show its objective, information scope and the
shared venue exposure. Open the evidence slate with the actual run, branch, seed, checkpoint and
source mode; follow the field mapping below. Keep the model provenance separate from freshness.

**Voice:** “Borrowers and the lender share constraints. Each sees only its scoped observation.
This run's model source is shown here; a fresh computation can still use scripted actors.”

## 00:25-00:40 Shock

**Shot:** Show the public post and the following borrower request, lender intents and journal in
the linked evidence view. For the scripted shock/control fixture, show both labelled sides and
use its test command from the submission instructions. Do not silently replace the filmed run
with the fixture. If the current run lacks a trace, show the fixture separately as wiring evidence.

**Voice:** “The scripted shock/control test proves wiring, not independent live-model choice.
The post, request, accepted intents and journal establish the recorded action path. An observation
hash identifies an input; it cannot reveal an actor's unseen causal reasoning.”

## 00:40-01:35 Fork

**Shot:** Compare the three policy branches with the same shock seed and checkpoint, their reserve
floor and obligation outcomes, and the lender's binding capacity. By 00:55, preview Execution to
complete the judge's first-minute path, without implying that execution has happened. Return to
Simulation and start one genuinely fresh branch on camera with the authorized operator action.
Show the new branch metadata and committed rounds as it completes; label every precomputed cohort
**Replay**. A re-fork may reuse a branch ID, so identity alone is not freshness evidence.

**Voice:** “Policies drive the treasury in these branches; other actors re-react. This new branch
runs now. Freshness, model provenance, replay status and provider mode answer different questions.
The result is a comparison, not permission to execute.”

## 01:35-02:00 Break

**Shot:** Show the failing policies' obligation and floor conditions from the actual results. Use
this supported cut-line path; the demo does not currently expose a reverse-stress run. Only use a
reverse-stress shot if that feature actually ran and its evidence is available, and label it so.

**Voice:** “Here is the constraint that breaks each losing policy. If all policies fail, the system
returns the earliest unmet obligation and escalation; it must not quietly lower the reserve floor.”

## 02:00-03:55 Execute

**Shot:** Insert the earlier capture labelled “Earlier: initial approval and execution” with its
actual run, snapshot and execution IDs. Show the bound amount, currency, expiry and plan hash during
the original approval. Do not approve or execute that same plan again. Return to the prepared
execution's own receipt and show its queried final state, request IDs, provider IDs, settled
balances and loan reconciliation. Keep the original capture's identity distinct from the fresh
comparison branch. If no original footage exists, inspect the saved approval and receipt and
narrate that as inspection, not a new approval. Show setup wallet funding separately from the plan.
Do not film the token.

**Voice:** “This previously approved plan crossed the gateway. The banner identifies fake or Airwallex
sandbox, and the receipt identifies connected-account Mode A or fallback Mode B. In Mode B this
advance is an advance inflow (sandbox simulation), not a lender disbursement through Airwallex;
repayment is ledger-only and simulated. Pending or unknown is not settled.”

If sandbox evidence is unavailable, say “This take uses a simulated provider; no sandbox execution
is claimed.” Keep that label on the shot. Never use fake receipts under a sandbox narration.

## 03:55-04:35 Explain

**Shot:** Ask the actor a read-only interview question using the operator-authorized POST; show
its evidence IDs. Open the grounded report for the same run. Finish on the repository and setup
links and the visible provider/model/replay labels. Do not invent a probability or a receipt.

**Voice:** “The report's figures trace to structured results. The interview can explain recorded
observations but cannot move money. The source, setup steps and limitations are linked.”

## Evidence rules

Use the actual fields below as the evidence slate. These are field names to capture, not example
values or fabricated run identifiers. Missing metadata stays unavailable; it cannot be backfilled
from a receipt belonging to another run.

### Run identity

Show `run_id`, `branch_id`, `seed`, `checkpoint_round` and `snapshot_id` together before discussing
coupling. In a command-line demo receipt the mapping is `run_id`, `seed`,
`story.shock.checkpoint.branch`, `story.shock.checkpoint.round`, and
`story.shock.checkpoint.snapshot_id`; the selected fresh branch is
`checkpoints.fresh_branch.branch_id`. In API branch data the checkpoint field is
`checkpoint_round`. If the UI omits a field, put the corresponding structured result alongside it;
never infer the seed from a branch name.

### Model provenance

Show `model: scripted|live` from the run's own source, separately from provider `mode: fake|sandbox`.
The API health response describes the service, not historical proof for an unrelated run. The
scripted deployment cannot be narrated as a live-model choice. A sandbox receipt alone says
nothing about the actors' model source.

### Freshness and replay

For the on-camera fresh branch, capture the parent checkpoint, start and completion, committed
rounds, `created_at` and `cached` where available. The demo receipt's `fresh_branch` checkpoint
records creation time, parent snapshot, round count, model-call count and cache status. Preserve
**Replay** on cached/precomputed evidence and transcript re-runs. Fresh does not mean live model.

### Scripted wiring

`tests/simulation/test_coupled.py::test_public_shock_traceable_response` is the separate
ScriptedModel shock/control proof. It proves wiring, not independent live-model choice. Its
control omits the public rumour and retains capacity. Do not attribute that controlled contrast
to a filmed live model without a separate recorded live-model experiment.

### Trace chain

Keep the same run and branch on every link: public `post_id` → borrower request `intent_id` and
`evidence_ids` → lender accept/disburse intents → C2 `journal_id` → journal `source_intent_id`.
Capture the scoped observation identified by `obs_hash` and its transcript entry. In the fixture,
round four's request does not post a journal; the disbursement posts in the following round.
A hash alone cannot prove causal reasoning. The minimal demo receipt contains story/checkpoint
summaries, not this whole trace; use the run detail or the separately labelled fixture evidence.

### Sandbox receipt

Bind the execution and its `request_id`, provider ID, final state and reconciliation to the
approved run/plan. Validate the captured command-line receipt with
`uv run python checks/demo_receipt.py var/demo/live.json --require-live` when it is genuinely a
sandbox run. Mode B labels remain visible. A sandbox receipt never proves live-model choice, and
a fresh branch never proves sandbox execution. If either is missing, say so and keep that gap in
the submitted description.

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
Before the take, `uv run python checks/recording_ready.py <Demo URL>` must print `GO`.

Keep synthetic data and provider/model labels visible. Use an operator-only token outside the
capture area for POSTs. Do not film environment files, headers containing credentials or a token
entry. Reserve enough time and model budget for a genuinely fresh branch during the take. If it
cannot finish, record that limitation rather than cutting a replay into a purported live shot.

The opening minute visits Overview → Live Simulation → Decisions → Execution (preview), then
returns to the branch. The full execution happens in the Execute beat. Pause the narration for
necessary UI navigation; the final edit must preserve ordering, labels and waiting-time disclosures.

Rehearse the timing first with `bash scripts/walkthrough.sh "$LEDGERWORLD_URL"`. It drives the
deployed app read-only through the seven beats below in real time with each Shot as a caption,
records a silent labelled webm with an SRT of the Voice lines, and prints planned against actual
seconds per beat. It performs no operator action, so it is a rehearsal, never the take.

If no human take exists, `bash scripts/narrated_take.sh "$LEDGERWORLD_URL"` records a machine
take: a 3-second card naming the voice as synthetic, the same beats voiced with each Voice line,
and, with `LEDGERWORLD_DEMO_TOKEN` set, the fresh fork, an approval request and the interview sent
off-screen, their answers on the caption. It stops unless the check above prints `GO`, never
executes, and leaves one MP4 and its SRT in a temporary directory (`--keep DIR` copies them and
`beats.json` somewhere lasting); uploading it is a separate step. Every beat ends at its planned
time even when a screen stalls, and the take fails if the MP4 runs past 4:40 or a beat ends more
than 2 s late.

## 00:00-00:15 State

**Shot:** Overview with the mode banner, `as_of`, snapshot, cash buckets and next obligation. Name
the prepared `run_id` and associated execution, or show unavailable and stop the success take.

**Voice:** “Will you have enough for payroll? See cash in the bank, money set aside and payments
still due. This is made-up company data; nothing moves until you approve and send.”

## 00:15-00:25 World

**Shot:** Open Live Simulation. Select one actor and show its objective, information scope and the
shared venue exposure. Open the evidence slate with the actual run, branch, seed, checkpoint and
source mode; follow the field mapping below. Keep the model provenance separate from freshness.

**Voice:** “Your lender and other borrowers share risks. Each sees only its own information and
public news. The label says whether agents follow scripts or use a model.”

## 00:25-00:40 Shock

**Shot:** Show the public post and the following borrower request, lender intents and journal in
the linked evidence view. For the scripted shock/control fixture, show both labelled sides and
use its test command from the submission instructions. Do not silently replace the filmed run
with the fixture. If the current run lacks a trace, show the fixture separately as wiring evidence.

**Voice:** “What if a payment is late and worrying news spreads? Follow the request for money
through to the books. The scripted test checks the steps, not a model's own choices. It shows
what happened, not why an agent thought it should.”

## 00:40-01:35 Fork

**Shot:** Compare the three policy branches with the same shock seed and checkpoint, their reserve
floor and obligation outcomes, and the lender's binding capacity. By 00:55, preview Execution to
complete the judge's first-minute path, without implying that execution has happened. Return to
Simulation and start one genuinely fresh branch on camera with the authorized operator action.
Show the new branch metadata and committed rounds as it completes; label every precomputed cohort
**Replay**. A re-fork may reuse a branch ID, so identity alone is not freshness evidence.

**Voice:** “Compare doing nothing, keeping a fixed buffer and borrowing just enough. Which plan
covers payroll, stays above your safety minimum, and at what fee? Each plan guides your company's
choices; your lender and the other borrowers respond again. We're running a new what-if now.
Earlier results are labelled Replay. Fresh does not mean the agents used a live model, and neither
Fresh nor Replay tells you whether the bank connection is simulated or sandbox. Comparing plans
does not approve a payment.”

## 01:35-02:00 Break

**Shot:** Show the failing policies' obligation and floor conditions from the actual results. Use
this supported cut-line path; the demo does not currently expose a reverse-stress run. Only use a
reverse-stress shot if that feature actually ran and its evidence is available, and label it so.

**Voice:** “See which bill goes unpaid or when cash drops below your safety minimum. If no plan
keeps you safe, you see the first bill you cannot pay and who to contact. The app never lowers
your minimum to make a plan look safe.”

## 02:00-03:55 Execute

**Shot:** Insert the earlier capture labelled “Earlier: initial approval and execution” with its
actual run, snapshot and execution IDs. Show the bound amount, currency, expiry and plan hash during
the original approval. Do not approve or execute that same plan again. Return to the prepared
execution's own receipt and show its queried final state, request IDs, provider IDs, settled
balances and loan reconciliation. Keep the original capture's identity distinct from the fresh
comparison branch. If no original footage exists, inspect the saved approval and receipt and
narrate that as inspection, not a new approval. Show setup wallet funding separately from the plan.
Do not film the token.

**Voice:** “Check what moved and whether it matches your books. This is the earlier approved plan,
not a new payment. The banner says Simulated bank connection or Sandbox bank. The receipt names
connected-account Mode A or fallback Mode B. In Mode B, the advance inflow (sandbox simulation)
adds test money; it is not a lender disbursement through Airwallex. Repayment is recorded only in
the books and is simulated. Pending means still waiting; unknown means we cannot confirm. Neither
means the money has arrived.”

If sandbox evidence is unavailable, say “This take uses a simulated provider; no sandbox execution
is claimed.” Keep that label on the shot. Never use fake receipts under a sandbox narration.

## 03:55-04:35 Explain

**Shot:** Ask the actor a read-only interview question using the operator-authorized POST; show
its evidence IDs. Open the grounded report for the same run. Finish on the repository and setup
links and the visible provider/model/replay labels. Do not invent a probability or a receipt.

**Voice:** “Ask why cash ran short, then check the figures against the saved results. The interview
explains only what the agent could see; it cannot move money. The source code, setup steps and
limitations are linked.”

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

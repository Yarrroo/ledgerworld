<template>
  <ScreenShell title="Execution" headline="From approved plan to proof." :subtitle="subtitle" :lead="lead"
               :reading="state" :refresh="refresh">
    <template #action>
      <Tip>
        <button ref="opener" type="button" class="lw-button" data-test="review-plan"
                :disabled="!!reviewWhy" aria-describedby="review-why" @click="openReview">Review plan<Arrow /></button>
        <template #tip>
          <span id="review-why" data-test="review-why">{{ reviewWhy || authority }}</span>
          <span data-test="authority"><template v-if="reviewWhy || authority"> · </template>Reading needs no
            operator access. Approving and executing take it, entered in the review; it stays in this tab's
            memory and is forgotten on reload.</span>
        </template>
      </Tip>
    </template>
    <template #default="{ body }">
    <p v-if="flow.blocked" class="lw-alert" role="alert" data-test="blocked">{{ flow.blocked }}</p>
    <p v-if="flow.message" class="lw-note" role="status" data-test="message">{{ flow.message }}</p>
    <p v-for="[run, held] in waiting" :key="run" class="lw-actions">
      <Tip :text="held.unseen === 'execution' ? `Execution ${held.followedId} of run ${run}` : `Run ${run}`">
        <RouterLink class="lw-button lw-button--quiet" data-test="elsewhere"
                    :to="{ path: route.path, query: { run_id: run, execution_id: held.unseen === 'execution' ? held.followedId : undefined } }">
          <template v-if="held.unseen === 'execution'">Read the execution sent for another run</template>
          <template v-else>Open the other run: approval outcome unknown</template>
        </RouterLink>
      </Tip>
    </p>

    <div v-if="execution" class="lw-execution-banner" :class="{ 'lw-execution-banner--ok': allReconciled }"
         role="status" data-test="execution-banner">
      <Tip :text="`${lead} Read ${formatTime(execution.as_of).utc}; not final: later provider events can open an incident.`">
        <span aria-hidden="true">{{ allReconciled ? '✓' : incidents.length ? '!' : '◷' }}</span>
        {{ allReconciled ? 'Reconciled as of' : 'Execution read as of' }} {{ formatTime(execution.as_of).utc }}
      </Tip>
      <span>{{ !legs.some((leg) => leg.receipt) ? 'No provider receipt recorded' : execution.mode === 'fake' ? 'Illustrative receipt' : LABELS[execution.mode] || execution.mode }}</span>
    </div>
    <ol v-if="execution" class="lw-execution-progress" aria-label="Execution progress" data-test="execution-progress">
      <li v-for="step in progress" :key="step.name" :data-reached="step.done">
        <span class="lw-execution-progress__mark" aria-hidden="true">{{ step.done ? '✓' : '○' }}</span>
        <span>{{ step.name }}<span class="lw-visually-hidden">{{ step.done ? ', reached' : ', not reached' }}</span></span>
        <small>{{ step.note }}</small>
      </li>
    </ol>

    <div class="lw-exec">
      <section class="lw-exec__terms" aria-labelledby="summary-heading" data-test="summary"
               data-panel="What you approved">
        <h2 id="summary-heading">Bound approval</h2>
        <dl v-if="execution" class="lw-terms lw-summary-terms" data-test="approval-summary">
          <dt>Provider</dt><dd>{{ LABELS[execution.mode] || execution.mode }}</dd>
          <dt>Status</dt><dd>{{ allReconciled ? 'Reconciled' : 'Read execution legs' }}</dd>
        </dl>
        <template v-if="held">
          <dl class="lw-terms" data-test="summary-held">
            <dt>Approval</dt>
            <dd class="lw-copyable" data-test="summary-held-approval">
              <span class="lw-hash">{{ held.approval_id }}</span>
              <button type="button" class="lw-copy" data-test="copy-held-approval"
                      @click="copy('Approval id', held.approval_id)">Copy<span class="lw-visually-hidden"> approval id</span></button>
            </dd>
            <dt>State</dt>
            <dd data-test="summary-held-state">
              <Tip text="Confirmed in this tab and not executed; kept in this tab's memory only.">
                <span :class="['lw-status', `lw-status--${STAGES[stage].tone}`]">
                  <span aria-hidden="true">{{ STAGES[stage].icon }}</span><span>{{ heldState }}</span>
                </span>
              </Tip>
            </dd>
            <dt>Observed snapshot</dt><dd>{{ held.snapshot_id }}</dd>
            <dt>Provider</dt><dd>{{ LABELS[held.mode] || held.mode }}</dd>
            <dt>Plan hash</dt><dd class="lw-hash" data-test="summary-held-hash">{{ held.plan_hash }}</dd>
            <dt>Expires</dt><dd data-test="summary-held-expires">{{ expires.utc }} · {{ expires.local }}</dd>
          </dl>
        </template>
        <details v-if="execution" class="lw-calc" data-test="summary-plain">
          <summary>View all terms →</summary>
          <dl class="lw-terms">
            <dt>Approval</dt>
            <dd class="lw-copyable">
              <span class="lw-hash" data-test="summary-approval">{{ execution.approval_id }}</span>
              <button type="button" class="lw-copy" data-test="copy-summary-approval"
                      @click="copy('Approval id', execution.approval_id)">Copy<span class="lw-visually-hidden"> approval id</span></button>
            </dd>
            <dt>Observed snapshot</dt><dd>{{ execution.snapshot_id }}</dd>
            <dt>Status read</dt><dd data-test="summary-read">{{ formatTime(execution.as_of).utc }}</dd>
          </dl>
        </details>
        <p v-else-if="!held" class="lw-time">No approval to summarise: the linked execution has not been read.</p>
        <p v-if="token" class="lw-actions">
          <button type="button" class="lw-button lw-button--quiet" data-test="forget-token"
                  @click="forgetAccess">Forget access</button>
        </p>
      </section>

      <section class="lw-exec__legs" aria-labelledby="receipts-heading" data-test="receipts" data-panel="Money moved">
        <h2 id="receipts-heading">Execution legs</h2>
        <HowWeKnow test="how-execution">
          <span class="lw-source" data-test="context">
            Run {{ body.run_id ?? 'unavailable' }} ·
            <template v-if="activeId">execution {{ activeId }}</template>
            <template v-else>no execution is linked to this run</template>
            · the plan executed is the one the server bound on the observed snapshot, never a branch.
          </span>
          <span>The amounts in the page's opening sentence are the provider receipts of the advance (in)
            and the payout and repayment legs (out); checked against your books means each leg is
            reconciled to its ledger journal. Provider: {{ LABELS[body.mode] || body.mode }}.</span>
        </HowWeKnow>
        <p v-if="notFound" class="lw-note" role="status" data-test="not-found">
          <template v-if="followedId === activeId">
            No execution is recorded yet for {{ activeId }}; this does not mean it failed. Reading again.
          </template>
          <template v-else>Execution {{ activeId }} is unavailable: the server has no record of it.</template>
        </p>
        <p v-if="pollError" class="lw-note" data-test="poll-error">
          {{ STATES.error.icon }} {{ execution ? STATES.error.word : 'Could not read' }}: {{ pollError.replace(/\.$/, '') }}.<template v-if="rereading"> Reading again.</template>
        </p>
        <p v-if="!execution && !notFound && !pollError" class="lw-time" data-test="no-execution">
          Unavailable: no execution to show for this run.
        </p>
        <template v-if="execution">
          <p v-if="!legs.length" class="lw-note" role="status" data-test="no-legs">
            No legs are recorded yet for this execution; reading again.
          </p>
          <ol class="lw-legs">
            <li v-for="(leg, index) in legs" :key="leg.leg_id" :data-test="`leg-${leg.kind}`">
              <details class="lw-leg" :data-test="leg.receipt ? 'receipt' : 'receipt-details'">
                <summary class="lw-leg__row">
                  <span class="lw-leg__number">{{ index + 1 }}</span>
                  <span class="lw-leg__name">{{ legTitle(leg) }}<small data-test="receipt-mode">{{ leg.mode }}</small><small v-if="leg.kind === 'advance' && execution.mode === 'sandbox' && /simulation/.test(leg.label)">Sandbox simulation</small></span>
                  <Tip class="lw-leg__amount" @click.stop.prevent :text="leg.receipt ? `Provider receipt amount, observed ${formatTime(leg.receipt.observed_at).utc}` : 'No provider receipt amount is available.'">
                    <span data-test="receipt-amount">{{ leg.receipt ? receiptMoney(leg.receipt) : 'Unavailable' }}</span>
                  </Tip>
                  <Tip class="lw-leg__status" @click.stop.prevent>
                    <span :class="['lw-status', 'lw-leg__pill', `lw-status--${leg.tone}`]" data-test="receipt-pill">
                      <span aria-hidden="true">{{ leg.icon }}</span><span>{{ legPill(leg) }}</span>
                    </span>
                    <template #tip><span data-test="leg-status"><span aria-hidden="true">{{ leg.icon }}</span>{{ leg.text }}</span>. Not final: later provider events can open an incident.</template>
                  </Tip>
                  <span class="lw-leg__chevron"><span aria-hidden="true">⌄</span><span class="lw-visually-hidden">Open receipt</span></span>
                  <span class="lw-visually-hidden">Open receipt and identifiers</span>
                </summary>
                <div class="lw-leg__detail">
                  <dl class="lw-terms">
                    <template v-for="[term, value] in legIds(leg)" :key="term">
                      <dt>{{ term }}</dt><dd class="lw-copyable"><span>{{ value || 'Unavailable' }}</span>
                        <button v-if="value" type="button" class="lw-copy" :aria-label="`Copy ${term}`"
                                @click="copy(term, value)">Copy</button>
                      </dd>
                    </template>
                    <template v-if="leg.receipt">
                      <dt>Currency</dt><dd>{{ leg.receipt.currency }}</dd>
                      <dt>Observed</dt><dd>{{ formatTime(leg.receipt.observed_at).utc }}</dd>
                      <dt>Receipt</dt><dd>{{ leg.mode }}</dd>
                      <dt>Label</dt><dd>{{ leg.label || leg.receipt.label }}</dd>
                    </template>
                  </dl>
                  <ol class="lw-steps" :aria-label="`Progress of ${leg.label || leg.kind}`" data-test="steps">
                    <li v-for="step in leg.steps" :key="step.name"
                        :class="{ [`lw-steps__${step.mark}`]: step.mark !== 'todo', 'lw-steps__now': step.now }"
                        :aria-current="step.now ? 'step' : undefined">
                      <span aria-hidden="true">{{ STEP_MARK[step.mark] }}</span> {{ step.name }}<template
                        v-if="step.note"> · {{ step.note }}</template><span
                        v-if="step.mark === 'done'" class="lw-visually-hidden">, reached</span>
                    </li>
                  </ol>
                  <details v-if="leg.receipt" class="lw-calc">
                    <summary>Open receipt →</summary>
                    <dl class="lw-terms">
                      <dt>Status</dt><dd>{{ leg.receipt.status }}</dd>
                      <dt>Amount</dt><dd>{{ leg.receipt.currency }} {{ leg.receipt.amount }}</dd>
                      <dt>Provider</dt><dd>{{ leg.mode }}</dd>
                      <dt>Fields</dt><dd>{{ leg.receipt.raw_keys.join(', ') }}</dd>
                    </dl>
                  </details>
                </div>
              </details>
            </li>
          </ol>
        </template>
      </section>

      <section class="lw-exec__incidents" aria-labelledby="incidents-heading" data-panel="Incidents">
        <h2 id="incidents-heading">Incidents</h2>
        <div v-if="incidents.length" class="lw-alert" role="alert" data-test="incident">
          <ul class="lw-evidence">
            <li v-for="item in incidents" :key="item.key">
              <strong>{{ item.line }}</strong>
              <dl class="lw-terms">
                <template v-for="[term, value] in item.evidence" :key="term"><dt>{{ term }}</dt><dd>{{ value }}</dd></template>
              </dl>
            </li>
          </ul>
          <HowWeKnow test="how-incident">No reversal or resend is offered here; the operator resolves it with
            the provider.</HowWeKnow>
        </div>
        <p v-else-if="execution" class="lw-time" data-test="no-incidents">
          <span class="lw-incident-check" aria-hidden="true">✓</span>
          <Tip :text="`None open as of ${formatTime(execution.as_of).utc}; a later word from the bank can still open one.`">No
            open incidents for this reading.</Tip>
        </p>
        <p v-else class="lw-time">Unavailable until an execution is read.</p>
      </section>
    </div>

    <p class="lw-visually-hidden" role="status" aria-live="polite" data-test="copied">{{ copied }}</p>

    <div v-if="flow.open" class="lw-overlay">
      <div ref="dialog" class="lw-dialog" role="dialog" aria-modal="true" aria-labelledby="review-heading"
           data-test="review" :data-stage="stage" :class="{ 'lw-dialog--bound': !!flow.approval }">
        <div class="lw-dialog__body">
          <h2 id="review-heading" ref="heading" tabindex="-1">Review before you execute.</h2>
          <p class="lw-review-subtitle"><Tip :text="`Run ${body.run_id} · ${LABELS[body.mode] || body.mode}`">{{ PLANS[policy] ?? policy }} · Current observed snapshot</Tip></p>
          <div class="lw-approval-grid" :class="{ 'lw-approval-grid--bound': !!flow.approval }">
          <section class="lw-approval-create" aria-labelledby="create-heading" data-test="create-stage">
            <h3 id="create-heading"><span class="lw-review-number">1</span> Create approval</h3>
            <dl class="lw-terms lw-review-context">
              <dt>Policy</dt><dd>{{ PLANS[policy] ?? policy }}</dd>
              <dt>Scenario-set</dt><dd>{{ decisions?.cohort ?? 'Unavailable' }} · {{ decisions?.weight_kind ?? 'Unavailable' }}</dd>
              <dt>Facility fee</dt><dd><Tip :text="`Scenario-set cost, not a current-plan quote: ${scenarioCost}`" data-test="fee-context">
                <span data-test="branch-fees">{{ branchFees }}</span>
                <template #tip><span data-test="scenario-cost">{{ scenarioCost }}</span>. Scenario-set cost, not a current-plan quote.</template>
              </Tip></dd>
              <dt>Approval lifetime</dt><dd>15 minutes <Tip text="Default set by the server; check the absolute expiry returned with your approval.">by default</Tip></dd>
            </dl>
            <template v-if="!flow.approval">
              <p v-if="stage === 'unknown'" class="lw-alert" data-test="stage-blocked">{{ flow.blocked }}</p>
              <p v-else class="lw-alert lw-review-note">Exact execution legs are returned after approval creation.</p>
              <form class="lw-field" @submit.prevent>
                <label for="operator-token">Operator access password</label>
                <div class="lw-password">
                  <input id="operator-token" v-model="token" :type="showToken ? 'text' : 'password'" autocomplete="off"
                         spellcheck="false" data-test="token">
                  <button type="button" class="lw-copy" data-test="show-token" :aria-pressed="showToken"
                          @click="showToken = !showToken">{{ showToken ? 'Hide' : 'Show' }}<span class="lw-visually-hidden"> password</span></button>
                </div>
              </form>
              <p class="lw-time">Kept in this tab only.</p>
            </template>
            <p v-else class="lw-time">Approval created. Check the bound terms before execution.</p>
          </section>
          <section class="lw-approval-bound" aria-labelledby="bound-heading" data-test="bound-stage">
            <h3 id="bound-heading"><span class="lw-review-number">2</span> Check bound terms</h3>
            <Tip :text="stageHeading"><p :class="['lw-status', `lw-status--${STAGES[stage].tone}`]" data-test="stage">
              <span aria-hidden="true">{{ STAGES[stage].icon }}</span><span>{{ STAGES[stage].word }}</span>
            </p></Tip>
            <p v-if="!flow.approval" class="lw-time">Create an approval to read its exact terms.</p>
          <template v-if="flow.approval">
            <p v-if="stage === 'executing' || stage === 'reconciled' || stage === 'incident'"
               class="lw-note" role="status" data-test="stage-status">{{ stageStatus }}</p>
            <dl class="lw-terms" data-test="bound">
              <dt>Approval</dt>
              <dd class="lw-copyable">
                <span class="lw-hash">{{ flow.approval.approval_id }}</span>
                <button type="button" class="lw-copy" data-test="copy-approval"
                        @click="copy('Approval id', flow.approval.approval_id)">Copy<span class="lw-visually-hidden"> approval id</span></button>
              </dd>
              <dt>Entity</dt><dd>{{ flow.approval.entity }}</dd>
              <dt>Account</dt><dd>{{ flow.approval.account }}</dd>
              <dt>Observed snapshot</dt><dd>{{ flow.approval.snapshot_id }}</dd>
              <dt>Provider</dt><dd>{{ LABELS[flow.approval.mode] || flow.approval.mode }}</dd>
              <dt>Plan hash</dt>
              <dd class="lw-copyable">
                <Tip :text="flow.approval.plan_hash"><span class="lw-hash" data-test="plan-hash">{{ flow.approval.plan_hash }}</span></Tip>
                <button type="button" class="lw-copy" data-test="copy-hash"
                        @click="copy('Plan hash', flow.approval.plan_hash)">Copy<span class="lw-visually-hidden"> plan hash</span></button>
              </dd>
              <dt>Expires</dt>
              <dd data-test="expires">{{ expires.utc }} · {{ expires.local }}</dd>
            </dl>
            <div v-if="!flow.executed || flow.invalid" class="lw-table-wrap" tabindex="0"
                 role="region" aria-label="Bound legs">
              <table class="lw-table" data-test="legs">
                <thead><tr><th scope="col">Execution legs (bound)</th><th scope="col">Amount</th></tr></thead>
                <tbody>
                  <tr v-for="leg in flow.approval.legs" :key="leg.index">
                    <td><strong>{{ leg.index }} · {{ leg.kind }}</strong>
                      <div>{{ leg.source }} → {{ leg.counterparty }}</div>
                      <details class="lw-bound-conditions"><summary>Conditions</summary>
                        <dl class="lw-terms">
                          <dt>Funded by</dt><dd>{{ leg.funded_by ?? '—' }}</dd>
                          <dt>After</dt><dd>{{ (leg.after ?? []).join(', ') || '—' }}</dd>
                          <dt>Facility</dt><dd>{{ leg.facility_id ?? '—' }}</dd>
                        </dl>
                      </details>
                    </td>
                    <td class="lw-num">{{ money(leg.amount) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <ul v-else-if="sent" class="lw-stage-legs" data-test="stage-legs">
              <li v-for="leg in legs" :key="leg.leg_id" :class="['lw-status', `lw-status--${leg.tone}`]">
                <span aria-hidden="true">{{ leg.icon }}</span><span>{{ leg.label || leg.kind }}: {{ leg.text }}</span>
              </li>
            </ul>
            <ul v-if="stage === 'incident'" class="lw-alert lw-evidence" data-test="stage-incident">
              <li v-for="item in incidents" :key="item.key">{{ item.line }}</li>
            </ul>
          </template>
          </section>
          </div>
        </div>

        <div class="lw-dialog__footer lw-actions">
          <button v-if="!flow.approval" type="button" class="lw-button" data-test="confirm" :disabled="!!confirmWhy"
                  aria-describedby="confirm-why" @click="confirmApproval">Create approval</button>
          <span v-if="!flow.approval" class="lw-time">This does not execute funds.</span>
          <button v-else-if="!flow.executed || flow.invalid" type="button" class="lw-button"
                  data-test="execute" :disabled="!!executeWhy" aria-describedby="execute-why"
                  @click="executePlan">Execute approved plan</button>
          <button v-else type="button" class="lw-button" data-test="read-status"
                  :disabled="flow.submitting" :aria-disabled="readingNow || undefined"
                  @click="readNow">{{ CHECK }}</button>
          <button type="button" class="lw-button lw-button--quiet" :disabled="flow.submitting"
                  @click="closeReview">{{ flow.approval ? 'Close' : 'Cancel' }}</button>
          <span v-if="!flow.approval" id="confirm-why" class="lw-time" data-test="confirm-why">{{ confirmWhy }}</span>
          <span v-else id="execute-why" class="lw-time" role="status" data-test="execute-why">{{ executeWhy }}</span>
        </div>
      </div>
    </div>
    </template>
  </ScreenShell>
</template>

<script>
import { reactive, ref } from 'vue'

// The operator token: this tab's memory only. Module scope survives moving between screens and
// dies with the page; it is never written to storage, a URL, markup or a log.
const token = ref('')

// An operation whose outcome this tab does not know, kept in the same tab memory as the token:
// run id -> { blocked, followedId, readBy, unseen }. Leaving the screen and coming back restores
// the block and resumes reading the execution, so the token never outlives its quarantine. Forget
// access does not lift it: only a reload does. `unseen` ('execution' or 'approval') marks an outcome
// that answered after its screen moved on: it is linked until its own run's screen shows it.
const unresolved = reactive(new Map())

// Runs with a POST still unanswered, whichever view sent it: a view since left keeps no other trace,
// so a returned screen must not send a second one for the same run before the first answers.
const inflight = reactive(new Set())

/** The tab reloaded, as far as this screen can tell: token and quarantine both forgotten. */
export function forgetTab () {
  token.value = ''
  unresolved.clear()
  inflight.clear()
}
</script>

<script setup>
import { computed, nextTick, onUnmounted, reactive, shallowRef, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Arrow from '../components/Arrow.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
import Tip from '../components/Tip.vue'
import {
  ApiError, LABELS, PLANS, STATES, ScreenShell, decimalMinor, feesAcross, formatMoney, formatTime, getOverview, kindText,
  latestOnly, money, noDemoRun, request, useReading
} from '../api/v1.js'

/** The legs that bring money in and the ones that pay it out, for the lead sentence. */
const INFLOW = new Set(['advance'])
const OUTFLOW = new Set(['payout', 'repayment'])
const WORD = { pending: 'Pending', submitted: 'Submitted', settled: 'Settled', failed: 'Failed', unknown: 'Unknown' }
const UNSETTLED = new Set(['pending', 'submitted', 'unknown'])
const POLL_MS = 5000
const POST_TIMEOUT_MS = 30000
const APPROVAL_UNKNOWN = 'Approval outcome unknown; operator resolution required'
/** The review's read-again button, as its label and as the status lines name it. */
const CHECK = 'Check the status'
const REFUSALS = {
  snapshot_moved: 'Observed state changed; reload and review a new plan',
  approval_expired: 'Approval expired',
  approval_used: 'This approval was already executed'
}
/** E4: how far a leg has come; a leg is reconciled only once confirmed and journalled. */
const STEPS = ['Ready', 'Submitted', 'Provider-confirmed', 'Reconciled']
const STEP = { pending: 0, submitted: 1, unknown: 1, settled: 2, failed: 1 }
/** The steps only a provider operation reaches; a ledger-only leg skips them. */
const PROVIDER_STEPS = new Set([1, 2])
const STEP_MARK = { done: '●', skipped: '–', todo: '○' }
/** The dialog's stages (HANDOFF "Approval & execution state machine"), each with a word and icon. */
const STAGES = {
  review: { word: 'Review', icon: '○', tone: 'muted' },
  submitting: { word: 'Creating approval', icon: '◷', tone: 'warn' },
  unknown: { word: 'Outcome unknown', icon: '!', tone: 'bad' },
  approved: { word: 'Approved, not executed', icon: '✓', tone: 'ok' },
  expired: { word: 'Not executable', icon: '✕', tone: 'bad' },
  executing: { word: 'Executing', icon: '◷', tone: 'warn' },
  reconciled: { word: 'Reconciled', icon: '✓', tone: 'ok' },
  incident: { word: 'Incident', icon: '!', tone: 'bad' }
}

const route = useRoute()
const enc = encodeURIComponent

/** A 2xx whose body is missing or incomplete: answered, but what it says cannot be read. */
const unreadable = () => new ApiError(null, 'unreadable', 'the answer could not be read')
const isText = (x) => typeof x === 'string' && x !== ''
const isTextOrNull = (x) => x == null || isText(x)
// C6 times in the one form the server emits and every browser parses alike; Date.parse alone also
// takes "1" or "Nov 5", and only some engines take a space separator
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/
const isTime = (iso) => ISO.test(iso) && !Number.isNaN(Date.parse(iso))

/** A C6 execution leg and incident as the receipts and the incident view draw them. */
const isExecutionLeg = (l) => isText(l?.leg_id) && isText(l.kind) && Object.hasOwn(WORD, l.state) &&
  typeof l.reconciled === 'boolean' &&
  (l.receipt == null || (isText(l.receipt.status) && Array.isArray(l.receipt.raw_keys)))
const isIncident = (i) => isText(i?.leg_id) && isText(i.kind) && isText(i.state) && isTime(i.opened_at)

/** GET /executions/:id; an answer about another execution, or an incomplete one, is unreadable. */
async function readExecution (id, signal) {
  const body = await request(`/executions/${enc(id)}`, { signal })
  const readable = body?.execution_id === id && isTime(body.as_of) && isText(body.mode) &&
    isText(body.approval_id) && isText(body.snapshot_id) &&
    Array.isArray(body.legs) && body.legs.every(isExecutionLeg) &&
    Array.isArray(body.incidents) && body.incidents.every(isIncident)
  if (!readable) throw unreadable()
  return body
}

/** GET /decisions/:run; one without its status, results' costs or selected policy is unreadable. */
async function readDecisions (runId) {
  const body = await request(`/decisions/${enc(runId)}`)
  const readable = isText(body?.status) && Array.isArray(body.results) &&
    body.results.every((r) => Number.isSafeInteger(r?.funding_cost?.minor) && isText(r.funding_cost.currency)) &&
    (body.status !== 'selected' || isText(body.selected))
  if (!readable) throw unreadable()
  return body
}

/** A read that may name nothing yet: 404 is "not there", every other failure is an error. */
async function optional (reading) {
  try {
    return await reading
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

// One generation for every read of an execution's state, the screen's own and the polls: an
// answer is applied only if no read issued after it has been applied already.
const guard = latestOnly()

const { state, refresh } = useReading(async () => {
  const overview = await getOverview()
  const asked = route.query.run_id || null
  const runId = asked || overview.demo.run_id
  const demo = !asked || asked === overview.demo.run_id
  const executionId = route.query.execution_id || (demo ? overview.demo.execution_id : null) || null
  if (!runId && !executionId) throw noDemoRun()
  let decisionsError = ''
  let executionError = null
  const { generation } = guard.issue()
  const [decisions, execution] = await Promise.all([
    // the receipts still read when this fails; only the review needs the decision
    runId ? optional(readDecisions(runId)).catch((error) => { decisionsError = error.message; return null }) : null,
    // and the review still opens when the receipts cannot be read
    executionId ? optional(readExecution(executionId)).catch((error) => { executionError = error; return null }) : null
  ])
  const head = execution ?? overview
  return {
    as_of: head.as_of, mode: head.mode, snapshot_id: head.snapshot_id, run_id: runId,
    execution_id: executionId, decisions, decisionsError, execution, executionError, generation
  }
})

const decisions = computed(() => state.body?.decisions ?? null)
const policy = computed(() => decisions.value?.selected ?? null)
const selectedRows = computed(() =>
  (decisions.value?.results ?? []).filter((r) => r.policy === policy.value))
const branchFees = computed(() =>
  selectedRows.value.map((r) => `${r.scenario_id} ${money(r.funding_cost)}`).join(' · ') || 'None')
const scenarioCost = computed(() => (selectedRows.value.length ? feesAcross(selectedRows.value) : 'None'))

// ------------------------------------------------------------------ approve, then execute

const flow = reactive({
  open: false, approval: null, serverAt: 0, receivedAt: 0, submitting: false, executed: false,
  invalid: '', blocked: '', message: ''
})
const showToken = ref(false)
watch(() => flow.open, () => { showToken.value = false })
const opener = shallowRef(null)
const heading = shallowRef(null)
const now = shallowRef(Date.now())
let clock = null
// The screen is gone: a late answer, success or failure, applies nothing to it and starts no
// timer; an unknown outcome is still held in tab memory, so coming back restores its block. A
// POST is never aborted (its effect stands either way); the polled status read is, since
// nothing will show it.
let disposed = false
const reads = new AbortController()

/** Why nothing can be approved from this screen right now, or '' when it can. */
const authority = computed(() => {
  if (!token.value) return 'Operator access required'
  return ''
})

const reviewWhy = computed(() => {
  if (state.status === 'loading') return 'Loading'
  if (state.status === 'error') return 'Last loaded, not current: reload first'
  const d = decisions.value
  if (state.body.decisionsError) return `Decision unavailable: ${state.body.decisionsError}`
  if (!d) return 'No decision is available for this run'
  if (/reverse[_-]stress/.test(d.cohort)) return 'A search result is not a decision; nothing to review'
  if (d.status === 'all_infeasible') return 'No feasible plan: escalate on Decisions, nothing to approve'
  if (d.status !== 'selected') return 'Nothing is selected yet'
  if (flow.blocked) return flow.blocked
  const held = unresolved.get(state.body.run_id)
  if (held?.unseen === 'execution') {
    return `Execution ${held.followedId} of this run answered while you were away: read it first`
  }
  const sendingHere = flow.submitting && sentFrom === screen
  if (inflight.has(state.body.run_id) && !sendingHere) {
    return 'A request for this run, sent from a screen since left, is not answered yet'
  }
  // a review opened now could be neither confirmed nor closed while that request is out
  if (flow.submitting && !sendingHere) return 'A request sent from the last screen is not answered yet'
  return ''
})

const confirmWhy = computed(() => {
  if (reviewWhy.value) return reviewWhy.value
  if (authority.value) return authority.value
  if (flow.submitting) return 'Sending'
  return ''
})

/** The server's clock: the approval response's as_of plus the time this tab has waited since. */
const serverNow = computed(() => flow.serverAt + (now.value - flow.receivedAt))
const expires = computed(() => formatTime(flow.approval?.expires_at))

/** Why the bound approval itself can no longer be executed from here, or ''. */
const staleWhy = computed(() => {
  const a = flow.approval
  if (!a) return ''
  if (a.mode !== state.body?.mode) return 'The bound provider mode differs from this screen; review again'
  if ((decisions.value?.results ?? []).some((r) => r.branch_id === a.snapshot_id)) {
    return 'Bound to a hypothetical branch, not the observed state; review again'
  }
  if (serverNow.value >= Date.parse(a.expires_at)) return 'Approval expired'
  return ''
})

const executeWhy = computed(() => {
  if (!flow.approval) return 'Confirm approval first'
  if (flow.blocked) return flow.blocked
  if (flow.invalid) return flow.invalid
  if (flow.executed) return 'Sent once; its status is read below, never sent again'
  if (authority.value) return authority.value
  if (staleWhy.value) return staleWhy.value
  if (flow.submitting) return 'Sending'
  return ''
})

/**
 * The approval this tab confirmed and has not executed, or null. It belongs to the screen it was
 * confirmed on: a new screen (newScreen) and Forget access both drop it.
 */
const held = computed(() => flow.executed ? null : flow.approval)
/** What the held approval can do now, with the reason when it cannot be executed. */
const heldState = computed(() => {
  const why = flow.blocked || staleWhy.value
  return why ? `${STAGES[stage.value].word}: ${why}` : 'Approved, not executed; executable until it expires'
})

/**
 * Forget the operator token, and with it an approval confirmed and not executed: only a fresh
 * review takes access again, so a kept approval could be neither executed nor replaced.
 */
function forgetAccess () {
  token.value = ''
  const id = held.value?.approval_id
  if (!id || flow.submitting) return
  dropReview()
  flow.message = `Approval ${id} was not executed and expires unused.`
}

/**
 * No answer, a server/proxy failure, or a 2xx this screen cannot read: the POST may or may not
 * have taken effect. Only a 4xx is a definite refusal.
 */
const unanswered = (error) => !(error?.status >= 400 && error.status < 500)

/** A C3 leg as the bound-terms table shows it. */
const isLeg = (l) => Number.isSafeInteger(l?.index) && isText(l.kind) && isText(l.source) &&
  isText(l.counterparty) && Number.isSafeInteger(l.amount?.minor) && isText(l.amount.currency) &&
  isTextOrNull(l.funded_by) && isTextOrNull(l.facility_id) &&
  (l.after == null || (Array.isArray(l.after) && l.after.every(Number.isSafeInteger))) // leg indices

/** The approval a 201 bound, with every term the review shows; anything less is unreadable. */
function boundApproval (answer) {
  const a = answer?.approval
  const readable = isTime(answer?.as_of) && isText(a?.approval_id) && isText(a.plan_hash) &&
    isText(a.entity) && isText(a.account) && isText(a.snapshot_id) && isText(a.mode) &&
    isTime(a.expires_at) && Array.isArray(a.legs) && a.legs.length > 0 && a.legs.every(isLeg)
  if (!readable) throw unreadable()
  return a
}

function refusal (error) {
  return REFUSALS[error.code] || `Refused: ${error.message}`
}

/** Remember, against the run it was sent for, what this tab still has to resolve or read. */
function hold (runId, patch) {
  unresolved.set(runId, { ...unresolved.get(runId), ...patch })
}

let screen = 0 // bumped by every new screen (newScreen) and on leaving the view
let sentFrom = -1 // the screen this view's own POST in flight was sent from

/** Where a POST was sent from, fixed when it is sent: the run, and the screen it was asked on. */
const origin = () => ({ run: state.body.run_id, screen })
/** The screen a POST was asked on is gone: its answer is never shown in that review again. */
const moved = (from) => from.screen !== screen

const waiting = computed(() => [...unresolved].filter(([, held]) => held.unseen))
const accepted = (id) => `Execution ${id} accepted; reading its provider state.`
/** The review and its approval go: on a new screen, on Forget access, or when a waiting outcome is shown. */
const dropReview = () => Object.assign(flow, { open: false, approval: null, invalid: '', executed: false })

async function openReview () {
  if (reviewWhy.value) return
  flow.open = true
  await nextTick()
  heading.value?.focus()
}

async function closeReview () {
  if (flow.submitting) return // the answer to an in-flight POST is shown where it was asked
  flow.open = false
  // an approval that can no longer execute goes, with or without operator access held
  if (flow.approval && (flow.invalid || flow.executed || flow.blocked || staleWhy.value)) dropReview()
  await nextTick()
  opener.value?.focus()
}

async function confirmApproval () {
  if (confirmWhy.value || flow.approval) return
  const from = origin()
  const runId = from.run
  flow.submitting = true
  sentFrom = screen
  inflight.add(runId)
  flow.message = ''
  try {
    const answer = await request('/approvals', {
      method: 'POST', token: token.value, signal: AbortSignal.timeout(POST_TIMEOUT_MS),
      body: { run_id: runId, policy: policy.value }
    })
    const approval = boundApproval(answer) // unreadable is unknown, and held, even once left
    if (moved(from)) { // never offered outside the review it was asked in; unused, it expires
      if (!disposed) {
        flow.message = `Approval ${approval.approval_id} for run ${runId} was created after ` +
          'this screen moved on; it was not executed and expires unused.'
      }
      return
    }
    flow.approval = approval
    flow.serverAt = Date.parse(answer.as_of)
    flow.receivedAt = Date.now()
    now.value = flow.receivedAt
    clock = clock ?? setInterval(() => { now.value = Date.now() }, 1000)
    await nextTick()
    heading.value?.focus()
  } catch (error) {
    if (unanswered(error)) {
      if (!moved(from)) {
        hold(runId, { blocked: APPROVAL_UNKNOWN })
        flow.blocked = APPROVAL_UNKNOWN
      } else {
        hold(runId, { blocked: APPROVAL_UNKNOWN, unseen: 'approval' }) // held even once left
        if (!disposed) flow.message = `Run ${runId}: ${APPROVAL_UNKNOWN}`
      }
    } else if (!disposed) flow.message = (moved(from) ? `Run ${runId}: ` : '') + refusal(error)
  } finally {
    flow.submitting = false
    inflight.delete(runId)
  }
}

async function executePlan () {
  if (executeWhy.value) return
  const id = flow.approval.approval_id
  const from = origin()
  const runId = from.run
  flow.submitting = true
  sentFrom = screen
  inflight.add(runId)
  flow.executed = true
  try {
    const answer = await request('/executions', {
      method: 'POST', token: token.value, signal: AbortSignal.timeout(POST_TIMEOUT_MS),
      body: { approval_id: id }
    })
    // the server names an execution by its approval id; any other answer is unreadable
    if (answer?.execution_id !== id) throw unreadable()
    if (!moved(from)) {
      hold(runId, { followedId: id, unseen: false })
      flow.message = accepted(id)
      follow(id)
    } else {
      hold(runId, { followedId: id, unseen: 'execution' }) // held even once left
      if (!disposed) flow.message = `Execution ${id} for run ${runId} was accepted after this screen moved on.`
    }
  } catch (error) {
    if (!unanswered(error)) { // refused: nothing was sent; said where it was asked, or by run once moved
      if (disposed) return
      if (moved(from)) flow.message = `Run ${runId}: ${refusal(error)}`
      else flow.invalid = refusal(error)
      return
    }
    const blocked = `Execution outcome unknown; reading its status by approval id ${id}. Do not send again.`
    if (!moved(from)) {
      hold(runId, { blocked, followedId: id, readBy: id, unseen: false })
      flow.blocked = blocked
      follow(id)
    } else {
      hold(runId, { blocked, followedId: id, readBy: id, unseen: 'execution' }) // held even once left
      if (!disposed) {
        flow.message = `Execution outcome unknown for run ${runId}; its status is read by approval id ` +
          `${id} on that run's screen. Do not send again.`
      }
    }
  } finally {
    flow.submitting = false
    inflight.delete(runId) // released even once left: a returned screen may send again
  }
  // the dialog stays on the execution it sent, reading its status; Close drops the used approval
}

// ----------------------------------------------------------------- provider state, polled

const activeId = shallowRef(null)
// the execution on screen: only an accepted reading, the screen's own read or a poll
const execution = shallowRef(null)
const notFound = shallowRef(false)
const pollError = shallowRef('')
const retrying = shallowRef(false) // a failed read worth reading again: no answer, or retry-later
const rereading = shallowRef(false) // a read is scheduled: what "Reading again" says
let failedAt = 0 // generation of the newest failed read: only a later answer clears its error
let timer = null
const followedId = shallowRef(null)
let followed = false // an execution this tab sent: a refresh re-reads it, never swaps it for another
let autoReviewed = false // review=1 opens the review once, not on every refresh

/** Still moving: no legs queued yet, or a leg neither final nor reconciled. */
const moving = (body) => !body.legs.length ||
  body.legs.some((l) => UNSETTLED.has(l.state) || (!l.reconciled && l.state !== 'failed'))

/**
 * Read again in 5 s while the outcome is open or the last read failed. An execution this tab sent
 * is read until a read shows it finished, whatever the last read returned; one named by the
 * context is read only while a loaded answer shows it moving, so an id the server does not have
 * (404) is not polled.
 */
function schedule () {
  clearTimeout(timer)
  if (disposed) return
  const body = execution.value
  const keep = Boolean(pollError.value && retrying.value) || (followed ? (!body || moving(body)) : Boolean(body && moving(body)))
  timer = keep ? setTimeout(poll, POLL_MS) : null
  rereading.value = keep
}

/** A failed read: said, kept as the newest failure, and read again unless refused outright. */
function failed (error, generation) {
  pollError.value = error.message
  retrying.value = unanswered(error) || [408, 429].includes(error.status)
  failedAt = Math.max(failedAt, generation)
}

/** An answer to a read issued after the newest failure clears its error; an older one does not. */
function answered (generation) {
  if (generation > failedAt) pollError.value = ''
}

/** Read an execution's state by id; out-of-order or other-execution answers are dropped. */
async function poll () {
  const id = activeId.value
  if (!id || disposed) return
  const ticket = guard.issue()
  try {
    const body = await readExecution(id, reads.signal)
    if (disposed || !guard.accept(ticket, id)) return
    execution.value = body
    notFound.value = false
    answered(ticket.generation)
  } catch (error) {
    if (disposed) return
    if (error.status === 404) {
      if (!guard.accept(ticket, id)) return
      execution.value = null // the server has no record: no earlier reading stands beside that
      notFound.value = true
      answered(ticket.generation)
    } else {
      // a failed read is no answer: it never discards a reading issued before it
      if (!guard.current(ticket, id)) return
      failed(error, ticket.generation)
    }
  }
  schedule()
}

/** A held block, said truthfully: its lookup is claimed only while this screen is reading it. */
function blockFor (held) {
  if (!held.readBy || followedId.value === held.readBy) return held.blocked
  return `Execution outcome unknown for approval ${held.readBy}; not read on this screen. Do not send again.`
}

function follow (id) {
  followed = true
  followedId.value = id
  activeId.value = id
  guard.select(id)
  execution.value = null
  notFound.value = false
  pollError.value = '' // another execution's failure is not this one's
  poll()
}

/**
 * What this tab holds for the run now shown decides the block and the execution followed: a block
 * or an execution sent for another run is not this screen's. Unresolved work from before the
 * screen was last left is restored, and its execution read again unless the address names another
 * one. Returns whether it resumed reading a held execution.
 */
function restore (body) {
  const held = unresolved.get(body.run_id)
  if (followed && held?.followedId !== followedId.value) {
    followed = false
    followedId.value = null
  }
  const named = route.query.execution_id
  const resume = held?.followedId && !followed && (!named || named === held.followedId)
  if (resume) follow(held.followedId)
  if (held?.unseen === 'approval' || (held?.unseen && followedId.value === held.followedId)) {
    if (held.unseen === 'execution' && !held.readBy) flow.message = accepted(held.followedId)
    held.unseen = false // shown on its own run's screen at last
    if (!flow.submitting) dropReview() // a review opened meanwhile closes, as after one sent in place
  }
  flow.blocked = held?.blocked ? blockFor(held) : ''
  return Boolean(resume)
}

watch(() => state.body, (body, before) => {
  if (!body) return
  // a refresh that names another prepared run under the same address is a new screen too
  if (before && body.run_id !== before.run_id) newScreen()
  if (restore(body)) return
  if (followed) {
    poll() // Refresh re-reads the execution this tab sent
    return
  }
  if (activeId.value !== body.execution_id) { // another execution: nothing read for the last stands
    execution.value = null
    notFound.value = false
    pollError.value = ''
  }
  activeId.value = body.execution_id
  guard.select(body.execution_id)
  // this read replaces any poll answered before it and invalidates every poll issued before it;
  // a poll issued after it and already answered is newer, and stays. A failed read is no answer:
  // it shows its error and discards nothing read before it.
  const ticket = { generation: body.generation, context: body.execution_id }
  if (body.executionError) {
    if (guard.current(ticket)) failed(body.executionError, body.generation)
  } else if (guard.accept(ticket)) {
    execution.value = body.execution
    notFound.value = Boolean(body.execution_id && !body.execution)
    answered(body.generation)
  }
  schedule()
  if (route.query.review === '1' && !autoReviewed && !reviewWhy.value) {
    autoReviewed = true
    openReview()
  }
})

// What the tab holds for the run on screen is shown as soon as it changes, not only on the next
// load: an answer that found its run already on screen (sent from a screen since left, or before
// a navigation to the same run), or the quarantine forgotten. A load is the body watcher's.
const heldHere = () => state.body && unresolved.get(state.body.run_id)
watch([() => state.body?.run_id, () => heldHere()?.blocked, () => heldHere()?.followedId,
  () => heldHere()?.unseen], ([run], [before]) => {
  if (state.status === 'loaded' && run === before) restore(state.body)
})

/**
 * Another run or execution on this view: nothing shown for the last one stands. A POST still in
 * flight answers to the screen it was sent from (origin), never to this one.
 */
function newScreen () {
  screen += 1
  dropReview()
  flow.message = ''
  followed = false
  followedId.value = null
  activeId.value = null
  execution.value = null
  notFound.value = false
  pollError.value = ''
  clearTimeout(timer)
}

// The view is reused across query-only navigation: a new run or execution is a new screen.
watch(() => [route.query.run_id, route.query.execution_id].join('|'), () => {
  newScreen()
  refresh()
})

onUnmounted(() => {
  disposed = true
  screen += 1 // a POST still in flight answers to a screen that is gone
  reads.abort()
  clearTimeout(timer)
  clearInterval(clock)
})

/** The same evidence threshold feeds leg status, trackers and both hero readings. */
const isReconciledLeg = (leg, incidents) => leg.state === 'settled' && leg.reconciled && !!leg.journal_id &&
  !incidents.some((i) => i.leg_id === leg.leg_id && i.state === 'open')

/** One row per leg: C4 state and reconciliation as the API reports it, never inferred. */
const legs = computed(() => {
  const body = execution.value
  if (!body) return []
  return body.legs.map((leg) => {
    const open = body.incidents.filter((i) => i.leg_id === leg.leg_id && i.state === 'open')
    // a provider-backed leg settles only on a provider object, which names it; one settled with no
    // provider id is the ledger-only repayment (mode B): nothing was submitted or confirmed
    const local = leg.state === 'settled' && !leg.provider_id
    const status = leg.receipt?.status ?? (local ? 'Ledger only, no provider operation' : 'no provider status')
    let text, tone, icon
    if (leg.state === 'unknown') {
      [text, tone, icon] = ['Outcome unknown; checking provider status. Do not send again.', 'bad', '!']
    } else if (open.length) {
      [text, tone, icon] = [`${WORD[leg.state]} · ${status} · incident open`, 'bad', '!']
    } else if (leg.state === 'failed') {
      [text, tone, icon] = [`Failed · ${status}`, 'bad', '✕']
    } else if (isReconciledLeg(leg, body.incidents)) {
      [text, tone, icon] = [`${status} · reconciled as of ${formatTime(body.as_of).utc}`, 'ok', '✓']
    } else {
      [text, tone, icon] = [`${WORD[leg.state] ?? leg.state} · ${status} · not reconciled`, 'warn', '◷']
    }
    const mode = leg.receipt?.mode ?? body.mode
    // an open incident takes the leg back from Reconciled: the tracker never outruns the evidence
    const reconciled = isReconciledLeg(leg, body.incidents)
    const step = reconciled ? 3 : local ? 0 : STEP[leg.state] ?? 0
    const now = local && reconciled ? 'ledger only' : { failed: 'failed', unknown: 'outcome unknown' }[leg.state] ?? ''
    const steps = STEPS.map((name, n) => {
      const mark = local && PROVIDER_STEPS.has(n) ? 'skipped' : n <= step ? 'done' : 'todo'
      return { name, mark, now: n === step, note: mark === 'skipped' ? 'not applicable' : n === step ? now : '' }
    })
    return { ...leg, text, tone, icon, steps, mode: local ? 'Ledger only (simulated)' : LABELS[mode] || mode }
  })
})

const legTitle = (leg) => leg.label || kindText(leg.kind)
const legPill = (leg) => leg.state === 'unknown' ? 'Outcome unknown' :
  `${leg.receipt?.status ?? WORD[leg.state]}${leg.tone === 'ok' ? ' · Reconciled' : leg.tone === 'bad' ? ' · Needs review' : ' · Not reconciled'}`
const legIds = (leg) => [
  ['Request id', leg.receipt?.request_id ?? leg.request_id],
  ['Provider id', leg.receipt?.provider_id ?? leg.provider_id],
  ['Journal', leg.journal_id]
]

/** E6: each open incident with the evidence it was raised on, never a guessed outcome. */
const incidents = computed(() => {
  const body = execution.value
  if (!body) return []
  const read = formatTime(body.as_of).utc
  const evidence = (leg, extra = []) => [
    ['Affected leg', leg?.label || leg?.leg_id],
    ['Provider id', leg?.receipt?.provider_id ?? leg?.provider_id ?? 'none returned'],
    ['Request id', leg?.receipt?.request_id ?? leg?.request_id ?? 'none returned'],
    ['Observed status', leg?.receipt?.status ?? 'no provider status'],
    ...extra,
    ['Last read', read]
  ]
  const legOf = (id) => body.legs.find((l) => l.leg_id === id)
  return [
    ...body.legs.filter((l) => l.state === 'unknown').map((l) => ({
      key: `unknown:${l.leg_id}`,
      line: `${l.leg_id}: Outcome unknown; checking provider status. Do not send again.`,
      evidence: evidence(l)
    })),
    ...body.incidents.filter((i) => i.state === 'open').map((i, n) => ({
      key: `incident:${i.incident_id ?? `${i.leg_id}:${i.kind}:${n}`}`, // no id: the order tells them apart
      line: `${kindText(i.kind)} on ${i.leg_id}, opened ${formatTime(i.opened_at).utc}`,
      evidence: evidence(legOf(i.leg_id), [['Opened', formatTime(i.opened_at).utc]])
    }))
  ]
})

/** Aggregate progress cannot outrun any leg; ledger-only entries skip provider steps. */
const allReconciled = computed(() => !!legs.value.length && !incidents.value.length &&
  legs.value.every((l) => isReconciledLeg(l, execution.value.incidents)))
const progress = computed(() => {
  const provider = legs.value.filter((l) => !(l.state === 'settled' && !l.provider_id))
  const submitted = !!provider.length && provider.every((l) => !!(l.provider_id || l.receipt?.provider_id))
  const confirmed = !!provider.length && provider.every((l) => l.state === 'settled' && l.provider_id && l.receipt)
  return [
    { name: 'Approved', done: !!execution.value?.approval_id, note: 'Plan authorized' },
    { name: 'Submitted', done: submitted, note: provider.length ? submitted ? 'Sent to provider' : 'Submission unconfirmed' : 'No provider operation' },
    { name: 'Provider confirmed', done: confirmed, note: provider.length ? 'Provider evidence' : 'Not applicable' },
    { name: 'Reconciled', done: allReconciled.value, note: 'Matched in ledger' }
  ]
})

/**
 * Money a set of legs moved, from their provider receipts ("USD 10,000.00"), one sum per
 * currency; '' when no leg of that kind is there, "an unknown amount" when a receipt does not read.
 * Ledger-only legs carry no receipt and are counted apart (`ledgerOnly`).
 */
const ledgerOnly = (leg) => !leg.receipt && !leg.provider_id
function movedWords (legs) {
  legs = legs.filter((l) => !ledgerOnly(l))
  if (!legs.length) return ''
  const sums = new Map()
  for (const leg of legs) {
    const r = leg.receipt
    const minor = r ? decimalMinor(r.amount, r.currency) : null
    if (minor === null) return 'an unknown amount'
    sums.set(r.currency, (sums.get(r.currency) ?? 0) + minor)
  }
  return [...sums].map(([currency, minor]) => formatMoney(minor, currency)).join(' and ')
}

/**
 * The finance lead's answer, first (COPY.md, Execution): what the approved plan moved in and
 * paid out and whether it is checked against their books; before an execution, that nothing
 * moves until they approve and then send. Amounts are the legs' provider receipts.
 */
const lead = computed(() => {
  const body = execution.value
  if (!body) {
    // sent from this tab and not recorded yet: never "nothing moves", which invites a second send
    if (notFound.value && followedId.value && followedId.value === activeId.value) {
      return 'The plan you sent is not recorded yet; reading again. Do not send it twice.'
    }
    if (activeId.value && !notFound.value) {
      if (!pollError.value) return 'Reading what the plan you sent moved.'
      // not reading again: an execution this tab sent always is, so Check the status (its review's)
      // is not on screen here, and the header has no Refresh; a reload reads it again
      return `We could not read what the plan you sent moved yet; ${rereading.value ? 'reading again' : 'reload the page to try again'}.`
    }
    return held.value
      ? 'You approved the plan; nothing moves until you send it.'
      : 'Nothing moves until you approve and then send.'
  }
  if (incidents.value.length || body.legs.some((l) => l.state === 'failed')) {
    const n = incidents.value.length
    return `Something needs a look: ${n || 'a'} problem${n > 1 ? 's' : ''} on the plan you sent; nothing is resent.`
  }
  if (!body.legs.length) return 'The plan you approved is sent; its payments are not recorded yet.'
  const n = body.legs.length
  const checked = body.legs.filter((l) => isReconciledLeg(l, body.incidents)).length
  if (checked < n) return `The plan you approved is under way: ${checked} of ${n} payments checked against your books so far.`
  const moved = movedWords(body.legs.filter((l) => INFLOW.has(l.kind)))
  const paid = movedWords(body.legs.filter((l) => OUTFLOW.has(l.kind)))
  const local = body.legs.filter(ledgerOnly).length
  const parts = [moved && `moved ${moved} in`, paid && `paid ${paid} out`].filter(Boolean)
  let what = parts.length ? parts.join(' and ') : ''
  if (local) {
    const entries = `${local} ledger-only entr${local === 1 ? 'y' : 'ies'}`
    what = what ? `${what}, plus ${entries}` : `booked ${entries}`
  }
  what = what || `made its ${n === 1 ? 'payment' : 'payments'}`
  return `The plan you approved ${what} — ${n === 2 ? 'both ' : n > 2 ? 'all ' : ''}checked against your books.`
})

/** The hero's one line: which plan this record is for and how far its legs are checked. */
const subtitle = computed(() => {
  const body = execution.value
  const plan = PLANS[policy.value] ?? 'Approved plan'
  if (!body) return held.value ? `${plan} · approved, not sent` : 'No execution recorded yet'
  const n = body.legs.length
  const checked = body.legs.filter((l) => isReconciledLeg(l, body.incidents)).length
  return `Observed execution record · ${checked} of ${n} legs reconciled`
})

/** A receipt's amount in the page's money style; as the provider wrote it when it does not read. */
function receiptMoney (r) {
  const minor = decimalMinor(r.amount, r.currency)
  return minor === null ? `${r.currency} ${r.amount}` : formatMoney(minor, r.currency)
}

// ------------------------------------------------------------------ the dialog's stage

/** The execution this dialog sent, as last read; null until a read of it answered. */
const sent = computed(() => {
  const body = execution.value
  return flow.executed && body && body.execution_id === flow.approval?.approval_id ? body : null
})

/** One stage at a time, derived from the flow the guards keep (never stored beside it). */
const stage = computed(() => {
  if (!flow.approval) {
    if (flow.submitting) return 'submitting'
    return flow.blocked ? 'unknown' : 'review'
  }
  if (flow.invalid) return 'expired'
  if (flow.executed) {
    const body = sent.value
    if (!flow.submitting && body) {
      // an unknown leg is still being read (executing); an open incident or a failure is not
      const opened = body.incidents.some((i) => i.state === 'open')
      if (opened || body.legs.some((l) => l.state === 'failed')) return 'incident'
      if (allReconciled.value) return 'reconciled'
    }
    return 'executing'
  }
  if (flow.blocked) return 'unknown' // an outcome held for this run blocks the bound approval too
  return staleWhy.value ? 'expired' : 'approved'
})

const stageHeading = computed(() => ({
  review: `Review the plan · ${PLANS[policy.value] ?? policy.value}`,
  submitting: 'Creating approval',
  unknown: flow.blocked === APPROVAL_UNKNOWN ? 'Approval outcome unknown' : 'Outcome unknown for this run',
  approved: 'Approved terms · not yet executed',
  expired: flow.invalid ? 'Execution refused · not executed' : 'Approval no longer executable',
  executing: 'Executing approved plan',
  reconciled: 'Reconciled',
  incident: 'Incident · evidence kept'
})[stage.value])

const stageStatus = computed(() => {
  const id = flow.approval?.approval_id
  if (flow.submitting) return `Sending execution of approval ${id} once.`
  // said once per change of state, never per poll: no read time of its own in this live text
  const failure = pollError.value && (rereading.value
    ? `Could not read the status of execution ${id}; reading again.`
    : `Could not read the status of execution ${id}: ${pollError.value.replace(/\.$/, '')}. ${CHECK} to try again.`)
  // a failed read is said beside a terminal stage or a held block: the stage and its last read stand
  const beside = (said) => (failure ? `${said} ${failure}` : said)
  const body = sent.value
  if (stage.value === 'reconciled') {
    return beside(`Every leg reconciled as of ${formatTime(body.as_of).utc}; not final, a later read can open an incident.`)
  }
  if (stage.value === 'incident') return beside(`${CHECK} stays available; nothing is resent or reversed.`)
  if (flow.blocked) return beside(flow.blocked)
  return failure || `Execution ${id}: reading status.`
})

// ------------------------------------------------------------------ dialog mechanics

const dialog = shallowRef(null)
const copied = shallowRef('')
const readingNow = shallowRef(false)

/** Copy an id or hash and say so, or say why not; the announcement is polite, never focus. */
async function copy (what, value) {
  copied.value = ''
  try {
    await navigator.clipboard.writeText(value)
    copied.value = `${what} copied`
  } catch {
    copied.value = `${what} not copied: select it and copy it by hand`
  }
}

/** Read the execution's status now: a GET, never a resend, one at a time. */
async function readNow () {
  if (readingNow.value) return
  readingNow.value = true
  try {
    await poll()
  } finally {
    readingNow.value = false
  }
}

const FOCUSABLE = 'button, [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])'
/** Tab and Shift+Tab stay inside the dialog while it is open. */
function trap (event) {
  const box = dialog.value
  if (!box) return
  const items = [...box.querySelectorAll(FOCUSABLE)].filter((el) => {
    if (el.disabled) return false
    for (let node = el; node && node !== box; node = node.parentElement) {
      const style = getComputedStyle(node)
      if (style.display === 'none' || style.visibility === 'hidden') return false
      if (node.parentElement?.tagName === 'DETAILS' && !node.parentElement.open && node.tagName !== 'SUMMARY') return false
    }
    return true
  })
  const at = document.activeElement
  const inside = box.contains(at)
  if (!items.length) {
    event.preventDefault()
    heading.value?.focus()
    return
  }
  const [first, last] = [items[0], items[items.length - 1]]
  if (event.shiftKey && (!inside || at === first || at === heading.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (!inside || at === last)) {
    event.preventDefault()
    first.focus()
  }
}

/** Escape (when safe) and Tab while the dialog is open, wherever focus has gone. */
function onKey (event) {
  if (!flow.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeReview()
  } else if (event.key === 'Tab') trap(event)
}
// Capture before nested tooltips consume Escape: the modal owns dismissal while it is open.
document.addEventListener('keydown', onKey, true)
onUnmounted(() => document.removeEventListener('keydown', onKey, true))

// A new stage keeps focus in the dialog: a control that went away or was disabled hands focus to
// the heading; focus already on a live control inside stays where it is.
watch(stage, async () => {
  if (!flow.open) return
  await nextTick()
  const at = document.activeElement
  if (!dialog.value?.contains(at) || at?.disabled) heading.value?.focus()
})
</script>

<style scoped>
.lw-field {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--lw-space-2);
  margin: var(--lw-space-2) 0;
}
.lw-field input {
  min-height: var(--lw-target);
  min-width: 0;
  flex: 1 1 12rem;
  padding: 0 var(--lw-space-2);
  border: 1px solid var(--lw-ink-muted);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  color: var(--lw-ink);
  font: inherit;
}
.lw-terms {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--lw-space-1) var(--lw-space-3);
  margin: var(--lw-space-2) 0;
}
.lw-terms dt { color: var(--lw-ink-muted); }
.lw-terms dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
@media (max-width: 480px) {
  .lw-terms { grid-template-columns: 1fr; }
  .lw-terms dd { margin-bottom: var(--lw-space-2); }
}
.lw-hash { font-family: var(--lw-font-figure); }
.lw-tile > h2 { margin-top: 0; }
.lw-legs {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 0;
}
.lw-exec {
  display: grid;
  gap: var(--lw-space-6);
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "legs" "terms" "incidents";
  margin-top: var(--lw-space-6);
}
.lw-exec__terms { grid-area: terms; }
.lw-exec__legs { grid-area: legs; }
.lw-exec__incidents { grid-area: incidents; }
.lw-exec h2 { margin-top: 0; }
/* desktop: legs left, bound terms and incidents right */
@media (min-width: 1200px) {
  .lw-exec {
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    grid-template-areas: "legs terms" "legs incidents";
    align-items: start;
  }
  .lw-exec__incidents { align-self: start; }
}
.lw-steps {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-1) var(--lw-space-3);
  margin: var(--lw-space-2) 0;
  padding: 0;
  list-style: none;
  color: var(--lw-ink-muted);
  font-size: 13px;
  line-height: 18px;
}
.lw-steps__done { color: var(--lw-ink); }
.lw-steps__now { font-weight: 600; }
.lw-copyable {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--lw-space-2);
}
.lw-copyable .lw-hash { min-width: 0; overflow-wrap: anywhere; }
.lw-copy {
  min-height: var(--lw-target);
  min-width: var(--lw-target);
  padding: 0 var(--lw-space-3);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: transparent;
  color: var(--lw-link);
  font: inherit;
  cursor: pointer;
}
.lw-copy:focus-visible { outline: 2px solid var(--lw-focus); outline-offset: 2px; }
.lw-evidence { margin: 0; padding-left: var(--lw-space-4); }
.lw-evidence > li + li { margin-top: var(--lw-space-3); }
.lw-stage-legs {
  display: grid;
  gap: var(--lw-space-2);
  margin: var(--lw-space-2) 0;
  padding: 0;
  list-style: none;
}
.lw-overlay {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--lw-space-4);
  overflow-y: auto;
  background: rgb(14 20 17 / 0.45);
}
/* one focused dialog: the body scrolls, the action footer stays in view */
.lw-dialog {
  display: flex;
  flex-direction: column;
  width: min(76rem, 100%);
  max-height: calc(100vh - 2 * var(--lw-space-4));
  max-height: calc(100dvh - 2 * var(--lw-space-4));
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  color: var(--lw-ink);
}
.lw-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: var(--lw-space-4);
}
.lw-dialog__body > .lw-status { margin: 0 0 var(--lw-space-2); }
.lw-dialog__footer {
  flex: none;
  margin: 0;
  padding: var(--lw-space-3) var(--lw-space-4);
  border-top: 1px solid var(--lw-rule);
  background: var(--lw-surface-raised);
}
.lw-dialog h2 { margin-top: 0; }
.lw-dialog h2:focus { outline: none; }
.lw-dialog h2:focus-visible { outline: 2px solid var(--lw-focus); }
/* phone: full-height dialog with a fixed action footer */
@media (max-width: 767px) {
  .lw-overlay { padding: 0; align-items: stretch; }
  .lw-dialog {
    width: 100%;
    height: 100vh;
    height: 100dvh;
    max-height: none;
    border: 0;
    border-radius: 0;
  }
}
.lw-execution-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--lw-space-2) var(--lw-space-4);
  padding: var(--lw-space-4);
  background: var(--lw-selected);
  color: var(--lw-ink);
}
.lw-execution-banner--ok { color: var(--lw-ok); }
.lw-execution-progress {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  list-style: none;
  margin: 0;
  padding: var(--lw-space-6) 0;
  border-bottom: 1px solid var(--lw-rule);
  gap: var(--lw-space-2);
}
.lw-execution-progress li { display: grid; gap: var(--lw-space-1); min-width: 0; position: relative; }
.lw-execution-progress small { color: var(--lw-ink-muted); }
.lw-execution-progress__mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--lw-rule);
  border-radius: 50%;
  background: var(--lw-surface);
  color: var(--lw-ink-muted);
}
.lw-execution-progress li[data-reached="true"] .lw-execution-progress__mark {
  background: var(--lw-brand);
  border-color: var(--lw-brand);
  color: var(--lw-on-brand);
}
.lw-execution-progress li:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 15px;
  left: 38px;
  right: 0;
  border-top: 1px solid var(--lw-rule);
}
.lw-execution-progress li[data-reached="true"]:not(:last-child)::after { border-color: var(--lw-brand); }
.lw-leg { border-top: 1px solid var(--lw-rule); }
.lw-legs > li:last-child { border-bottom: 1px solid var(--lw-rule); }
.lw-leg__row {
  list-style: none;
  display: grid;
  grid-template-columns: 38px minmax(0, 1.2fr) auto minmax(0, 1fr) 20px;
  align-items: center;
  gap: var(--lw-space-3);
  padding: var(--lw-space-4) 0;
  cursor: pointer;
  min-height: var(--lw-target);
}
.lw-leg__row::-webkit-details-marker { display: none; }
.lw-leg__number, .lw-incident-check {
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--lw-selected);
  color: var(--lw-brand);
}
.lw-leg__name { font-family: var(--lw-font-heading); font-size: 20px; line-height: 1.2; }
.lw-leg__name small { display: block; font: 12px/1.5 var(--lw-font-text); color: var(--lw-ink-muted); margin-top: 4px; }
.lw-leg__amount { font-family: var(--lw-font-heading); font-size: 24px; font-weight: 600; }
.lw-leg__status { justify-self: end; font-size: 12px; }
.lw-leg__pill { background: var(--lw-selected); border-radius: 4px; padding: 6px 8px; }
.lw-leg__chevron { justify-self: end; }
.lw-leg[open] > summary .lw-leg__chevron { transform: rotate(180deg); }
.lw-leg__detail { padding: 0 var(--lw-space-4) var(--lw-space-4); }
.lw-summary-terms { margin-bottom: var(--lw-space-6); }
.lw-exec__incidents { border-top: 1px solid var(--lw-rule); padding-top: var(--lw-space-4); }
.lw-exec__incidents [data-test="no-incidents"] { display: flex; align-items: center; gap: var(--lw-space-3); color: var(--lw-ink); }
.lw-incident-check { flex-shrink: 0; }
.lw-review-subtitle { color: var(--lw-ink-muted); margin-top: 0; }
.lw-dialog #review-heading { font-size: clamp(28px, 3vw, 42px); font-family: var(--lw-font-heading); margin-bottom: var(--lw-space-2); }
.lw-approval-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--lw-space-6); }
.lw-approval-grid > section { min-width: 0; }
.lw-approval-bound { background: var(--lw-selected); padding: var(--lw-space-4); }
.lw-approval-create { padding: var(--lw-space-4) 0; }
.lw-approval-grid h3 { font: 28px/1.3 var(--lw-font-heading); margin: 0 0 var(--lw-space-4); display: flex; align-items: center; gap: var(--lw-space-3); }
.lw-review-number { display: grid; place-items: center; border: 1px solid var(--lw-rule); border-radius: 50%; width: 44px; height: 44px; flex-shrink: 0; }
.lw-approval-bound .lw-review-number { background: var(--lw-brand); color: var(--lw-on-brand); }
.lw-review-context { grid-template-columns: 9rem minmax(0, 1fr); }
.lw-review-context dt, .lw-review-context dd { padding-block: var(--lw-space-3); border-top: 1px solid var(--lw-rule); }
.lw-review-note { font-size: 14px; }
.lw-field label { flex-basis: 100%; }
.lw-password { display: flex; width: 100%; gap: var(--lw-space-2); }
.lw-password input { width: 0; }
.lw-approval-bound .lw-hash { display: inline-block; max-width: 16ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
.lw-dialog--bound .lw-dialog__footer { justify-content: flex-end; }
.lw-approval-bound .lw-table { min-width: 0; width: 100%; }
.lw-approval-bound .lw-table td { overflow-wrap: anywhere; white-space: normal; }
.lw-approval-bound .lw-table td:last-child { white-space: nowrap; }
.lw-bound-conditions summary { cursor: pointer; min-height: var(--lw-target); display: flex; align-items: center; color: var(--lw-link); }
.lw-bound-conditions .lw-terms { font-size: 12px; }
.lw-bound-conditions dd { overflow-wrap: anywhere; }
@media (min-width: 1200px) {
  .lw-exec { column-gap: var(--lw-space-6); }
  .lw-exec__terms, .lw-exec__incidents { border-left: 1px solid var(--lw-rule); padding-left: var(--lw-space-6); }
}
@media (max-width: 767px) {
  .lw-approval-grid { grid-template-columns: minmax(0, 1fr); }
  .lw-approval-grid:not(.lw-approval-grid--bound) .lw-approval-bound,
  .lw-approval-grid--bound .lw-approval-create { display: none; }
  .lw-dialog__footer { gap: var(--lw-space-2); }
  .lw-dialog__footer .lw-time { font-size: 12px; }
  .lw-leg__row { grid-template-columns: 32px minmax(0, 1fr) auto 16px; gap: var(--lw-space-2); }
  .lw-leg__number { width: 30px; height: 30px; }
  .lw-leg__name { font-size: 18px; }
  .lw-leg__amount { font-size: 20px; }
  .lw-leg__status { grid-row: 2; grid-column: 2 / 4; justify-self: start; }
  .lw-leg__chevron { grid-column: 4; grid-row: 1; }
  .lw-execution-progress { font-size: 12px; }
  .lw-execution-progress small { display: none; }
  .lw-execution-banner { font-size: 13px; }
  .lw-review-context { grid-template-columns: 1fr minmax(0, 1fr); }
  .lw-review-context dd { margin-bottom: 0; }
}
</style>

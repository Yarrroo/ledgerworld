<template>
  <ScreenShell v-slot="{ body }" title="Execution" :reading="state" :refresh="refresh">
    <section class="lw-exec__context" aria-labelledby="context-heading" data-panel="Execution context">
      <h2 id="context-heading" class="lw-visually-hidden">Execution context</h2>
      <p class="lw-source" data-test="context">
        Run {{ body.run_id ?? 'unavailable' }} ·
        <template v-if="activeId">execution {{ activeId }}</template>
        <template v-else>no execution is linked to this run</template>
        · the plan executed is the one the server bound on the observed snapshot, never a branch.
      </p>
    </section>

    <section class="lw-tile" aria-labelledby="authority-heading" data-test="authority" data-panel="Approval review">
      <h2 id="authority-heading">Approval review</h2>
      <p class="lw-time">Reading needs no operator access. Approving and executing take it, entered
        in the review; it stays in this tab's memory and is forgotten on reload.</p>
      <div class="lw-actions">
        <button ref="opener" type="button" class="lw-button" data-test="review-plan"
                :disabled="!!reviewWhy" aria-describedby="review-why" @click="openReview">Review plan</button>
        <button v-if="token" type="button" class="lw-button lw-button--quiet"
                data-test="forget-token" @click="token = ''">Forget access</button>
        <span id="review-why" class="lw-time" data-test="review-why">{{ reviewWhy || authority }}</span>
      </div>
    </section>

    <p v-if="flow.blocked" class="lw-alert" role="alert" data-test="blocked">{{ flow.blocked }}</p>
    <p v-if="flow.message" class="lw-note" role="status" data-test="message">{{ flow.message }}</p>
    <p v-for="[run, held] in waiting" :key="run" class="lw-actions">
      <RouterLink class="lw-button lw-button--quiet" data-test="elsewhere"
                  :to="{ path: route.path, query: { run_id: run, execution_id: held.unseen === 'execution' ? held.followedId : undefined } }">
        <template v-if="held.unseen === 'execution'">Read execution {{ held.followedId }} of run {{ run }}</template>
        <template v-else>Open run {{ run }}: approval outcome unknown</template>
      </RouterLink>
    </p>

    <div class="lw-exec">
      <section class="lw-exec__terms" aria-labelledby="summary-heading" data-test="summary"
               data-panel="Approval summary">
        <h2 id="summary-heading">Approval summary</h2>
        <dl v-if="execution" class="lw-terms">
          <dt>Approval</dt>
          <dd class="lw-copyable">
            <span class="lw-hash" data-test="summary-approval">{{ execution.approval_id }}</span>
            <button type="button" class="lw-copy" data-test="copy-summary-approval"
                    @click="copy('Approval id', execution.approval_id)">Copy<span class="lw-visually-hidden"> approval id</span></button>
          </dd>
          <dt>Observed snapshot</dt><dd>{{ execution.snapshot_id }}</dd>
          <dt>Provider</dt><dd>{{ LABELS[execution.mode] || execution.mode }}</dd>
          <dt>Status read</dt><dd data-test="summary-read">{{ formatTime(execution.as_of).utc }}</dd>
        </dl>
        <p v-else class="lw-time">No approval to summarise: the linked execution has not been read.</p>
      </section>

      <section class="lw-exec__legs" aria-labelledby="receipts-heading" data-test="receipts" data-panel="Leg tracker">
        <h2 id="receipts-heading">Legs and receipts</h2>
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
            <li v-for="leg in legs" :key="leg.leg_id" class="lw-tile" :data-test="`leg-${leg.kind}`">
              <div class="lw-tile__label">{{ leg.label || leg.kind }}</div>
              <div :class="['lw-status', `lw-status--${leg.tone}`]" data-test="leg-status">
                <span aria-hidden="true">{{ leg.icon }}</span><span>{{ leg.text }}</span>
              </div>
              <ol class="lw-steps" :aria-label="`Progress of ${leg.label || leg.kind}`" data-test="steps">
                <li v-for="(step, n) in STEPS" :key="step"
                    :class="{ 'lw-steps__done': n <= leg.step, 'lw-steps__now': n === leg.step }"
                    :aria-current="n === leg.step ? 'step' : undefined">
                  <span aria-hidden="true">{{ n <= leg.step ? '●' : '○' }}</span> {{ step }}<template
                    v-if="n === leg.step && leg.stepNote"> · {{ leg.stepNote }}</template><span
                    v-if="n <= leg.step" class="lw-visually-hidden">, reached</span>
                </li>
              </ol>
              <div class="lw-time">
                <span data-test="receipt-mode">{{ leg.mode }}</span><template v-if="leg.receipt">
                  · {{ leg.receipt.currency }} {{ leg.receipt.amount }}</template>
              </div>
              <details v-if="leg.receipt" class="lw-calc" data-test="receipt">
                <summary>Open receipt</summary>
                <dl class="lw-calc__body lw-terms">
                  <dt>Provider id</dt><dd>{{ leg.receipt.provider_id }}</dd>
                  <dt>Request id</dt><dd>{{ leg.receipt.request_id }}</dd>
                  <dt>Status</dt><dd>{{ leg.receipt.status }}</dd>
                  <dt>Amount</dt><dd>{{ leg.receipt.currency }} {{ leg.receipt.amount }}</dd>
                  <dt>Journal</dt><dd>{{ leg.journal_id ?? 'not posted' }}</dd>
                  <dt>Observed</dt><dd>{{ formatTime(leg.receipt.observed_at).utc }}</dd>
                  <dt>Provider</dt><dd>{{ LABELS[leg.receipt.mode] || leg.receipt.mode }}</dd>
                  <dt>Fields kept</dt><dd>{{ leg.receipt.raw_keys.join(', ') }}</dd>
                </dl>
              </details>
            </li>
          </ol>
          <p class="lw-time">PAID means reconciled as of the time shown, not final: a later provider
            event can still open an incident.</p>
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
          <p>No reversal or resend is offered here; the operator resolves it with the provider.</p>
        </div>
        <p v-else-if="execution" class="lw-time" data-test="no-incidents">
          None open as of {{ formatTime(execution.as_of).utc }}.
        </p>
        <p v-else class="lw-time">Unavailable until an execution is read.</p>
      </section>
    </div>

    <p class="lw-visually-hidden" role="status" aria-live="polite" data-test="copied">{{ copied }}</p>

    <div v-if="flow.open" class="lw-overlay">
      <div ref="dialog" class="lw-dialog" role="dialog" aria-modal="true" aria-labelledby="review-heading"
           data-test="review" :data-stage="stage">
        <div class="lw-dialog__body">
          <p :class="['lw-status', `lw-status--${STAGES[stage].tone}`]" data-test="stage">
            <span aria-hidden="true">{{ STAGES[stage].icon }}</span><span>{{ STAGES[stage].word }}</span>
          </p>
          <h2 id="review-heading" ref="heading" tabindex="-1">{{ stageHeading }}</h2>

          <template v-if="!flow.approval">
            <dl class="lw-terms">
              <dt>Run</dt><dd>{{ body.run_id }}</dd>
              <dt>Compared on</dt>
              <dd>{{ decisions.snapshot_id }} · cohort {{ decisions.cohort }} · {{ decisions.weight_kind }}</dd>
              <dt>Provider</dt><dd>{{ LABELS[body.mode] || body.mode }}</dd>
              <dt>Bound on</dt><dd>the current observed snapshot, by the server when you confirm</dd>
              <dt>Approval lifetime</dt>
              <dd>15 minutes by default, set by the server; the absolute expiry is shown after confirmation</dd>
              <dt>Funding cost per branch</dt><dd data-test="branch-fees">{{ branchFees }}</dd>
              <dt>Scenario-set cost</dt><dd data-test="scenario-cost">{{ scenarioCost }}</dd>
            </dl>
            <p v-if="stage === 'unknown'" class="lw-alert" data-test="stage-blocked">{{ flow.blocked }}</p>
            <p v-else class="lw-note">
              The legs and amounts are bound by the server at confirmation; this API offers no
              preview. Confirming creates an approval only: you check its terms before a separate
              Execute.
            </p>
            <form class="lw-field" @submit.prevent>
              <label for="operator-token">Operator access</label>
              <input id="operator-token" v-model="token" type="password" autocomplete="off"
                     spellcheck="false" data-test="token">
            </form>
          </template>

          <template v-else>
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
                <span class="lw-hash" data-test="plan-hash">{{ flow.approval.plan_hash }}</span>
                <button type="button" class="lw-copy" data-test="copy-hash"
                        @click="copy('Plan hash', flow.approval.plan_hash)">Copy<span class="lw-visually-hidden"> plan hash</span></button>
              </dd>
              <dt>Expires</dt>
              <dd data-test="expires">{{ expires.utc }} · {{ expires.local }}</dd>
            </dl>
            <div v-if="!flow.executed || flow.invalid" class="lw-table-wrap" tabindex="0"
                 role="region" aria-label="Bound legs">
              <table class="lw-table" data-test="legs">
                <thead>
                  <tr><th scope="col">#</th><th scope="col">Kind</th><th scope="col">Amount</th>
                    <th scope="col">Source</th><th scope="col">Counterparty</th><th scope="col">Funded by</th>
                    <th scope="col">After</th><th scope="col">Facility</th></tr>
                </thead>
                <tbody>
                  <tr v-for="leg in flow.approval.legs" :key="leg.index">
                    <td>{{ leg.index }}</td><td>{{ leg.kind }}</td>
                    <td class="lw-num">{{ money(leg.amount) }}</td>
                    <td>{{ leg.source }}</td><td>{{ leg.counterparty }}</td>
                    <td>{{ leg.funded_by ?? '—' }}</td><td>{{ (leg.after ?? []).join(', ') || '—' }}</td>
                    <td>{{ leg.facility_id ?? '—' }}</td>
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
        </div>

        <div class="lw-dialog__footer lw-actions">
          <button v-if="!flow.approval" type="button" class="lw-button" data-test="confirm" :disabled="!!confirmWhy"
                  aria-describedby="confirm-why" @click="confirmApproval">Confirm approval</button>
          <button v-else-if="!flow.executed || flow.invalid" type="button" class="lw-button"
                  data-test="execute" :disabled="!!executeWhy" aria-describedby="execute-why"
                  @click="executePlan">Execute approved plan</button>
          <button v-else type="button" class="lw-button" data-test="read-status"
                  :disabled="flow.submitting" :aria-disabled="readingNow || undefined"
                  @click="readNow">Read status</button>
          <button type="button" class="lw-button lw-button--quiet" :disabled="flow.submitting"
                  @click="closeReview">{{ flow.approval ? 'Close' : 'Cancel' }}</button>
          <span v-if="!flow.approval" id="confirm-why" class="lw-time" data-test="confirm-why">{{ confirmWhy }}</span>
          <span v-else id="execute-why" class="lw-time" role="status" data-test="execute-why">{{ executeWhy }}</span>
        </div>
      </div>
    </div>
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
import {
  ApiError, LABELS, STATES, ScreenShell, formatMoney, formatTime, getOverview, latestOnly, money, noDemoRun,
  request, useReading
} from '../api/v1.js'

const NAMES = { 'no-action': 'No action', 'fixed-reserve': 'Fixed reserve', integrated: 'Integrated' }
const WORD = { pending: 'Pending', submitted: 'Submitted', settled: 'Settled', failed: 'Failed', unknown: 'Unknown' }
const UNSETTLED = new Set(['pending', 'submitted', 'unknown'])
const POLL_MS = 5000
const POST_TIMEOUT_MS = 30000
const APPROVAL_UNKNOWN = 'Approval outcome unknown; operator resolution required'
const REFUSALS = {
  snapshot_moved: 'Observed state changed; reload and review a new plan',
  approval_expired: 'Approval expired',
  approval_used: 'This approval was already executed'
}
/** E4: how far a leg has come; a leg is reconciled only once confirmed and journalled. */
const STEPS = ['Ready', 'Submitted', 'Provider-confirmed', 'Reconciled']
const STEP = { pending: 0, submitted: 1, unknown: 1, settled: 2, failed: 1 }
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
const scenarioCost = computed(() => {
  const rows = selectedRows.value
  if (!rows.length) return 'None'
  const currency = rows[0].funding_cost.currency
  if (rows.some((r) => r.funding_cost.currency !== currency)) return 'Mixed currencies; not summed'
  const total = rows.reduce((sum, r) => sum + r.funding_cost.minor, 0)
  return `${formatMoney(total, currency)} across ${rows.length} scenarios; not the current execution fee`
})

// ------------------------------------------------------------------ approve, then execute

const flow = reactive({
  open: false, approval: null, serverAt: 0, receivedAt: 0, submitting: false, executed: false,
  invalid: '', blocked: '', message: ''
})
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

let screen = 0 // bumped by every navigation to another run or execution, and on leaving the view
let sentFrom = -1 // the screen this view's own POST in flight was sent from

/** Where a POST was sent from, fixed when it is sent: the run, and the screen it was asked on. */
const origin = () => ({ run: state.body.run_id, screen })
/** The screen a POST was asked on is gone: its answer is never shown in that review again. */
const moved = (from) => from.screen !== screen

const waiting = computed(() => [...unresolved].filter(([, held]) => held.unseen))
const accepted = (id) => `Execution ${id} accepted; reading its provider state.`
/** The review and its approval go: after a navigation, or when a waiting outcome is shown. */
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
  if (flow.invalid || flow.executed || (flow.approval && executeWhy.value && !authority.value)) dropReview()
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

watch(() => state.body, (body) => {
  if (!body) return
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

// The view is reused across query-only navigation: a new run or execution is a new screen. A
// POST still in flight answers to the screen it was sent from (origin), never to this one.
watch(() => [route.query.run_id, route.query.execution_id].join('|'), () => {
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
  refresh()
})

onUnmounted(() => {
  disposed = true
  screen += 1 // a POST still in flight answers to a screen that is gone
  reads.abort()
  clearTimeout(timer)
  clearInterval(clock)
})

/** One row per leg: C4 state and reconciliation as the API reports it, never inferred. */
const legs = computed(() => {
  const body = execution.value
  if (!body) return []
  return body.legs.map((leg) => {
    const open = body.incidents.filter((i) => i.leg_id === leg.leg_id && i.state === 'open')
    const status = leg.receipt?.status ?? 'no provider status'
    let text, tone, icon
    if (leg.state === 'unknown') {
      [text, tone, icon] = ['Outcome unknown; checking provider status. Do not send again.', 'bad', '!']
    } else if (open.length) {
      [text, tone, icon] = [`${WORD[leg.state]} · ${status} · incident open`, 'bad', '!']
    } else if (leg.state === 'failed') {
      [text, tone, icon] = [`Failed · ${status}`, 'bad', '✕']
    } else if (leg.reconciled) {
      [text, tone, icon] = [`${status} · reconciled as of ${formatTime(body.as_of).utc}`, 'ok', '✓']
    } else {
      [text, tone, icon] = [`${WORD[leg.state] ?? leg.state} · ${status} · not reconciled`, 'warn', '◷']
    }
    const mode = leg.receipt?.mode ?? body.mode
    // an open incident takes the leg back from Reconciled: the tracker never outruns the evidence
    const step = leg.reconciled && leg.state === 'settled' && !open.length ? 3 : STEP[leg.state] ?? 0
    const stepNote = { failed: 'failed', unknown: 'outcome unknown' }[leg.state] ?? ''
    return { ...leg, text, tone, icon, step, stepNote, mode: LABELS[mode] || mode }
  })
})

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
      line: `${i.kind.replace(/_/g, ' ')} on ${i.leg_id}, opened ${formatTime(i.opened_at).utc}`,
      evidence: evidence(legOf(i.leg_id), [['Opened', formatTime(i.opened_at).utc]])
    }))
  ]
})

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
      if (body.legs.length && body.legs.every((l) => l.reconciled)) return 'reconciled'
    }
    return 'executing'
  }
  if (flow.blocked) return 'unknown' // an outcome held for this run blocks the bound approval too
  return staleWhy.value ? 'expired' : 'approved'
})

const stageHeading = computed(() => ({
  review: `Review plan · ${NAMES[policy.value]}`,
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
  const body = sent.value
  if (stage.value === 'reconciled') {
    return `Every leg reconciled as of ${formatTime(body.as_of).utc}; not final, a later read can open an incident.`
  }
  if (stage.value === 'incident') return `Read status stays available; nothing is resent or reversed.`
  if (flow.blocked) return flow.blocked
  // said once per change of state, never per poll: no read time in this live text
  if (pollError.value) {
    return rereading.value
      ? `Could not read the status of execution ${id}; reading again.`
      : `Could not read the status of execution ${id}: ${pollError.value.replace(/\.$/, '')}. Read status to try again.`
  }
  return `Execution ${id}: reading status.`
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
  const items = [...box.querySelectorAll(FOCUSABLE)].filter((el) => !el.disabled)
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
document.addEventListener('keydown', onKey)
onUnmounted(() => document.removeEventListener('keydown', onKey))

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
  gap: var(--lw-space-3);
}
.lw-exec {
  display: grid;
  gap: var(--lw-space-6);
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "terms" "legs" "incidents";
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
  width: min(48rem, 100%);
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
</style>

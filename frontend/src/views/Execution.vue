<template>
  <ScreenShell v-slot="{ body }" title="Execution" :reading="state" :refresh="refresh">
    <p class="lw-source" data-test="context">
      Run {{ body.run_id ?? 'unavailable' }} ·
      <template v-if="activeId">execution {{ activeId }}</template>
      <template v-else>no execution is linked to this run</template>
      · the plan executed is the one the server bound on the observed snapshot, never a branch.
    </p>

    <section class="lw-tile" aria-labelledby="authority-heading" data-test="authority">
      <h2 id="authority-heading">Approval</h2>
      <p class="lw-time">Reading needs no token. Approving and executing take the operator token,
        entered in the review; it stays in this tab's memory and is forgotten on reload.</p>
      <div class="lw-actions">
        <button ref="opener" type="button" class="lw-button" data-test="review-plan"
                :disabled="!!reviewWhy" aria-describedby="review-why" @click="openReview">Review plan</button>
        <button v-if="token" type="button" class="lw-button lw-button--quiet"
                data-test="forget-token" @click="token = ''">Forget token</button>
        <span id="review-why" class="lw-time" data-test="review-why">{{ reviewWhy || authority }}</span>
      </div>
    </section>

    <p v-if="flow.blocked" class="lw-alert" role="alert" data-test="blocked">{{ flow.blocked }}</p>
    <p v-else-if="flow.message" class="lw-note" role="status" data-test="message">{{ flow.message }}</p>

    <section v-if="incidents.length" class="lw-alert" role="alert" aria-labelledby="incident-heading"
             data-test="incident">
      <h2 id="incident-heading">Incident</h2>
      <ul>
        <li v-for="line in incidents" :key="line">{{ line }}</li>
      </ul>
      <p>No reversal or resend is offered here; the operator resolves it with the provider.</p>
    </section>

    <section aria-labelledby="receipts-heading" data-test="receipts">
      <h2 id="receipts-heading">Provider state and receipts</h2>
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
        <p class="lw-time">
          {{ LABELS[execution.mode] || execution.mode }} · approval {{ execution.approval_id }} ·
          observed snapshot {{ execution.snapshot_id }} · read {{ formatTime(execution.as_of).utc }}
        </p>
        <p v-if="!legs.length" class="lw-note" role="status" data-test="no-legs">
          No legs are recorded yet for this execution; reading again.
        </p>
        <ol class="lw-legs">
          <li v-for="leg in legs" :key="leg.leg_id" class="lw-tile" :data-test="`leg-${leg.kind}`">
            <div class="lw-tile__label">{{ leg.label || leg.kind }}</div>
            <div :class="['lw-status', `lw-status--${leg.tone}`]" data-test="leg-status">
              <span aria-hidden="true">{{ leg.icon }}</span><span>{{ leg.text }}</span>
            </div>
            <div class="lw-time" data-test="receipt-mode">{{ leg.mode }}</div>
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

    <div v-if="flow.open" class="lw-overlay">
      <div ref="dialog" class="lw-dialog" role="dialog" aria-modal="true" aria-labelledby="review-heading"
           data-test="review" @keydown.esc.prevent="closeReview">
        <template v-if="!flow.approval">
          <h2 id="review-heading" ref="heading" tabindex="-1">Review plan · {{ NAMES[policy] }}</h2>
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
          <p class="lw-note">
            The legs and amounts are bound by the server at confirmation; this API offers no
            preview. Confirming creates an approval only: you check its terms before a separate
            Execute.
          </p>
          <form class="lw-field" @submit.prevent>
            <label for="operator-token">Operator token</label>
            <input id="operator-token" v-model="token" type="password" autocomplete="off"
                   spellcheck="false" data-test="token">
          </form>
          <div class="lw-actions">
            <button type="button" class="lw-button" data-test="confirm" :disabled="!!confirmWhy"
                    aria-describedby="confirm-why" @click="confirmApproval">Confirm approval</button>
            <button type="button" class="lw-button lw-button--quiet" :disabled="flow.submitting" @click="closeReview">Cancel</button>
            <span id="confirm-why" class="lw-time" data-test="confirm-why">{{ confirmWhy }}</span>
          </div>
        </template>
        <template v-else>
          <h2 id="review-heading" ref="heading" tabindex="-1">Approved terms · not yet executed</h2>
          <dl class="lw-terms" data-test="bound">
            <dt>Approval</dt><dd>{{ flow.approval.approval_id }}</dd>
            <dt>Entity</dt><dd>{{ flow.approval.entity }}</dd>
            <dt>Account</dt><dd>{{ flow.approval.account }}</dd>
            <dt>Observed snapshot</dt><dd>{{ flow.approval.snapshot_id }}</dd>
            <dt>Provider</dt><dd>{{ LABELS[flow.approval.mode] || flow.approval.mode }}</dd>
            <dt>Plan hash</dt><dd class="lw-hash" data-test="plan-hash">{{ flow.approval.plan_hash }}</dd>
            <dt>Expires</dt>
            <dd data-test="expires">{{ expires.utc }} · {{ expires.local }}</dd>
          </dl>
          <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Bound legs">
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
          <div class="lw-actions">
            <button type="button" class="lw-button" data-test="execute" :disabled="!!executeWhy"
                    aria-describedby="execute-why" @click="executePlan">Execute approved plan</button>
            <button type="button" class="lw-button lw-button--quiet" :disabled="flow.submitting" @click="closeReview">Close</button>
            <span id="execute-why" class="lw-time" role="status" data-test="execute-why">{{ executeWhy }}</span>
          </div>
        </template>
      </div>
    </div>
  </ScreenShell>
</template>

<script>
import { ref } from 'vue'

// The operator token: this tab's memory only. Module scope survives moving between screens and
// dies with the page; it is never written to storage, a URL, markup or a log.
const token = ref('')

// An operation whose outcome this tab does not know, kept in the same tab memory as the token:
// run id -> { blocked, followedId }. Leaving the screen and coming back restores the block and
// resumes reading the execution, so the token never outlives its quarantine. Forget token does
// not lift it: only a reload does.
const unresolved = new Map()

/** The tab reloaded, as far as this screen can tell: token and quarantine both forgotten. */
export function forgetTab () {
  token.value = ''
  unresolved.clear()
}
</script>

<script setup>
import { computed, nextTick, onUnmounted, reactive, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ApiError, LABELS, STATES, ScreenShell, formatMoney, formatTime, getOverview, latestOnly, money,
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
  if (!token.value) return 'Operator authorisation required'
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

const executeWhy = computed(() => {
  const a = flow.approval
  if (!a) return 'Confirm approval first'
  if (flow.blocked) return flow.blocked
  if (flow.invalid) return flow.invalid
  if (flow.executed) return 'Sent once; its status is read below, never sent again'
  if (authority.value) return authority.value
  if (a.mode !== state.body?.mode) return 'The bound provider mode differs from this screen; review again'
  if ((decisions.value?.results ?? []).some((r) => r.branch_id === a.snapshot_id)) {
    return 'Bound to a hypothetical branch, not the observed state; review again'
  }
  if (serverNow.value >= Date.parse(a.expires_at)) return 'Approval expired'
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

/** Still showing the run a POST was sent for: its answer belongs on this screen, not another's. */
const here = (runId) => state.body?.run_id === runId

async function openReview () {
  if (reviewWhy.value) return
  flow.open = true
  await nextTick()
  heading.value?.focus()
}

async function closeReview () {
  if (flow.submitting) return // the answer to an in-flight POST is shown where it was asked
  flow.open = false
  if (flow.invalid || flow.executed || (flow.approval && executeWhy.value && !authority.value)) {
    flow.approval = null
    flow.invalid = ''
    flow.executed = false
  }
  await nextTick()
  opener.value?.focus()
}

async function confirmApproval () {
  if (confirmWhy.value || flow.approval) return
  const runId = state.body.run_id
  flow.submitting = true
  flow.message = ''
  try {
    const answer = await request('/approvals', {
      method: 'POST', token: token.value, signal: AbortSignal.timeout(POST_TIMEOUT_MS),
      body: { run_id: state.body.run_id, policy: policy.value }
    })
    const approval = boundApproval(answer) // unreadable is unknown, and held, even once left
    if (disposed) return
    flow.approval = approval
    flow.serverAt = Date.parse(answer.as_of)
    flow.receivedAt = Date.now()
    now.value = flow.receivedAt
    clock = clock ?? setInterval(() => { now.value = Date.now() }, 1000)
    await nextTick()
    heading.value?.focus()
  } catch (error) {
    if (unanswered(error)) {
      hold(runId, { blocked: APPROVAL_UNKNOWN })
      if (!disposed && here(runId)) flow.blocked = APPROVAL_UNKNOWN
    } else if (!disposed) flow.message = refusal(error)
  } finally {
    flow.submitting = false
  }
}

async function executePlan () {
  if (executeWhy.value) return
  const id = flow.approval.approval_id
  const runId = state.body.run_id
  flow.submitting = true
  flow.executed = true
  try {
    const answer = await request('/executions', {
      method: 'POST', token: token.value, signal: AbortSignal.timeout(POST_TIMEOUT_MS),
      body: { approval_id: id }
    })
    // the server names an execution by its approval id; any other answer is unreadable
    if (answer?.execution_id !== id) throw unreadable()
    hold(runId, { followedId: id })
    if (disposed) return
    if (here(runId)) {
      flow.message = `Execution ${id} accepted; reading its provider state.`
      follow(id)
    }
  } catch (error) {
    if (!unanswered(error)) {
      if (disposed) return
      flow.submitting = false
      flow.invalid = refusal(error)
      return
    }
    const blocked = `Execution outcome unknown; reading its status by approval id ${id}. Do not send again.`
    hold(runId, { blocked, followedId: id, readBy: id })
    if (disposed) return
    if (here(runId)) {
      flow.blocked = blocked
      follow(id)
    }
  }
  flow.submitting = false
  await closeReview()
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

watch(() => state.body, (body) => {
  if (!body) return
  // What this tab holds for the run now shown decides the block and the execution followed: a
  // block or an execution sent for another run is not this screen's. Unresolved work from before
  // the screen was last left is restored, and its execution read again unless the address names
  // another one.
  const held = unresolved.get(body.run_id)
  if (followed && held?.followedId !== followedId.value) {
    followed = false
    followedId.value = null
  }
  const named = route.query.execution_id
  const resume = held?.followedId && !followed && (!named || named === held.followedId)
  if (resume) follow(held.followedId)
  flow.blocked = held?.blocked ? blockFor(held) : ''
  if (resume) return
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

// The view is reused across query-only navigation: a new run or execution is a new screen.
watch(() => [route.query.run_id, route.query.execution_id].join('|'), () => {
  if (!flow.submitting) { // an in-flight POST keeps its review until it is answered
    flow.open = false
    Object.assign(flow, { approval: null, invalid: '', executed: false, message: '' })
    followed = false
    followedId.value = null
    activeId.value = null
    execution.value = null
    notFound.value = false
    pollError.value = ''
    clearTimeout(timer)
  }
  refresh()
})

onUnmounted(() => {
  disposed = true
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
    return { ...leg, text, tone, icon, mode: LABELS[mode] || mode }
  })
})

const incidents = computed(() => {
  const body = execution.value
  if (!body) return []
  return [
    ...body.legs.filter((l) => l.state === 'unknown').map((l) =>
      `${l.leg_id}: Outcome unknown; checking provider status. Do not send again.`),
    ...body.incidents.filter((i) => i.state === 'open').map((i) =>
      `${i.kind.replace(/_/g, ' ')} on ${i.leg_id}, opened ${formatTime(i.opened_at).utc}`)
  ]
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
.lw-overlay {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: var(--lw-space-4);
  overflow-y: auto;
  background: rgb(14 20 17 / 0.45);
}
.lw-dialog {
  width: min(48rem, 100%);
  padding: var(--lw-space-4);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  color: var(--lw-ink);
}
.lw-dialog h2:focus { outline: none; }
.lw-dialog h2:focus-visible { outline: 2px solid var(--lw-focus); }
</style>

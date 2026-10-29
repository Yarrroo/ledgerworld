// Decisions and Execution mounted on responses built from the decisions and execution module
// fixtures and the recorded C6/C3 examples, checked against the UI design fixtures
// decide-execute.json and accessibility.json, loaded unchanged. No request leaves the test: fetch
// is replaced by a table of answers keyed "METHOD /path", and every call is recorded.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Decisions from '../../src/views/Decisions.vue'
import Execution, { forgetTab } from '../../src/views/Execution.vue'

import decideExecute from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/decide-execute.json'
import accessibility from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/accessibility.json'
import policyComparison from '../../../prp/2026-10-20-ledgerworld/design/modules/decisions/fixtures/policy-comparison.json'
import allInfeasible from '../../../prp/2026-10-20-ledgerworld/design/modules/decisions/fixtures/all-infeasible.json'
import approvalBinding from '../../../prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/approval-binding.json'
import legStateMachine from '../../../prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/leg-state-machine.json'
import overviewLf1 from '../../../contracts/examples/c6_api/valid-overview-lf1.json'
import executionSettled from '../../../contracts/examples/c6_api/valid-execution.json'
import boundApproval from '../../../contracts/examples/c3_bound_approval/valid-lf1-integrated.json'
import submittedPayout from '../../../contracts/examples/c4_provider_op/valid-submitted-payout.json'

const kase = (id) => decideExecute.cases.find((c) => c.id === id)
const a11y = (id) => accessibility.cases.find((c) => c.id === id)
const clone = (x) => JSON.parse(JSON.stringify(x))
const Stub = { render: () => h('div', 'stub') }
const TOKEN = 'operator-test-token-not-a-secret'
const ORDER = policyComparison.policies_in_order

// ------------------------------------------------------------------------------ responses

/** GET /decisions/run-1, built from the decisions module's paired comparison (T11). */
function decisionsBody ({ replay = false, cohort = decideExecute.comparison.cohort, mode = 'fake' } = {}) {
  const branches = policyComparison.expect.branches
  const results = Object.keys(branches).flatMap((s) => ORDER.map((policy) => {
    const b = branches[s][policy]
    return {
      policy, scenario_id: s, branch_id: `run-1-${s}-${policy}`, replay,
      obligations_unmet: b.obligations_unmet, floor_kept: b.short_minor === 0,
      min_cash: { minor: b.min_cash, currency: 'USD', status: 'known' },
      funding_cost: { minor: b.funding_cost_minor, currency: 'USD' }, feasible: b.feasible
    }
  }))
  return {
    as_of: '2026-11-05T10:00:00Z', mode, run_id: 'run-1', snapshot_id: 'lf1', checkpoint_round: 3,
    cohort, weight_kind: decideExecute.comparison.weight_kind, status: policyComparison.expect.status,
    results, selected: policyComparison.expect.selected, escalation: null
  }
}

/** The all-infeasible case: nothing selected, the escalation the decisions module names. */
function infeasibleBody () {
  const c = allInfeasible.cases[0].expect
  return {
    ...decisionsBody({ cohort: 's1' }),
    results: decisionsBody().results.filter((r) => r.scenario_id === 's1').map((r) => ({ ...r, floor_kept: false, feasible: false })),
    status: c.status, selected: c.selected,
    escalation: {
      earliest_unmet: `reserve floor on ${c.escalation.earliest_unmet.account} at t=${c.escalation.earliest_unmet.at_h} h`,
      binding: c.escalation.binding, contact: c.escalation.escalate_to
    }
  }
}

const overview = (demo = { run_id: 'run-1', execution_id: null }, mode = 'fake') =>
  ({ ...clone(overviewLf1.instance), demo, mode })

const approvalBody = (patch = {}) => ({
  as_of: approvalBinding.now, mode: 'fake', approval: { ...clone(boundApproval.instance), ...patch }
})

/** POST /executions accepted: the server names the execution by its approval id. */
const accepted = (id = 'apr-1') => ({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: id })

const advance = () => clone(executionSettled.instance.legs[0])
const payout = (patch = {}) => ({
  ...clone(submittedPayout.instance), label: 'payout from the operator account', ...patch
})
const receipt = (leg, status) => ({
  ...advance().receipt, provider_id: `fake-${leg.kind}-1`, request_id: leg.request_id,
  kind: leg.kind, status, amount: '50000.00', label: leg.label, observed_at: '2026-11-05T10:01:45Z'
})

function executionBody ({ legs, incidents = [], mode = 'fake' }) {
  return { ...clone(executionSettled.instance), mode, legs, incidents }
}

const sentPayout = () => {
  const leg = payout({ provider_id: 'fake-payout-1' })
  return { ...leg, receipt: receipt(leg, 'SENT') }
}
const paidPayout = () => {
  const leg = payout({ provider_id: 'fake-payout-1', state: 'settled', reconciled: true, journal_id: 'j-payroll-1' })
  return { ...leg, receipt: receipt(leg, 'PAID') }
}

// ------------------------------------------------------------------------------ transport

const refuse = (status, code, detail = code) => ({ refused: { status, body: { error: { code, detail } } } })
/** A 2xx whose body does not parse: the POST was answered, but what it did cannot be read. */
const UNREADABLE = { unreadable: true }
const timeout = () => new TypeError('The operation was aborted due to timeout')

/** Answer "METHOD /path" from ``answers``; anything unlisted is a 404. Returns the call log. */
function serve (answers) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const path = new URL(url).pathname.replace('/api/v1', '')
    calls.push({ method, path, headers: init.headers, signal: init.signal, body: init.body && JSON.parse(init.body) })
    let answer = answers[`${method} ${path}`]
    if (typeof answer === 'function') answer = await answer()
    if (answer instanceof Error) throw answer
    if (answer === undefined) answer = refuse(404, 'not_found', `nothing at ${path}`)
    if (answer.refused) {
      return { ok: false, status: answer.refused.status, json: async () => clone(answer.refused.body) }
    }
    if (answer === UNREADABLE) {
      const status = { 'POST /approvals': 201, 'POST /executions': 202 }[`${method} ${path}`] ?? 200
      return { ok: true, status, json: async () => { throw new SyntaxError('Unexpected end of JSON input') } }
    }
    return { ok: true, status: 200, json: async () => clone(answer) }
  }))
  return calls
}

const posts = (calls, path) => calls.filter((c) => c.method === 'POST' && (!path || c.path === path))
const gets = (calls, path) => calls.filter((x) => x.method === 'GET' && x.path === path)

async function open (component, path) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/overview', component: Stub },
      { path: '/decisions', component: Decisions },
      { path: '/execution', component: Execution }
    ]
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(component, { global: { plugins: [router] }, attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

const mounted = []
const text = (w, test) => w.get(`[data-test="${test}"]`).text().replace(/\s+/g, ' ')
const disabled = (w, test) => w.get(`[data-test="${test}"]`).attributes('disabled') !== undefined
const focused = () => document.activeElement
/** A link to work held for another run: its words, and its tooltip naming that run (and execution). */
const heldLink = (l) => [l.text().replace(/\s+/g, ' '), l.element.closest('.lw-tip').querySelector('[role="tooltip"]').textContent.trim()]
/** An element's own words, without the tooltip bubbles it carries (hidden until asked for). */
function bare (wrapper) {
  const copy = wrapper.element.cloneNode(true)
  copy.querySelectorAll('[role="tooltip"]').forEach((t) => t.remove())
  return copy.textContent.replace(/\s+/g, ' ').trim()
}
const tipOf = (wrapper) => wrapper.element.closest('.lw-tip').querySelector('[role="tooltip"]').textContent.trim()
/** The scenario-set cost as the screens print it (the design fixture's cost_label predates the plain-words copy). */
const COST = '$2,400 across 3 what-ifs'
const EXEC_ELSEWHERE = 'Read the execution sent for another run'
const RUN_ELSEWHERE = 'Open the other run: approval outcome unknown'
/** The screen's re-read: the tab becomes visible again (the header has no Refresh button). */
async function reread () {
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await nextTick()
}
/** Fake only the timers, so promises and fetch still settle; tick() is one poll interval. */
const fakeTimers = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
const tick = async () => { vi.advanceTimersByTime(5000); await flushPromises() }

async function enterToken (w) {
  await w.get('[data-test="token"]').setValue(TOKEN)
}

/** Execution with a selected decision and nothing executed yet; the operator holds a token. */
async function reviewReady (answers = {}) {
  const calls = serve({
    'GET /overview': overview(),
    'GET /decisions/run-1': decisionsBody(),
    'POST /approvals': approvalBody(),
    ...answers
  })
  const w = await open(Execution, '/execution')
  await w.get('[data-test="review-plan"]').trigger('click')
  await flushPromises()
  await enterToken(w)
  return { w, calls }
}

async function approve (w) {
  await w.get('[data-test="confirm"]').trigger('click')
  await flushPromises()
}

/** The dialog's way out (Cancel before an approval, Close after): it never closes itself. */
async function closeDialog (w) {
  await w.get('[data-test="review"]').find('button.lw-button--quiet').trigger('click')
  await flushPromises()
}

afterEach(async () => {
  while (mounted.length) {
    const w = mounted.pop()
    await w.find('[data-test="forget-token"]').exists() && w.get('[data-test="forget-token"]').trigger('click')
    w.unmount()
  }
  forgetTab()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

// -------------------------------------------------------------------------------- Decisions

describe('Decisions: policies side by side', () => {
  it('shows the three policies in order, each labelled with its cohort and weight kind', async () => {
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody() })
    const w = await open(Decisions, '/decisions')
    const c = decideExecute.comparison
    const tiles = w.findAll('[data-test^="policy-"]')
    expect(tiles.map((t) => t.attributes('data-test'))).toEqual(ORDER.map((p) => `policy-${p}`))
    for (const t of tiles) expect(t.text()).toContain(`${c.weight_kind} · cohort ${c.cohort}`)
    expect(text(w, 'cohort')).toContain(c.estimate_kind)
    expect(w.text()).not.toMatch(/%|probability of/i)
    expect(w.get(`[data-test="policy-${c.expected_selected}"]`).find('[data-test="selected"]').exists()).toBe(true)
  })

  it('states the scenario-set cost apart from the current-plan fee', async () => {
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody() })
    const w = await open(Decisions, '/decisions')
    const cost = w.get('[data-test="policy-integrated"]').get('[data-test="cost"]')
    expect(bare(cost)).toBe(COST)
    expect(cost.get('[role="tooltip"]').text()).toContain('the current plan\'s fee is set at review')
    expect(w.get('[data-test="policy-no-action"]').text()).toContain('broken in 2 of 3 what-ifs')
    expect(w.get('[data-test="policy-integrated"]').text()).toContain('kept in all 3 what-ifs')
  })

  it('all-infeasible offers escalation, not approval', async () => {
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': infeasibleBody() })
    const w = await open(Decisions, '/decisions')
    const esc = text(w, 'escalation')
    const want = allInfeasible.cases[0].expect.escalation
    expect(esc).toContain(want.binding)
    expect(esc).toContain(want.escalate_to)
    expect(esc).toContain('Earliest unmet: reserve floor')
    expect(w.find('[data-test="review-plan"]').exists()).toBe(decideExecute.comparison.all_infeasible.approval_enabled)
    expect(w.text()).toContain('ranking shown, not executable')
  })

  it('a reverse-stress search is labelled as a search, with no probability and no review', async () => {
    const s = kase('search')
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody({ cohort: s.cohort }) })
    const w = await open(Decisions, '/decisions')
    expect(text(w, 'search')).toContain(s.expect.label)
    expect(w.text()).not.toContain('%')
    expect(w.find('[data-test="review-plan"]').exists()).toBe(false)
  })

  it('a replayed comparison is labelled replay and reviews the current observed plan, not the branch', async () => {
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody({ replay: true }) })
    const w = await open(Decisions, '/decisions')
    expect(text(w, 'replay')).toContain('Replay')
    expect(w.text()).toContain('Replay · Hypothetical branch run-1-s1-integrated')
    const review = w.get('[data-test="review-plan"]')
    expect(review.attributes('href')).toBe('/execution?run_id=run-1&review=1')
    expect(tipOf(review)).toContain('worked out again on today\'s real figures')
  })
})

// -------------------------------------------------------------------------------- Execution

describe('Execution: authority and the bounded approval', () => {
  it('public read: screens visible, approval and execution disabled outside authority', async () => {
    const c = kase('public-read')
    const calls = serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody() })
    const w = await open(Execution, '/execution')
    expect(text(w, 'context-provider')).toBe('Simulated provider')
    expect(text(w, 'review-why')).toBe(c.expect.reason)
    expect(w.find('[data-test="token"]').exists()).toBe(false) // the read path never asks for it
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    expect(disabled(w, 'confirm')).toBe(!c.expect.approve_enabled)
    expect(text(w, 'confirm-why')).toBe(c.expect.reason)
    expect(w.find('[data-test="execute"]').exists()).toBe(c.expect.execute_enabled)
    expect(posts(calls)).toHaveLength(0)
  })

  it('review only: shows the terms the API supplies before binding and sends nothing', async () => {
    const { w, calls } = await reviewReady()
    expect(kase('review-only').expect.explicit_confirm_required).toBe(true)
    const review = text(w, 'review')
    expect(review).toContain('15 minutes')
    expect(review).toContain('Simulated provider')
    expect(text(w, 'scenario-cost')).toBe(COST)
    expect(text(w, 'branch-fees')).toContain('s1 $800')
    expect(posts(calls)).toHaveLength(kase('review-only').expect.provider_calls)
  })

  it('approve then execute: two explicit acts, each POST sent once, execution id = approval id', async () => {
    const c = kase('approve-then-execute').expect
    const { w, calls } = await reviewReady({
      'POST /executions': accepted(),
      'GET /executions/apr-1': executionBody({ legs: [advance(), sentPayout()] })
    })
    const confirm = w.get('[data-test="confirm"]')
    await Promise.all([confirm.trigger('click'), confirm.trigger('click')])
    await flushPromises()
    expect(posts(calls, '/approvals')).toHaveLength(c.approval_posts)
    expect(posts(calls, '/executions')).toHaveLength(0) // confirmation is not execution
    expect(text(w, 'plan-hash')).toBe(boundApproval.instance.plan_hash)
    expect(text(w, 'expires')).toContain('2026-11-05 10:15 UTC · local')
    expect(text(w, 'legs')).toContain('$10,000')
    expect(text(w, 'legs')).toContain('reservation:res-payroll-1')

    const execute = w.get('[data-test="execute"]')
    expect(disabled(w, 'execute')).toBe(false)
    await Promise.all([execute.trigger('click'), execute.trigger('click')])
    await flushPromises()
    expect(posts(calls, '/executions')).toHaveLength(c.execution_posts)
    expect(posts(calls, '/executions')[0].body).toEqual({ approval_id: 'apr-1' })
    for (const p of posts(calls)) expect(p.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(calls.some((x) => x.method === 'GET' && x.path === '/executions/apr-1')).toBe(true)
    // the dialog follows what it sent: executing until every leg reads reconciled
    expect(w.get('[data-test="review"]').attributes('data-stage')).toBe('executing')
    expect(w.find('[data-test="execute"]').exists()).toBe(false) // no execute-again action
    await closeDialog(w)
    expect(w.find('[data-test="review"]').exists()).toBe(false)
    expect(text(w, 'context')).toContain(`execution ${c.execution_id === 'approval_id' ? 'apr-1' : c.execution_id}`)
  })

  it('the token stays out of markup, URLs and request bodies', async () => {
    const { w, calls } = await reviewReady()
    await approve(w)
    expect(document.body.innerHTML).not.toContain(TOKEN)
    for (const x of calls) {
      expect(x.path).not.toContain(TOKEN)
      expect(JSON.stringify(x.body ?? {})).not.toContain(TOKEN)
    }
    expect(window.location.href).not.toContain(TOKEN)
    expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toContain(TOKEN)
  })

  it('snapshot moved: the review is invalidated and Execute disabled', async () => {
    const c = kase('snapshot-moved').expect
    const { w, calls } = await reviewReady({ 'POST /executions': refuse(409, kase('snapshot-moved').server_refusal) })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(disabled(w, 'execute')).toBe(!c.invalidate_review || !c.execute_enabled)
    expect(text(w, 'execute-why')).toBe(c.message)
    await w.get('[data-test="execute"]').trigger('click')
    expect(posts(calls, '/executions')).toHaveLength(1)
  })

  it('expired on the server clock: Execute disabled', async () => {
    const c = kase('expired')
    const { w, calls } = await reviewReady({
      'POST /approvals': { ...approvalBody(), as_of: boundApproval.instance.expires_at }
    })
    expect(c.now_equals_expires_at).toBe(true)
    await approve(w)
    expect(disabled(w, 'execute')).toBe(!c.expect.execute_enabled)
    expect(text(w, 'execute-why')).toBe(c.expect.message)
    expect(posts(calls, '/executions')).toHaveLength(0)
  })

  it('bound terms that do not match the review keep Execute disabled', async () => {
    const { w } = await reviewReady({
      'POST /approvals': approvalBody({ mode: 'sandbox' })
    })
    await approve(w)
    expect(disabled(w, 'execute')).toBe(true)
    expect(text(w, 'execute-why')).toContain('mode differs')
  })

  it('approval POST timeout: no repeat, operator resolution required, no invented lookup', async () => {
    const c = kase('approval-post-timeout').expect
    const { w, calls } = await reviewReady({ 'POST /approvals': timeout() })
    await approve(w)
    expect(text(w, 'blocked')).toBe(c.message)
    expect(disabled(w, 'confirm')).toBe(true)
    await w.get('[data-test="confirm"]').trigger('click')
    await flushPromises()
    expect(posts(calls, '/approvals')).toHaveLength(1)
    expect(calls.filter((x) => x.path.startsWith('/approvals/'))).toHaveLength(c.invent_lookup_endpoint ? 1 : 0)
  })

  it('execution POST timeout: resolved by GET on the approval id; 404 is not failure', async () => {
    const c = kase('execution-post-timeout').expect
    const { w, calls } = await reviewReady({ 'POST /executions': timeout() })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    const [method, path] = c.read_route.split(' ')
    expect(calls.filter((x) => x.method === method && x.path === path.replace('/api/v1', ''))).toHaveLength(1)
    expect(posts(calls, '/executions')).toHaveLength(c.repeat_post ? 2 : 1)
    expect(text(w, 'not-found')).toContain('does not mean it failed')
    expect(c.not_found_means_failed).toBe(false)
    expect(disabled(w, 'review-plan')).toBe(!c.manual_new_execution_enabled)
    expect(text(w, 'blocked')).toContain('Do not send again')
  })
})

describe('Execution: provider state, receipts and reconciliation', () => {
  async function showing (body, demoExecution = 'apr-1') {
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: demoExecution }, body.mode),
      'GET /decisions/run-1': decisionsBody({ mode: body.mode }),
      'GET /executions/apr-1': body
    })
    return open(Execution, '/execution')
  }

  it('submitted · SENT reads not reconciled, never paid', async () => {
    const c = kase('submitted')
    const w = await showing(executionBody({ legs: [sentPayout()] }))
    const status = text(w, 'leg-status')
    expect(status).toContain(c.expect.label)
    expect(status).not.toContain('PAID')
  })

  it('PAID reads reconciled as of a time, with provider and journal ids, never final', async () => {
    const c = kase('reconciled').expect
    const w = await showing(executionBody({ legs: [paidPayout()] }))
    expect(text(w, 'leg-status')).toBe(`✓${c.label} 2026-11-05 10:02 UTC`)
    const opened = text(w, 'receipt')
    expect(opened).toContain('fake-payout-1')
    expect(opened).toContain('j-payroll-1')
    expect(c.claim_irreversible_finality).toBe(false)
    expect(w.text()).not.toMatch(/irreversibl|permanently final/i)
    expect(w.text()).toContain('not final')
  })

  it('unknown state renders the incident view and offers nothing to send', async () => {
    const c = kase('unknown').expect
    const leg = payout({ state: 'unknown' })
    const w = await showing(executionBody({ legs: [leg] }))
    expect(w.find('[data-test="incident"]').exists()).toBe(c.incident_visible)
    expect(text(w, 'incident')).toContain(c.message)
    expect(text(w, 'leg-status')).toContain(c.message)
    expect(w.findAll('button').map((b) => b.text())).not.toContain('Execute approved plan')
  })

  it('PAID then FAILED: the success text goes, the incident shows, there is no reverse', async () => {
    const c = kase('paid-then-failed')
    const leg = paidPayout()
    const w = await showing(executionBody({
      legs: [leg],
      incidents: [{ incident_id: 'inc-1', leg_id: leg.leg_id, kind: c.incident, state: 'open', opened_at: '2026-11-05T10:05:00Z' }]
    }))
    expect(text(w, 'leg-status')).not.toContain('reconciled as of')
    expect(text(w, 'incident')).toContain('paid then failed')
    expect(w.findAll('button').some((b) => /revers/i.test(b.text()))).toBe(c.expect.reverse_button)
  })

  it('a fake-mode receipt is labelled simulated provider', async () => {
    const c = kase('fake').expect
    const w = await showing(executionBody({ legs: [advance()] }))
    expect(text(w, 'context-provider')).toBe(c.banner_and_receipt)
    expect(text(w, 'receipt-mode').toLowerCase()).toBe('simulated provider')
    expect(text(w, 'receipt')).toContain(c.banner_and_receipt)
    expect(w.text()).not.toMatch(/live checkpoint/i)
  })

  it('mode B: sandbox banner, and the advance keeps its sandbox-simulation label', async () => {
    const c = kase('mode-b').expect
    const leg = { ...advance(), receipt: { ...advance().receipt, mode: 'sandbox' } }
    const w = await showing(executionBody({ legs: [leg], mode: 'sandbox' }))
    expect(text(w, 'context-provider')).toBe(c.banner)
    expect(text(w, 'leg-advance')).toContain(c.advance_label)
    expect(text(w, 'receipt-mode')).toBe('Airwallex sandbox')
  })

  // board item 149: the ledger-only repayment as GET /executions serialises it (routes._leg) after
  // the outbox's pending → settled ledger_only move: no provider id, so no receipt
  it('mode B: a ledger-only repayment is reconciled locally, never submitted or provider-confirmed', async () => {
    const machine = legStateMachine.ledger_only
    const repayment = {
      leg_id: 'apr-1:repayment', request_id: 'req-repayment-1', kind: 'repayment',
      provider_id: machine.provider_id, state: machine.path.at(-1), receipt: null,
      reconciled: true, journal_id: 'j-repayment-1', label: machine.receipt_label
    }
    const w = await showing(executionBody({ legs: [advance(), repayment], mode: 'sandbox' }))
    const tile = w.get('[data-test="leg-repayment"]')
    const steps = tile.get('[data-test="steps"]')
    const done = steps.findAll('.lw-steps__done').map((s) => s.text())
    expect(done.join(' | ')).not.toMatch(/Submitted|Provider-confirmed/)
    expect(done).toHaveLength(2) // Ready and Reconciled
    expect(steps.findAll('.lw-steps__skipped').map((s) => s.text().replace(/\s+/g, ' '))).toEqual([
      '– Submitted · not applicable', '– Provider-confirmed · not applicable'
    ])
    expect(steps.get('[aria-current="step"]').text()).toMatch(/^● Reconciled · ledger only/)
    expect(tile.get('[data-test="leg-status"]').text()).toMatch(/^✓Ledger only, no provider operation · reconciled as of/)
    expect(tile.get('[data-test="receipt-mode"]').text()).toBe('Ledger only (simulated)')
    expect(tile.find('[data-test="receipt"]').exists()).toBe(false)
    // the provider-backed advance beside it still reaches every milestone on its evidence
    expect(w.get('[data-test="leg-advance"]').findAll('.lw-steps__done')).toHaveLength(4)
  })

  it('no execution linked: unavailable, never another run\'s receipt', async () => {
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody() })
    const w = await open(Execution, '/execution')
    expect(text(w, 'no-execution')).toContain('Unavailable')
    expect(text(w, 'context')).toContain('no execution is linked')
  })

  it('polling updates the state in place and never moves focus', async () => {
    fakeTimers()
    let body = executionBody({ legs: [sentPayout()] })
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': () => body
    })
    const w = await open(Execution, '/execution')
    const token = w.get('[data-test="how-context-bar"]').element
    token.focus()
    body = executionBody({ legs: [paidPayout()] })
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
    expect(focused()).toBe(token)
  })
})

describe('accessibility: keyboard review (mocked transport only)', () => {
  const c = a11y('keyboard-review').expect

  it('focus moves into the review, Escape dismisses it with no POST and returns focus', async () => {
    const { w, calls } = await reviewReady()
    expect(focused().id).toBe('review-heading')
    const buttons = w.get('[data-test="review"]').findAll('button').map((b) => b.text())
    expect(buttons).toEqual(['Approve', 'Cancel']) // logical order: the act, then the way out
    await w.get('[data-test="review"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(!c.escape_dismisses_review_without_post)
    expect(posts(calls)).toHaveLength(0)
    expect(focused()).toBe(w.get('[data-test="review-plan"]').element)
    expect(c.focus_returns_to_opener).toBe(true)
  })

  it('confirm, execute and close by keyboard; Enter on the page executes nothing', async () => {
    const { w, calls } = await reviewReady({
      'POST /executions': accepted(),
      'GET /executions/apr-1': executionBody({ legs: [advance()] })
    })
    await approve(w)
    expect(focused().id).toBe('review-heading')
    await w.get('main').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(posts(calls, '/executions')).toHaveLength(c.enter_on_page_does_not_execute ? 0 : 1)
    expect(w.findAll('button').every((b) => b.attributes('type') === 'button')).toBe(true)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(posts(calls, '/executions')).toHaveLength(1)
    expect(focused().id).toBe('review-heading') // the Execute button went: focus stays in the dialog
    await closeDialog(w)
    expect(focused()).toBe(w.get('[data-test="review-plan"]').element)
  })

  it('every state carries text, not colour alone', async () => {
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': executionBody({ legs: [advance(), sentPayout()] })
    })
    const w = await open(Execution, '/execution')
    for (const s of w.findAll('[data-test="leg-status"]')) {
      expect(s.find('[aria-hidden="true"]').exists()).toBe(true)
      expect(s.text().replace(/^[^A-Za-z]+/, '')).toMatch(/[A-Za-z]{3,}/)
    }
    expect(a11y('status-not-colour').expect.each_state_has_text).toBe(true)
  })
})

describe('vet round 1', () => {
  it('a 5xx on the execution POST is an unknown outcome: read back by approval id, never resent', async () => {
    const { w, calls } = await reviewReady({ 'POST /executions': refuse(504, 'http_error', 'HTTP 504') })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(calls.filter((x) => x.method === 'GET' && x.path === '/executions/apr-1')).toHaveLength(1)
    expect(posts(calls, '/executions')).toHaveLength(1)
    expect(text(w, 'blocked')).toContain('Do not send again')
  })

  it('a 5xx on the approval POST blocks for the operator like a timeout', async () => {
    const { w, calls } = await reviewReady({ 'POST /approvals': refuse(502, 'http_error', 'HTTP 502') })
    await approve(w)
    expect(text(w, 'blocked')).toBe(kase('approval-post-timeout').expect.message)
    expect(disabled(w, 'confirm')).toBe(true)
    expect(posts(calls, '/approvals')).toHaveLength(1)
  })

  it('a failed decisions read still shows the receipts and says why review is unavailable', async () => {
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': refuse(409, 'fork_failed', 'the fork of run-1 failed; fork it again'),
      'GET /executions/apr-1': executionBody({ legs: [advance()] })
    })
    const w = await open(Execution, '/execution')
    expect(text(w, 'leg-status')).toContain('SETTLED · reconciled as of')
    expect(disabled(w, 'review-plan')).toBe(true)
    expect(text(w, 'review-why')).toContain('fork it again')
  })

  it('review=1 opens the review once; Cancel then Refresh does not reopen it', async () => {
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody() })
    const w = await open(Execution, '/execution?run_id=run-1&review=1')
    expect(w.find('[data-test="review"]').exists()).toBe(true)
    await w.get('[data-test="review"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    await reread()
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(false)
  })

  it('an expired approval is dropped on close, so a fresh review can confirm again', async () => {
    const { w } = await reviewReady({
      'POST /approvals': { ...approvalBody(), as_of: boundApproval.instance.expires_at }
    })
    await approve(w)
    expect(text(w, 'execute-why')).toBe('Approval expired')
    await w.get('[data-test="review"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="confirm"]').exists()).toBe(true)
  })
})

describe('vet round 2', () => {

  it('a failed status read after an unanswered execution POST keeps reading', async () => {
    fakeTimers()
    let answer = timeout()
    const { w, calls } = await reviewReady({
      'POST /executions': timeout(), 'GET /executions/apr-1': () => answer
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    answer = executionBody({ legs: [paidPayout()] })
    await tick()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
  })

  it('an execution with no legs yet is not finished: it says so and keeps reading', async () => {
    fakeTimers()
    let body = executionBody({ legs: [] })
    const { w, calls } = await reviewReady({
      'POST /executions': accepted(),
      'GET /executions/apr-1': () => body
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(text(w, 'no-legs')).toContain('No legs are recorded yet')
    body = executionBody({ legs: [advance()] })
    await tick()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
    expect(w.find('[data-test="no-legs"]').exists()).toBe(false)
  })

  it('a settled leg not yet reconciled keeps being read until reconciled', async () => {
    fakeTimers()
    const settledOnly = { ...paidPayout(), reconciled: false }
    let body = executionBody({ legs: [settledOnly] })
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': () => body
    })
    const w = await open(Execution, '/execution')
    expect(text(w, 'leg-status')).toContain('not reconciled')
    body = executionBody({ legs: [paidPayout()] })
    await tick()
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
  })

  it('Refresh re-reads an execution this tab sent', async () => {
    let body = executionBody({ legs: [paidPayout()] })
    const { w } = await reviewReady({
      'POST /executions': accepted(),
      'GET /executions/apr-1': () => body
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(text(w, 'leg-status')).toContain('reconciled as of')
    const leg = paidPayout()
    body = executionBody({ legs: [leg], incidents: [{ incident_id: 'inc-1', leg_id: leg.leg_id, kind: 'paid_then_failed', state: 'open', opened_at: '2026-11-05T10:05:00Z' }] })
    await reread()
    await flushPromises()
    expect(text(w, 'incident')).toContain('paid then failed')
  })

  it('a query-only navigation reloads the screen for the new run', async () => {
    const other = { ...decisionsBody(), run_id: 'run-2' }
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody(), 'GET /decisions/run-2': other })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(text(w, 'cohort')).toContain('Run run-1')
    await w.vm.$router.push('/decisions?run_id=run-2')
    await flushPromises()
    expect(text(w, 'cohort')).toContain('Run run-2')
  })

  it('the review cannot be closed while the execution POST is in flight', async () => {
    let release
    const { w } = await reviewReady({
      'POST /executions': () => new Promise((resolve) => { release = resolve })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.get('[data-test="review"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(true)
    release(refuse(409, 'snapshot_moved'))
    await flushPromises()
    expect(text(w, 'execute-why')).toBe(kase('snapshot-moved').expect.message)
  })

  it('an execution the server does not have is unavailable, not polled forever', async () => {
    fakeTimers()
    const calls = serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-9' }),
      'GET /decisions/run-1': decisionsBody()
    })
    const w = await open(Execution, '/execution')
    await tick()
    await tick()
    expect(gets(calls, '/executions/apr-9')).toHaveLength(1)
    expect(text(w, 'not-found')).toContain('unavailable')
  })
})

describe('vet round 2, re-read', () => {
  it('a navigation during an in-flight POST still reloads the screen for the new run', async () => {
    let release
    const { w, calls } = await reviewReady({
      'POST /executions': () => new Promise((resolve) => { release = resolve }),
      'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' }
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    expect(calls.some((x) => x.path === '/decisions/run-2')).toBe(true)
    expect(text(w, 'context')).toContain('Run run-2')
    release(accepted())
    await flushPromises()
  })
})

describe('a successful POST whose answer cannot be read is an unknown outcome', () => {
  const { approval: _, ...noApproval } = approvalBody()
  const legs = (patch) => boundApproval.instance.legs.map((l, i) => (i ? l : { ...l, ...patch }))
  const approvals = {
    'an unparseable body': UNREADABLE,
    'a body with no approval': noApproval,
    'an approval with no id': approvalBody({ approval_id: undefined }),
    'an approval with no entity': approvalBody({ entity: undefined }),
    'an approval with no legs': approvalBody({ legs: undefined }),
    'an approval with no legs bound': approvalBody({ legs: [] }),
    'a leg with no kind': approvalBody({ legs: legs({ kind: undefined }) }),
    'a leg whose after is not a list': approvalBody({ legs: legs({ after: 'res-1' }) }),
    'a leg whose after holds no leg index': approvalBody({ legs: legs({ after: [{}] }) }),
    'a leg funded by something that is not a source': approvalBody({ legs: legs({ funded_by: {} }) }),
    'an approval with no readable expiry': approvalBody({ expires_at: 'soon' }),
    'an expiry that is not ISO-8601': approvalBody({ expires_at: '1' }),
    'no server time': { ...approvalBody(), as_of: undefined }
  }
  for (const [what, answer] of Object.entries(approvals)) {
    it(`approval POST answered with ${what}: blocked for the operator, never confirmed again`, async () => {
      const { w, calls } = await reviewReady({ 'POST /approvals': answer })
      await approve(w)
      expect(text(w, 'blocked')).toBe(kase('approval-post-timeout').expect.message)
      expect(w.find('[data-test="message"]').exists()).toBe(false) // not shown as a refusal
      expect(w.find('[data-test="execute"]').exists()).toBe(false)
      expect(disabled(w, 'confirm')).toBe(true)
      await w.get('[data-test="confirm"]').trigger('click')
      await flushPromises()
      expect(posts(calls, '/approvals')).toHaveLength(1)
    })
  }

  const executions = {
    'an unparseable body': UNREADABLE,
    'a body with no execution id': { as_of: '2026-11-05T10:00:05Z', mode: 'fake' },
    'another execution id': accepted('apr-9')
  }
  for (const [what, answer] of Object.entries(executions)) {
    it(`execution POST answered with ${what}: read back by the approval id, never resent`, async () => {
      const { w, calls } = await reviewReady({
        'POST /executions': answer,
        'GET /executions/apr-1': executionBody({ legs: [advance(), sentPayout()] })
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      expect(posts(calls, '/executions')).toHaveLength(1)
      expect(calls.filter((x) => x.method === 'GET' && x.path === '/executions/apr-1')).toHaveLength(1)
      expect(calls.some((x) => x.method === 'GET' && x.path === '/executions/apr-9')).toBe(false)
      expect(text(w, 'blocked')).toContain('reading its status by approval id apr-1. Do not send again.')
      expect(text(w, 'context')).toContain('execution apr-1')
      expect(text(w, 'leg-status')).toContain('reconciled as of')
    })
  }

  const paid = () => executionBody({ legs: [paidPayout()] })
  const openIncident = { incident_id: 'inc-1', leg_id: paidPayout().leg_id, state: 'open', opened_at: '2026-11-05T10:05:00Z' }
  const reads = {
    'an unparseable body': UNREADABLE,
    'a body with no legs': accepted(),
    'another execution': { ...paid(), execution_id: 'apr-9' },
    'no provider mode': { ...paid(), mode: undefined },
    'a leg with no state': executionBody({ legs: [{ ...paidPayout(), state: undefined }] }),
    'an incident with no kind': { ...paid(), incidents: [openIncident] },
    'a leg in a state C6 does not have': executionBody({ legs: [{ ...paidPayout(), state: 'cancelled' }] })
  }
  for (const [what, first] of Object.entries(reads)) {
    it(`a status read answered with ${what} is not a state: it says so and reads again`, async () => {
      fakeTimers()
      let answer = first
      const { w, calls } = await reviewReady({
        'POST /executions': accepted(),
        'GET /executions/apr-1': () => answer
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      expect(text(w, 'poll-error')).toContain('the answer could not be read')
      expect(w.find('[data-test="leg-status"]').exists()).toBe(false)
      answer = paid()
      await tick()
      expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
      expect(w.find('[data-test="poll-error"]').exists()).toBe(false)
      expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
    })
  }

  it('a failed read after "not recorded yet" keeps that answer, says so, and the next answer clears it', async () => {
    fakeTimers()
    let answer // unlisted: 404
    const { w } = await reviewReady({ 'POST /executions': accepted(), 'GET /executions/apr-1': () => answer })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(text(w, 'not-found')).toContain('does not mean it failed')
    answer = UNREADABLE
    await tick()
    expect(text(w, 'poll-error')).toContain('the answer could not be read')
    expect(text(w, 'not-found')).toContain('does not mean it failed') // a failed read discards nothing
    expect(w.find('[data-test="no-execution"]').exists()).toBe(false) // a payment just sent
    answer = undefined
    await tick()
    expect(w.find('[data-test="not-found"]').exists()).toBe(true)
    expect(w.find('[data-test="poll-error"]').exists()).toBe(false)
  })

  it('an unreadable linked execution is said so, not "no record", and the review still opens', async () => {
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': UNREADABLE
    })
    const w = await open(Execution, '/execution')
    expect(text(w, 'poll-error')).toContain('the answer could not be read')
    expect(w.find('[data-test="not-found"]').exists()).toBe(false)
    expect(disabled(w, 'review-plan')).toBe(false)
  })

  it('a linked execution whose read failed is read again until it reads, and never said "last loaded"', async () => {
    fakeTimers()
    let answer = UNREADABLE
    const calls = serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': () => answer
    })
    const w = await open(Execution, '/execution')
    expect(text(w, 'poll-error')).toContain('Could not read: the answer could not be read. Reading again.')
    expect(w.find('[data-test="no-execution"]').exists()).toBe(false)
    answer = paid()
    await tick()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
    expect(w.find('[data-test="poll-error"]').exists()).toBe(false)
  })

  const decisionsAnswers = {
    'an unparseable body': UNREADABLE,
    'a selected decision naming no policy': { ...decisionsBody(), selected: null },
    'a result with no funding cost': { ...decisionsBody(), results: [{ ...decisionsBody().results[0], funding_cost: undefined }] }
  }
  for (const [what, answer] of Object.entries(decisionsAnswers)) {
    it(`a decision answered with ${what} is said so, not "no decision", and nothing can be reviewed`, async () => {
      serve({ 'GET /overview': overview(), 'GET /decisions/run-1': answer })
      const w = await open(Execution, '/execution')
      expect(disabled(w, 'review-plan')).toBe(true)
      expect(text(w, 'review-why')).toBe('Decision unavailable: the answer could not be read')
    })
  }

  it('a space-separated time is not read: browsers disagree on it, so it fails closed everywhere', async () => {
    const { w } = await reviewReady({ 'POST /approvals': approvalBody({ expires_at: '2026-11-05 10:15:00+00:00' }) })
    await approve(w)
    expect(text(w, 'blocked')).toBe(kase('approval-post-timeout').expect.message)
  })

  it('a read that fails after the screen is left schedules nothing', async () => {
    fakeTimers()
    const calls = serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': UNREADABLE
    })
    const w = await open(Execution, '/execution')
    vi.advanceTimersByTime(5000) // the re-read is in flight
    mounted.splice(mounted.indexOf(w), 1)
    w.unmount()
    await flushPromises()
    await tick()
    await tick()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
  })

  it('a read refused outright (4xx) is said, and not read again', async () => {
    fakeTimers()
    const calls = serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': refuse(403, 'forbidden', 'not yours')
    })
    const w = await open(Execution, '/execution')
    expect(text(w, 'poll-error')).toContain('not yours')
    expect(text(w, 'poll-error')).not.toContain('Reading again')
    await tick()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(1)
  })

  // board item 167: the header has no Refresh button, and Check the status lives only in the
  // review of an execution this tab sent; the lead names the action that reads again here
  it('a read refused outright names a working way to try again in the lead, and that way reads again', async () => {
    let answer = refuse(403, 'forbidden', 'not yours')
    const calls = serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': () => answer
    })
    const w = await open(Execution, '/execution')
    const lead = () => w.get('[data-test="hero-lead"] [role="tooltip"]').text().trim()
    expect(lead()).toBe('We could not read what the plan you sent moved yet; reload the page to try again.')
    expect(lead()).not.toMatch(/refresh/i)
    expect(w.findAll('button').map((b) => b.text())).not.toContain('Refresh')
    expect(w.find('[data-test="read-status"]').exists()).toBe(false)
    answer = paid()
    await reread() // the screen reads its execution again when shown again, as on a reload
    await flushPromises()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
    expect(w.find('[data-test="poll-error"]').exists()).toBe(false)
  })

  it('a failed read of the linked execution is not shown against the one this tab then sends', async () => {
    const { w } = await reviewReady({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-0' }),
      'GET /executions/apr-0': UNREADABLE,
      'POST /executions': accepted(),
      'GET /executions/apr-1': () => new Promise(() => {}) // still being read
    })
    expect(text(w, 'poll-error')).toContain('the answer could not be read')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(text(w, 'context')).toContain('execution apr-1')
    expect(w.find('[data-test="poll-error"]').exists()).toBe(false)
  })

  it('an unreadable approval answered after the screen is left is held: the run is blocked on return', async () => {
    let release
    const { w, calls } = await reviewReady({ 'POST /approvals': () => new Promise((resolve) => { release = resolve }) })
    await w.get('[data-test="confirm"]').trigger('click')
    mounted.splice(mounted.indexOf(w), 1)
    w.unmount()
    release(UNREADABLE)
    await flushPromises()
    const back = await open(Execution, '/execution')
    expect(text(back, 'blocked')).toBe(kase('approval-post-timeout').expect.message)
    expect(disabled(back, 'review-plan')).toBe(true)
    expect(posts(calls, '/approvals')).toHaveLength(1)
  })

  it('"Reading again" is said exactly when a read is scheduled, and a 429 is read again', async () => {
    fakeTimers()
    let answer = refuse(403, 'forbidden', 'not yours')
    const { w, calls } = await reviewReady({ 'POST /executions': accepted(), 'GET /executions/apr-1': () => answer })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(text(w, 'poll-error')).toContain('not yours. Reading again.') // an execution this tab sent
    answer = refuse(429, 'rate_limited', 'slow down')
    await tick()
    expect(text(w, 'poll-error')).toContain('slow down. Reading again.')
    answer = paid()
    await tick()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(3)
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
  })

  it('a read error ending in a period is not shown with two', async () => {
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': refuse(503, 'http_error', 'down for maintenance.')
    })
    const w = await open(Execution, '/execution')
    expect(text(w, 'poll-error')).toContain('down for maintenance. Reading again.')
  })

  it('a run change leaves no "not recorded yet" from the last execution while the next one loads', async () => {
    let overviewAnswer = overview()
    const { w } = await reviewReady({
      'POST /executions': accepted(),
      'GET /overview': () => overviewAnswer,
      'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' }
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(text(w, 'not-found')).toContain('does not mean it failed')
    overviewAnswer = new Promise(() => {}) // the next screen is still loading
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    expect(w.find('[data-test="not-found"]').exists()).toBe(false)
  })
})

describe('a POST answered after a query navigation stays with its own run', () => {
  /** Review on the demo run (run-1) with the given POST held until ``hold.release`` is called. */
  async function heldOn (route) {
    const hold = {}
    let approvals = 0
    const { w, calls } = await reviewReady({
      // each approval is a new one, and its execution is named by its id
      'POST /approvals': () => approvalBody({ approval_id: `apr-${++approvals}` }),
      [route]: () => new Promise((resolve, reject) => { hold.release = resolve; hold.fail = reject }),
      'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' },
      'GET /decisions/run-3': { ...decisionsBody(), run_id: 'run-3' },
      'GET /executions/apr-1': executionBody({ legs: [paidPayout()] })
    })
    return { w, calls, hold }
  }

  /** Execute on run-1, open run-2 while the POST is held, then answer it. */
  async function answeredOnRun2 (answer = { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' }) {
    const held = await heldOn('POST /executions')
    await approve(held.w)
    await held.w.get('[data-test="execute"]').trigger('click')
    await held.w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    held.hold.release(answer)
    await flushPromises()
    return held
  }

  it('an accepted execution is not shown under the newly selected run, and is read on return', async () => {
    const { w, calls, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(false)
    hold.release({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' })
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-2')
    expect(text(w, 'context')).not.toContain('apr-1')
    expect(w.find('[data-test="leg-payout"]').exists()).toBe(false)
    expect(gets(calls, '/executions/apr-1')).toHaveLength(0)
    expect(text(w, 'message')).toContain('Execution apr-1 for run run-1 was accepted')
    await w.get('[data-test="elsewhere"]').trigger('click')
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-1 · execution apr-1')
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
  })

  it('an unanswered execution keeps its unknown outcome with its own run, never another\'s', async () => {
    const { w, calls, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    hold.fail(timeout())
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-2')
    expect(text(w, 'context')).not.toContain('apr-1')
    expect(gets(calls, '/executions/apr-1')).toHaveLength(0)
    expect(text(w, 'message')).toContain('unknown for run run-1')
    expect(text(w, 'message')).toContain('Do not send again')
    expect(w.find('[data-test="blocked"]').exists()).toBe(false) // the block is run-1's, not run-2's
    expect(heldLink(w.get('[data-test="elsewhere"]'))).toEqual([EXEC_ELSEWHERE, 'Execution apr-1 of run run-1'])
    await w.vm.$router.push('/execution')
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-1 · execution apr-1')
    expect(gets(calls, '/executions/apr-1')).toHaveLength(1)
    expect(text(w, 'blocked')).toContain('reading its status by approval id apr-1')
  })

  it('the outcome reaches its run by any address that names it', async () => {
    const { w } = await answeredOnRun2()
    await w.vm.$router.push('/execution?run_id=run-1')
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-1 · execution apr-1')
    expect(w.find('[data-test="elsewhere"]').exists()).toBe(false)
  })

  it('the link to the outcome survives a further navigation until its run is read', async () => {
    const { w } = await answeredOnRun2()
    await w.vm.$router.push('/execution?run_id=run-3')
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-3')
    expect(heldLink(w.get('[data-test="elsewhere"]'))).toEqual([EXEC_ELSEWHERE, 'Execution apr-1 of run run-1'])
  })

  it('two outcomes that answered on other screens each keep their own link', async () => {
    const { w, hold } = await answeredOnRun2()
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-3')
    await flushPromises()
    hold.release({ as_of: '2026-11-05T10:00:09Z', mode: 'fake', execution_id: 'apr-2' })
    await flushPromises()
    expect(w.findAll('[data-test="elsewhere"]').map(heldLink)).toEqual([
      [EXEC_ELSEWHERE, 'Execution apr-1 of run run-1'], [EXEC_ELSEWHERE, 'Execution apr-2 of run run-2']
    ])
  })

  it('an outcome answered after moving to the same run is shown there, with no review opened meanwhile', async () => {
    const { w, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-1')
    await flushPromises()
    expect(disabled(w, 'review-plan')).toBe(true)
    hold.release({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' })
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(false)
    expect(text(w, 'context')).toContain('Run run-1 · execution apr-1')
  })

  /** Leave the screen (the router unmounts it) and come back to a fresh mount in the same tab. */
  async function remount (w, path = '/execution') {
    mounted.splice(mounted.indexOf(w), 1)
    w.unmount()
    return open(Execution, path)
  }

  it('an execution answered after the view was left is linked on another run\'s screen, not read by the old view', async () => {
    const { w, calls, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    const back = await remount(w, '/execution?run_id=run-2')
    hold.release({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' })
    await flushPromises()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(0)
    await back.get('[data-test="elsewhere"]').trigger('click')
    await flushPromises()
    expect(text(back, 'context')).toContain('Run run-1 · execution apr-1')
  })

  it('an approval answered unknown after the view was left blocks the screen that came back at once', async () => {
    const { w, hold } = await heldOn('POST /approvals')
    await w.get('[data-test="confirm"]').trigger('click')
    const back = await remount(w)
    hold.fail(timeout())
    await flushPromises()
    expect(text(back, 'blocked')).toBe(kase('approval-post-timeout').expect.message)
    expect(disabled(back, 'review-plan')).toBe(true)
  })

  it('an approval answered unknown after moving to another run says so there', async () => {
    const { w, hold } = await heldOn('POST /approvals')
    await w.get('[data-test="confirm"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    hold.fail(timeout())
    await flushPromises()
    expect(text(w, 'message')).toBe(`Run run-1: ${kase('approval-post-timeout').expect.message}`)
  })

  it('a run whose execution answered while away is not reviewed again until that one is read', async () => {
    const { w, calls } = await answeredOnRun2()
    await w.vm.$router.push('/execution?run_id=run-1&execution_id=apr-7')
    await flushPromises()
    expect(text(w, 'review-why')).toBe('Execution apr-1 of this run answered while you were away: read it first')
    expect(disabled(w, 'review-plan')).toBe(true)
    await w.get('[data-test="elsewhere"]').trigger('click')
    await flushPromises()
    expect(text(w, 'context')).toContain('execution apr-1')
    expect(disabled(w, 'review-plan')).toBe(false)
    expect(posts(calls, '/executions')).toHaveLength(1)
  })

  it('an execution answered after leaving is shown at once on a returned screen of its run', async () => {
    const { w, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    const back = await remount(w)
    hold.release({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' })
    await flushPromises()
    expect(text(back, 'context')).toContain('Run run-1 · execution apr-1')
    expect(back.find('[data-test="elsewhere"]').exists()).toBe(false)
    expect(text(back, 'message')).toBe('Execution apr-1 accepted; reading its provider state.')
  })

  it('a read in flight when the view is left does not keep polling from the dead view', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
    let first
    let reads = 0
    const { w, calls } = await reviewReady({
      'POST /executions': { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' },
      'GET /executions/apr-1': () => (++reads === 1 ? new Promise((resolve) => { first = resolve }) : refuse(404, 'not_found'))
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    await remount(w)
    first(refuse(404, 'not_found'))
    await flushPromises()
    const before = gets(calls, '/executions/apr-1').length
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(gets(calls, '/executions/apr-1').length - before).toBe(1) // the live view's read only
  })

  it('an unknown approval for a run left behind keeps a link until that run is open', async () => {
    const { w, hold } = await heldOn('POST /approvals')
    await w.get('[data-test="confirm"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    hold.fail(timeout())
    await flushPromises()
    await w.vm.$router.push('/execution?run_id=run-3')
    await flushPromises()
    expect(heldLink(w.get('[data-test="elsewhere"]'))).toEqual([RUN_ELSEWHERE, 'Run run-1'])
    await w.get('[data-test="elsewhere"]').trigger('click')
    await flushPromises()
    expect(text(w, 'blocked')).toBe(kase('approval-post-timeout').expect.message)
    expect(w.find('[data-test="elsewhere"]').exists()).toBe(false)
  })

  it('forgetting the tab lifts a block shown on screen', async () => {
    const { w } = await reviewReady({ 'POST /approvals': timeout() })
    await approve(w)
    expect(w.find('[data-test="blocked"]').exists()).toBe(true)
    forgetTab()
    await flushPromises()
    expect(w.find('[data-test="blocked"]').exists()).toBe(false)
  })

  it('a returned screen does not send for a run while a left view\'s POST for it is unanswered', async () => {
    const { w, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    const back = await remount(w)
    expect(text(back, 'review-why')).toBe('A request for this run, sent from a screen since left, is not answered yet')
    expect(disabled(back, 'review-plan')).toBe(true)
    hold.release({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' })
    await flushPromises()
    expect(text(back, 'context')).toContain('execution apr-1')
    expect(disabled(back, 'review-plan')).toBe(false)
  })

  it('an unknown approval is linked as an approval, not as the run\'s earlier execution', async () => {
    let approvals = 0
    const held = {}
    const { w } = await reviewReady({
      'POST /approvals': () => (++approvals === 1 ? approvalBody() : new Promise((resolve, reject) => { held.fail = reject })),
      'POST /executions': { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' },
      'GET /executions/apr-1': executionBody({ legs: [paidPayout()] }),
      'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' }
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    await closeDialog(w)
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    await w.get('[data-test="confirm"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    held.fail(timeout())
    await flushPromises()
    expect(heldLink(w.get('[data-test="elsewhere"]'))).toEqual([RUN_ELSEWHERE, 'Run run-1'])
    expect(w.get('[data-test="elsewhere"]').attributes('href')).toBe('/execution?run_id=run-1')
  })

  it('returning to a run in the same view while its POST is unanswered does not offer a review', async () => {
    const { w } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    await w.vm.$router.push('/execution')
    await flushPromises()
    expect(text(w, 'review-why')).toBe('A request for this run, sent from a screen since left, is not answered yet')
    expect(disabled(w, 'review-plan')).toBe(true)
  })

  it('another run is not reviewed while this view\'s approval POST from the last screen is unanswered', async () => {
    const { w, hold } = await heldOn('POST /approvals')
    await w.get('[data-test="confirm"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    expect(text(w, 'review-why')).toBe('A request sent from the last screen is not answered yet')
    expect(disabled(w, 'review-plan')).toBe(true)
    hold.release(approvalBody())
    await flushPromises()
    expect(disabled(w, 'review-plan')).toBe(false)
  })

  it('another run is not reviewed while this view\'s POST from the last screen is unanswered', async () => {
    const { w, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    // a review opened now could be neither confirmed nor closed until run-1 answers
    expect(text(w, 'review-why')).toBe('A request sent from the last screen is not answered yet')
    expect(disabled(w, 'review-plan')).toBe(true)
    hold.release(accepted())
    await flushPromises()
    expect(disabled(w, 'review-plan')).toBe(false)
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    await w.get('[data-test="review"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(false)
  })

  it('a refusal for another run is shown even while this run is blocked', async () => {
    let approvals = 0
    const held = {}
    const { w } = await reviewReady({
      'POST /approvals': () => (++approvals === 1 ? timeout() : approvalBody()),
      'POST /executions': () => new Promise((resolve) => { held.release = resolve }),
      'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' }
    })
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    await approve(w) // run-2's approval outcome is unknown: run-2 is blocked
    await w.vm.$router.push('/execution?run_id=run-1')
    await flushPromises()
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    held.release(refuse(409, 'approval_expired'))
    await flushPromises()
    expect(w.find('[data-test="blocked"]').exists()).toBe(true)
    expect(text(w, 'message')).toBe('Run run-1: Approval expired')
  })

  it('a refusal answered after leaving and returning is shown, and does not disable the next approval', async () => {
    const { w, hold } = await heldOn('POST /executions')
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    await w.vm.$router.push('/execution')
    await flushPromises()
    hold.release(refuse(409, 'snapshot_moved'))
    await flushPromises()
    expect(text(w, 'message')).toBe(`Run run-1: ${kase('snapshot-moved').expect.message}`)
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    await approve(w)
    expect(text(w, 'execute-why')).toBe('')
  })

  it('an approval answered after leaving and returning is not installed in a closed review', async () => {
    const { w, hold } = await heldOn('POST /approvals')
    await w.get('[data-test="confirm"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    await w.vm.$router.push('/execution')
    await flushPromises()
    hold.release(approvalBody())
    await flushPromises()
    expect(text(w, 'message')).toContain('for run run-1')
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="execute"]').exists()).toBe(false)
  })

  it('an approval answered after the navigation is not offered for execution on the new run', async () => {
    const { w, calls, hold } = await heldOn('POST /approvals')
    await w.get('[data-test="confirm"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    hold.release(approvalBody())
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(false)
    expect(text(w, 'message')).toContain('for run run-1')
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="execute"]').exists()).toBe(false)
    expect(text(w, 'review')).toContain('run-2')
    expect(posts(calls, '/executions')).toHaveLength(0)
  })
})

describe('leaving and returning to Execution (board item 95)', () => {
  const APPROVAL_UNKNOWN = kase('approval-post-timeout').expect.message

  /** Leave the screen (the router unmounts it) and come back to a fresh mount in the same tab. */
  async function leaveAndReturn (w, path = '/execution') {
    mounted.splice(mounted.indexOf(w), 1)
    w.unmount()
    return open(Execution, path)
  }

  it('an unknown approval outcome stays blocked on return, while the token is still held', async () => {
    const { w, calls } = await reviewReady({ 'POST /approvals': timeout() })
    await approve(w)
    expect(text(w, 'blocked')).toBe(APPROVAL_UNKNOWN)
    const back = await leaveAndReturn(w)
    expect(back.find('[data-test="forget-token"]').exists()).toBe(true) // the authority survived
    expect(text(back, 'blocked')).toBe(APPROVAL_UNKNOWN)
    expect(disabled(back, 'review-plan')).toBe(true)
    await back.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    expect(back.find('[data-test="confirm"]').exists()).toBe(false)
    expect(posts(calls, '/approvals')).toHaveLength(1)
  })

  it('an unknown execution outcome stays blocked on return and its lookup resumes', async () => {
    const { w, calls } = await reviewReady({ 'POST /executions': timeout() })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(1)
    const back = await leaveAndReturn(w)
    expect(text(back, 'blocked')).toContain('Do not send again')
    expect(disabled(back, 'review-plan')).toBe(true)
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2) // read again by the approval id
    expect(text(back, 'not-found')).toContain('does not mean it failed')
    expect(posts(calls, '/executions')).toHaveLength(1)
  })

  it('an accepted execution is still read on return, not swapped for the demo one', async () => {
    const { w, calls } = await reviewReady({
      'POST /executions': { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' },
      'GET /executions/apr-1': executionBody({ legs: [paidPayout()] })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    const back = await leaveAndReturn(w)
    expect(text(back, 'context')).toContain('execution apr-1')
    expect(text(back, 'leg-status')).toContain('PAID · reconciled as of')
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
  })

  it('a query-only navigation away and back resumes the unknown execution lookup', async () => {
    const { w, calls } = await reviewReady({
      'POST /executions': timeout(),
      'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' }
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    await w.vm.$router.push('/execution?run_id=run-1')
    await flushPromises()
    expect(text(w, 'context')).toContain('execution apr-1')
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
    expect(text(w, 'blocked')).toContain('Do not send again')
  })

  it('an execution the address names is read as named, not swapped for the held one', async () => {
    const { w, calls } = await reviewReady({
      'POST /executions': timeout(),
      'GET /executions/apr-7': executionBody({ legs: [paidPayout()] })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    const back = await leaveAndReturn(w, '/execution?run_id=run-1&execution_id=apr-7')
    expect(text(back, 'context')).toContain('execution apr-7')
    expect(gets(calls, '/executions/apr-1')).toHaveLength(1)
    expect(text(back, 'blocked')).toContain('Do not send again') // still this run's quarantine
    expect(text(back, 'blocked')).toContain('approval apr-1; not read on this screen')
    expect(text(back, 'blocked')).not.toContain('reading its status')
  })

  it('a block belongs to its run: another run is not blocked by it, and coming back restores it', async () => {
    const { w, calls } = await reviewReady({
      'POST /approvals': timeout(),
      'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' }
    })
    await approve(w)
    await w.get('[data-test="review"]').find('button.lw-button--quiet').trigger('click') // Cancel
    await flushPromises()
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    expect(w.find('[data-test="blocked"]').exists()).toBe(false)
    expect(disabled(w, 'review-plan')).toBe(false)
    await w.vm.$router.push('/execution?run_id=run-1')
    await flushPromises()
    expect(text(w, 'blocked')).toBe(APPROVAL_UNKNOWN)
    expect(disabled(w, 'review-plan')).toBe(true)
    expect(posts(calls, '/approvals')).toHaveLength(1)
  })
})

describe('vet round 2: an answer belongs to the run it was sent for (board item 95)', () => {
  const run2 = { 'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' } }
  const APPROVAL_UNKNOWN = kase('approval-post-timeout').expect.message

  it('an approval answered unknown after moving to another run blocks its own run, not that one', async () => {
    let release
    const { w } = await reviewReady({
      ...run2, 'POST /approvals': () => new Promise((resolve) => { release = resolve })
    })
    await w.get('[data-test="confirm"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    release(timeout())
    await flushPromises()
    expect(w.find('[data-test="blocked"]').exists()).toBe(false)
    await w.vm.$router.push('/execution?run_id=run-1')
    await flushPromises()
    expect(text(w, 'blocked')).toBe(APPROVAL_UNKNOWN)
  })

  it('an execution accepted after moving to another run is not read on that run', async () => {
    let release
    const { w } = await reviewReady({
      ...run2,
      'POST /executions': () => new Promise((resolve) => { release = resolve }),
      'GET /executions/apr-1': executionBody({ legs: [paidPayout()] })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    release({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' })
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-2 · no execution is linked')
    await w.vm.$router.push('/execution?run_id=run-1')
    await flushPromises()
    expect(text(w, 'context')).toContain('execution apr-1')
  })

  it('an unknown approval after an accepted execution keeps its own reason on return', async () => {
    let approvals = 0
    const { w } = await reviewReady({
      'POST /approvals': () => (++approvals === 1 ? approvalBody() : timeout()),
      'POST /executions': { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' },
      'GET /executions/apr-1': executionBody({ legs: [paidPayout()] }),
      'GET /executions/apr-7': executionBody({ legs: [paidPayout()] })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    await closeDialog(w)
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
    await approve(w)
    expect(text(w, 'blocked')).toBe(APPROVAL_UNKNOWN)
    mounted.splice(mounted.indexOf(w), 1)
    w.unmount()
    const back = await open(Execution, '/execution?run_id=run-1&execution_id=apr-7')
    expect(text(back, 'blocked')).toBe(APPROVAL_UNKNOWN)
  })

  it('a failed reload keeps the block of the run still on screen', async () => {
    let overviewAnswer = overview()
    const { w } = await reviewReady({ ...run2, 'POST /approvals': timeout(), 'GET /overview': () => overviewAnswer })
    await approve(w)
    overviewAnswer = refuse(500, 'http_error', 'HTTP 500')
    await w.vm.$router.push('/execution?run_id=run-2')
    await flushPromises()
    expect(text(w, 'context')).toContain('Run run-1')
    expect(text(w, 'blocked')).toBe(APPROVAL_UNKNOWN)
  })
})

describe('unmount with a request pending', () => {
  const fakeTimers = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
  const gets = (calls, path) => calls.filter((x) => x.method === 'GET' && x.path === path)
  const held = () => { let release; const promise = new Promise((resolve) => { release = resolve }); return { promise, release } }

  /** Leave the screen with the token still held, as navigating away does; afterEach forgets the tab. */
  async function leave (w) {
    mounted.splice(mounted.indexOf(w), 1)
    w.unmount()
  }

  /** What the gone screen still holds: a late answer must have written none of it. */
  const flowOf = (w) => {
    const { approval, message, blocked, invalid, submitting } = w.vm.flow
    return { approval: approval?.approval_id ?? null, message, blocked, invalid, submitting }
  }

  it('a status read answered after the screen is gone schedules no further read', async () => {
    fakeTimers()
    let answer = executionBody({ legs: [sentPayout()] })
    const calls = serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': () => answer
    })
    const w = await open(Execution, '/execution')
    const pending = held()
    answer = pending.promise
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
    expect(gets(calls, '/executions/apr-1')[1].signal.aborted).toBe(false)
    await leave(w)
    expect(gets(calls, '/executions/apr-1')[1].signal.aborted).toBe(true) // the outstanding read is cancelled
    pending.release(executionBody({ legs: [sentPayout()] }))
    await flushPromises()
    vi.advanceTimersByTime(30000)
    await flushPromises()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(2)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('an execution POST answered after the screen is gone starts no status reads', async () => {
    fakeTimers()
    const pending = held()
    const { w, calls } = await reviewReady({
      'POST /executions': () => pending.promise,
      'GET /executions/apr-1': executionBody({ legs: [sentPayout()] })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await leave(w)
    pending.release({ as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' })
    await flushPromises()
    vi.advanceTimersByTime(30000)
    await flushPromises()
    expect(posts(calls, '/executions')).toHaveLength(1)
    expect(gets(calls, '/executions/apr-1')).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
    expect(flowOf(w).message).toBe('')
  })

  it('an unanswered execution POST failing after the screen is gone starts no status reads', async () => {
    fakeTimers()
    const pending = held()
    const { w, calls } = await reviewReady({ 'POST /executions': () => pending.promise })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await leave(w)
    pending.release(refuse(503, 'unavailable'))
    await flushPromises()
    vi.advanceTimersByTime(30000)
    await flushPromises()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
    expect(flowOf(w).blocked).toBe('')
  })

  it('a refused execution POST after the screen is gone applies no refusal', async () => {
    const pending = held()
    const { w } = await reviewReady({ 'POST /executions': () => pending.promise })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await leave(w)
    pending.release(refuse(409, 'snapshot_moved'))
    await flushPromises()
    expect(flowOf(w).invalid).toBe('')
  })

  it('an approval POST answered after the screen is gone starts no expiry clock', async () => {
    fakeTimers()
    const pending = held()
    const { w } = await reviewReady({ 'POST /approvals': () => pending.promise })
    await w.get('[data-test="confirm"]').trigger('click')
    await leave(w)
    pending.release(approvalBody())
    await flushPromises()
    expect(vi.getTimerCount()).toBe(0)
    expect(flowOf(w).approval).toBe(null)
  })

  it('an approval POST failing after the screen is gone blocks nothing', async () => {
    const pending = held()
    const { w } = await reviewReady({ 'POST /approvals': () => pending.promise })
    await w.get('[data-test="confirm"]').trigger('click')
    await leave(w)
    pending.release(refuse(503, 'unavailable'))
    await flushPromises()
    expect(flowOf(w)).toMatchObject({ approval: null, blocked: '', message: '' })
  })

  it('an unknown execution outcome answered after the screen is gone is still held on return', async () => {
    const pending = held()
    const { w, calls } = await reviewReady({ 'POST /executions': () => pending.promise })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await leave(w)
    pending.release(refuse(503, 'unavailable'))
    await flushPromises()
    expect(gets(calls, '/executions/apr-1')).toHaveLength(0) // nothing read while away
    const back = await open(Execution, '/execution')
    expect(text(back, 'blocked')).toContain('Do not send again')
    expect(disabled(back, 'review-plan')).toBe(true)
    expect(gets(calls, '/executions/apr-1')).toHaveLength(1) // the lookup resumes on return
    expect(posts(calls, '/executions')).toHaveLength(1)
  })

  it('an unknown approval outcome answered after the screen is gone blocks on return', async () => {
    const pending = held()
    const { w } = await reviewReady({ 'POST /approvals': () => pending.promise })
    await w.get('[data-test="confirm"]').trigger('click')
    await leave(w)
    pending.release(refuse(503, 'unavailable'))
    await flushPromises()
    const back = await open(Execution, '/execution')
    expect(text(back, 'blocked')).toBe(kase('approval-post-timeout').expect.message)
    expect(disabled(back, 'review-plan')).toBe(true)
  })
})

describe('correction: a status read never overwrites a newer one', () => {
  const settledOnly = () => ({ ...paidPayout(), reconciled: false })
  const withIncident = () => {
    const leg = paidPayout()
    return executionBody({
      legs: [leg],
      incidents: [{ incident_id: 'inc-1', leg_id: leg.leg_id, kind: 'paid_then_failed', state: 'open', opened_at: '2026-11-05T10:05:00Z' }]
    })
  }
  const HOLD = Symbol('hold')
  /**
   * GET /executions/apr-1 answered from a queue, the last entry repeating. holdThen(next) makes
   * the next read wait for release(body), and every read after it answer `next`.
   */
  function queued (first) {
    const queue = [first]
    let held
    const answer = () => {
      const next = queue.length > 1 ? queue.shift() : queue[0]
      return next === HOLD ? new Promise((resolve) => { held = resolve }) : next
    }
    return { answer, holdThen: (next) => queue.splice(0, queue.length, HOLD, next), release: (body) => held(body) }
  }

  /** Execution linked by the overview, its first read moving (settled, not reconciled). */
  async function openLinked () {
    fakeTimers()
    const reads = queued(executionBody({ legs: [settledOnly()] }))
    const calls = serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': reads.answer
    })
    return { w: await open(Execution, '/execution'), reads, calls }
  }

  it('a poll started before Refresh cannot overwrite the reconciled receipt Refresh read', async () => {
    const { w, reads } = await openLinked()
    expect(text(w, 'leg-status')).toContain('not reconciled')
    reads.holdThen(executionBody({ legs: [paidPayout()] }))
    await tick() // the poll is now in flight, holding the older state
    await reread()
    await flushPromises()
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
    reads.release(executionBody({ legs: [settledOnly()] }))
    await flushPromises()
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
  })

  it('a poll started before Refresh cannot clear the incident Refresh read', async () => {
    const { w, reads } = await openLinked()
    reads.holdThen(withIncident())
    await tick()
    await reread()
    await flushPromises()
    expect(text(w, 'incident')).toContain('paid then failed')
    reads.release(executionBody({ legs: [settledOnly()] }))
    await flushPromises()
    expect(text(w, 'incident')).toContain('paid then failed')
  })

  it('a poll answered after Refresh began reading stays: the older Refresh read does not replace it', async () => {
    const { w, reads } = await openLinked()
    reads.holdThen(withIncident())
    await reread() // Refresh's read is now in flight
    await flushPromises()
    await tick() // a later poll answers with the newer state first
    expect(text(w, 'incident')).toContain('paid then failed')
    reads.release(executionBody({ legs: [settledOnly()] }))
    await flushPromises()
    expect(text(w, 'incident')).toContain('paid then failed')
  })

  it('an execution this tab sent: a poll started before Refresh cannot overwrite its re-read', async () => {
    fakeTimers()
    const reads = queued(executionBody({ legs: [sentPayout()] }))
    const { w } = await reviewReady({
      'POST /executions': { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' },
      'GET /executions/apr-1': reads.answer
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    reads.holdThen(withIncident())
    await tick()
    await reread()
    await flushPromises()
    expect(text(w, 'incident')).toContain('paid then failed')
    reads.release(executionBody({ legs: [sentPayout()] }))
    await flushPromises()
    expect(text(w, 'incident')).toContain('paid then failed')
  })

  it('a poll that fails after Refresh began is no answer: the Refresh read still shows, the error stands', async () => {
    const { w, reads } = await openLinked()
    reads.holdThen(timeout())
    await reread() // Refresh's read is now in flight
    await flushPromises()
    await tick() // a later poll fails
    expect(w.find('[data-test="poll-error"]').exists()).toBe(true)
    reads.release(executionBody({ legs: [paidPayout()] }))
    await flushPromises()
    expect(text(w, 'leg-status')).toContain('PAID · reconciled as of')
    expect(w.find('[data-test="poll-error"]').exists()).toBe(true) // the newest read did fail
  })

  it('a Refresh read older than an applied answer never reaches the screen', async () => {
    const { w, reads, calls } = await openLinked()
    reads.holdThen(refuse(404, 'not_found'))
    await reread()
    await flushPromises()
    await tick() // a later poll answers: the server has no record
    reads.release(executionBody({ legs: [paidPayout()] }))
    await flushPromises()
    expect(w.find('[data-test="not-found"]').exists()).toBe(true)
    // the 404 is the newest answer: no earlier legs stand beside it, and it is not polled again
    expect(w.find('[data-test="leg-status"]').exists()).toBe(false)
    const reads404 = calls.filter((c) => c.path === '/executions/apr-1').length
    await tick()
    expect(calls.filter((c) => c.path === '/executions/apr-1')).toHaveLength(reads404)
  })
})

// A demo cleared while the screen is open: the refresh explains the absence in place of the old
// run's figures, never as a failure whose Retry can only fail again.
describe('no prepared run on refresh', () => {
  it('Decisions shows the empty state, not the last run under an error', async () => {
    let demo = { run_id: 'run-1', execution_id: null }
    serve({ 'GET /overview': () => overview(demo), 'GET /decisions/run-1': decisionsBody(), 'GET /treasury': refuse(404, 'none', 'none') })
    const w = await open(Decisions, '/decisions')
    expect(w.find('[data-test="cohort"]').exists()).toBe(true)
    demo = { run_id: null, execution_id: null }
    await reread()
    await flushPromises()
    expect(w.find('[data-test="error"]').exists()).toBe(false)
    expect(w.get('[data-test="empty"]').text()).toContain('No prepared run yet')
    expect(w.find('[data-test="cohort"]').exists()).toBe(false)
    expect(w.get('main').attributes('aria-busy')).toBe('false')
  })
})

describe('the approval dialog, one stage at a time (board item 133)', () => {
  const stage = (w) => w.get('[data-test="review"]').attributes('data-stage')

  it('review, approved, then reconciled once every leg the execution read is reconciled', async () => {
    const { w } = await reviewReady({
      'POST /executions': accepted(),
      'GET /executions/apr-1': executionBody({ legs: [advance(), paidPayout()] })
    })
    expect(stage(w)).toBe('review')
    await approve(w)
    expect(stage(w)).toBe('approved')
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(stage(w)).toBe('reconciled')
    expect(text(w, 'stage-status')).toContain('not final')
    expect(w.get('[data-test="stage-legs"]').findAll('li')).toHaveLength(2)
    expect(w.find('[data-test="read-status"]').exists()).toBe(true)
  })

  it('an open incident on the sent execution is its own stage, evidence kept, nothing to resend', async () => {
    const leg = paidPayout()
    const { w, calls } = await reviewReady({
      'POST /executions': accepted(),
      'GET /executions/apr-1': executionBody({
        legs: [leg],
        incidents: [{ incident_id: 'inc-1', leg_id: leg.leg_id, kind: 'paid_then_failed', state: 'open', opened_at: '2026-11-05T10:05:00Z' }]
      })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    expect(stage(w)).toBe('incident')
    expect(text(w, 'stage-incident')).toContain('paid then failed')
    expect(text(w, 'incident')).toContain('fake-payout-1') // the page keeps the provider id as evidence
    expect(w.get('[data-test="leg-payout"] [aria-current="step"]').text()).toContain('Provider-confirmed')
    const before = gets(calls, '/executions/apr-1').length
    await w.get('[data-test="read-status"]').trigger('click')
    await flushPromises()
    expect(gets(calls, '/executions/apr-1').length).toBe(before + 1)
    expect(posts(calls, '/executions')).toHaveLength(1)
  })

  it('an unanswered approval is the unknown stage: confirm disabled, the reason said in the dialog', async () => {
    const { w } = await reviewReady({ 'POST /approvals': timeout() })
    await approve(w)
    expect(stage(w)).toBe('unknown')
    expect(text(w, 'stage-blocked')).toBe(kase('approval-post-timeout').expect.message)
    expect(disabled(w, 'confirm')).toBe(true)
  })

  it('an expired approval is the expired stage', async () => {
    const { w } = await reviewReady({
      'POST /approvals': { ...approvalBody(), as_of: boundApproval.instance.expires_at }
    })
    await approve(w)
    expect(stage(w)).toBe('expired')
    expect(disabled(w, 'execute')).toBe(true)
  })

  it('copying the plan hash announces it, and says so when the clipboard refuses', async () => {
    const { w } = await reviewReady()
    await approve(w)
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    await w.get('[data-test="copy-hash"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(boundApproval.instance.plan_hash)
    expect(text(w, 'copied')).toBe('Plan hash copied')
    writeText.mockRejectedValueOnce(new Error('denied'))
    await w.get('[data-test="copy-approval"]').trigger('click')
    await flushPromises()
    expect(text(w, 'copied')).toContain('Approval id not copied')
  })

  it('Tab from the last control wraps to the first, Shift+Tab from the first to the last', async () => {
    const { w } = await reviewReady()
    await approve(w)
    const box = w.get('[data-test="review"]')
    const controls = box.findAll('button, [tabindex="0"]').filter((b) => b.attributes('disabled') === undefined)
    const [first, last] = [controls[0].element, controls[controls.length - 1].element]
    last.focus()
    await box.trigger('keydown', { key: 'Tab' })
    expect(focused()).toBe(first)
    first.focus()
    await box.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(focused()).toBe(last)
  })

  describe('vet round 1', () => {
    it('Escape and Tab still reach the dialog when focus has fallen to the page', async () => {
      const { w } = await reviewReady()
      await approve(w)
      document.body.focus()
      document.activeElement?.blur?.()
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
      await flushPromises()
      expect(w.get('[data-test="review"]').element.contains(focused())).toBe(true)
      document.activeElement.blur()
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      await flushPromises()
      expect(w.find('[data-test="review"]').exists()).toBe(false)
    })

    it('Read status keeps its focus while its read is out', async () => {
      let answer
      const { w } = await reviewReady({
        'POST /executions': accepted(),
        'GET /executions/apr-1': () => answer ?? executionBody({ legs: [sentPayout()] })
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      answer = new Promise(() => {}) // a read that does not answer yet
      const button = w.get('[data-test="read-status"]')
      button.element.focus()
      await button.trigger('click')
      expect(button.attributes('disabled')).toBeUndefined()
      expect(focused()).toBe(button.element)
    })

    it('a status read refused outright is said in the dialog, not "reading status"', async () => {
      const { w } = await reviewReady({
        'POST /executions': accepted(),
        'GET /executions/apr-1': refuse(403, 'forbidden', 'not allowed')
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      expect(text(w, 'stage-status')).toContain('Could not read')
      expect(text(w, 'stage-status')).not.toContain('reading status')
    })

    it('an execution refused for its access is said refused, not "no longer executable"', async () => {
      const { w } = await reviewReady({ 'POST /executions': refuse(401, 'unauthorised', 'bad access') })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      expect(text(w, 'review')).toContain('Execution refused')
      expect(text(w, 'review')).not.toContain('no longer executable')
    })

    it('a block raised for this run while an approval is open is not shown as approved', async () => {
      let approvals = 0
      serve({
        'GET /overview': overview(),
        'GET /decisions/run-1': decisionsBody(),
        'POST /approvals': () => (++approvals === 1 ? approvalBody() : timeout())
      })
      const a = await open(Execution, '/execution')
      await a.get('[data-test="review-plan"]').trigger('click')
      await flushPromises()
      await enterToken(a)
      await approve(a)
      expect(a.get('[data-test="review"]').attributes('data-stage')).toBe('approved')
      const b = await open(Execution, '/execution')
      await b.get('[data-test="review-plan"]').trigger('click')
      await flushPromises()
      await approve(b)
      await flushPromises()
      expect(disabled(a, 'execute')).toBe(true)
      expect(a.get('[data-test="review"]').attributes('data-stage')).toBe('unknown')
      for (const w of [b, a]) { // both views share one tab's memory: released here, in order
        mounted.splice(mounted.indexOf(w), 1)
        w.unmount()
      }
    })

    it('a failed leg is not shown as still in progress at Submitted', async () => {
      serve({
        'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
        'GET /decisions/run-1': decisionsBody(),
        'GET /executions/apr-1': executionBody({ legs: [payout({ state: 'failed' })] })
      })
      const w = await open(Execution, '/execution')
      expect(w.get('[data-test="leg-payout"] [aria-current="step"]').text()).toMatch(/failed/i)
    })

    it('a leg whose outcome is unknown keeps the dialog executing, not incident', async () => {
      const { w } = await reviewReady({
        'POST /executions': accepted(),
        'GET /executions/apr-1': executionBody({ legs: [payout({ state: 'unknown' })] })
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      expect(w.get('[data-test="review"]').attributes('data-stage')).toBe('executing')
    })

    it('two open incidents of one kind on one leg each keep their own evidence row', async () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const leg = { ...paidPayout(), state: 'submitted', reconciled: false } // still moving: read again
      const other = payout({ leg_id: 'leg-2', state: 'unknown' })
      const twice = { leg_id: leg.leg_id, kind: 'paid_then_failed', state: 'open', opened_at: '2026-11-05T10:05:00Z' }
      const pair = [twice, { ...twice, opened_at: '2026-11-05T10:06:00Z' }]
      let body = executionBody({ legs: [other, leg], incidents: pair })
      fakeTimers()
      serve({
        'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
        'GET /decisions/run-1': decisionsBody(),
        'GET /executions/apr-1': () => body
      })
      const w = await open(Execution, '/execution')
      // the unknown leg resolves and a third incident opens: the list is re-keyed, not appended
      body = executionBody({
        legs: [{ ...other, state: 'submitted' }, leg],
        incidents: [...pair, { ...twice, incident_id: 'inc-3', kind: 'amount_mismatch' }]
      })
      await tick()
      expect(w.get('[data-test="incident"]').findAll('ul.lw-evidence > li')).toHaveLength(3)
      expect(warn.mock.calls.flat().join(' ')).not.toMatch(/Duplicate keys/)
      warn.mockRestore()
    })

    it('a poll that changes only the read time does not change what the live status says', async () => {
      fakeTimers()
      let body = executionBody({ legs: [sentPayout()] })
      const { w } = await reviewReady({
        'POST /executions': accepted(),
        'GET /executions/apr-1': () => body
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      const said = text(w, 'stage-status')
      body = { ...executionBody({ legs: [sentPayout()] }), as_of: '2026-11-05T10:09:00Z' }
      await tick()
      expect(text(w, 'stage-status')).toBe(said)
    })
  })

  describe('correction: a failed Read status is said after a terminal stage (board item 150)', () => {
    const incident = () => {
      const leg = paidPayout()
      return executionBody({
        legs: [leg],
        incidents: [{ incident_id: 'inc-1', leg_id: leg.leg_id, kind: 'paid_then_failed', state: 'open', opened_at: '2026-11-05T10:05:00Z' }]
      })
    }

    for (const [name, read, base] of [
      ['reconciled', () => executionBody({ legs: [advance(), paidPayout()] }), 'Every leg reconciled as of'],
      ['incident', incident, 'Check the status stays available']
    ]) {
      it(`${name}: a refused read is said in the dialog, the stage and its last read time kept`, async () => {
        let answer = read()
        const { w } = await reviewReady({
          'POST /executions': accepted(),
          'GET /executions/apr-1': () => answer
        })
        await approve(w)
        await w.get('[data-test="execute"]').trigger('click')
        await flushPromises()
        expect(stage(w)).toBe(name)
        const kept = text(w, 'stage-status')
        answer = refuse(403, 'forbidden', 'not allowed.')
        await w.get('[data-test="read-status"]').trigger('click')
        await flushPromises()
        expect(stage(w)).toBe(name)
        const said = text(w, 'stage-status')
        expect(said).toContain(base)
        expect(said).toContain(kept) // the last successful read's time is not dropped
        expect(said).toContain('Could not read the status of execution apr-1: not allowed. Check the status to try again.')
        expect(said).toContain(`${text(w, 'read-status')} to try again`) // names the button as it is labelled (item 167)
        answer = read()
        await w.get('[data-test="read-status"]').trigger('click')
        await flushPromises()
        expect(text(w, 'stage-status')).toBe(kept) // a later answer clears the error
      })

      it(`${name}: an unanswered read says it is reading again`, async () => {
        fakeTimers()
        let answer = read()
        const { w } = await reviewReady({
          'POST /executions': accepted(),
          'GET /executions/apr-1': () => answer
        })
        await approve(w)
        await w.get('[data-test="execute"]').trigger('click')
        await flushPromises()
        answer = timeout()
        await w.get('[data-test="read-status"]').trigger('click')
        await flushPromises()
        expect(stage(w)).toBe(name)
        expect(text(w, 'stage-status')).toContain(base)
        expect(text(w, 'stage-status')).toContain('Could not read the status of execution apr-1; reading again.')
      })
    }

    it('an unanswered execution POST: a failed read is said beside its unknown outcome', async () => {
      const { w } = await reviewReady({
        'POST /executions': timeout(),
        'GET /executions/apr-1': refuse(403, 'forbidden', 'not allowed')
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      expect(stage(w)).toBe('executing')
      const said = text(w, 'stage-status')
      expect(said).toContain('Execution outcome unknown; reading its status by approval id apr-1. Do not send again.')
      // an execution this tab sent is read until a read shows it finished, refusals included
      expect(said).toContain('Could not read the status of execution apr-1; reading again.')
    })
  })
})


describe('the Approval summary shows the approval this tab holds (board item 151)', () => {
  const held = (w) => w.find('[data-test="summary-held"]')
  const reopen = async (w) => {
    await w.get('[data-test="review-plan"]').trigger('click')
    await flushPromises()
  }

  it('confirmed then closed unexecuted: its terms and expiry are summarised, not "no approval"', async () => {
    const { w, calls } = await reviewReady()
    await approve(w)
    await closeDialog(w)
    expect(w.find('[data-test="review"]').exists()).toBe(false)
    expect(text(w, 'summary')).not.toContain('No approval to summarise')
    expect(text(w, 'summary-held-approval')).toContain('apr-1')
    expect(text(w, 'summary-held-hash')).toContain(boundApproval.instance.plan_hash)
    expect(text(w, 'summary-held-expires')).toContain('2026-11-05 10:15 UTC')
    expect(text(w, 'summary-held-state')).toContain('Approved, not executed')
    expect(posts(calls, '/executions')).toHaveLength(0)
    // reopening shows the same approval, still executable
    await reopen(w)
    expect(w.get('[data-test="review"]').attributes('data-stage')).toBe('approved')
    expect(disabled(w, 'execute')).toBe(false)
  })

  it('past its expiry the summary says it is not executable, and Close on reopen drops it', async () => {
    // the tab's clock too: expiry is the server's as_of plus the time this tab has waited
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    const { w } = await reviewReady()
    await approve(w)
    await closeDialog(w)
    expect(text(w, 'summary-held-state')).toContain('Approved, not executed')
    vi.advanceTimersByTime(15 * 60 * 1000) // as_of 10:00:00 + 15 min = expires_at
    await flushPromises()
    expect(text(w, 'summary-held-state')).toContain('Approval expired')
    expect(text(w, 'summary-held-state')).not.toContain('Approved, not executed')
    await reopen(w)
    expect(w.get('[data-test="review"]').attributes('data-stage')).toBe('expired')
    await closeDialog(w)
    expect(held(w).exists()).toBe(false)
    expect(text(w, 'summary')).toContain('No approval to summarise')
  })

  it('an executed approval is summarised by its execution, not as held', async () => {
    const { w } = await reviewReady({
      'POST /executions': accepted(),
      'GET /executions/apr-1': executionBody({ legs: [advance(), paidPayout()] })
    })
    await approve(w)
    await w.get('[data-test="execute"]').trigger('click')
    await flushPromises()
    await closeDialog(w)
    expect(held(w).exists()).toBe(false)
    expect(text(w, 'summary-approval')).toContain('apr-1')
  })

  it('Forget access drops an unexecuted approval and says so: a fresh review takes access again', async () => {
    const { w, calls } = await reviewReady()
    await approve(w)
    await closeDialog(w)
    await w.get('[data-test="forget-token"]').trigger('click')
    await flushPromises()
    expect(held(w).exists()).toBe(false)
    expect(text(w, 'message')).toBe('Approval apr-1 was not executed and expires unused.')
    await reopen(w)
    expect(w.find('[data-test="token"]').exists()).toBe(true)
    expect(w.find('[data-test="confirm"]').exists()).toBe(true)
    expect(posts(calls, '/executions')).toHaveLength(0)
  })

  it('an approval past its expiry is dropped on Close', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    const { w } = await reviewReady()
    await approve(w)
    vi.advanceTimersByTime(15 * 60 * 1000)
    await flushPromises()
    await closeDialog(w)
    expect(held(w).exists()).toBe(false)
  })

  describe('a refresh that names another prepared run', () => {
    let demo
    const prepared = (answers = {}) => {
      demo = { run_id: 'run-1', execution_id: null }
      return reviewReady({
        'GET /overview': () => overview(demo),
        'GET /decisions/run-2': { ...decisionsBody(), run_id: 'run-2' },
        ...answers
      })
    }
    const refreshTo = async (w, run) => {
      demo = { run_id: run, execution_id: null }
      await reread()
      await flushPromises()
    }

    it('drops the approval: a fresh review for the new run, and nothing comes back with the old one', async () => {
      const { w, calls } = await prepared()
      await approve(w)
      await closeDialog(w)
      expect(held(w).exists()).toBe(true)
      await refreshTo(w, 'run-2')
      expect(text(w, 'context')).toContain('run-2')
      expect(held(w).exists()).toBe(false)
      await reopen(w)
      expect(w.get('[data-test="review"]').attributes('data-stage')).toBe('review')
      expect(w.find('[data-test="execute"]').exists()).toBe(false)
      await closeDialog(w)
      await refreshTo(w, 'run-1')
      expect(held(w).exists()).toBe(false)
      expect(posts(calls, '/executions')).toHaveLength(0)
    })

    it('nothing said for the last run stays: its execution message goes with it', async () => {
      const { w } = await prepared({
        'POST /executions': accepted(),
        'GET /executions/apr-1': executionBody({ legs: [advance(), paidPayout()] })
      })
      await approve(w)
      await w.get('[data-test="execute"]').trigger('click')
      await flushPromises()
      await closeDialog(w)
      expect(text(w, 'message')).toContain('Execution apr-1 accepted')
      await refreshTo(w, 'run-2')
      expect(w.find('[data-test="message"]').exists()).toBe(false)
      expect(text(w, 'context')).toContain('no execution is linked')
    })

    it('an approval answered after the run changed is not installed under the new run', async () => {
      let answer
      const { w } = await prepared({ 'POST /approvals': () => new Promise((resolve) => { answer = resolve }) })
      await w.get('[data-test="confirm"]').trigger('click')
      await flushPromises()
      await refreshTo(w, 'run-2')
      answer(approvalBody())
      await flushPromises()
      expect(held(w).exists()).toBe(false)
      expect(text(w, 'message')).toContain('was created after this screen moved on')
    })
  })
})

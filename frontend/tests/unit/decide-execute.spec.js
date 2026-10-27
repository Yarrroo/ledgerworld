// Decisions and Execution mounted on responses built from the decisions and execution module
// fixtures and the recorded C6/C3 examples, checked against the UI design fixtures
// decide-execute.json and accessibility.json, loaded unchanged. No request leaves the test: fetch
// is replaced by a table of answers keyed "METHOD /path", and every call is recorded.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Decisions from '../../src/views/Decisions.vue'
import Execution from '../../src/views/Execution.vue'

import decideExecute from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/decide-execute.json'
import accessibility from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/accessibility.json'
import policyComparison from '../../../prp/2026-10-20-ledgerworld/design/modules/decisions/fixtures/policy-comparison.json'
import allInfeasible from '../../../prp/2026-10-20-ledgerworld/design/modules/decisions/fixtures/all-infeasible.json'
import approvalBinding from '../../../prp/2026-10-20-ledgerworld/design/modules/execution/fixtures/approval-binding.json'
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
const timeout = () => new TypeError('The operation was aborted due to timeout')

/** Answer "METHOD /path" from ``answers``; anything unlisted is a 404. Returns the call log. */
function serve (answers) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const path = new URL(url).pathname.replace('/api/v1', '')
    calls.push({ method, path, headers: init.headers, body: init.body && JSON.parse(init.body) })
    let answer = answers[`${method} ${path}`]
    if (typeof answer === 'function') answer = await answer()
    if (answer instanceof Error) throw answer
    if (answer === undefined) answer = refuse(404, 'not_found', `nothing at ${path}`)
    if (answer.refused) {
      return { ok: false, status: answer.refused.status, json: async () => clone(answer.refused.body) }
    }
    return { ok: true, status: 200, json: async () => clone(answer) }
  }))
  return calls
}

const posts = (calls, path) => calls.filter((c) => c.method === 'POST' && (!path || c.path === path))

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

afterEach(async () => {
  while (mounted.length) {
    const w = mounted.pop()
    await w.find('[data-test="forget-token"]').exists() && w.get('[data-test="forget-token"]').trigger('click')
    w.unmount()
  }
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
    const cost = w.get('[data-test="policy-integrated"]').get('[data-test="cost"]').text()
    expect(cost).toBe(decideExecute.comparison.cost_label)
    expect(w.get('[data-test="policy-no-action"]').text()).toContain('breached in 2 of 3 scenarios')
    expect(w.get('[data-test="policy-integrated"]').text()).toContain('kept in all 3 scenarios')
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
    expect(w.text()).toContain('re-decided on the current observed snapshot')
  })
})

// -------------------------------------------------------------------------------- Execution

describe('Execution: authority and the bounded approval', () => {
  it('public read: screens visible, approval and execution disabled outside authority', async () => {
    const c = kase('public-read')
    const calls = serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody() })
    const w = await open(Execution, '/execution')
    expect(text(w, 'mode')).toBe('Simulated provider')
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
    expect(text(w, 'scenario-cost')).toBe(decideExecute.comparison.cost_label)
    expect(text(w, 'branch-fees')).toContain('s1 USD 800.00')
    expect(posts(calls)).toHaveLength(kase('review-only').expect.provider_calls)
  })

  it('approve then execute: two explicit acts, each POST sent once, execution id = approval id', async () => {
    const c = kase('approve-then-execute').expect
    const { w, calls } = await reviewReady({
      'POST /executions': { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' },
      'GET /executions/apr-1': executionBody({ legs: [advance(), sentPayout()] })
    })
    const confirm = w.get('[data-test="confirm"]')
    await Promise.all([confirm.trigger('click'), confirm.trigger('click')])
    await flushPromises()
    expect(posts(calls, '/approvals')).toHaveLength(c.approval_posts)
    expect(posts(calls, '/executions')).toHaveLength(0) // confirmation is not execution
    expect(text(w, 'plan-hash')).toBe(boundApproval.instance.plan_hash)
    expect(text(w, 'expires')).toContain('2026-11-05 10:15 UTC · local')
    expect(text(w, 'legs')).toContain('USD 10,000.00')
    expect(text(w, 'legs')).toContain('reservation:res-payroll-1')

    const execute = w.get('[data-test="execute"]')
    expect(disabled(w, 'execute')).toBe(false)
    await Promise.all([execute.trigger('click'), execute.trigger('click')])
    await flushPromises()
    expect(posts(calls, '/executions')).toHaveLength(c.execution_posts)
    expect(posts(calls, '/executions')[0].body).toEqual({ approval_id: 'apr-1' })
    for (const p of posts(calls)) expect(p.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(calls.some((x) => x.method === 'GET' && x.path === '/executions/apr-1')).toBe(true)
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
    expect(text(w, 'mode')).toBe(c.banner_and_receipt)
    expect(text(w, 'receipt-mode').toLowerCase()).toBe('simulated provider')
    expect(text(w, 'receipt')).toContain(c.banner_and_receipt)
    expect(w.text()).not.toMatch(/live checkpoint/i)
  })

  it('mode B: sandbox banner, and the advance keeps its sandbox-simulation label', async () => {
    const c = kase('mode-b').expect
    const leg = { ...advance(), receipt: { ...advance().receipt, mode: 'sandbox' } }
    const w = await showing(executionBody({ legs: [leg], mode: 'sandbox' }))
    expect(text(w, 'mode')).toBe(c.banner)
    expect(text(w, 'leg-advance')).toContain(c.advance_label)
    expect(text(w, 'receipt-mode')).toBe('Airwallex sandbox')
  })

  it('no execution linked: unavailable, never another run\'s receipt', async () => {
    serve({ 'GET /overview': overview(), 'GET /decisions/run-1': decisionsBody() })
    const w = await open(Execution, '/execution')
    expect(text(w, 'no-execution')).toContain('Unavailable')
    expect(text(w, 'context')).toContain('no execution is linked')
  })

  it('polling updates the state in place and never moves focus', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
    let body = executionBody({ legs: [sentPayout()] })
    serve({
      'GET /overview': overview({ run_id: 'run-1', execution_id: 'apr-1' }),
      'GET /decisions/run-1': decisionsBody(),
      'GET /executions/apr-1': () => body
    })
    const w = await open(Execution, '/execution')
    const token = w.get('[data-test="refresh"]').element
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
    expect(buttons).toEqual(['Confirm approval', 'Cancel']) // logical order: the act, then the way out
    await w.get('[data-test="review"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(w.find('[data-test="review"]').exists()).toBe(!c.escape_dismisses_review_without_post)
    expect(posts(calls)).toHaveLength(0)
    expect(focused()).toBe(w.get('[data-test="review-plan"]').element)
    expect(c.focus_returns_to_opener).toBe(true)
  })

  it('confirm, execute and close by keyboard; Enter on the page executes nothing', async () => {
    const { w, calls } = await reviewReady({
      'POST /executions': { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: 'apr-1' },
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

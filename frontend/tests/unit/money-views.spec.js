// Overview, Treasury and Lending mounted on recorded C6 responses (contracts/examples/c6_api,
// recorded from the API on the LF-1/LF-2 fixtures), checked against the UI design fixtures
// money-views.json and data-states.json, loaded unchanged. No request leaves the test: fetch is
// replaced by a table of recorded answers.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Overview from '../../src/views/Overview.vue'
import Treasury from '../../src/views/Treasury.vue'
import Lending from '../../src/views/Lending.vue'
import {
  PLAIN, contextKey, formatMoney, formatTime, freshness, latestOnly, metricText, useReading
} from '../../src/api/v1.js'

import moneyViews from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/money-views.json'
import dataStates from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/data-states.json'
import overviewLf1 from '../../../contracts/examples/c6_api/valid-overview-lf1.json'
import overviewFreeze from '../../../contracts/examples/c6_api/valid-overview-lf2-venue-freeze.json'
import treasuryDelayed from '../../../contracts/examples/c6_api/valid-treasury-lf1-delayed.json'
import lendingLf2 from '../../../contracts/examples/c6_api/valid-lending-lf2.json'
import lendingFreeze from '../../../contracts/examples/c6_api/valid-lending-lf2-venue-freeze.json'
import overviewStale from '../../../contracts/examples/c6_api/valid-overview-lf-stale.json'
import lendingStale from '../../../contracts/examples/c6_api/valid-lending-lf-stale.json'

const record = (view, kase) => moneyViews.records.find((r) => r.view === view && r.case === kase)
const stateCase = (id) => dataStates.cases.find((c) => c.id === id)
const clone = (x) => JSON.parse(JSON.stringify(x))
const Stub = { render: () => h('div', 'stub') }

/** Answer each /api/v1 path from ``answers`` (a body, an Error, or a function returning one). */
function serve (answers) {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const path = new URL(url).pathname.replace('/api/v1', '')
    let answer = answers[path]
    if (typeof answer === 'function') answer = await answer()
    if (answer === undefined) throw new Error(`no recorded answer for ${path}`)
    if (answer instanceof Error) throw answer
    return { ok: true, status: 200, json: async () => clone(answer) }
  }))
}

/** Serve Lending beside an overview of the same context (Lending reads both). */
function serveLending (lending, overview = overviewLf1.instance) {
  const current = () => (typeof lending === 'function' ? lending() : lending)
  serve({
    '/lending': current,
    '/overview': () => {
      const l = current()
      return l instanceof Error ? overview : { ...clone(overview), snapshot_id: l.snapshot_id, mode: l.mode }
    }
  })
}

function router (extra = ['/simulation', '/decisions']) {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/overview', component: Overview },
      { path: '/treasury', component: Treasury },
      { path: '/lending', component: Lending },
      ...extra.map((path) => ({ path, component: Stub }))
    ]
  })
}

async function open (component, path, routes) {
  const r = router(routes)
  await r.push(path)
  await r.isReady()
  const wrapper = mount(component, { global: { plugins: [r] } })
  await flushPromises()
  return wrapper
}

const text = (wrapper, test) => wrapper.get(`[data-test="${test}"]`).text().replace(/\s+/g, ' ')
const disabled = (wrapper, test) => wrapper.get(`[data-test="${test}"]`).attributes('disabled') !== undefined

afterEach(() => vi.unstubAllGlobals())

// ------------------------------------------------------------------- money-views.json

describe('money-views fixture', () => {
  it('the recorded C6 examples are the projections the fixture records describe', () => {
    const o = overviewLf1.instance
    const r = record('Overview', 'no-shock').input
    expect([o.cash.minor, o.spendable.minor, o.coverage.min_projected.minor,
      o.coverage.floor.minor, o.coverage.headroom.minor]).toEqual(
      [r.settled_minor, r.spendable_minor, r.min_projected_cash_minor, r.floor_minor, r.headroom_minor])
    expect(o.upcoming_outflows[0]).toMatchObject({
      obligation_id: r.next_obligation.id, due_at: r.next_obligation.due_at,
      amount: { minor: r.next_obligation.amount_minor }
    })

    const [a] = treasuryDelayed.instance.accounts
    const t = record('Treasury', 'receipt-delayed-240h').input
    expect([a.buckets.settled.minor, a.buckets.reserved.minor, a.spendable.minor, a.floor.minor])
      .toEqual([t.settled_minor, t.reserved_minor, t.spendable_minor, t.floor_minor])
    expect(Math.min(...a.projected.map((p) => p.value.minor))).toBe(t.min_projected_cash_minor)

    for (const [example, kase] of [[lendingLf2, 'lf2-before'], [lendingFreeze, 'lf2-venue-freeze']]) {
      const l = record('Lending', kase).input
      const { parts, K_p: kp } = example.instance.capacity
      expect([parts.settled_known.minor, parts.committed_undrawn.minor, parts.floor.minor, kp.minor])
        .toEqual([l.settled_known_minor, l.committed_undrawn_minor, l.floor_minor, l.K_p_minor])
    }
    expect(lendingFreeze.instance.capacity.authority).toBe(record('Lending', 'lf2-venue-freeze').input.authority)
  })

  it('Overview no-shock: cash, spendability, coverage against the floor, the next deadline', async () => {
    serve({ '/overview': overviewLf1.instance })
    const w = await open(Overview, '/overview')
    const { expect: want } = record('Overview', 'no-shock')
    expect(text(w, 'settled')).toContain(want.settled)
    expect(text(w, 'spendable')).toContain(want.spendable)
    expect(text(w, 'coverage')).toContain(want.coverage)
    expect(text(w, 'floor-status')).toBe(`✓${want.status}`) // icon, then the word
    expect(text(w, 'open-simulation')).toBe(want.cta)
    expect(w.get('[data-test="open-simulation"]').attributes('href')).toBe('/simulation?run_id=run-1')
    expect(text(w, 'due')).toContain('2026-01-06 16:00 UTC')
    expect(text(w, 'due')).toContain('local ')
    expect(text(w, 'due')).toContain('in 40 hours')
    expect(text(w, 'next-obligation')).toContain('USD 50,000.00')
    // source and mode stay on the banner
    expect(text(w, 'context-provider')).toBe(dataStates.labels.fake)
    expect(text(w, 'source')).toBe(`${moneyViews.context.source_label} lf1`)
  })

  it('Overview names why the simulation cannot open when its screen or its run is absent', async () => {
    serve({ '/overview': overviewLf1.instance })
    let w = await open(Overview, '/overview', [])
    expect(disabled(w, 'open-simulation')).toBe(true)
    expect(text(w, 'open-simulation-why')).toBe('The simulation screen is not part of this build')
    const body = clone(overviewLf1.instance)
    body.demo.run_id = null
    serve({ '/overview': body })
    w = await open(Overview, '/overview')
    expect(disabled(w, 'open-simulation')).toBe(true)
    expect(text(w, 'open-simulation-why')).toBe('No demonstration run is prepared')
  })

  it('Overview says it is loading, not that no run exists, while a refresh is in flight', async () => {
    let hold = false
    serve({ '/overview': () => (hold ? new Promise(() => {}) : overviewLf1.instance) })
    const w = await open(Overview, '/overview')
    hold = true
    await w.get('[data-test="refresh"]').trigger('click')
    await flushPromises()
    expect(disabled(w, 'open-simulation')).toBe(true)
    expect(text(w, 'open-simulation-why')).toBe('Loading the current overview')
  })

  it('Treasury receipt-delayed-240h: floor breached, the shortfall and its calculation', async () => {
    serve({ '/treasury': treasuryDelayed.instance })
    const w = await open(Treasury, '/treasury')
    const { expect: want } = record('Treasury', 'receipt-delayed-240h')
    expect(text(w, 'floor-status')).toBe(`✕${want.status}`)
    expect(text(w, 'shortfall')).toBe(want.shortfall)
    const calc = text(w, 'calculation')
    expect(calc).toContain(want.calculation.split(';')[0])
    // the delayed receipt and the withdrawal 48 hours out are named as not yet counted 40 hours out
    expect(calc).toContain('due after this point (in 40 hours), so not counted')
    expect(calc).toMatch(/exchange withdrawal wd-1 in \(expected in 2 days\)/)
    expect(calc).toMatch(/receivable rcv-1 in \(expected in 252 hours\)/)
    // S and P are separate measures
    expect(text(w, 'spendable')).toContain('USD 20,000.00')
    expect(text(w, 'timeline')).toContain('✕ below floor, short USD 10,000.00')
    // payroll stays visible with its reservation and both time labels
    const obligations = text(w, 'obligations')
    expect(obligations).toContain('payroll · payroll-1')
    expect(obligations).toContain('USD 50,000.00')
    expect(obligations).toContain('res-payroll-1')
    expect(obligations).toContain('2026-01-06 16:00 UTC (in 40 hours)')
    // the currency is always named: every money figure carries it, the calculation names it
    for (const figure of w.findAll('.lw-figure')) {
      expect(figure.text()).toMatch(/^(lowest )?USD |^Unknown$|^Not assessed$/)
    }
    expect(calc).toContain('in USD')
  })

  it('Lending lf2-before: K_p and the calculation from its API parts', async () => {
    serveLending(lendingLf2.instance)
    const w = await open(Lending, '/lending')
    const { expect: want } = record('Lending', 'lf2-before')
    expect(text(w, 'capacity-value')).toBe(want.capacity)
    expect(text(w, 'calculation')).toContain(want.calculation)
    expect(text(w, 'facility-terms')).toContain(want.cta)
    const facilities = text(w, 'facilities')
    expect(facilities).toContain('adv-a · revenue_advance')
    expect(facilities).toContain('USD 10,000.00') // principal
    expect(facilities).toContain('USD 800.00') // fee
    expect(facilities).toContain('USD 10,800.00') // owed
    expect(facilities).toContain('Not assessed') // no revenue observed yet: not zero
    expect(w.get('[data-test="fund"]').attributes('href')).toBe('/decisions?run_id=run-1')
  })

  it('Lending lf2-venue-freeze: known funds only, the venue unknown, funding disabled with why', async () => {
    serve({ '/lending': lendingFreeze.instance, '/overview': overviewFreeze.instance })
    const w = await open(Lending, '/lending')
    const { expect: want } = record('Lending', 'lf2-venue-freeze')
    expect(text(w, 'capacity-value')).toBe(want.capacity)
    expect(text(w, 'not-current')).toContain(`Lender venue account · ? ${want.venue}`)
    expect(text(w, 'not-current')).not.toMatch(/USD 0\.00/)
    expect(disabled(w, 'fund')).toBe(!want.funding_enabled)
    expect(text(w, 'fund-why')).toBe(want.reason)
    expect(text(w, 'authority')).toContain('reduced')
  })

  it('Lending shows one moment across the six-hour freshness boundary, not two', async () => {
    // Lending read at t0 + 6 h (pool fresh, full authority); the overview of the same snapshot
    // read later, past the boundary, already lists the pool accounts as not current.
    serveLending(lendingLf2.instance, overviewStale.instance)
    let w = await open(Lending, '/lending')
    expect(text(w, 'authority')).toContain('full')
    expect(w.find('[data-test="not-current"]').exists()).toBe(false)
    // and the other way: Lending past the boundary, the overview still before it (complete)
    serveLending(lendingStale.instance)
    w = await open(Lending, '/lending')
    expect(text(w, 'authority')).toContain('reduced')
    expect(text(w, 'not-current')).toContain('Lender operating account · ◷ Stale')
    expect(text(w, 'not-current')).toContain('Lender venue account · ? Unknown')
    expect(disabled(w, 'fund')).toBe(true)
  })

  it('Lending refuses to merge two snapshots into one apparent state', async () => {
    serve({ '/lending': lendingFreeze.instance, '/overview': overviewLf1.instance })
    const w = await open(Lending, '/lending')
    expect(text(w, 'error')).toContain('different snapshots or modes')
    expect(w.find('[data-test="capacity"]').exists()).toBe(false)
  })
})

// Recorded 7 h after the observation under the venue freeze: two accounts stale (observed, not
// current), the venue unknown. completeness.missing names all three; each keeps its own reason.
describe('a stale account is not current, and it is not unknown', () => {
  it('Overview names each account with its own reason', async () => {
    serve({ '/overview': overviewStale.instance })
    const w = await open(Overview, '/overview')
    const partial = text(w, 'partial')
    expect(partial).toContain('Borrower a operating account · ◷ Stale, as of 2026-01-05 12:00 UTC')
    expect(partial).toContain('Lender operating account · ◷ Stale, as of 2026-01-05 12:00 UTC')
    expect(partial).toContain('Lender venue account · ? Unknown')
    expect(partial).not.toMatch(/operating · \? Unknown/)
    expect(partial).not.toContain('not observed')
    // Cash and S include a stale value and say Stale; K_p counts known balances only.
    expect(partial).toContain('the figures that include it say Stale')
    expect(partial).toContain('Lender capacity counts known balances only')
    expect(text(w, 'settled')).toContain('USD 70,000.00 · stale') // its last value, kept
  })

  it('Lending marks the stale pool account stale and only the venue unknown', async () => {
    serve({ '/lending': lendingStale.instance, '/overview': overviewStale.instance })
    const w = await open(Lending, '/lending')
    const shown = text(w, 'not-current')
    expect(shown).toContain('Lender operating account · ◷ Stale')
    const asOf = w.get('[data-test="not-current"]').findAll('.lw-time').map((t) => t.text())
    expect(asOf).toEqual(['as of 2026-01-05 12:00 UTC']) // the stale one only; unknown has no time
    expect(shown).toContain('Lender venue account · ? Unknown')
    expect(shown).not.toContain('Lender operating account · ? Unknown')
    expect(shown).not.toContain('Borrower a operating account') // not the pool's
    expect(shown).not.toMatch(/not observed/i)
    expect(disabled(w, 'fund')).toBe(true)
  })

  it('only a stale account shows a time, whatever the response carries', () => {
    const at = '2026-01-05T12:00:00Z'
    expect(freshness({ account_id: 'lender/venue', status: 'unknown', as_of: at }).text)
      .toBe('Lender venue account · ? Unknown')
    expect(freshness({ account_id: 'lender/operating', status: 'stale', as_of: at }).at)
      .toBe('2026-01-05 12:00 UTC')
  })
})

// ------------------------------------------------------------------ Treasury: P's terms

function treasuryWith (change) {
  const body = clone(treasuryDelayed.instance)
  change(body, body.accounts[0])
  return body
}

describe('Treasury shows the terms the ledger counts in P', () => {
  it('a committed reservation is counted once, through its outflow, not again as its obligation', async () => {
    serve({
      '/treasury': treasuryWith((body, a) => {
        a.buckets.pending_out.push({
          flow_id: 'out:res-payroll-1', kind: 'payroll', reservation_id: 'res-payroll-1',
          amount: { minor: 5000000, currency: 'USD' }, expected_at: '2026-01-06T16:00:00Z'
        })
      })
    })
    const w = await open(Treasury, '/treasury')
    expect(text(w, 'calculation')).toContain('70,000.00 settled - 50,000.00 payroll = 20,000.00')
    expect(text(w, 'calculation')).not.toContain('payroll - 50,000.00 payroll')
  })

  it('a missed obligation is still owed and is still a term', async () => {
    serve({ '/treasury': treasuryWith((body) => { body.obligations[0].state = 'missed' }) })
    const w = await open(Treasury, '/treasury')
    expect(text(w, 'calculation')).toContain('70,000.00 settled - 50,000.00 payroll = 20,000.00')
  })

  it('an obligation due after the lowest point is named as excluded, not silently dropped', async () => {
    serve({
      '/treasury': treasuryWith((body) => {
        body.obligations.push({ ...clone(body.obligations[0]), obligation_id: 'tax-1', kind: 'tax',
          reservation_id: null, due_at: '2026-01-07T12:00:00Z' })
      })
    })
    const w = await open(Treasury, '/treasury')
    expect(text(w, 'calculation')).toContain('tax tax-1 due (in 60 hours)')
  })

  it('a floor metric with no minor at all reads Unknown, never Floor breached', async () => {
    serve({ '/treasury': treasuryWith((body, a) => { a.floor = { currency: 'USD', status: 'unknown' } }) })
    const w = await open(Treasury, '/treasury')
    expect(text(w, 'floor-status')).toBe('?Unknown')
    expect(w.find('[data-test="shortfall"]').exists()).toBe(false)
  })

  it('an unknown floor reads Unknown, never Floor kept', async () => {
    serve({
      '/treasury': treasuryWith((body, a) => {
        a.floor = { minor: null, currency: 'USD', status: 'unknown', as_of: null }
      })
    })
    const w = await open(Treasury, '/treasury')
    expect(text(w, 'floor-status')).toBe('?Unknown')
    expect(w.find('.lw-status--ok').exists()).toBe(false)
    expect(text(w, 'timeline')).not.toContain('floor kept')
  })
})

// ------------------------------------------------------------------- data-states.json

function overviewWith (metric) {
  const body = clone(overviewLf1.instance)
  body.cash = { ...metric }
  return body
}

function lendingWithKp (change) {
  const lending = clone(lendingLf2.instance)
  lending.capacity.K_p = change(lending.capacity.K_p)
  return lending
}

describe('data-states fixture', () => {
  it('zero stays zero', async () => {
    const c = stateCase('zero')
    expect(metricText({ minor: c.value_minor, currency: 'USD', status: c.status })).toBe(c.expect.text)
    serve({ '/overview': overviewWith({ minor: 0, currency: 'USD', status: 'known' }) })
    const w = await open(Overview, '/overview')
    expect(text(w, 'settled')).toContain(c.expect.text)
  })

  it('unknown is never zero, and an unknown capacity disables funding', async () => {
    const c = stateCase('unknown')
    const unknown = { minor: c.value_minor, currency: 'USD', status: c.status }
    expect(metricText(unknown)).toBe(c.expect.text)
    serve({ '/overview': overviewWith(unknown) })
    const w = await open(Overview, '/overview')
    expect(text(w, 'settled')).toContain(c.expect.text)
    expect(text(w, 'settled')).not.toContain('USD 0.00')

    serveLending(lendingWithKp(() => unknown))
    const l = await open(Lending, '/lending')
    expect(text(l, 'capacity-value')).toBe('Unknown')
    expect(disabled(l, 'fund')).toBe(!c.expect.approval_enabled)
  })

  it('stale keeps its value, says so, shows its as_of and disables funding', async () => {
    const c = stateCase('stale')
    const stale = { minor: c.value_minor, currency: 'USD', status: c.status, as_of: c.as_of }
    serve({ '/overview': overviewWith(stale) })
    const w = await open(Overview, '/overview')
    expect(text(w, 'settled')).toContain(c.expect.text)
    expect(text(w, 'as-of')).toBe('as of 2026-01-04 12:00 UTC')

    serveLending(lendingWithKp((kp) => ({ ...kp, status: 'stale' })))
    const l = await open(Lending, '/lending')
    expect(text(l, 'capacity-value')).toBe('USD 42,000.00 · stale')
    expect(disabled(l, 'fund')).toBe(!c.expect.approval_enabled)
  })

  it('partial shows the known metrics and names what is missing', async () => {
    serve({ '/overview': overviewFreeze.instance })
    const w = await open(Overview, '/overview')
    expect(text(w, 'settled')).toContain('USD 70,000.00')
    expect(text(w, 'lender-capacity')).toContain('USD 27,000.00')
    expect(text(w, 'partial')).toContain('Lender venue account')
  })

  it('unassessed reads Not assessed and never a green floor', async () => {
    const c = stateCase('unassessed')
    const body = clone(overviewLf1.instance)
    body.coverage.floor = { minor: null, currency: 'USD', status: 'unassessed' }
    body.coverage.headroom = { minor: null, currency: 'USD', status: 'unassessed' }
    serve({ '/overview': body })
    const w = await open(Overview, '/overview')
    expect(text(w, 'floor-status')).toBe(`–${c.expect.text}`)
    expect(text(w, 'coverage')).not.toContain('Floor kept')
    expect(w.find('.lw-status--ok').exists()).toBe(c.expect.show_green_feasible)
  })

  it('loading marks the page busy, shows no figure and no enabled action', async () => {
    serve({ '/overview': () => new Promise(() => {}) })
    const r = router()
    await r.push('/overview')
    const w = mount(Overview, { global: { plugins: [r] } })
    await flushPromises()
    expect(w.get('main').attributes('aria-busy')).toBe(String(stateCase('loading').expect.aria_busy))
    expect(w.findAll('.lw-skeleton').length).toBeGreaterThan(0)
    expect(w.get('main').text()).not.toMatch(/\d/)
    expect(text(w, 'mode')).toBe('Bank connection not loaded')
    expect(w.find('a.lw-button').exists()).toBe(false)
  })

  it('a failed refresh keeps the last values labelled not current, and disables funding', async () => {
    const c = stateCase('refresh-failed')
    let fail = false
    serveLending(() => (fail ? new Error('connection reset') : lendingLf2.instance))
    const w = await open(Lending, '/lending')
    expect(w.get('[data-test="fund"]').attributes('href')).toBeDefined()
    fail = true
    await w.get('[data-test="refresh"]').trigger('click')
    await flushPromises()
    expect(text(w, 'error')).toContain(c.expect.previous_values_label)
    expect(text(w, 'capacity-value')).toBe('USD 42,000.00') // last loaded, still shown
    expect(disabled(w, 'fund')).toBe(!c.expect.approval_enabled)
    expect(text(w, 'fund-why')).toBe('Last loaded, not current; reload before funding')
  })

  it('a failed refresh after a context change drops the reloaded notice beside the error', async () => {
    let mode = 'fake'
    let fail = false
    serveLending(() => (fail ? new Error('connection reset') : { ...clone(lendingLf2.instance), mode }))
    const w = await open(Lending, '/lending')
    mode = 'sandbox'
    await w.get('[data-test="refresh"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="context-changed"]').exists()).toBe(true)
    fail = true
    await w.get('[data-test="refresh"]').trigger('click')
    await flushPromises()
    expect(text(w, 'error')).toContain('Last loaded, not current')
    expect(w.find('[data-test="context-changed"]').exists()).toBe(false)
  })

  it('late-response: an answer for a context no longer selected is discarded', () => {
    const c = stateCase('late-response')
    const guard = latestOnly()
    const tickets = {}
    for (const req of c.requests) {
      guard.select(contextKey({ run_id: req.run_id }))
      tickets[req.run_id] = guard.issue()
    }
    guard.select(contextKey({ run_id: c.selected_run_id }))
    const rendered = []
    for (const req of [...c.requests].sort((a, b) => a.arrival_order - b.arrival_order)) {
      if (guard.accept(tickets[req.run_id], contextKey({ run_id: req.run_id }))) rendered.push(req.run_id)
    }
    expect(rendered).toEqual([c.expect.rendered_run_id])
    expect(rendered).not.toContain(c.expect.discard_response_for)
  })

  it('same-context out-of-order polls: the older generation is discarded, the incident stays', () => {
    const c = stateCase('same-context-out-of-order-polls')
    const guard = latestOnly(contextKey({ mode: c.context.mode, run_id: c.context.execution_id }))
    const tickets = c.responses.map(() => guard.issue())
    let shown = null
    const discarded = []
    for (const r of [...c.responses].sort((a, b) => a.arrival_order - b.arrival_order)) {
      if (guard.accept(tickets[r.request_generation - 1])) shown = r
      else discarded.push(r.request_generation)
    }
    expect(discarded).toEqual([c.expect.discard_request_generation])
    expect(shown.provider_status).toBe(c.expect.rendered_provider_status)
    expect(Boolean(shown.incident)).toBe(c.expect.incident_still_visible)
  })

  it('a reading applies only its newest request, whichever answers first', async () => {
    const answers = []
    const probe = mount(defineComponent({
      setup () {
        return useReading(() => new Promise((resolve) => answers.push(resolve)))
      },
      render: () => h('div')
    }))
    probe.vm.refresh() // a second request while the first is out
    answers[0]({ ...clone(overviewLf1.instance), snapshot_id: 'old' })
    await flushPromises()
    expect(probe.vm.state.body).toBe(null)
    expect(probe.vm.state.status).toBe('loading')
    answers[1](clone(overviewLf1.instance))
    await flushPromises()
    expect(probe.vm.state.body.snapshot_id).toBe('lf1')
  })

  it('mode-changed: the banner follows the new answer and nothing old is merged in', async () => {
    const c = stateCase('mode-changed')
    let mode = c.from
    serveLending(() => ({ ...clone(lendingLf2.instance), mode }))
    const w = await open(Lending, '/lending')
    expect(text(w, 'context-provider')).toBe(dataStates.labels[c.from])
    mode = c.to
    await w.get('[data-test="refresh"]').trigger('click')
    await flushPromises()
    expect(text(w, 'context-provider')).toBe(c.expect.banner)
    expect(Boolean(text(w, 'context-changed'))).toBe(c.expect.reload_context)
    expect(text(w, 'context-changed')).toContain(PLAIN[c.to])
  })
})

describe('formatting and labels', () => {
  it('money is integer minor units with the currency named', () => {
    expect(formatMoney(7000000, 'USD')).toBe('USD 70,000.00')
    expect(formatMoney(-1000000, 'USD')).toBe('USD -10,000.00')
    expect(formatMoney(5, 'USD')).toBe('USD 0.05')
    expect(formatMoney(1234, 'JPY')).toBe('JPY 1,234')
  })

  it('an amount beyond exact integers is refused, never printed rounded or in exponent form', () => {
    expect(formatMoney(1e21, 'USD')).toBe('USD Unrepresentable amount')
    expect(formatMoney(2 ** 53 + 2, 'USD')).toBe('USD Unrepresentable amount')
  })

  it('an unparseable time is Unavailable, not a crash', () => {
    expect(formatTime('not a time')).toEqual({ utc: 'Unavailable', local: '' })
  })

  it('a replay of a run with no branch is not called a hypothetical branch', async () => {
    serve({ '/overview': { ...clone(overviewLf1.instance), run_id: 'run-7', replay: true } })
    const w = await open(Overview, '/overview')
    expect(text(w, 'source')).toBe(`${dataStates.labels.replay} · run-7`)
  })

  it('a hypothetical branch or a replay is never labelled the observed snapshot', async () => {
    serve({ '/overview': { ...clone(overviewLf1.instance), branch_id: 'br-integrated' } })
    let w = await open(Overview, '/overview')
    expect(text(w, 'source')).toBe(`${dataStates.labels.branch} br-integrated`)
    serve({ '/overview': { ...clone(overviewLf1.instance), branch_id: 'br-1', replay: true } })
    w = await open(Overview, '/overview')
    expect(text(w, 'source')).toContain(dataStates.labels.replay)
  })
})

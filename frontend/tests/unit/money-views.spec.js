// Overview, Treasury and Lending mounted on recorded C6 responses (contracts/examples/c6_api,
// recorded from the API on the LF-1/LF-2 fixtures), checked against the UI design fixtures
// money-views.json and data-states.json, loaded unchanged. No request leaves the test: fetch is
// replaced by a table of recorded answers.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Overview from '../../src/views/Overview.vue'
import Treasury from '../../src/views/Treasury.vue'
import Lending from '../../src/views/Lending.vue'
import {
  FLOOR_WORDS, STATES, contextKey, formatMoney, formatTime, freshness, latestOnly, metricText, useReading
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
/** What the page shows of an element, its tooltips' words left out (they are not on the page until asked for). */
function shown (wrapper, test) {
  const el = wrapper.get(`[data-test="${test}"]`).element.cloneNode(true)
  for (const bubble of el.querySelectorAll('[role="tooltip"]')) bubble.remove()
  return el.textContent.replace(/\s+/g, ' ').trim()
}
/** The words of the tooltip inside (or on) ``test``. */
const tip = (wrapper, test) => wrapper.get(`[data-test="${test}"] [role="tooltip"]`).text().replace(/\s+/g, ' ')
/** The fixtures' "USD 70,000.00" as the mockups' figure: "$70,000" (MATCH.md item 5, formatMoney). */
const asShown = (s) => s.replace(/USD (-?)(\d[\d,]*)\.(\d\d)/g,
  (_, sign, whole, cents) => `${sign}$${whole}${cents === '00' ? '' : `.${cents}`}`)
/** The tab comes back into view: a screen reads again (the header has no Refresh button). */
async function revisit () {
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await flushPromises()
}

// every screen listens on the document for its tab coming back; one left mounted would answer too
enableAutoUnmount(afterEach)
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
    expect(shown(w, 'settled')).toContain(asShown(want.settled))
    expect(shown(w, 'spendable')).toContain(asShown(want.spendable))
    // the headroom is the figure; the minimum projected cash and the floor it is against, its tooltip
    expect(shown(w, 'coverage')).toContain('$10,000')
    const [minimum, floor] = want.coverage.split(' / ').map((part) => asShown(part.split(' ').slice(0, 2).join(' ')))
    expect(tip(w, 'tip-coverage')).toContain(`lowest point ahead ${minimum} · safety minimum ${floor}`)
    expect(text(w, 'floor-status')).toBe(`${STATES.kept.icon} ${FLOOR_WORDS.kept}`) // icon, then the words
    expect(text(w, 'open-simulation')).toBe(want.cta)
    expect(w.get('[data-test="open-simulation"]').attributes('href')).toBe('/simulation?run_id=run-1')
    expect(text(w, 'due')).toContain('2026-01-06 16:00 UTC')
    expect(text(w, 'due')).toContain(formatTime('2026-01-06T16:00:00Z').local)
    expect(text(w, 'next-due-at')).toContain('in 40h')
    expect(text(w, 'next-obligation')).toContain('$50,000')
    // source and mode stay on the banner
    expect(text(w, 'context-provider')).toBe(dataStates.labels.fake)
    expect(text(w, 'source')).toBe(`${moneyViews.context.source_label} lf1`)
  })

  it('Overview names why the simulation cannot open when its screen or its run is absent', async () => {
    serve({ '/overview': overviewLf1.instance })
    let w = await open(Overview, '/overview', [])
    expect(disabled(w, 'open-simulation')).toBe(true)
    expect(tip(w, 'open-simulation-why')).toBe('The simulation screen is not part of this build')
    const body = clone(overviewLf1.instance)
    body.demo.run_id = null
    serve({ '/overview': body })
    w = await open(Overview, '/overview')
    expect(disabled(w, 'open-simulation')).toBe(true)
    expect(tip(w, 'open-simulation-why')).toBe('No demonstration run is prepared')
  })

  it('Overview says it is loading, not that no run exists, while a refresh is in flight', async () => {
    let hold = false
    serve({ '/overview': () => (hold ? new Promise(() => {}) : overviewLf1.instance) })
    const w = await open(Overview, '/overview')
    hold = true
    await revisit()
    expect(disabled(w, 'open-simulation')).toBe(true)
    expect(tip(w, 'open-simulation-why')).toBe('Loading the current overview')
  })

  it('Treasury receipt-delayed-240h: floor breached, the shortfall and its calculation', async () => {
    serve({ '/treasury': treasuryDelayed.instance })
    const w = await open(Treasury, '/treasury')
    const { expect: want } = record('Treasury', 'receipt-delayed-240h')
    expect(text(w, 'floor-status')).toBe(`${STATES.breached.icon}${FLOOR_WORDS.breached}`) // fixture: ${want.status}
    // the fixture's "USD 10,000.00 at t=40 h": the amount short, then when (40 hours out)
    expect(text(w, 'shortfall')).toBe(`${asShown(want.shortfall.split(' at ')[0])} short on 6 Jan (in 40 hours)`)
    const calc = text(w, 'calculation')
    expect(calc).toContain(want.calculation.split(';')[0])
    // the delayed receipt and the withdrawal 48 hours out are named as not yet counted 40 hours out
    expect(calc).toContain('due after this point (in 40 hours), so not counted')
    expect(calc).toMatch(/exchange withdrawal wd-1 in \(expected in 2 days\)/)
    expect(calc).toMatch(/receivable rcv-1 in \(expected in 252 hours\)/)
    // S and P are separate measures
    expect(shown(w, 'spendable')).toContain('$20,000')
    expect(text(w, 'coverage')).toContain(FLOOR_WORDS.breached)
    // payroll stays visible with its reservation and both time labels (the id, reservation and UTC time in tooltips)
    const payroll = text(w, 'obligation-payroll-1')
    expect(payroll).toContain('payroll')
    expect(payroll).toContain('obligation payroll-1')
    expect(payroll).toContain('$50,000')
    expect(payroll).toContain('set aside')
    expect(payroll).toContain('Reservation res-payroll-1')
    expect(payroll).toContain('in 40 hours')
    expect(payroll).toContain('2026-01-06 16:00 UTC')
    // the currency is always named: every money figure carries its symbol, the calculation names it
    for (const figure of w.findAll('.lw-figure')) {
      expect(figure.text()).toMatch(/^(lowest )?\$|^Unknown$|^Not assessed$/)
    }
    expect(calc).toContain('in USD')
  })

  it('Lending lf2-before: K_p and the calculation from its API parts', async () => {
    serveLending(lendingLf2.instance)
    const w = await open(Lending, '/lending')
    const { expect: want } = record('Lending', 'lf2-before')
    expect(shown(w, 'capacity-value')).toBe(asShown(want.capacity))
    expect(text(w, 'calculation')).toContain(want.calculation)
    expect(text(w, 'view-repayments')).toBe('View repayment schedule')
    const facilities = text(w, 'facilities')
    expect(facilities).toContain('adv-a · revenue_advance')
    expect(facilities).toContain('$10,000') // principal
    expect(facilities).toContain('$800') // fee
    expect(facilities).toContain('$10,800') // owed
    expect(facilities).toContain('Not assessed') // no revenue observed yet: not zero
    expect(w.get('[data-test="fund"]').attributes('href')).toBe('/decisions?run_id=run-1')
  })

  it('Lending lf2-venue-freeze: known funds only, the venue unknown, funding disabled with why', async () => {
    serve({ '/lending': lendingFreeze.instance, '/overview': overviewFreeze.instance })
    const w = await open(Lending, '/lending')
    const { expect: want } = record('Lending', 'lf2-venue-freeze')
    expect(shown(w, 'capacity-value')).toBe(asShown(want.capacity))
    expect(shown(w, 'not-current')).toContain(`Lender venue account · ? ${want.venue}`)
    expect(text(w, 'not-current')).not.toMatch(/\$0(?![\d,])/)
    expect(disabled(w, 'fund')).toBe(!want.funding_enabled)
    expect(tip(w, 'fund-why')).toBe(want.reason)
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
    expect(shown(w, 'not-current')).toContain('Lender operating account · ◷ Stale')
    expect(shown(w, 'not-current')).toContain('Lender venue account · ? Unknown')
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
    // Cash includes a stale value and says Stale, its last value kept
    expect(shown(w, 'settled')).toContain('$70,000 · stale')
  })

  it('Lending marks the stale pool account stale and only the venue unknown', async () => {
    serve({ '/lending': lendingStale.instance, '/overview': overviewStale.instance })
    const w = await open(Lending, '/lending')
    const listed = shown(w, 'not-current')
    expect(listed).toContain('Lender operating account · ◷ Stale')
    // each account's as of is in its tooltip: the stale one only; unknown has no time
    const tips = w.get('[data-test="not-current"]').findAll('[role="tooltip"]').map((t) => t.text())
    expect(tips.filter((t) => /as of/.test(t))).toEqual(['Lender operating account · ◷ Stale, as of 2026-01-05 12:00 UTC (lender/operating)'])
    expect(listed).toContain('Lender venue account · ? Unknown')
    expect(listed).not.toContain('Lender operating account · ? Unknown')
    expect(text(w, 'not-current')).not.toContain('Borrower a operating account') // not the pool's
    expect(text(w, 'not-current')).not.toMatch(/not observed/i)
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
    expect(text(w, 'coverage')).not.toContain(FLOOR_WORDS.kept)
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
    expect(metricText({ minor: c.value_minor, currency: 'USD', status: c.status })).toBe(asShown(c.expect.text))
    serve({ '/overview': overviewWith({ minor: 0, currency: 'USD', status: 'known' }) })
    const w = await open(Overview, '/overview')
    expect(shown(w, 'settled')).toBe(`Settled cash${asShown(c.expect.text)}`)
  })

  it('unknown is never zero, and an unknown capacity disables funding', async () => {
    const c = stateCase('unknown')
    const unknown = { minor: c.value_minor, currency: 'USD', status: c.status }
    expect(metricText(unknown)).toBe(c.expect.text)
    serve({ '/overview': overviewWith(unknown) })
    const w = await open(Overview, '/overview')
    expect(shown(w, 'settled')).toBe(`Settled cash${c.expect.text}`)
    expect(text(w, 'settled')).not.toMatch(/\$0(?![\d,])/)

    serveLending(lendingWithKp(() => unknown))
    const l = await open(Lending, '/lending')
    expect(shown(l, 'capacity-value')).toBe('Unknown')
    expect(disabled(l, 'fund')).toBe(!c.expect.approval_enabled)
  })

  it('stale keeps its value, says so, shows its as_of and disables funding', async () => {
    const c = stateCase('stale')
    const stale = { minor: c.value_minor, currency: 'USD', status: c.status, as_of: c.as_of }
    serve({ '/overview': overviewWith(stale) })
    const w = await open(Overview, '/overview')
    expect(shown(w, 'settled')).toContain(asShown(c.expect.text))
    expect(tip(w, 'tip-settled')).toContain('Stale as of 2026-01-04 12:00 UTC')

    serveLending(lendingWithKp((kp) => ({ ...kp, status: 'stale' })))
    const l = await open(Lending, '/lending')
    expect(shown(l, 'capacity-value')).toBe('$42,000 · stale')
    expect(disabled(l, 'fund')).toBe(!c.expect.approval_enabled)
  })

  it('partial shows the known metrics and names what is missing', async () => {
    serve({ '/overview': overviewFreeze.instance })
    const w = await open(Overview, '/overview')
    expect(shown(w, 'settled')).toContain('$70,000')
    expect(shown(w, 'spendable')).toContain('$20,000')
    // (Overview has no lender-capacity figure since mockup 01: the lender's capacity rides its
    // node in World exposure, drawn only when the API serves a relation, and this fixture has none)
    expect(text(w, 'partial')).toContain('Lender venue account')
  })

  it('unassessed reads Not assessed and never a green floor', async () => {
    const c = stateCase('unassessed')
    const body = clone(overviewLf1.instance)
    body.coverage.floor = { minor: null, currency: 'USD', status: 'unassessed' }
    body.coverage.headroom = { minor: null, currency: 'USD', status: 'unassessed' }
    serve({ '/overview': body })
    const w = await open(Overview, '/overview')
    expect(text(w, 'floor-status')).toBe(`– ${c.expect.text}`)
    expect(text(w, 'coverage')).not.toContain(FLOOR_WORDS.kept)
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
    expect(text(w, 'mode')).toBe('Provider not loaded')
    expect(w.find('a.lw-button').exists()).toBe(false)
  })

  it('a failed refresh keeps the last values labelled not current, and disables funding', async () => {
    const c = stateCase('refresh-failed')
    let fail = false
    serveLending(() => (fail ? new Error('connection reset') : lendingLf2.instance))
    const w = await open(Lending, '/lending')
    expect(w.get('[data-test="fund"]').attributes('href')).toBeDefined()
    fail = true
    await revisit()
    expect(text(w, 'error')).toContain(c.expect.previous_values_label)
    expect(shown(w, 'capacity-value')).toBe('$42,000') // last loaded, still shown
    expect(disabled(w, 'fund')).toBe(!c.expect.approval_enabled)
    expect(tip(w, 'fund-why')).toBe('Last loaded, not current; reload before funding')
  })

  it('a failed refresh after a context change drops the reloaded notice beside the error', async () => {
    let mode = 'fake'
    let fail = false
    serveLending(() => (fail ? new Error('connection reset') : { ...clone(lendingLf2.instance), mode }))
    const w = await open(Lending, '/lending')
    mode = 'sandbox'
    await revisit()
    expect(w.find('[data-test="context-changed"]').exists()).toBe(true)
    fail = true
    await revisit()
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
    await revisit()
    expect(text(w, 'context-provider')).toBe(c.expect.banner)
    expect(Boolean(text(w, 'context-changed'))).toBe(c.expect.reload_context)
    expect(text(w, 'context-changed')).toContain(c.expect.banner) // the header names the provider (MATCH.md item 3)
  })
})

describe('formatting and labels', () => {
  it('money is integer minor units with the currency named', () => {
    expect(formatMoney(7000000, 'USD')).toBe('$70,000')
    expect(formatMoney(7000050, 'USD')).toBe('$70,000.50')
    expect(formatMoney(-1000000, 'USD')).toBe('-$10,000')
    expect(formatMoney(5, 'USD')).toBe('$0.05')
    expect(formatMoney(1234, 'JPY')).toBe('JPY 1,234')
    expect(formatMoney(1230, 'CHF')).toBe('CHF 12.30')
  })

  it('an amount beyond exact integers is refused, never printed rounded or in exponent form', () => {
    expect(formatMoney(1e21, 'USD')).toBe('Unrepresentable amount')
    expect(formatMoney(2 ** 53 + 2, 'USD')).toBe('Unrepresentable amount')
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

// ------------------------------------------------- the rebuilt Treasury and Lending (items 159, 160)

describe('Treasury as mockup 02 keeps its rules', () => {
  it('a bridge with nothing held lists no "Less" line', async () => {
    serve({
      '/treasury': treasuryWith((body, a) => {
        a.buckets.reserved = { minor: 0, currency: 'USD' }
        body.obligations[0].reservation_id = null
      })
    })
    const w = await open(Treasury, '/treasury')
    expect(text(w, 'spend-bridge')).not.toContain('Less')
  })

  it('a past deadline reads "5h ago", never "h-5"', async () => {
    serve({ '/treasury': treasuryWith((body) => { body.obligations[0].due_at = '2026-01-04T19:00:00Z' }) })
    const w = await open(Treasury, '/treasury')
    expect(shown(w, 'obligation-payroll-1')).toContain('5h ago')
    expect(shown(w, 'obligation-payroll-1')).not.toContain('h-5')
  })

  it('a deep link to the one account lands on a focusable panel, named once', async () => {
    serve({ '/treasury': treasuryDelayed.instance })
    const w = await open(Treasury, '/treasury?focus=account:borrower-a/operating')
    const targets = w.findAll('[data-focus="account:borrower-a/operating"]')
    expect(targets).toHaveLength(1)
    expect(targets[0].attributes('tabindex')).toBe('-1')
  })

  it('with several accounts the selector, not the panel, is the deep link target', async () => {
    serve({
      '/treasury': treasuryWith((body, a) => { body.accounts.push({ ...clone(a), id: 'borrower-a/reserve' }) })
    })
    const w = await open(Treasury, '/treasury?focus=account:borrower-a/operating')
    expect(w.findAll('[data-focus="account:borrower-a/operating"]')).toHaveLength(1)
    expect(w.get('.lw-tre').attributes('data-focus')).toBeUndefined()
  })
})

describe('Lending as mockup 03: the map draws each party once', () => {
  const venue = (source) => ({ kind: 'venue_exposure', ref: `x-${source}`, source: { entity_id: source, name: source },
    target: { entity_id: 'venue', name: 'Exchange venue' }, amount: null })
  const withOverview = (change) => { const o = clone(overviewLf1.instance); change(o); return o }
  const nodeIds = (w) => w.findAll('[data-test="map-node"]').map((n) => n.attributes('data-node'))
  const relations = (w) => w.findAll('[data-test="relations"] li').map((li) => shown({ get: () => li }, null))

  it('a treasury that is also a borrower is one node', async () => {
    serveLending(lendingLf2.instance, withOverview((o) => {
      o.company = { entity_id: 'borrower-a', name: 'Northwind Parts' }
      o.relations = [venue('borrower-a')]
    }))
    const w = await open(Lending, '/lending')
    const ids = nodeIds(w)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('two facilities to one borrower are one link, not two drawn on top of each other', async () => {
    const lending = clone(lendingLf2.instance)
    lending.facilities[1].borrower = lending.facilities[0].borrower
    serveLending(lending)
    const w = await open(Lending, '/lending')
    expect(relations(w).filter((r) => r.includes(`→ ${lending.facilities[0].borrower}`))).toHaveLength(1)
  })

  it('the treasury link names an expected withdrawal only when there is exactly one', async () => {
    const lending = lendingLf2.instance
    const withdrawal = (id) => ({ flow_id: id, kind: 'exchange_withdrawal', reservation_id: null,
      amount: { minor: 1500000, currency: 'USD' }, expected_at: '2026-01-07T00:00:00Z' })
    const treasury = (flows) => {
      const t = clone(treasuryDelayed.instance)
      t.snapshot_id = lending.snapshot_id
      t.mode = lending.mode
      t.accounts[0].buckets.pending_in = flows
      return t
    }
    const overview = { ...withOverview((o) => { o.relations = [venue('treasury')] }), snapshot_id: lending.snapshot_id, mode: lending.mode }
    serve({ '/lending': lending, '/overview': overview, '/treasury': treasury([withdrawal('wd-1')]) })
    let w = await open(Lending, '/lending')
    expect(relations(w).find((r) => r.startsWith('Treasury →'))).toContain('Expected withdrawal')
    w.unmount()
    serve({ '/lending': lending, '/overview': overview, '/treasury': treasury([withdrawal('wd-1'), withdrawal('wd-2')]) })
    w = await open(Lending, '/lending')
    expect(relations(w).find((r) => r.startsWith('Treasury →'))).not.toContain('Expected withdrawal')
  })

  it('a treasury whose cash the overview does not serve says nothing about its cash', async () => {
    serveLending(lendingLf2.instance, withOverview((o) => { o.cash = null; o.relations = [venue('treasury')] }))
    const w = await open(Lending, '/lending')
    const node = w.findAll('[data-test="map-node"]').find((n) => n.attributes('data-node') === 'treasury')
    expect(node.get('[role="tooltip"]').text()).not.toContain('Unavailable')
  })
})

// Overview as one payroll decision around the 72-hour cash path, on the recorded baseline
// (contracts/examples/c6_api/valid-overview-demo-baseline.json, the API's answer on the demo world
// before any run) and that answer with the prepared delayed receipt and its late path (the API's
// scenario.outlook). The interaction at every width is e2e/ux/overview.spec.ts and
// e2e/ux/match-overview.spec.ts; this is the offline fast tier.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Overview from '../../src/views/Overview.vue'
import baseline from '../../../contracts/examples/c6_api/valid-overview-demo-baseline.json'

const Stub = { render: () => h('div', 'stub') }
const clone = (x) => JSON.parse(JSON.stringify(x))

async function open (body) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => clone(body) })))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: ['/overview', '/treasury', '/lending', '/simulation'].map((path) =>
      ({ path, component: path === '/overview' ? Overview : Stub }))
  })
  await router.push('/overview')
  await router.isReady()
  const wrapper = mount(Overview, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

const text = (w, test) => w.get(`[data-test="${test}"]`).text().replace(/\s+/g, ' ').trim()
/** What a reader sees of an element: its text pieces apart, a closed tooltip left out. */
function face (w, test) {
  const el = w.get(`[data-test="${test}"]`).element.cloneNode(true)
  el.querySelectorAll('[role="tooltip"]').forEach((t) => t.remove())
  const parts = []
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  while (walk.nextNode()) parts.push(walk.currentNode.textContent)
  return parts.join(' ').replace(/\s+/g, ' ').replace(/ ([,.])/g, '$1').trim()
}
/** The API's answer with the prepared delayed receipt: the receivable past the horizon. */
const LATE = [[0, 7000000], [2, 2000000], [3, 3500000], [4, 3500000]].map(([n, minor]) => {
  const p = clone(baseline.instance.outlook[n])
  return { ...p, value: { ...p.value, minor } }
})
const withRun = () => ({
  ...clone(baseline.instance),
  demo: { run_id: 'run-1', execution_id: null },
  scenario: { family: 'delayed-receipt', about: 'The receivable is delayed.', params: { flow_id: 'receivable-1', delay_h: 240 }, outlook: clone(LATE) }
})

/**
 * The value a y pixel stands for on the chart's own axis: the $0 gridline and the top one, read
 * off the drawing and its labels, so a figure drawn at the wrong height reads as the wrong value.
 */
function axisOf (w) {
  const grid = w.findAll('.lw-path__grid').map((l) => Number(l.attributes('y1')))
  const labels = w.findAll('.lw-path__axis text').map((t) => t.text())
  const zero = grid[labels.indexOf('$0')]
  const top = grid.at(-1)
  const topMinor = Number(labels.at(-1).replace(/[$,]/g, '').replace(/k$/, '000').replace(/M$/, '000000')) * 100
  return (py) => Math.round(((zero - py) / (zero - top)) * topMinor)
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('the first screen: the answer, its condition, the equation', () => {
  it('O1 names the complete snapshot, the currency and the company', async () => {
    const w = await open(baseline.instance)
    expect(text(w, 'context-line')).toBe('Snapshot demo-world · USD · Synthetic data')
    expect(text(w, 'context-bar-snapshot')).toBe('demo-world')
    expect(text(w, 'company')).toBe('Northwind PartsSynthetic company')
  })

  it('answers whether payroll is covered, with where cash is lowest against the floor', async () => {
    const w = await open(baseline.instance)
    expect(text(w, 'hero-headline')).toBe('Payroll is covered.')
    expect(face(w, 'hero-subtitle')).toBe('Cash dips to $40,000 at hour 40, $10,000 above the reserve floor.')
    // the finance lead's sentence stays the condition's tooltip
    expect(w.get('[data-test="hero-lead"] [role="tooltip"]').text()).toContain("You're covered until payroll on 2 Jan")
  })

  it('names the receipt the answer depends on when the prepared what-if delays it', async () => {
    const w = await open(withRun())
    expect(face(w, 'hero-subtitle')).toBe(
      'Cash dips to $40,000 at hour 40, $10,000 above the reserve floor, as long as the $20,000 receivable lands at hour 12.')
  })

  it('O2 shows settled − reserved = spendable, the API inputs of each in its tooltip', async () => {
    const w = await open(baseline.instance)
    expect(face(w, 'settled')).toBe('Settled $70,000')
    expect(face(w, 'reserved')).toBe('− Payroll reserve $50,000')
    expect(face(w, 'spendable')).toMatch(/^= Spendable now \$20,000/)
    const tip = w.get('[data-test="tip-spendable"] [role="tooltip"]')
    expect(tip.attributes('hidden')).toBeDefined()
    expect(tip.text().replace(/\s+/g, ' ')).toContain(
      '70,000.00 settled − 50,000.00 reserved − 0.00 pledged = $20,000')
    await w.get('[data-test="tip-spendable"]').trigger('focusin')
    expect(tip.attributes('hidden')).toBeUndefined()
  })

  it('a breached floor is the headline and on the page, not only in a tooltip', async () => {
    const body = withRun()
    body.coverage.headroom = { ...body.coverage.headroom, minor: -500000 }
    body.coverage.min_projected = { ...body.coverage.min_projected, minor: 2500000 }
    const w = await open(body)
    expect(text(w, 'hero-headline')).toBe('Cash falls below the reserve floor.')
    expect(face(w, 'hero-subtitle')).toContain('$25,000 at hour 40, $5,000 below the reserve floor')
    const alert = w.get('[data-test="coverage"] [data-test="floor-alert"]')
    expect(alert.element.closest('[role="tooltip"]')).toBeNull()
    expect(alert.text()).toContain('Below your safety minimum')
  })
})

describe('the cash path is the API data, drawn', () => {
  it('O3 draws every API point, each a control with its time, amount and event', async () => {
    const w = await open(baseline.instance)
    expect(w.findAll('[data-test="outlook-point"]').length).toBe(5)
    const rows = w.findAll('[data-test="outlook-tip"]').map((r) => r.text().replace(/\s+/g, ' '))
    expect(rows.map((r) => r.match(/\((now|in \d+ (hours?|days?))\)/)[1])).toEqual(['now', 'in 12 hours', 'in 40 hours', 'in 2 days', 'in 3 days'])
    expect(rows[2]).toContain('$40,000')
    expect(rows[2]).toContain('payroll-1 -$50,000')
    expect(face(w, 'outlook-low-label')).toBe('Low point $40,000 $10,000 above the floor')
    expect(face(w, 'outlook-floor-label')).toBe('Reserve floor $30,000')
  })

  it('the floor, the trough and the late path sit at the API values for the same snapshot', async () => {
    const body = withRun()
    const w = await open(body)
    const value = axisOf(w)
    expect(value(Number(w.get('[data-test="outlook-floor"]').attributes('y1')))).toBe(body.coverage.floor.minor)
    const trough = w.get('[data-test="outlook-low-label"] circle')
    expect(value(Number(trough.attributes('cy')))).toBe(body.coverage.min_projected.minor)
    // the dashed path passes through each late point the API served, at its value
    const d = w.get('[data-test="late-path"] path').attributes('d')
    const ys = [...d.matchAll(/[MV]\s*(?:[\d.]+,)?([\d.]+)/g)].map((m) => value(Number(m[1])))
    expect(ys).toEqual(body.scenario.outlook.map((p) => p.value.minor))
    expect(face(w, 'late-low-label')).toBe('$20,000 if late $10,000 below the floor')
    // a breach is drawn only where the late path is under the floor
    expect(w.findAll('.lw-path__breach')).toHaveLength(body.scenario.outlook.filter((p) => p.value.minor < body.coverage.floor.minor).length)
  })

  it('the what-if table reads both low points against the floor; Hide path takes the dashed path away', async () => {
    const w = await open(withRun())
    expect(face(w, 'coverage')).toMatch(/^As planned, h40 \$40,000 \+\$10,000/)
    expect(face(w, 'late-row')).toBe('If late (hypothetical), h40 $20,000 −$10,000')
    expect(text(w, 'what-if-why')).toBe('Payroll is still paid from its reserve. The reserve floor is what breaks.')
    expect(text(w, 'scenario').startsWith('Hypothetical · dashed path')).toBe(true)
    await w.get('[data-test="toggle-late"]').trigger('click')
    expect(w.find('[data-test="late-path"]').exists()).toBe(false)
    // one signal for assistive tech: the label says what a press does, no contradicting pressed state
    expect(w.get('[data-test="toggle-late"]').text()).toBe('Show path')
    expect(w.get('[data-test="toggle-late"]').attributes('aria-pressed')).toBeUndefined()
    // hidden means hidden: no point's tooltip keeps the what-if's figure
    expect(w.findAll('[data-test="outlook-tip"]').some((t) => t.text().includes('If late'))).toBe(false)
    expect(face(w, 'late-row')).toContain('$20,000') // the table keeps the numbers
  })

  it('the payroll under the axis opens its Treasury row in this snapshot', async () => {
    const w = await open(baseline.instance)
    const link = w.findAll('[data-test="outlook-event"]').find((e) => e.element.tagName === 'A')
    expect(link.attributes('href')).toBe('/treasury?focus=obligation:payroll-1&snapshot=demo-world')
    expect(link.text()).toContain('payroll')
  })
})

describe('Open simulation and the depth under the decision', () => {
  it('Open simulation opens the prepared run; without one it is disabled and says why', async () => {
    let w = await open(withRun())
    expect(w.get('a[data-test="open-simulation"]').attributes('href')).toBe('/simulation?run_id=run-1')
    w.unmount()
    w = await open(baseline.instance)
    expect(w.get('[data-test="open-simulation"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-test="open-simulation-why"] [role="tooltip"]').text()).toBe('No demonstration run is prepared')
    expect(w.get('[data-test="explore-why"] [role="tooltip"]').text()).toBe('No demonstration run is prepared')
    expect(text(w, 'what-if-why')).toBe('No prepared run, so no what-if to draw.')
  })

  it('O4 deep-links the next obligation to its Treasury row in this snapshot', async () => {
    const w = await open(baseline.instance)
    expect(text(w, 'next-obligation')).toContain('Held by reservation payroll-hold')
    expect(w.get('[data-test="open-treasury"]').attributes('href'))
      .toBe('/treasury?focus=obligation:payroll-1&snapshot=demo-world')
  })

  it('O5 lists the relationships as text; O6 shows the scenario as run, read-only', async () => {
    const w = await open(withRun())
    const relations = w.findAll('[data-test="relation"]').map((r) => r.text().replace(/\s+/g, ' '))
    expect(relations).toHaveLength(3)
    const lender = relations.find((r) => r.startsWith('Harbourline Credit pool'))
    expect(lender).toContain('Committed line to Bellfield Kitchens: $10,000.')
    expect(text(w, 'scenario')).toContain('If the $20,000 receivable arrives late')
    expect(text(w, 'scenario-timing')).toBe('receivable expected in 12h, delayed 10 days')
    expect(face(w, 'settled')).toBe('Settled $70,000') // nothing observed changed
  })

  it('O6 says an early arrival as early, never as an unknown delay', async () => {
    const body = withRun()
    body.scenario.params.delay_h = -2
    const w = await open(body)
    expect(text(w, 'scenario-timing')).toBe('receivable expected in 12h, early by 2 hours')
  })

  it('O6 shows a scenario amount in its currency, never as raw minor units', async () => {
    const body = withRun()
    body.scenario = { family: 'fx-gap', about: 'A currency gap.', params: { amount_minor: 1000000, currency: 'EUR' }, outlook: [] }
    const w = await open(body)
    const amount = w.findAll('[data-test="scenario-preview"] dt').find((dt) => dt.text() === 'amount')
    expect(amount.element.nextElementSibling.textContent).toBe('€10,000')
    expect(text(w, 'scenario-preview')).not.toContain('1000000')
    expect(w.find('[data-test="late-path"]').exists()).toBe(false)
  })

  it('a payee owed two obligations reads their count, never only the last one\'s amount', async () => {
    const body = withRun()
    const owed = body.relations.find((r) => r.kind === 'obligation')
    body.relations.push({ ...clone(owed), ref: 'payroll-2', amount: { ...owed.amount, minor: 100000 } })
    const w = await open(body)
    const node = w.findAll('[data-test="relation"]').find((n) => n.text().includes('payroll bureau'))
    expect(node.get('small').text()).toBe('2 obligations owed')
  })
})

describe('the answer and the chart hold off the recorded answer', () => {
  it('an obligation beyond the projection is not called covered', async () => {
    const body = clone(baseline.instance)
    body.upcoming_outflows[0].due_at = '2026-01-05T04:00:00Z' // h100, past the 72-hour outlook
    const w = await open(body)
    expect(face(w, 'hero-headline')).toBe('Cash stays above the reserve floor.')
  })

  it('a what-if that keeps the floor is no condition of the answer', async () => {
    const body = withRun()
    body.scenario.outlook = body.scenario.outlook.map((p) => ({ ...p, value: { ...p.value, minor: Math.max(p.value.minor, 3500000) } }))
    const w = await open(body)
    expect(face(w, 'hero-subtitle')).toBe('Cash dips to $40,000 at hour 40, $10,000 above the reserve floor.')
    expect(text(w, 'what-if-why')).toBe('The reserve floor still holds.')
  })

  it('a path at or below zero with no floor keeps a handful of gridlines', async () => {
    const body = clone(baseline.instance)
    body.coverage.floor = { ...body.coverage.floor, minor: null, status: 'unassessed' }
    body.coverage.headroom = { ...body.coverage.headroom, minor: null, status: 'unassessed' }
    body.outlook = body.outlook.map((p, n) => ({ ...p, value: { ...p.value, minor: n ? -5000000 : 0 } }))
    const w = await open(body)
    const ticks = w.findAll('.lw-path__grid').length
    expect(ticks).toBeGreaterThanOrEqual(2)
    expect(ticks).toBeLessThanOrEqual(8)
  })

  it('a what-if low near the start keeps its label inside the chart', async () => {
    const body = withRun()
    // the what-if's low at h12: its label would run off the left edge
    body.scenario.outlook = [
      { ...clone(LATE[0]) },
      { ...clone(baseline.instance.outlook[1]), events: [], value: { ...LATE[1].value, minor: 1000000 } },
      ...clone(LATE).slice(1).map((p) => ({ ...p, value: { ...p.value, minor: 3500000 } }))
    ]
    const w = await open(body)
    const [line] = w.findAll('[data-test="late-low-label"] text')
    expect(line.attributes('text-anchor')).toBe('start')
    // its caption follows it to the right
    const caption = w.findAll('[data-test="late-path"] text').find((t) => t.text().includes('hypothetical'))
    expect(caption.attributes('text-anchor')).toBe('start')
  })

  it('the observed low label keeps clear of the what-if low label', async () => {
    // the what-if low just under the observed one at the same hour: the default place would overlap
    const body = withRun()
    body.scenario.outlook[1].value.minor = 3600000
    const w = await open(body)
    const [low] = w.findAll('[data-test="outlook-low-label"] text')
    const [late] = w.findAll('[data-test="late-low-label"] text')
    const y = (t) => Number(t.attributes('y'))
    const sameSide = low.attributes('text-anchor') === late.attributes('text-anchor')
    expect(sameSide && Math.abs(y(low) - y(late)) < 2 * 16).toBe(false)
  })

  it('a receipt the what-if moves inside the horizon has its own row in the cash data', async () => {
    const body = withRun()
    const moved = { ...clone(baseline.instance.outlook[1]), t: '2026-01-02T12:00:00Z', value: { ...LATE[0].value, minor: 9000000 } }
    body.scenario.outlook = [clone(LATE[0]), moved, ...clone(LATE).slice(1).map((p) => ({ ...p, value: { ...p.value, minor: p.value.minor + 2000000 } }))]
    const w = await open(body)
    const rows = w.findAll('[data-test="cash-data"] tbody tr').map((r) => r.text().replace(/\s+/g, ' '))
    expect(rows.some((r) => r.startsWith('36') && r.includes('(if late)'))).toBe(true)
  })

  it('a receipt the what-if moves onto a planned time is named in that row', async () => {
    const body = withRun()
    const receipt = clone(baseline.instance.outlook[1].events[0])
    body.scenario.outlook[1].events = [receipt, ...body.scenario.outlook[1].events] // lands with payroll at h40
    const w = await open(body)
    const row = w.findAll('[data-test="cash-data"] tbody tr').map((r) => r.text().replace(/\s+/g, ' ')).find((r) => r.startsWith('40'))
    expect(row).toContain('Payroll −$50,000; Receivable +$20,000 (if late)')
  })

  it('a what-if point that is unknown reads unknown in the tooltip, never an earlier figure', async () => {
    const body = withRun()
    body.scenario.outlook[1].value = { ...body.scenario.outlook[1].value, minor: null, status: 'unknown' }
    const w = await open(body)
    const tip = w.findAll('[data-test="outlook-tip"]')[2].text()
    expect(tip).toContain('If late (hypothetical): Unknown')
  })
})

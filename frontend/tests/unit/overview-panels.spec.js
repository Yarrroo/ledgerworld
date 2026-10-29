// Overview's panels O1–O6 on the recorded baseline (contracts/examples/c6_api/
// valid-overview-demo-baseline.json, the API's answer on the demo world before any run). The
// interaction at every width is e2e/ux/overview.spec.ts; this is the offline fast tier.
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

const text = (w, test) => w.get(`[data-test="${test}"]`).text().replace(/\s+/g, ' ')
const withRun = () => ({
  ...clone(baseline.instance),
  demo: { run_id: 'run-1', execution_id: null },
  scenario: { family: 'delayed-receipt', about: 'The receivable is delayed.', params: { flow_id: 'receivable-1', delay_h: 240 } }
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('Overview panels on the baseline', () => {
  it('O1 names the complete snapshot, the currency and the company', async () => {
    const w = await open(baseline.instance)
    expect(text(w, 'context-line')).toBe('Snapshot demo-world · USD · Synthetic data')
    expect(text(w, 'context-bar-snapshot')).toBe('demo-world')
    expect(text(w, 'company')).toBe('Northwind PartsSynthetic company')
    expect(text(w, 'hero-subtitle')).toContain('Northwind Parts treasury')
  })

  it('O2 carries the API inputs of each metric in its tooltip, shown only when asked for', async () => {
    const w = await open(baseline.instance)
    const tip = w.get('[data-test="tip-spendable"] [role="tooltip"]')
    expect(tip.attributes('hidden')).toBeDefined()
    expect(tip.text().replace(/\s+/g, ' ')).toContain(
      '70,000.00 settled − 50,000.00 reserved − 0.00 pledged = $20,000')
    await w.get('[data-test="tip-spendable"]').trigger('focusin')
    expect(tip.attributes('hidden')).toBeUndefined()
    expect(text(w, 'spendable')).toContain('$20,000')
  })

  it('O3 draws every API point and shows them as data, the lowest kept and green', async () => {
    const w = await open(baseline.instance)
    expect(w.findAll('[data-test="outlook-point"]').length).toBe(5)
    const lowest = w.findAll('.lw-outlook__dot').filter((d) => d.attributes('r') === '6')
    expect(lowest).toHaveLength(1)
    expect(lowest[0].classes()).toContain('is-ok')
    const rows = w.findAll('[data-test="outlook-tip"]').map((r) => r.text().replace(/\s+/g, ' '))
    expect(rows.map((r) => r.match(/\((now|in \d+ (hours?|days?))\)/)[1])).toEqual(['now', 'in 12 hours', 'in 40 hours', 'in 2 days', 'in 3 days'])
    expect(rows[2]).toContain('$40,000')
    expect(rows[2]).toContain('payroll-1 -$50,000')
  })

  it('O4 deep-links the next obligation to its Treasury row in this snapshot', async () => {
    const w = await open(baseline.instance)
    expect(text(w, 'next-obligation')).toContain('Held by reservation payroll-hold')
    expect(w.get('[data-test="open-treasury"]').attributes('href'))
      .toBe('/treasury?focus=obligation:payroll-1&snapshot=demo-world')
  })

  it('O5 lists the relationships as text; O6 previews the scenario read-only', async () => {
    const w = await open(withRun())
    const relations = w.findAll('[data-test="relation"]').map((r) => r.text().replace(/\s+/g, ' '))
    expect(relations).toHaveLength(3)
    const lender = relations.find((r) => r.startsWith('Harbourline Credit pool'))
    expect(lender).toContain('Committed line to Bellfield Kitchens: $10,000.')
    expect(text(w, 'scenario')).toContain('What if your $20,000 receivable arrives late?')
    await w.get('[data-test="preview-scenario"]').trigger('click')
    expect(text(w, 'scenario-timing')).toBe('receivable expected in 12h, delayed 10 days')
    expect(text(w, 'settled')).toContain('$70,000') // nothing observed changed
  })

  it('O6 says an early arrival as early, never as an unknown delay', async () => {
    const body = withRun()
    body.scenario.params.delay_h = -2
    const w = await open(body)
    await w.get('[data-test="preview-scenario"]').trigger('click')
    expect(text(w, 'scenario-timing')).toBe('receivable expected in 12h, early by 2 hours')
  })

  it('O6 shows a scenario amount in its currency, never as raw minor units', async () => {
    const body = withRun()
    body.scenario = { family: 'fx-gap', about: 'A currency gap.', params: { amount_minor: 1000000, currency: 'EUR' } }
    const w = await open(body)
    await w.get('[data-test="preview-scenario"]').trigger('click')
    const amount = w.findAll('[data-test="scenario-preview"] dt').find((dt) => dt.text() === 'amount')
    expect(amount.element.nextElementSibling.textContent).toBe('€10,000')
    expect(text(w, 'scenario-preview')).not.toContain('1000000')
  })

  it('without a prepared run, the scenario cannot be previewed and says why', async () => {
    const w = await open(baseline.instance)
    expect(w.get('[data-test="preview-scenario"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-test="preview-why"] [role="tooltip"]').text()).toBe('No prepared run, so no what-if to preview')
    expect(w.get('[data-test="explore-why"] [role="tooltip"]').text()).toBe('No demonstration run is prepared')
  })
})

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
    expect(text(w, 'context-snapshot')).toBe('demo-world')
    expect(text(w, 'context-currency')).toBe('USD')
    expect(text(w, 'context-panel')).toContain('Northwind Parts treasury (synthetic)')
  })

  it('O2 opens the API inputs of the metric chosen, one at a time, each linking its Treasury row', async () => {
    const w = await open(baseline.instance)
    expect(w.find('[data-test="metric-inputs"]').exists()).toBe(false)
    await w.get('[data-test="pick-spendable"]').trigger('click')
    expect(text(w, 'metric-inputs')).toContain(
      'treasury/operating (USD): 70,000.00 settled − 50,000.00 reserved − 0.00 pledged = USD 20,000.00')
    expect(w.get('[data-test="metric-link"]').attributes('href'))
      .toBe('/treasury?focus=account:treasury/operating&snapshot=demo-world')
    await w.get('[data-test="pick-settled"]').trigger('click')
    expect(w.findAll('[aria-expanded="true"]').length).toBe(1)
    await w.get('[data-test="pick-settled"]').trigger('click')
    expect(w.find('[data-test="metric-inputs"]').exists()).toBe(false)
  })

  it('O3 draws every API point and shows them as data, the lowest kept and green', async () => {
    const w = await open(baseline.instance)
    expect(w.findAll('[data-test="outlook-point"]').length).toBe(5)
    expect(w.get('[data-test="outlook-point"].is-low').classes()).toContain('is-ok')
    await w.get('[data-test="outlook-view-data"]').trigger('click')
    const rows = w.findAll('[data-test="outlook-table"] tbody tr').map((r) => r.text())
    expect(rows.map((r) => r.match(/t=\d+ h/)[0])).toEqual(['t=0 h', 't=12 h', 't=40 h', 't=48 h', 't=72 h'])
    expect(rows[2]).toContain('USD 40,000.00')
    expect(rows[2]).toContain('payroll-1 −USD 50,000.00')
  })

  it('O4 deep-links the next obligation to its Treasury row in this snapshot', async () => {
    const w = await open(baseline.instance)
    expect(text(w, 'next-obligation')).toContain('reserved · payroll-hold')
    expect(w.get('[data-test="open-treasury"]').attributes('href'))
      .toBe('/treasury?focus=obligation:payroll-1&snapshot=demo-world')
  })

  it('O5 lists the relationships as text; O6 previews the scenario read-only', async () => {
    const w = await open(withRun())
    const relations = w.findAll('[data-test="relation"]').map((r) => r.text().replace(/\s+/g, ' '))
    expect(relations).toHaveLength(4)
    expect(relations[1]).toMatch(/^Harbourline Credit pool \(synthetic\) → to Bellfield Kitchens \(synthetic\)/)
    expect(relations[1]).toContain('committed line line-b, limit USD 10,000.00')
    expect(text(w, 'scenario')).toContain('What if the USD 20,000.00 receivable arrives late?')
    await w.get('[data-test="preview-scenario"]').trigger('click')
    expect(text(w, 'scenario-timing')).toBe('receivable-1 expected t=12 h, delayed 240 h')
    expect(text(w, 'settled')).toContain('USD 70,000.00') // nothing observed changed
  })

  it('without a prepared run, the scenario cannot be previewed and says why', async () => {
    const w = await open(baseline.instance)
    expect(w.get('[data-test="preview-scenario"]').attributes('disabled')).toBeDefined()
    expect(text(w, 'preview-why')).toBe('No prepared run, so no scenario to preview')
    expect(text(w, 'explore-why')).toBe('No demonstration run is prepared')
  })
})

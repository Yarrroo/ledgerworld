// The UX 3–6 panels' own rules, each pinned (prp/2026-10-29-ux-panels/design.md): a minimum is
// Unknown when any scenario's is; a shortfall is shown only where the API says the floor broke,
// and only in the floor's currency; a shared venue's account belongs to the party that holds it;
// the cash chart marks no minimum it cannot know; Simulation names the account and snapshot a
// Treasury handoff carried. No request leaves the test.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Decisions from '../../src/views/Decisions.vue'
import Simulation from '../../src/views/Simulation.vue'
import CashChart from '../../src/components/CashChart.vue'
import { worldFor } from '../../src/api/world.js'

const Stub = { render: () => h('div', 'stub') }
const usd = (minor, status = 'known') => ({ minor, currency: 'USD', status, as_of: null })

function serve (answers) {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const path = new URL(url).pathname.replace('/api/v1', '')
    const answer = answers[path]
    if (answer === undefined) throw new Error(`no answer for ${path}`)
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(answer)) }
  }))
}

async function open (component, path) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: ['/decisions', '/simulation', '/execution', '/overview'].map((p) => ({
      path: p, component: p === path.split('?')[0] ? component : Stub
    }))
  })
  await router.push(path)
  await router.isReady()
  const w = mount(component, { global: { plugins: [router], stubs: { GraphPanel: Stub } } })
  await flushPromises()
  return w
}

afterEach(() => vi.unstubAllGlobals())

const row = (policy, scenario, min, floorKept, extra = {}) => ({
  policy, scenario_id: scenario, branch_id: `run-1-${scenario}-${policy}`, replay: false,
  obligations_unmet: 0, floor_kept: floorKept, min_cash: min, funding_cost: { minor: 0, currency: 'USD' },
  feasible: floorKept, ...extra
})

function decisions (results) {
  return {
    as_of: '2026-01-01T00:00:00Z', mode: 'fake', run_id: 'run-1', snapshot_id: 'demo-world', checkpoint_round: 2,
    cohort: 'delayed-receipt seed 7', weight_kind: 'unweighted', status: 'selected', results,
    selected: 'integrated', escalation: null
  }
}

function treasury (floor = usd(3000000)) {
  return {
    as_of: '2026-01-01T00:00:00Z', mode: 'fake', snapshot_id: 'demo-world', obligations: [],
    accounts: [{
      id: 'treasury/operating', entity: 'treasury', currency: 'USD', kind: 'cash', venue: null, floor,
      observability: 'known', as_of: '2026-01-01T00:00:00Z', authority: 'full', spendable: usd(2000000),
      buckets: { settled: { minor: 7000000, currency: 'USD' }, reserved: { minor: 0, currency: 'USD' },
        pledged: { minor: 0, currency: 'USD' }, pending_in: [], pending_out: [] },
      projected: []
    }]
  }
}

const text = (w, test) => w.get(`[data-test="${test}"]`).text().replace(/\s+/g, ' ')

describe('Decisions reads minima and shortfalls only as the API supports them', () => {
  it('a policy whose scenarios are partly unknown has an Unknown minimum, never one scenario\'s', async () => {
    serve({
      '/decisions/run-1': decisions([
        row('no-action', 's1', usd(5000000), true), row('no-action', 's2', usd(null, 'unknown'), false),
        row('integrated', 's1', usd(3000000), true), row('integrated', 's2', usd(3000000), true)
      ]),
      '/treasury': treasury()
    })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(text(w, 'gap-summary')).toContain('Minimum cash Unknown')
    expect(text(w, 'gap-summary')).not.toContain('the floor holds')
    expect(text(w, 'gap-summary')).not.toContain('50,000.00')
  })

  it('a shortfall is shown only on scenarios whose floor the API says broke', async () => {
    serve({
      // the branch kept its floor by the API; today's floor is higher than its minimum
      '/decisions/run-1': decisions([row('no-action', 's1', usd(2500000), true), row('integrated', 's1', usd(3000000), true)]),
      '/treasury': treasury()
    })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(w.get('[data-test="policy-no-action"]').text()).toContain('Largest shortNone')
  })

  it('a floor in another currency is never compared with a minimum', async () => {
    serve({
      '/decisions/run-1': decisions([row('no-action', 's1', usd(2000000), false), row('integrated', 's1', usd(3000000), true)]),
      '/treasury': treasury({ minor: 3000000, currency: 'EUR', status: 'known', as_of: null })
    })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(w.get('[data-test="policy-no-action"]').text()).toContain('Largest shortNot assessed')
    expect(text(w, 'gap-summary')).not.toContain('short')
  })
})

describe('the world file and the cash chart claim nothing they do not hold', () => {
  it('a shared venue\'s account is on the edge of the party that holds it, not on every party\'s', () => {
    const edges = worldFor('demo-world').edges.filter((e) => e.type === 'exposure')
    expect(edges.find((e) => e.from === 'lender').account).toBe('lender/venue')
    expect(edges.find((e) => e.from === 'treasury').account).toBeNull()
  })

  it('the chart marks no minimum when any point is unknown, and draws in time order', async () => {
    const w = mount(CashChart, {
      props: {
        asOf: '2026-01-01T00:00:00Z',
        floor: usd(3000000),
        points: [
          { t: '2026-01-03T00:00:00Z', value: usd(5000000) },
          { t: '2026-01-01T00:00:00Z', value: usd(1000000) },
          { t: '2026-01-02T00:00:00Z', value: usd(null, 'unknown') }
        ]
      }
    })
    await flushPromises()
    expect(w.findAll('.is-low')).toHaveLength(0)
    expect(w.findAll('[data-test="chart-point"]').map((p) => p.attributes('data-t')))
      .toEqual(['2026-01-01T00:00:00Z', '2026-01-03T00:00:00Z'])
  })
})

describe('Simulation names what a Treasury handoff carried', () => {
  it('the account, and a snapshot other than the run\'s', async () => {
    serve({
      '/runs/run-1': {
        as_of: '2026-01-01T20:00:00Z', mode: 'fake', run_id: 'run-1', snapshot_id: 'demo-world', status: 'done',
        committed_round: 1, branches: [{ branch_id: 'run-1-base', parent_branch_id: null, checkpoint_round: null, policy: null, replay: false }],
        rounds: [{ round: 1, branch_id: 'run-1-base', t_hours: 4, intents: [], cleared: [], journal_ids: [] }],
        feed: [], cash_paths: []
      }
    })
    const w = await open(Simulation, '/simulation?run_id=run-1&account=treasury/operating&snapshot=lf1')
    expect(text(w, 'handoff')).toContain('treasury/operating')
    expect(text(w, 'handoff')).toContain('snapshot lf1')
    expect(text(w, 'handoff')).toContain('demo-world')
  })
})

// With a prepared demo the money screens read the run's observed snapshot, named by the backend
// `obs-<world>-r<round>-<run>` (app/demo/run.py): the same world, the same run, a later moment.
describe('the observed snapshot of a prepared run is that run\'s world', () => {
  it('the world map is drawn for a snapshot observed from the world, and for no other', () => {
    expect(worldFor('obs-demo-r3-run-1')).not.toBeNull()
    expect(worldFor('lf1')).toBeNull()
  })

  it('Decisions judges the gap against the run\'s observed treasury, timed from the world\'s epoch', async () => {
    const observed = { ...treasury(), snapshot_id: 'obs-demo-r3-run-1' }
    observed.accounts[0].as_of = '2026-01-01T12:00:00Z'
    observed.accounts[0].buckets.pending_in = [{ flow_id: 'receivable-1', kind: 'receivable', reservation_id: null,
      amount: { minor: 2000000, currency: 'USD' }, expected_at: '2026-01-01T12:00:00Z' }]
    observed.obligations = [{ obligation_id: 'payroll-1', entity: 'treasury', account: 'treasury/operating',
      amount: { minor: 5000000, currency: 'USD' }, due_at: '2026-01-02T16:00:00Z', kind: 'payroll',
      mandatory: true, reservation_id: 'payroll-hold', state: 'open' }]
    serve({
      '/decisions/run-1': decisions([row('no-action', 's1', usd(2000000), false), row('integrated', 's1', usd(3000000), true)]),
      '/treasury': observed
    })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(text(w, 'gap-summary')).toContain('short USD 10,000.00')
    const at = w.findAll('[data-test="timing"] li').map((li) => li.attributes('data-at'))
    expect(at).toEqual(['12', '40', '252'])
  })

  it('a handoff from the run\'s own observed snapshot is not called another snapshot', async () => {
    serve({
      '/runs/run-1': {
        as_of: '2026-01-01T20:00:00Z', mode: 'fake', run_id: 'run-1', snapshot_id: 'demo-world', status: 'done',
        committed_round: 1, branches: [{ branch_id: 'run-1-base', parent_branch_id: null, checkpoint_round: null, policy: null, replay: false }],
        rounds: [{ round: 1, branch_id: 'run-1-base', t_hours: 4, intents: [], cleared: [], journal_ids: [] }],
        feed: [], cash_paths: []
      }
    })
    const w = await open(Simulation, '/simulation?run_id=run-1&account=treasury/operating&snapshot=obs-demo-r3-run-1')
    expect(text(w, 'handoff')).toContain('treasury/operating')
    expect(text(w, 'handoff')).not.toContain('this run is on')
  })
})

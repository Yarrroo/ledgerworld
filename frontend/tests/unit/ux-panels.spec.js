// The UX 3–6 panels' own rules, each pinned (prp/2026-10-29-ux-panels/design.md): a minimum is
// Unknown when any scenario's is; a shortfall is shown only where the API says the floor broke,
// and only in the floor's currency; a shared venue's account belongs to the party that holds it;
// the cash chart marks no minimum it cannot know; Simulation names the account and snapshot a
// Treasury handoff carried. No request leaves the test.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import { onPage as seen } from './visible.js' // what a reader sees, closed tooltips and dialogs left out
import Decisions from '../../src/views/Decisions.vue'
import Simulation from '../../src/views/Simulation.vue'
import CashOutlook from '../../src/components/CashOutlook.vue'
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
    expect(seen(w, 'gap-summary')).toContain('Not assessed')
    expect(w.get('[data-test="gap-tip"] [role="tooltip"]').text()).toContain('Lowest point Unknown')
    expect(w.find('[data-test="waterfall-bar-0"]').exists()).toBe(false)
    expect(text(w, 'gap-summary')).not.toContain('the floor holds')
    expect(text(w, 'gap-summary')).not.toContain('$50,000')
  })

  it('a shortfall is shown only on scenarios whose floor the API says broke', async () => {
    serve({
      // the branch kept its floor by the API; today's floor is higher than its minimum
      '/decisions/run-1': decisions([row('no-action', 's1', usd(2500000), true), row('integrated', 's1', usd(3000000), true)]),
      '/treasury': treasury()
    })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(w.get('[data-test="policy-no-action"]').text()).toContain('largest shortfall None')
  })

  it('a floor in another currency is never compared with a minimum', async () => {
    serve({
      '/decisions/run-1': decisions([row('no-action', 's1', usd(2000000), false), row('integrated', 's1', usd(3000000), true)]),
      '/treasury': treasury({ minor: 3000000, currency: 'EUR', status: 'known', as_of: null })
    })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(w.get('[data-test="policy-no-action"]').text()).toContain('largest shortfall Not assessed')
    expect(seen(w, 'gap-summary')).not.toContain('short')
  })
})

describe('Decisions mockup 05 bridge', () => {
  const result = () => decisions([row('no-action', 's1', usd(2000000), false), row('integrated', 's1', usd(3000000), true)])

  it('shows the stepper, three sourced bars and the chosen minimum in reading order', async () => {
    serve({ '/decisions/run-1': result(), '/treasury': treasury() })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(seen(w, 'decision-steps')).toContain('1 Rehearse2 Compare3 Review')
    expect(text(w, 'waterfall-bar-0')).toContain('$70,000')
    expect(text(w, 'waterfall-bar-1')).toContain('-$50,000')
    expect(text(w, 'waterfall-bar-2')).toContain('$20,000')
    expect(seen(w, 'explanation')).toContain('$30,000')
    expect(seen(w, 'explanation')).toContain('= reserve floor $30,000')
    expect(w.get('[data-test="how-decisions"]').element.open).toBe(false)
    const href = w.get('[data-test="review-plan"]').attributes('href')
    await w.get('[data-test="policy-no-action"] input').setValue()
    expect(seen(w, 'explanation')).toContain('$20,000')
    expect(seen(w, 'explanation')).toContain('< reserve floor $30,000')
    expect(w.get('[data-test="review-plan"]').attributes('href')).toBe(href)
  })

  for (const kind of ['unknown', 'stale', 'currency', 'snapshot', 'observability']) {
    it(`does not draw a made-up starting balance for ${kind}`, async () => {
      const t = treasury()
      if (kind === 'unknown') t.accounts[0].buckets.settled.minor = null
      if (kind === 'stale') t.accounts[0].buckets.settled.status = 'stale'
      if (kind === 'currency') t.accounts[0].buckets.settled.currency = 'EUR'
      if (kind === 'snapshot') t.snapshot_id = 'unrelated'
      if (kind === 'observability') t.accounts[0].observability = 'unknown'
      serve({ '/decisions/run-1': result(), '/treasury': t })
      const w = await open(Decisions, '/decisions?run_id=run-1')
      expect(w.find('[data-test="waterfall-bar-0"]').exists()).toBe(false)
      expect(seen(w, 'waterfall-unavailable')).toContain('no waterfall is drawn')
    })
  }

  it('refuses stale observed cash using the API metric state, not a field absent from Money', async () => {
    const t = treasury()
    t.as_of = '2026-01-01T12:00:00Z'
    t.accounts[0].authority = 'reduced'
    t.accounts[0].spendable = usd(2000000, 'stale')
    serve({ '/decisions/run-1': result(), '/treasury': t })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(w.find('[data-test="waterfall-bar-0"]').exists()).toBe(false)
  })

  it('compares an integrated-only result against its own known currency floor', async () => {
    const body = result()
    body.results = body.results.filter((r) => r.policy === 'integrated')
    serve({ '/decisions/run-1': body, '/treasury': treasury() })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(seen(w, 'explanation')).toContain('= reserve floor $30,000')
    expect(seen(w, 'explanation')).not.toContain('Not assessed')
  })

  it('shows Now and remaining time from an observation after world hour zero', async () => {
    const t = treasury()
    t.as_of = '2026-01-01T12:00:00Z'
    t.accounts[0].as_of = t.as_of
    t.obligations = [{ obligation_id: 'payroll', kind: 'payroll', account: t.accounts[0].id,
      due_at: '2026-01-02T16:00:00Z', amount: { minor: 5000000, currency: 'USD' } }]
    serve({ '/decisions/run-1': result(), '/treasury': t })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(w.get('[data-test="timing"] tr[data-at="12"] th').text()).toContain('Now')
    expect(w.get('[data-test="timing"] tr[data-at="40"] th').text()).toContain('In 28h')
  })

  it('uses a signed scale when the remaining balance is negative', async () => {
    const body = result()
    body.results[0].min_cash = usd(-1000000)
    serve({ '/decisions/run-1': body, '/treasury': treasury() })
    const w = await open(Decisions, '/decisions?run_id=run-1')
    expect(text(w, 'waterfall-bar-2')).toContain('-$10,000')
    const rect = w.get('[data-test="waterfall-bar-2"] rect')
    expect(Number(rect.attributes('height'))).toBeGreaterThan(0)
    expect(Number(rect.attributes('y'))).toBeLessThan(230)
    expect(rect.classes()).toContain('is-out')
    expect(rect.classes()).not.toContain('is-remaining')
  })
})

describe('the world file and the cash chart claim nothing they do not hold', () => {
  it('a shared venue\'s account is on the edge of the party that holds it, not on every party\'s', () => {
    const edges = worldFor('demo-world').edges.filter((e) => e.type === 'exposure')
    expect(edges.find((e) => e.from === 'lender').account).toBe('lender/venue')
    expect(edges.find((e) => e.from === 'treasury').account).toBeNull()
  })

  it('the chart marks no minimum when any point is unknown, and draws no dot for it', async () => {
    const w = mount(CashOutlook, {
      props: {
        asOf: '2026-01-01T00:00:00Z',
        currency: 'USD',
        floor: usd(3000000),
        lowAt: null, // Treasury names no lowest point when any point is unknown
        points: [
          { t: '2026-01-01T00:00:00Z', value: usd(1000000), events: [] },
          { t: '2026-01-02T00:00:00Z', value: usd(null, 'unknown'), events: [] },
          { t: '2026-01-03T00:00:00Z', value: usd(5000000), events: [] }
        ]
      }
    })
    await flushPromises()
    expect(w.find('[data-test="outlook-low-label"]').exists()).toBe(false)
    expect(w.findAll('circle.lw-outlook__dot')).toHaveLength(2)
    expect(w.findAll('[data-test="outlook-point"]').map((p) => p.attributes('data-t')))
      .toEqual(['2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', '2026-01-03T00:00:00Z'])
  })
})

function simRun (branch = 'run-1-base') {
  return {
    as_of: '2026-01-01T20:00:00Z', mode: 'fake', run_id: 'run-1', snapshot_id: 'demo-world', status: 'done',
    committed_round: 1, branches: [{ branch_id: branch, parent_branch_id: null, checkpoint_round: null, policy: null, replay: false }],
    rounds: [{ round: 1, branch_id: branch, t_hours: 4, intents: [], cleared: [], journal_ids: [] }],
    feed: [], cash_paths: []
  }
}

describe('Simulation names what a Treasury handoff carried', () => {
  it('a snapshot other than the run\'s is said on the page; the account stays behind the (i)', async () => {
    serve({ '/runs/run-1': simRun() })
    const w = await open(Simulation, '/simulation?run_id=run-1&account=treasury/operating&snapshot=lf1')
    expect(seen(w, 'run-context')).toContain('snapshot lf1')
    expect(seen(w, 'run-context')).toContain('demo-world')
    expect(w.get('[data-test="handoff-mismatch"]').attributes('role')).toBe('status')
    expect(text(w, 'handoff')).toContain('treasury/operating')
    expect(seen(w, 'run-context')).not.toContain('treasury/operating')
  })

  it('a handoff on the run\'s own snapshot puts no note on the page', async () => {
    serve({ '/runs/run-1': simRun() })
    const w = await open(Simulation, '/simulation?run_id=run-1&account=treasury/operating&snapshot=demo-world')
    expect(w.find('[data-test="handoff-mismatch"]').exists()).toBe(false)
    expect(text(w, 'handoff')).toContain('treasury/operating')
    expect(text(w, 'handoff')).not.toContain('this run is on')
  })

  it('a scenario other than the run\'s is said on the page', async () => {
    serve({ '/runs/run-1': simRun('run-1-delayed-receipt-base') })
    const w = await open(Simulation, '/simulation?run_id=run-1&scenario=fx-gap')
    expect(seen(w, 'run-context')).toContain('fx-gap')
    expect(seen(w, 'run-context')).toContain('delayed-receipt')
  })

  it('the scenario the run plays is only echoed behind the (i)', async () => {
    serve({ '/runs/run-1': simRun('run-1-delayed-receipt-base') })
    const w = await open(Simulation, '/simulation?run_id=run-1&scenario=delayed-receipt')
    expect(w.find('[data-test="handoff-mismatch"]').exists()).toBe(false)
    expect(text(w, 'handoff')).toContain('Scenario asked for: delayed-receipt')
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
    expect(seen(w, 'gap-summary')).toContain('$10,000')
    expect(seen(w, 'gap-summary')).toContain('cash falls below your reserve floor')
    const at = w.findAll('[data-test="timing"] tr').map((tr) => tr.attributes('data-at'))
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
    expect(w.find('[data-test="handoff-mismatch"]').exists()).toBe(false)
  })
})

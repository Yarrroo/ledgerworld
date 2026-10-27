// The Live Simulation screen with the real upstream graph view: what an operator selected in the
// graph belongs to the round and run it was selected in. Scrubbing to another round, to an
// unloaded round or to another run closes the details; a poll that changes nothing keeps them.
// No request leaves the test: fetch answers GET /runs/<id> from a C6 RunResponse built from the
// UI design fixture scrubber.json.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Simulation from '../../src/views/Simulation.vue'
import i18n from '../../src/i18n/index.js'

import scrubber from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/scrubber.json'

const ctx = scrubber.context
const EPOCH = Date.parse('2026-01-05T00:00:00Z')
const at = (hours) => new Date(EPOCH + hours * 3_600_000).toISOString().replace('.000Z', 'Z')
const clone = (x) => JSON.parse(JSON.stringify(x))

/** The fixture's rounds as a C6 RunResponse: post → borrower-c's request → the lender's disbursals. */
function run (runId = ctx.run_id, status = 'done') {
  const previous = new Map()
  const rounds = scrubber.rounds.map((r) => {
    const intents = r.feed_ids.filter((id) => id.startsWith('i-')).map((id) => ({
      intent_id: id, branch_id: ctx.branch_id, round: r.round, actor_id: r.highlight_actor,
      type: r.highlight_actor === 'lender' ? 'disburse' : 'request_advance',
      params: { amount: { minor: 1200000, currency: 'USD' } },
      evidence_ids: previous.get(r.round - 1) ?? [], obs_hash: '0'.repeat(64)
    }))
    previous.set(r.round, [...r.feed_ids])
    return { round: r.round, branch_id: ctx.branch_id, t_hours: r.t_h, intents, cleared: [], journal_ids: [] }
  })
  const feed = scrubber.rounds.flatMap((r) => r.feed_ids.filter((id) => id.startsWith('p-')).map((id) => ({
    post_id: id, round: r.round, branch_id: ctx.branch_id, author: r.highlight_actor, text: 'Rumour'
  })))
  return {
    as_of: at(20), mode: ctx.mode, run_id: runId, snapshot_id: 'lf2', status,
    committed_round: ctx.last_committed_round, rounds, feed,
    cash_paths: [{ branch_id: ctx.branch_id, account_id: 'lender-pool',
      points: scrubber.rounds.map((r) => ({ t: at(r.t_h), value: { minor: r.K_p_minor, currency: 'USD', status: 'known' } })) }],
    branches: [{ branch_id: ctx.branch_id, parent_branch_id: null, checkpoint_round: null, policy: null, replay: false }]
  }
}

const mounted = []
afterEach(() => {
  while (mounted.length) mounted.pop().unmount()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function open (answer) {
  let gets = 0
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    gets += 1
    const id = decodeURIComponent(new URL(url).pathname.split('/').pop())
    return { ok: true, status: 200, json: async () => clone(answer(id)) }
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/simulation', component: Simulation }, { path: '/:any(.*)', component: { render: () => h('div') } }]
  })
  await router.push(`/simulation?run_id=${ctx.run_id}`)
  await router.isReady()
  const w = mount(Simulation, { attachTo: document.body, global: { plugins: [router, i18n] } })
  await flushPromises()
  mounted.push(w)
  // The upstream view draws on a data change or a window resize, not when it mounts.
  window.dispatchEvent(new Event('resize'))
  await flushPromises()
  return { w, router, gets: () => gets }
}

/** Click a drawn graph element the way a pointer does: on the SVG element d3 bound the datum to. */
async function pick (w, selector, matches) {
  const el = [...w.element.querySelectorAll(`[data-test="graph"] ${selector}`)].find((e) => matches(e.__data__))
  expect(el, `no ${selector} drawn for the selection`).toBeTruthy()
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
}
const pickNode = (w, uuid) => pick(w, 'circle', (d) => d?.id === uuid)
const pickEdge = (w, uuid) => pick(w, 'path', (d) => d?.rawData?.uuid === uuid)
const details = (w) => w.find('[data-test="graph"] .detail-panel')
async function scrubTo (w, round) {
  await w.get(`[data-test="tick-${round}"]`).trigger('click')
  await flushPromises()
}

describe('graph selection follows the round cursor', () => {
  it('scrubbing back past a selected node closes its details', async () => {
    const { w } = await open(() => run())
    await pickNode(w, 'actor:lender') // the lender first acts in round 5
    expect(details(w).text()).toContain('actor:lender')
    await scrubTo(w, 4)
    expect(details(w).exists()).toBe(false)
  })

  it('scrubbing back past a selected edge closes its details', async () => {
    const { w } = await open(() => run())
    await pickEdge(w, 'i-r5-lender-1->i-r4-borrower-c-1')
    expect(details(w).text()).toContain('i-r5-lender-1 cites i-r4-borrower-c-1')
    await scrubTo(w, 4)
    expect(details(w).exists()).toBe(false)
  })

  it('scrubbing to a round that was not returned closes the details', async () => {
    const { w } = await open(() => run())
    await pickNode(w, 'post:p-r3-1')
    expect(details(w).exists()).toBe(true)
    await scrubTo(w, 2)
    expect(w.get('[data-test="inspector"]').text()).toContain('Round not loaded')
    expect(details(w).exists()).toBe(false)
  })

  it('another run selected closes the old run\'s details', async () => {
    const { w, router } = await open((id) => run(id))
    await pickNode(w, 'actor:borrower-c')
    expect(details(w).exists()).toBe(true)
    await router.push('/simulation?run_id=run-other')
    await flushPromises()
    expect(w.get('[data-test="phase"]').text()).toContain('showing round 5')
    expect(details(w).exists()).toBe(false)
  })

  it('a poll that changes nothing keeps the selected details', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { w, gets } = await open(() => run(ctx.run_id, 'running'))
    await pickEdge(w, 'i-r5-lender-2->i-r4-borrower-c-1')
    const before = gets()
    await vi.advanceTimersByTimeAsync(4000)
    await flushPromises()
    expect(gets()).toBe(before + 1)
    expect(details(w).text()).toContain('i-r5-lender-2 cites i-r4-borrower-c-1')
  })
})

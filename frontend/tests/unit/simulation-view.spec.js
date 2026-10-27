// The Live Simulation screen mounted on a C6 RunResponse built from the UI design fixture
// scrubber.json, loaded unchanged: one committed-round cursor drives the feed, the cash paths and
// the graph. No request leaves the test: fetch is replaced by a recorder that answers each path.
//
// C6 RunResponse carries cash paths, not a per-round lender capacity: the fixture's K_p is
// projected onto a lender-account cash path, which is how the screen shows any account's path.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, watch } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Simulation from '../../src/views/Simulation.vue'

import scrubber from '../../../prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/scrubber.json'

const kase = (id) => scrubber.cases.find((c) => c.id === id)
const clone = (x) => JSON.parse(JSON.stringify(x))
const Stub = { render: () => h('div', 'stub') }
const EPOCH = Date.parse('2026-01-05T00:00:00Z')
const at = (hours) => new Date(EPOCH + hours * 3_600_000).toISOString().replace('.000Z', 'Z')
const ctx = scrubber.context

/** The upstream graph view stands in as a button that asks to expand, as the real one does. */
const graphs = []
const GraphStub = defineComponent({
  name: 'GraphPanel',
  props: { graphData: Object },
  emits: ['toggle-maximize', 'refresh'],
  setup (props, { emit, expose }) {
    expose({ closeDetailPanel: () => {} })
    watch(() => props.graphData, (g) => graphs.push(g), { immediate: true })
    return () => h('div', { 'data-test': 'graph-panel', 'data-nodes': props.graphData?.nodes.length ?? 0 }, [
      h('button', { type: 'button', 'data-test': 'expand', onClick: () => emit('toggle-maximize') }, 'Expand'),
      h('button', { type: 'button', 'data-test': 'graph-refresh', onClick: () => emit('refresh') }, 'Refresh')
    ])
  }
})

/** An intent of the fixture's chain: each cites the step before it (post → request → disbursal). */
function intent (id, round, actor, evidence) {
  return {
    intent_id: id, branch_id: ctx.branch_id, round, actor_id: actor,
    type: actor === 'lender' ? 'disburse' : 'request_advance',
    params: { amount: { minor: 1200000, currency: 'USD' } },
    evidence_ids: evidence, obs_hash: '0'.repeat(64)
  }
}

/** A C6 RunResponse holding exactly the fixture's rounds: round 1 and 2 were not returned. */
function run (change = {}) {
  const c = { ...ctx, ...change }
  const previous = new Map()
  const rounds = scrubber.rounds.map((r) => {
    const intents = r.feed_ids.filter((id) => id.startsWith('i-'))
      .map((id) => intent(id, r.round, r.highlight_actor, previous.get(r.round - 1) ?? []))
    previous.set(r.round, [...r.feed_ids])
    return {
      round: r.round, branch_id: c.branch_id, t_hours: r.t_h, intents,
      cleared: intents.map((i) => ({ intent_id: i.intent_id, status: 'accepted', journal_id: `j-${i.intent_id}`, round: r.round })),
      journal_ids: intents.map((i) => `j-${i.intent_id}`)
    }
  })
  const feed = scrubber.rounds.flatMap((r) => r.feed_ids.filter((id) => id.startsWith('p-')).map((id) => ({
    post_id: id, round: r.round, branch_id: c.branch_id, author: r.highlight_actor,
    text: 'Rumour: the treasury is short of cash'
  })))
  return {
    as_of: at(c.last_committed_round * c.round_hours), mode: c.mode, run_id: c.run_id,
    snapshot_id: 'lf2', status: 'done', committed_round: c.last_committed_round, rounds, feed,
    cash_paths: [{
      branch_id: c.branch_id, account_id: 'lender-pool',
      points: [{ t: at(0), value: { minor: null, currency: 'USD', status: 'unknown' } },
        ...scrubber.rounds.map((r) => ({ t: at(r.t_h), value: { minor: r.K_p_minor, currency: 'USD', status: 'known' } }))]
    }],
    branches: [{ branch_id: c.branch_id, parent_branch_id: null, checkpoint_round: null, policy: null, replay: c.replay }]
  }
}

/**
 * Record every request and answer it: GET /runs/<id> from ``body``, POSTs from ``posts``. An
 * answer may be a function (called per request, may return a promise held by the test).
 */
function serve (body, posts = {}) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const path = new URL(url).pathname.replace('/api/v1', '')
    const method = init.method || 'GET'
    calls.push({ path, method, headers: init.headers, body: init.body ? JSON.parse(init.body) : undefined })
    let answer = method === 'GET' ? (path === `/runs/${ctx.run_id}` ? body : undefined) : posts[path]
    if (typeof answer === 'function') answer = await answer()
    if (answer instanceof Error) throw answer
    if (answer === undefined) throw new Error(`no recorded answer for ${method} ${path}`)
    return { ok: true, status: method === 'GET' ? 200 : 202, json: async () => clone(answer) }
  }))
  return calls
}

/** A promise the test resolves itself: a request held in flight. */
function held () {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

async function open (body, posts) {
  const calls = serve(body, posts)
  const r = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/simulation', component: Simulation },
      { path: '/overview', component: Stub },
      { path: '/decisions', component: Stub }
    ]
  })
  await r.push(`/simulation?run_id=${ctx.run_id}`)
  await r.isReady()
  const wrapper = mount(Simulation, { attachTo: document.body, global: { plugins: [r], stubs: { GraphPanel: GraphStub } } })
  await flushPromises()
  mounted.push(wrapper)
  return { wrapper, calls, router: r }
}

const mounted = []
const text = (w, test) => w.get(`[data-test="${test}"]`).text().replace(/\s+/g, ' ')
const disabled = (w, test) => w.get(`[data-test="${test}"]`).attributes('disabled') !== undefined
const feedIds = (w) => w.findAll('[data-test="feed"] [data-id]').map((e) => e.attributes('data-id'))
async function scrubTo (w, round) {
  await w.get(`[data-test="tick-${round}"]`).trigger('click')
  await flushPromises()
}

afterEach(() => {
  while (mounted.length) mounted.pop().unmount()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('scrubber fixture', () => {
  it('cursor-r4: scrubbing to round 4 shows the feed and cash of round 4, nothing later', async () => {
    const want = kase('cursor-r4')
    const { wrapper: w } = await open(run())
    expect(text(w, 'cursor')).toContain(`Round ${ctx.last_committed_round} of ${ctx.last_committed_round}`)
    await scrubTo(w, want.select_round)
    const r = want.expect.all_panels_round
    expect(text(w, 'cursor')).toContain(`Round ${r} of`)
    expect(text(w, 'feed')).toContain(`round ${r}`)
    expect(text(w, 'cash')).toContain(`round ${r}`)
    expect(text(w, 'inspector')).toContain(`round ${r}`)
    expect(feedIds(w)).toContain(want.expect.feed_contains)
    expect(feedIds(w)).not.toContain(want.expect.feed_excludes)
    expect(text(w, 'cash-value')).toBe(want.expect.capacity)
    expect(text(w, 'phase')).toContain(`showing round ${r}`)
    // the graph holds only what existed by round 4: the post, its author and borrower-c
    expect(w.get('[data-test="graph-panel"]').attributes('data-nodes')).toBe('3')
  })

  it('round 5 shows its own cash, not round 4\'s, and the lender acted', async () => {
    const { wrapper: w } = await open(run())
    expect(text(w, 'cash-value')).toBe('USD 30,000.00')
    expect(feedIds(w)).toEqual(scrubber.rounds[2].feed_ids)
    expect(text(w, 'inspector')).toContain('lender · acted this round')
  })

  it('pause: playback stops locally and no request asks the server to stop', async () => {
    vi.useFakeTimers()
    const want = kase('pause')
    const { wrapper: w, calls } = await open(run())
    await w.get('[data-test="play"]').trigger('click') // from the end, playback starts at round 1
    expect(text(w, 'cursor')).toContain('Round 1 of')
    await vi.advanceTimersByTimeAsync(1500)
    expect(text(w, 'cursor')).toContain('Round 2 of')
    expect(text(w, 'play')).toBe(want.action)
    await w.get('[data-test="play"]').trigger('click')
    expect(text(w, 'paused')).toBe(want.expect.label)
    await vi.advanceTimersByTimeAsync(6000)
    expect(text(w, 'cursor')).toContain('Round 2 of') // cursor_stops
    expect(calls.every((c) => c.method === 'GET')).toBe(true) // server_job_not_cancelled
  })

  it('running-r6: the running round is not shown; the committed one is, and the job is polled', async () => {
    vi.useFakeTimers()
    const want = kase('running-r6')
    const body = run()
    body.status = 'running'
    body.rounds.push({ round: want.server_running_round, branch_id: ctx.branch_id, t_hours: 24,
      intents: [intent('i-r6-partial', 6, 'lender', [])], cleared: [], journal_ids: ['j-partial'] })
    const { wrapper: w, calls } = await open(body)
    expect(text(w, 'phase')).toContain(want.expect.label)
    expect(text(w, 'cursor')).toContain(`Round ${want.expect.display_round} of ${want.expect.display_round}`)
    expect(w.find('[data-test="tick-6"]').exists()).toBe(false)
    expect(feedIds(w)).not.toContain('i-r6-partial') // partial_journal_visible: false
    expect(disabled(w, 'fork')).toBe(true)
    const gets = calls.length
    await vi.advanceTimersByTimeAsync(4000)
    expect(calls.length).toBe(gets + 1)
  })

  it('invalid: the branch is labelled invalid and fork and compare are disabled', async () => {
    const want = kase('invalid')
    const body = run()
    body.status = 'failed'
    const { wrapper: w } = await open(body)
    expect(text(w, 'phase')).toContain(want.expect.label)
    expect(text(w, 'cursor')).toContain(`Round ${want.expect.display_round} of`)
    await w.get('[data-test="token"]').setValue('demo-token-for-test')
    expect(disabled(w, 'fork')).toBe(!want.expect.fork_enabled)
    expect(disabled(w, 'compare')).toBe(!want.expect.compare_enabled)
    expect(w.get('[data-test="compare"]').element.tagName).toBe('BUTTON')
  })

  it('replay: the Replay label is in the header, the feed, the cash path and the export', async () => {
    const want = kase('replay')
    const { wrapper: w } = await open(run(want.change))
    const label = want.expect.label_in_header_and_export
    expect(text(w, 'source').startsWith(`${label} ·`)).toBe(true)
    expect(text(w, 'feed-replay')).toBe(label)
    expect(text(w, 'cash-replay')).toBe(label)
    expect(text(w, 'replay-note')).toContain('replayed, not run fresh') // counts_as_fresh_branch: false
    const exported = JSON.parse(decodeURIComponent(w.get('[data-test="export"]').attributes('href').split(',').slice(1).join(',')))
    expect(exported.label).toBe(label)
    expect(exported.source.startsWith(label)).toBe(true)
    expect(JSON.stringify(exported)).not.toContain('token')
  })

  it('a fresh branch carries no Replay label anywhere', async () => {
    const { wrapper: w } = await open(run())
    expect(w.find('[data-test="feed-replay"]').exists()).toBe(false)
    expect(w.find('[data-test="cash-replay"]').exists()).toBe(false)
    expect(text(w, 'source')).toBe(`Hypothetical branch ${ctx.branch_id}`)
  })

  it('fork: carries the selected round, needs the token, and creates no approval', async () => {
    const want = kase('fork')
    const accepted = { as_of: at(20), mode: 'fake', job_id: 'job-1', run_id: ctx.run_id, branch_ids: ['b-1', 'b-2', 'b-3'] }
    const { wrapper: w, calls } = await open(run(), { [`/runs/${ctx.run_id}/fork`]: accepted })
    await scrubTo(w, want.select_round)
    expect(disabled(w, 'fork')).toBe(true)
    expect(text(w, 'fork-why')).toBe('Enter the demo token to fork')
    await w.get('[data-test="token"]').setValue('demo-token-for-test')
    expect(text(w, 'fork')).toBe(want.action)
    expect(text(w, 'fork-what')).toContain(`Forks ${want.expect.payload_parent_branch} at round ${want.expect.payload_round}`)
    await w.get('[data-test="fork"]').trigger('click')
    await flushPromises()
    const posts = calls.filter((c) => c.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0].path).toBe(`/runs/${ctx.run_id}/fork`)
    expect(posts[0].body).toEqual({ checkpoint_round: want.expect.payload_round, policies: ['no-action', 'fixed-reserve', 'integrated'] })
    expect(posts[0].headers.Authorization).toBe('Bearer demo-token-for-test')
    expect(calls.some((c) => c.path.startsWith('/approvals'))).toBe(want.expect.creates_approval)
    expect(text(w, 'forked')).toContain('round 4: b-1, b-2, b-3')
    expect(w.html()).not.toContain('demo-token-for-test')
  })

  it('interview: read-only, carries the actor and the selected round, behind the token', async () => {
    const want = kase('interview')
    const reply = { run_id: ctx.run_id, branch_id: ctx.branch_id, round: want.select_round, as_of: at(16),
      mode: 'fake', actor_id: want.select_actor, answer: 'I asked for an advance after the post.',
      read_only: true, replay: false, evidence_ids: ['p-r3-1'] }
    const { wrapper: w, calls } = await open(run(), { '/interview': reply })
    await scrubTo(w, want.select_round)
    await w.get(`[data-actor="${want.select_actor}"]`).trigger('click')
    await w.get('[data-test="question"]').setValue('Why did you ask for an advance?')
    expect(text(w, 'interview-why')).toBe('Enter the demo token to interview')
    await w.get('[data-test="token"]').setValue('demo-token-for-test')
    await w.get('[data-test="interview"]').trigger('submit')
    await flushPromises()
    const posts = calls.filter((c) => c.method === 'POST')
    expect(posts.map((c) => c.path)).toEqual(['/interview']) // no_financial_write
    expect(posts[0].body).toMatchObject({ run_id: ctx.run_id, branch_id: ctx.branch_id,
      round: want.expect.payload_round, actor_id: want.select_actor })
    expect(posts[0].headers.Authorization).toBe('Bearer demo-token-for-test')
    expect(text(w, 'answer')).toContain(`Read-only answer · ${want.select_actor} at round ${want.expect.payload_round}`)
    expect(want.expect.read_only).toBe(reply.read_only)
  })

  it('old-round-not-returned: a round the API did not return reads not loaded, never the latest', async () => {
    const want = kase('old-round-not-returned')
    const { wrapper: w } = await open(run())
    await scrubTo(w, want.select_round)
    expect(text(w, 'feed-unloaded')).toBe(want.expect.label)
    expect(text(w, 'cash-unloaded')).toBe(want.expect.label)
    expect(feedIds(w)).toEqual([])
    expect(w.text()).not.toContain('USD 30,000.00') // substitute_latest: false
    expect(w.text()).not.toContain('USD 42,000.00')
    expect(w.find('[data-test="export"]').exists()).toBe(false)
    expect(disabled(w, 'fork')).toBe(true)
  })

  it('phone: reading order, keyboard scrubbing and an expandable graph', async () => {
    const want = kase('phone')
    const { wrapper: w } = await open(run())
    const order = ['banner', 'controls', 'cash', 'feed', 'graph'].map((t) => w.get(`[data-test="${t}"]`).element)
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
    expect(want.expect.order).toHaveLength(order.length)
    const slider = w.get('[data-test="scrubber-slider"]')
    const [left, right, home, end] = want.expect.scrubber_keyboard
    await slider.trigger('keydown', { key: left })
    expect(text(w, 'cursor')).toContain('Round 4 of')
    await slider.trigger('keydown', { key: home })
    expect(slider.attributes('aria-valuenow')).toBe('1')
    await slider.trigger('keydown', { key: right })
    expect(slider.attributes('aria-valuenow')).toBe('2')
    await slider.trigger('keydown', { key: end })
    expect(slider.attributes('aria-valuenow')).toBe(String(ctx.last_committed_round))
    await w.get('[data-test="expand"]').trigger('click')
    expect(w.find('.lw-live').classes()).toContain('is-graph-expanded') // graph_can_expand
  })
})

describe('review findings, each pinned', () => {
  it('another run selected: the old run\'s state cannot fork or interview into the new one', async () => {
    const { wrapper: w, router } = await open(run())
    await w.get('[data-test="token"]').setValue('demo-token-for-test')
    await w.get('[data-actor="lender"]').trigger('click')
    await w.get('[data-test="question"]').setValue('Why?')
    expect(disabled(w, 'fork')).toBe(false)
    await router.push('/simulation?run_id=run-other') // its GET has no answer: it fails
    await flushPromises()
    expect(text(w, 'fork-why')).toBe('Not current: load this run first')
    expect(text(w, 'interview-why')).toBe('Not current: load this run first')
  })

  it('an interview answered after the run changed is not shown under the new run', async () => {
    const late = held()
    const reply = { run_id: ctx.run_id, branch_id: ctx.branch_id, round: 5, as_of: at(20), mode: 'fake',
      actor_id: 'lender', answer: 'old run', read_only: true, replay: false, evidence_ids: [] }
    const { wrapper: w, router } = await open(run(), { '/interview': () => late.promise })
    await w.get('[data-test="token"]').setValue('demo-token-for-test')
    await w.get('[data-actor="lender"]').trigger('click')
    await w.get('[data-test="question"]').setValue('Why?')
    await w.get('[data-test="interview"]').trigger('submit')
    await router.push('/simulation?run_id=run-other')
    await flushPromises()
    late.resolve(reply)
    await flushPromises()
    expect(w.find('[data-test="answer"]').exists()).toBe(false)
  })

  it('playing a finished run to its end stops without claiming a pause', async () => {
    vi.useFakeTimers()
    const { wrapper: w } = await open(run())
    await w.get('[data-test="play"]').trigger('click')
    await vi.advanceTimersByTimeAsync(1500 * 6)
    expect(text(w, 'cursor')).toContain(`Round ${ctx.last_committed_round} of`)
    expect(text(w, 'play')).toBe('Play')
    expect(w.find('[data-test="paused"]').exists()).toBe(false)
  })

  it('an actor who has not acted by the selected round cannot be interviewed there', async () => {
    const { wrapper: w } = await open(run())
    await w.get('[data-test="token"]').setValue('demo-token-for-test')
    await w.get('[data-actor="lender"]').trigger('click')
    await w.get('[data-test="question"]').setValue('Why?')
    expect(disabled(w, 'ask')).toBe(false)
    await scrubTo(w, 4)
    expect(text(w, 'interview-why')).toBe('lender has not acted by round 4')
    expect(disabled(w, 'ask')).toBe(true)
  })

  it('a poll that changes nothing keeps the graph object and the controls', async () => {
    vi.useFakeTimers()
    const body = run()
    body.status = 'running'
    const slow = held()
    let gets = 0
    const { wrapper: w } = await open(() => (++gets === 1 ? body : slow.promise))
    const shown = graphs[graphs.length - 1]
    await vi.advanceTimersByTimeAsync(4000) // the poll is in flight
    expect(disabled(w, 'refresh')).toBe(false)
    expect(disabled(w, 'play')).toBe(false)
    slow.resolve(body)
    await flushPromises()
    expect(graphs[graphs.length - 1]).toBe(shown)
  })

  it('a successful fork reloads the run, and a later failure clears the old success', async () => {
    let answer = { as_of: at(20), mode: 'fake', job_id: 'job-1', run_id: ctx.run_id, branch_ids: ['b-1'] }
    const { wrapper: w, calls } = await open(run(), { [`/runs/${ctx.run_id}/fork`]: () => answer })
    await w.get('[data-test="token"]').setValue('demo-token-for-test')
    await scrubTo(w, 4)
    const before = calls.filter((c) => c.method === 'GET').length
    await w.get('[data-test="fork"]').trigger('click')
    await flushPromises()
    expect(calls.filter((c) => c.method === 'GET').length).toBe(before + 1)
    expect(w.find('[data-test="forked"]').exists()).toBe(true)
    answer = new Error('fork_in_progress')
    await w.get('[data-test="fork"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="forked"]').exists()).toBe(false)
    expect(text(w, 'fork-error')).toContain('fork_in_progress')
  })

  it('the cursor names the round\'s own simulated time, and none for an unloaded round', async () => {
    const body = run()
    body.rounds[1].t_hours = 17 // round 4 at an hour that is not round × 4
    body.cash_paths[0].points[2].t = at(17)
    const { wrapper: w } = await open(body)
    await scrubTo(w, 4)
    expect(text(w, 'cursor')).toBe('Round 4 of 5 · simulated t=17 h')
    expect(text(w, 'cash-value')).toBe('USD 42,000.00')
    await scrubTo(w, 2)
    expect(text(w, 'cursor')).toBe('Round 2 of 5 · simulated time not loaded')
  })

  it('a reload asked for while a poll is in flight shows as loading, not as a quiet poll', async () => {
    vi.useFakeTimers()
    const body = run()
    body.status = 'running'
    const [poll, reload] = [held(), held()]
    let gets = 0
    const { wrapper: w } = await open(() => [body, poll.promise, reload.promise][Math.min(gets++, 2)])
    await vi.advanceTimersByTimeAsync(4000) // the poll is in flight
    expect(disabled(w, 'refresh')).toBe(false)
    await w.get('[data-test="graph-refresh"]').trigger('click') // the operator reloads
    await flushPromises()
    expect(disabled(w, 'refresh')).toBe(true)
    poll.resolve(body)
    reload.resolve(body)
    await flushPromises()
    expect(disabled(w, 'refresh')).toBe(false)
  })
})

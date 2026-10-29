// The Live Simulation world map draws an intent's edge as financial only when the coordinator
// accepted it and posted a journal: a rejected, pending, unjournalled or unverdicted disbursement
// is a proposal, never a movement. Every intent edge's evidence, and every feed item's, names the
// clearing verdict, its reason and the journal state, and says why nothing moved when nothing did.
// No request leaves the test.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import Simulation from '../../src/views/Simulation.vue'

const RUN = 'run-verdict'
const BRANCH = 'run-verdict-base'
const usd = { minor: 1200000, currency: 'USD' }

function intent (id, round, actor, type, evidence) {
  return { intent_id: id, branch_id: BRANCH, round, actor_id: actor, type, params: { amount: usd, from: 'lender' },
    evidence_ids: evidence, obs_hash: '0'.repeat(64) }
}

// Round 1: borrower-c asks (accepted, no journal: the message req:borrower-c:r1). Round 2: the
// lender answers it five ways, one per clearing outcome, and accepts it twice: once posting a
// journal, once not.
const DISBURSALS = [
  ['d-accepted', { status: 'accepted', journal_id: 'j-1' }],
  ['d-rejected', { status: 'rejected', reason: 'floor would break', journal_id: null }],
  ['d-pending', { status: 'pending', journal_id: null }],
  ['d-unjournalled', { status: 'accepted', journal_id: null }],
  ['d-missing', null]
]

const ACCEPTS = [
  ['a-journalled', { status: 'accepted', journal_id: 'j-2' }],
  ['a-plain', { status: 'accepted', journal_id: null }]
]

function run () {
  const ask = intent('ask', 1, 'borrower-c', 'request_advance', [])
  const pays = [...DISBURSALS.map(([id]) => intent(id, 2, 'lender', 'disburse', ['req:borrower-c:r1'])),
    ...ACCEPTS.map(([id]) => intent(id, 2, 'lender', 'accept', ['req:borrower-c:r1']))]
  const cleared = [...DISBURSALS, ...ACCEPTS].filter(([, c]) => c).map(([id, c]) => ({ intent_id: id, round: 2, ...c }))
  return {
    as_of: '2026-01-05T08:00:00Z', mode: 'fake', run_id: RUN, snapshot_id: 'lf2', status: 'done', committed_round: 2,
    rounds: [
      { round: 1, branch_id: BRANCH, t_hours: 4, intents: [ask], journal_ids: [],
        cleared: [{ intent_id: 'ask', round: 1, status: 'accepted', journal_id: null }] },
      { round: 2, branch_id: BRANCH, t_hours: 8, intents: pays, cleared, journal_ids: ['j-1', 'j-2'] }
    ],
    feed: [],
    cash_paths: [],
    branches: [{ branch_id: BRANCH, parent_branch_id: null, checkpoint_round: null, policy: null, replay: false }]
  }
}

/** The upstream graph view, standing in with the one method the screen calls on it. */
const GraphStub = defineComponent({
  name: 'GraphPanel',
  setup (_, { expose }) {
    expose({ closeDetailPanel: () => {} })
    return () => h('div')
  }
})

const mounted = []
afterEach(() => {
  while (mounted.length) mounted.pop().unmount()
  vi.unstubAllGlobals()
})

async function open (body) {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const path = new URL(url).pathname.replace('/api/v1', '')
    const answer = path === '/health' ? { ok: true, model: 'scripted' } : body
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(answer)) }
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/simulation', component: Simulation }, { path: '/:any(.*)', component: { render: () => h('div') } }]
  })
  await router.push(`/simulation?run_id=${RUN}`)
  await router.isReady()
  const w = mount(Simulation, { attachTo: document.body, global: { plugins: [router], stubs: { GraphPanel: GraphStub } } })
  await flushPromises()
  mounted.push(w)
  return w
}

const PROPOSAL = 'A proposal is not a ledger change until it is accepted and journalled.'
const ACCEPTED_NO_JOURNAL = 'Accepted with no journal: it changed no ledger.'

const edge = (w, id) => w.get(`[data-test="map-edge"][data-edge="${id}"]`)

/** Open an edge's evidence and read its rows back as an object. */
async function evidenceOf (w, id) {
  await edge(w, id).trigger('click')
  await flushPromises()
  const dl = w.get('[data-test="evidence-detail"]')
  const words = dl.findAll('dt').map((d) => d.text())
  const values = dl.findAll('dd').map((d) => d.text())
  const note = w.get('[data-test="evidence-sheet"]').find('p.lw-time')
  return { ...Object.fromEntries(words.map((k, i) => [k, values[i]])), note: note.exists() ? note.text() : '' }
}

describe('a disbursement edge carries its clearing verdict', () => {
  it('only an accepted, journalled disbursement is drawn as financial', async () => {
    const w = await open(run())
    const type = (id) => ['financial', 'request'].find((t) => edge(w, `cite:${id}:req:borrower-c:r1`).classes(`is-${t}`))
    expect(DISBURSALS.map(([id]) => [id, type(id)])).toEqual([
      ['d-accepted', 'financial'],
      ['d-rejected', 'request'],
      ['d-pending', 'request'],
      ['d-unjournalled', 'request'],
      ['d-missing', 'request']
    ])
  })

  it('the evidence names the verdict, its reason and the journal for every outcome', async () => {
    const w = await open(run())
    const read = async (id) => evidenceOf(w, `cite:${id}:req:borrower-c:r1`)

    const accepted = await read('d-accepted')
    expect(accepted).toMatchObject({ Type: 'financial', Verdict: 'Accepted', Journal: 'j-1' })
    expect(accepted.note).toBe('')

    const rejected = await read('d-rejected')
    expect(rejected).toMatchObject({ Type: 'request', Verdict: 'Rejected · floor would break', Journal: 'no ledger change' })
    expect(rejected.Relation).toContain('proposed disburse')
    expect(rejected.note).toBe(PROPOSAL)

    expect(await read('d-pending')).toMatchObject({ Verdict: 'Pending', Journal: 'no ledger change' })
    expect(await read('d-unjournalled')).toMatchObject({ Verdict: 'Accepted', Journal: 'no ledger change' })
    expect(await read('d-missing')).toMatchObject({ Verdict: 'No verdict recorded', Journal: 'no ledger change' })
  })

  it('any accepted, journalled intent is financial; an accepted one with no journal says it moved nothing', async () => {
    const w = await open(run())
    const journalled = await evidenceOf(w, 'cite:a-journalled:req:borrower-c:r1')
    expect(journalled).toMatchObject({ Type: 'financial', Verdict: 'Accepted', Journal: 'j-2' })
    expect(journalled.note).toBe('')
    const plain = await evidenceOf(w, 'cite:a-plain:req:borrower-c:r1')
    expect(plain).toMatchObject({ Type: 'request', Relation: 'accept on req:borrower-c:r1 · round 2', Journal: 'no ledger change' })
    expect(plain.note).toBe(ACCEPTED_NO_JOURNAL)
  })

  it('a request for funds carries its own verdict, and is not told it awaits a journal', async () => {
    const w = await open(run())
    const ask = await evidenceOf(w, 'intent:ask')
    expect(ask).toMatchObject({ Type: 'request', Verdict: 'Accepted', Journal: 'no ledger change' })
    expect(ask.note).toBe(ACCEPTED_NO_JOURNAL)
  })
})

describe('a feed item\'s evidence says the same as the map\'s', () => {
  const pickFeed = async (w, id) => {
    await w.get(`[data-test="feed"] [data-id="${id}"] [data-test="feed-open"]`).trigger('click')
    await flushPromises()
    return w.get('[data-test="evidence-sheet"]').find('p.lw-time').text()
  }

  it('an accepted request and a rejected disbursement each get their own note', async () => {
    const w = await open(run())
    expect(await pickFeed(w, 'd-rejected')).toBe(PROPOSAL)
    await w.get('[data-test="tick-1"]').trigger('click')
    await flushPromises()
    expect(await pickFeed(w, 'ask')).toBe(ACCEPTED_NO_JOURNAL)
  })
})

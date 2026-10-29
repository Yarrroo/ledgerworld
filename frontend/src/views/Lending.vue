<template>
  <ScreenShell v-slot="{ body }" title="Lending" :reading="state" :refresh="refresh" :stale="stale">
    <p class="lw-lead" data-test="lead">{{ lead }}</p>
    <p v-if="leadSeen" class="lw-time" data-test="lead-stale">{{ leadSeen }}</p>

    <section class="lw-len__context" aria-label="Your lender" data-panel="Your lender" data-test="pool-context">
      <p>Lender: <b data-test="pool">{{ poolName }}</b></p>
      <p v-if="reduced" class="lw-note" data-test="reduced">
        Some of the lender's balances could not be read, so only the money we can see is counted.
      </p>
      <HowWeKnow test="how-lending">
        <dl>
          <div><dt>Snapshot</dt><dd>{{ body.snapshot_id }}</dd></div>
          <div><dt>Currency</dt><dd>{{ capacity.K_p.currency }}</dd></div>
          <div>
            <dt>Balance authority</dt>
            <dd :class="['lw-status', `lw-status--${reduced ? 'warn' : 'muted'}`]" data-test="authority">
              <span aria-hidden="true">{{ reduced ? '!' : '●' }}</span>
              <span>Balance authority {{ capacity.authority }}</span>
            </dd>
          </div>
          <div><dt>Source time</dt><dd>{{ formatTime(capacity.K_p.as_of || body.as_of).utc }}</dd></div>
        </dl>
        <p>What the lender can still lend is the pool's lender capacity K_p, GET /api/v1/lending: settled
          known − committed undrawn − pledged − pool obligations due in the horizon − pool reserve floor.</p>
      </HowWeKnow>
    </section>

    <div class="lw-len">
      <div class="lw-len__main">
        <section aria-labelledby="capacity-heading" data-panel="What it can lend" data-test="bridge">
          <h2 id="capacity-heading">What the lender can still lend</h2>
          <article class="lw-tile" data-test="capacity">
            <div class="lw-tile__label">Left to lend · {{ poolName }}</div>
            <div class="lw-figure" data-test="capacity-value">{{ capacityText }}</div>
            <div :class="['lw-status', `lw-status--${stateOf(capacity.K_p.status).tone}`]" data-test="capacity-status">
              {{ metricStatus(capacity.K_p) }}
            </div>
            <ol class="lw-len__bridge" aria-label="Capacity bridge, every part" data-test="parts">
              <li v-for="p in parts" :key="p.key" :data-part="p.key">
                <span class="lw-len__sign" aria-hidden="true">{{ p.sign }}</span>
                <span class="lw-len__part">{{ p.label }}</span>
                <span class="lw-len__amount">{{ p.sign === '−' ? 'minus ' : '' }}{{ metricText(p.metric) }}</span>
                <span class="lw-len__state">{{ stateOf(p.metric.status).word }}</span>
                <span class="lw-len__bar" aria-hidden="true"><span :style="{ width: p.bar }" :class="`is-${p.tone}`" /></span>
              </li>
              <li class="lw-len__total" data-part="K_p">
                <span class="lw-len__sign" aria-hidden="true">=</span>
                <span class="lw-len__part">Left to lend</span>
                <span class="lw-len__amount">{{ metricText(capacity.K_p) }}</span>
                <span class="lw-len__state">{{ stateOf(capacity.K_p.status).word }}</span>
              </li>
            </ol>
            <details class="lw-calc" data-test="expand-calculation">
              <summary>See the calculation</summary>
              <div class="lw-calc__body" data-test="calculation">
                <p>In {{ capacity.K_p.currency }}, parts from the API:</p>
                <p>{{ calculation }}</p>
                <p>settled known − committed undrawn − pledged − pool obligations due − pool floor = K_p</p>
              </div>
            </details>
            <details class="lw-calc" data-test="evidence">
              <summary>View account evidence</summary>
              <div class="lw-calc__body">
                <p>Counted: settled known {{ metricText(capacity.parts.settled_known) }}, as of
                  {{ formatTime(capacity.parts.settled_known.as_of || body.as_of).utc }}.</p>
                <p v-if="poolAccounts.length">The pool's cash accounts on {{ body.snapshot_id }}: {{ poolAccounts.join(', ') }}.</p>
                <p v-if="notCurrent.length">Not counted: {{ notCurrent.map((f) => `${f.text} (${f.id})`).join('; ') }}.</p>
                <p v-else>Not counted: none; every pool cash account was observed.</p>
                <p>Balances per account are not itemised by GET /api/v1/lending; this screen shows no figure it was not given.</p>
              </div>
            </details>
          </article>
          <article v-if="notCurrent.length" class="lw-tile lw-len__unobserved" data-test="not-current">
            <div class="lw-tile__label">Couldn't read, so not counted</div>
            <template v-for="f in notCurrent" :key="f.id">
              <div class="lw-figure lw-figure--small">
                {{ f.name }} ·
                <span :class="['lw-status', `lw-status--${f.tone}`]">
                  <span aria-hidden="true">{{ f.icon }}</span> {{ f.word }}
                </span>
              </div>
              <div v-if="f.at" class="lw-time">as of {{ f.at }}</div>
            </template>
          </article>
        </section>

        <section aria-labelledby="map-heading" data-panel="Who it depends on" data-test="exposure">
          <h2 id="map-heading">Who else the lender depends on</h2>
          <WorldMap :nodes="map.nodes" :edges="map.edges" :selected="picked" :focus="body.pool"
                    label="The pool's facilities and shared venue exposure" @select="picked = $event" />
          <ul class="lw-len__relations" aria-label="Relationships as text" data-test="relations">
            <li v-for="e in map.edges" :key="e.id">
              <button type="button" class="lw-len__link" :data-edge="e.id" @click="picked = { kind: 'edge', id: e.id }">
                {{ nameOf(e.from) }} → {{ nameOf(e.to) }}
              </button>
              <span class="lw-time">{{ e.type }} · {{ e.label }}</span>
            </li>
          </ul>
          <p v-if="!map.world" class="lw-time" data-test="no-world">
            No world topology for snapshot {{ body.snapshot_id }}: only the API's facilities are drawn.
          </p>
        </section>
      </div>

      <div class="lw-len__inspector">
        <section aria-labelledby="freeze-heading" data-panel="If a venue freezes" data-test="freeze">
          <h2 id="freeze-heading">What if a venue freezes?</h2>
          <article class="lw-tile">
            <template v-if="reduced">
              <div class="lw-tile__label">Happening now</div>
              <p>Some balances can't be read: {{ notCurrent.map((f) => f.text).join('; ') }}.
                Only known money counts, and new lending is paused until they can be read again.</p>
            </template>
            <template v-else>
              <div class="lw-tile__label">What-if</div>
              <p>If the lender's venue balance{{ venueAccount ? ` (${venueAccount})` : '' }} could not be read,
                it would count as Unknown, not zero: only known money would count, and new lending would pause.</p>
            </template>
            <div class="lw-actions">
              <RouterLink v-if="freezeTarget" class="lw-button lw-button--quiet" :to="freezeTarget" data-test="rehearse-freeze">
                Rehearse venue freeze
              </RouterLink>
              <template v-else>
                <button type="button" class="lw-button lw-button--quiet" disabled aria-describedby="freeze-why"
                        data-test="rehearse-freeze">Rehearse venue freeze</button>
                <span id="freeze-why" class="lw-time" data-test="freeze-why">{{ freezeWhy }}</span>
              </template>
            </div>
          </article>
        </section>

        <section aria-labelledby="facilities-heading" data-panel="Loans made">
          <h2 id="facilities-heading">Loans the lender has made</h2>
          <ul class="lw-len__facilities" data-test="facility-list">
            <li v-for="f in body.facilities" :key="f.facility_id">
              <button type="button" class="lw-len__link" :data-test="`facility-${f.facility_id}`"
                      @click="picked = { kind: 'facility', id: f.facility_id }">Open facility {{ f.facility_id }}</button>
              <span class="lw-time">{{ kindText(f.kind) }} · to {{ nameOf(f.borrower) }} · {{ f.state }}</span>
              <span class="lw-len__owed">outstanding {{ money(f.outstanding) }}</span>
            </li>
            <li v-if="!body.facilities.length">No facilities</li>
          </ul>
          <details class="lw-calc" data-test="facility-terms">
            <summary>Open facility terms</summary>
            <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Facilities">
              <table class="lw-table" data-test="facilities">
                <thead>
                  <tr><th scope="col">Facility</th><th scope="col">Borrower</th><th scope="col">Principal</th>
                    <th scope="col">Fee</th><th scope="col">Owed</th><th scope="col">Observed revenue</th>
                    <th scope="col">Outstanding</th><th scope="col">State</th></tr>
                </thead>
                <tbody>
                  <tr v-for="f in body.facilities" :key="f.facility_id">
                    <td>{{ f.facility_id }} · {{ f.kind }}</td>
                    <td>{{ f.borrower }}</td>
                    <td class="lw-num">{{ money(f.principal) }}</td>
                    <td class="lw-num">{{ money(f.fee) }}</td>
                    <td class="lw-num">{{ money(f.owed) }}</td>
                    <td class="lw-num">{{ metricText(f.observed_revenue) }}</td>
                    <td class="lw-num">{{ money(f.outstanding) }}</td>
                    <td>{{ f.state }}</td>
                  </tr>
                  <tr v-if="!body.facilities.length"><td colspan="8">No facilities</td></tr>
                </tbody>
              </table>
            </div>
            <p class="lw-time">Repayment is computed from observed revenue only, never from a forecast.</p>
          </details>
        </section>

        <section aria-labelledby="plan-heading" data-panel="Compare plans">
          <h2 id="plan-heading">Compare funding plans</h2>
          <p class="lw-time">Compare ways to cover a cash gap. Nothing is lent from this page.</p>
          <div class="lw-actions">
            <RouterLink v-if="fundingTarget" class="lw-button" :to="fundingTarget" data-test="fund">
              Compare funding plans
            </RouterLink>
            <template v-else>
              <button type="button" class="lw-button" disabled aria-describedby="fund-why" data-test="fund">
                Compare funding plans
              </button>
              <span id="fund-why" class="lw-time" data-test="fund-why">{{ fundingWhy }}</span>
            </template>
          </div>
        </section>
      </div>
    </div>

    <DetailSheet :open="Boolean(detail)" :title="detail?.title ?? 'Details'" test="lending-detail" @close="picked = null">
      <template v-if="detail?.facility">
        <dl data-test="facility-detail">
          <dt>Facility</dt><dd>{{ detail.facility.facility_id }} · {{ kindText(detail.facility.kind) }}</dd>
          <dt>Parties</dt><dd>{{ nameOf(body?.pool) }} lends to {{ nameOf(detail.facility.borrower) }}</dd>
          <dt>Status</dt><dd>{{ detail.facility.state }}</dd>
          <dt>Principal</dt><dd>{{ money(detail.facility.principal) }}</dd>
          <dt>Fee</dt><dd>{{ money(detail.facility.fee) }}</dd>
          <dt>Owed</dt><dd>{{ money(detail.facility.owed) }}</dd>
          <dt>Outstanding</dt><dd>{{ money(detail.facility.outstanding) }}</dd>
          <dt>Observed revenue</dt><dd>{{ metricText(detail.facility.observed_revenue) }}</dd>
        </dl>
        <details class="lw-calc" data-test="repayments">
          <summary>View repayments</summary>
          <div class="lw-calc__body">
            <p>Observed revenue: {{ metricText(detail.facility.observed_revenue) }}<template
              v-if="detail.facility.observed_revenue.as_of">, as of {{ formatTime(detail.facility.observed_revenue.as_of).utc }}</template>.</p>
            <p>Receipts applied to this facility are not itemised by GET /api/v1/lending; outstanding is the API's figure.
              Repayment is computed from observed revenue only, never from a forecast.</p>
          </div>
        </details>
        <p class="lw-time">Terms are not proof of disbursement.</p>
      </template>
      <template v-else-if="detail?.edge">
        <dl data-test="edge-detail">
          <dt>Relationship</dt><dd>{{ nameOf(detail.edge.from) }} → {{ nameOf(detail.edge.to) }}</dd>
          <dt>Type</dt><dd>{{ detail.edge.type }}</dd>
          <dt>Evidence</dt><dd>{{ detail.edge.label }}</dd>
          <dt>Source</dt><dd>{{ detail.edge.source }}</dd>
        </dl>
        <p v-if="detail.edge.note" class="lw-time">{{ detail.edge.note }}</p>
      </template>
      <template v-else-if="detail?.node">
        <dl data-test="node-detail">
          <dt>Party</dt><dd>{{ detail.node.label }}</dd>
          <dt>Role</dt><dd>{{ detail.node.role || 'not named by the world file' }}</dd>
          <dt>Relationships</dt><dd>{{ detail.links.length ? detail.links.join('; ') : 'none drawn' }}</dd>
        </dl>
      </template>
    </DetailSheet>
  </ScreenShell>
</template>

<script setup>
/**
 * Lending (handoff L1–L6). Capacity and its parts come from one Lending read; the pool accounts
 * K_p could not count, each stale or unknown, come from Lending itself (`capacity.unobserved`,
 * read at the same moment as its authority), never from the overview: two reads either side of
 * the freshness boundary would pair full authority with accounts the newer read no longer counts.
 * The exposure map draws the API's facilities (pool → borrower) and, for the snapshot the world
 * file describes, its shared venue exposures; the treasury read, when it answers in the same
 * context, names the treasury's expected venue withdrawal. No amount is computed here.
 */
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import DetailSheet from '../components/DetailSheet.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
import WorldMap from '../components/WorldMap.vue'
import { FAMILIES, worldFor } from '../api/world.js'
import {
  ApiError, ScreenShell, accountName, amountText, amountWords, contextKey, formatTime, freshness, getLending, getOverview,
  getTreasury, hoursFrom, kindText, lastSeen, metricStatus, metricText, money, routeExists, staleOf, stateOf, useReading
} from '../api/v1.js'

const router = useRouter()

async function load () {
  const [lending, overview, treasury] = await Promise.all([
    getLending(), getOverview(), getTreasury().catch(() => null)
  ])
  if (contextKey(lending) !== contextKey(overview)) {
    throw new ApiError(0, 'context_mismatch',
      'lending and overview answered for different snapshots or modes; reload')
  }
  const sameTreasury = treasury && contextKey(treasury) === contextKey(lending) ? treasury : null
  return { ...lending, demo: overview.demo, treasury: sameTreasury }
}

const { state, refresh } = useReading(load)
const capacity = computed(() => state.body.capacity)
const reduced = computed(() => capacity.value.authority !== 'full')
const world = computed(() => worldFor(state.body?.snapshot_id))

const nameOf = (id) => world.value?.actors.find((a) => a.id === id)?.label ?? id
const poolName = computed(() => {
  const name = nameOf(state.body.pool)
  return name === state.body.pool ? name : `${name} (${state.body.pool})`
})

const capacityText = computed(() => {
  const text = metricText(capacity.value.K_p)
  return reduced.value && capacity.value.K_p.minor !== null ? `${text} (known funds only)` : text
})

/** The finance lead's answer (COPY.md): the API's K_p, then how it is worked out. */
const lead = computed(() => {
  const kp = capacity.value.K_p
  if (kp.minor === null) return 'What your lender can still lend is unknown right now; here is what we can see.'
  if (kp.minor <= 0) return 'Your lender cannot lend you anything right now; here is how that number is worked out.'
  const known = reduced.value ? ' from the money we can see' : ''
  return `Your lender can still lend you up to ${amountWords(kp)}${known}; here is how that number is worked out.`
})
const leadSeen = computed(() => lastSeen(capacity.value.K_p))

const PARTS = [
  ['settled_known', 'Cash the lender holds', '+'],
  ['committed_undrawn', 'Promised, not yet drawn', '−'],
  ['pledged', 'Pledged as collateral', '−'],
  ['obligations_due', "The lender's own bills due soon", '−'],
  ['floor', "The lender's safety minimum", '−']
]
const parts = computed(() => {
  const whole = capacity.value.parts.settled_known.minor
  return PARTS.map(([key, label, sign]) => {
    const metric = capacity.value.parts[key]
    const share = whole > 0 && metric.minor != null ? Math.min(100, (100 * metric.minor) / whole) : 0
    return { key, label, sign, metric, bar: `${share}%`, tone: sign === '+' ? 'in' : 'out' }
  })
})

const calculation = computed(() => {
  const terms = PARTS.map(([key]) => amountText(capacity.value.parts[key]))
  return `${terms.join(' - ')} = ${amountText(capacity.value.K_p)}`
})

const notCurrent = computed(() => capacity.value.unobserved.map(freshness))
const stale = computed(() => staleOf(state.body?.capacity.unobserved))

/** The pool's cash account ids the world file lists for this snapshot (ids only, no balances). */
const poolAccounts = computed(() => {
  const w = world.value
  if (!w) return []
  return [...new Set(w.edges.filter((e) => e.type === 'exposure' && e.from === state.body.pool && e.account)
    .map((e) => e.account))]
})
const venueAccount = computed(() => poolAccounts.value[0] ?? null)

// L3: the pool at the centre, its borrowers, and the venue it shares with the treasury.
const map = computed(() => {
  const body = state.body
  const w = world.value
  const nodes = new Map()
  const node = (id) => {
    if (nodes.has(id)) return
    const actor = w?.actors.find((a) => a.id === id)
    nodes.set(id, { id, label: actor?.label ?? id, role: actor?.role ?? null })
  }
  node(body.pool)
  const edges = []
  for (const f of body.facilities) {
    node(f.borrower)
    edges.push({ id: `facility:${f.facility_id}`, from: body.pool, to: f.borrower, type: 'financial',
      label: `${f.facility_id} · ${kindText(f.kind)} · outstanding ${money(f.outstanding)}`,
      tag: kindText(f.kind),
      facility: f.facility_id, source: 'facility, GET /api/v1/lending' })
  }
  for (const e of w?.edges ?? []) {
    if (e.type !== 'exposure') continue
    node(e.from)
    node(e.to)
    let label = e.label
    let note = ''
    if (e.account) {
      const unobserved = notCurrent.value.find((f) => f.id === e.account)
      label = `${accountName(e.account, { owner: true })} · ${unobserved ? `${unobserved.icon} ${unobserved.word}` : 'counted in K_p'}`
      note = 'Its balance is not itemised by the lending read; an unknown balance is excluded, never zero.'
    }
    const flow = e.flow && body.treasury?.accounts.flatMap((a) => a.buckets.pending_in).find((x) => x.flow_id === e.flow)
    if (e.from !== body.pool && flow) {
      label = `${flow.flow_id} · ${money(flow.amount)} expected ${hoursFrom(body.treasury.as_of, flow.expected_at)}`
      note = 'An expected venue withdrawal, not settled cash.'
    }
    edges.push({ ...e, label, note, source: flow ? 'pending flow, GET /api/v1/treasury' : `world file, snapshot ${w.snapshotId}` })
  }
  return { world: Boolean(w), nodes: [...nodes.values()], edges }
})

const picked = ref(null)
const detail = computed(() => {
  const p = picked.value
  const body = state.body
  if (!p || !body) return null
  if (p.kind === 'facility' || (p.kind === 'edge' && p.id.startsWith('facility:'))) {
    const id = p.kind === 'facility' ? p.id : p.id.slice('facility:'.length)
    const facility = body.facilities.find((f) => f.facility_id === id)
    return facility ? { title: `Facility ${id}`, facility } : null
  }
  if (p.kind === 'edge') {
    const edge = map.value.edges.find((e) => e.id === p.id)
    return edge ? { title: `${nameOf(edge.from)} → ${nameOf(edge.to)}`, edge } : null
  }
  const n = map.value.nodes.find((x) => x.id === p.id)
  if (!n) return null
  const links = map.value.edges.filter((e) => e.from === n.id || e.to === n.id)
    .map((e) => `${nameOf(e.from)} → ${nameOf(e.to)}: ${e.label}`)
  return { title: n.label, node: n, links }
})

// L4: a prepared venue-freeze scenario, when the world has one.
const freezeFamily = computed(() => FAMILIES.find((f) => /freeze/.test(f.id)) ?? null)
const freezeTarget = computed(() => (freezeFamily.value && state.body?.demo?.run_id && routeExists(router, '/simulation')
  ? { path: '/simulation', query: { run_id: state.body.demo.run_id, scenario: freezeFamily.value.id } }
  : null))
const freezeWhy = computed(() => (freezeFamily.value
  ? 'No demonstration run is prepared'
  : 'No prepared venue-freeze scenario: none of the six scenario families freezes the venue'))

const fundingWhy = computed(() => {
  if (state.status === 'error') return 'Last loaded, not current; reload before funding'
  if (state.status !== 'loaded') return 'Loading'
  if (reduced.value) return 'Balance authority reduced; refresh observed evidence before funding'
  if (capacity.value.K_p.status !== 'known') {
    return `Capacity is ${metricText(capacity.value.K_p)}; refresh observed evidence before funding`
  }
  return 'The decisions screen is not part of this build'
})
const fundingTarget = computed(() => {
  if (state.status !== 'loaded' || reduced.value || capacity.value.K_p.status !== 'known') return null
  if (!routeExists(router, '/decisions')) return null
  const run = state.body.demo.run_id
  return run ? { path: '/decisions', query: { run_id: run } } : { path: '/decisions' }
})
</script>

<style scoped>
.lw-len__context dl {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-3) var(--lw-space-6);
  margin: 0;
  padding: var(--lw-space-3) 0;
  border-top: 1px solid var(--lw-rule);
  border-bottom: 1px solid var(--lw-rule);
}

.lw-len__context > p { margin: 0 0 var(--lw-space-2); }

.lw-len__context dt {
  font-size: 13px;
  color: var(--lw-ink-muted);
}

.lw-len__context dd { margin: 0; font-weight: 600; overflow-wrap: anywhere; }

.lw-len {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--lw-space-6);
  margin-top: var(--lw-space-6);
}

@media (min-width: 1200px) {
  .lw-len { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); align-items: start; }
}

.lw-len__main,
.lw-len__inspector {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--lw-space-6);
  min-width: 0;
}

.lw-len > *,
.lw-len__main > *,
.lw-len__inspector > * { min-width: 0; }

.lw-len__bridge {
  list-style: none;
  margin: var(--lw-space-4) 0 0;
  padding: 0;
}

.lw-len__bridge li {
  display: grid;
  grid-template-columns: 1.5em minmax(0, 1fr) minmax(9em, auto);
  grid-template-areas: 'sign part amount' '. bar state';
  gap: 2px var(--lw-space-3);
  align-items: center;
  padding: var(--lw-space-2) 0;
  border-top: 1px solid var(--lw-rule);
}

.lw-len__sign { grid-area: sign; font-weight: 700; color: var(--lw-ink-muted); }
.lw-len__part { grid-area: part; }
.lw-len__amount { grid-area: amount; font-variant-numeric: tabular-nums; text-align: right; font-weight: 600; }
.lw-len__state { grid-area: state; font-size: 13px; color: var(--lw-ink-muted); text-align: right; }
.lw-len__bar { grid-area: bar; height: 6px; background: var(--lw-selected); border-radius: 3px; overflow: hidden; }
.lw-len__bar span { display: block; height: 100%; }
.lw-len__bar .is-in { background: var(--lw-brand); }
.lw-len__bar .is-out { background: var(--lw-warn); }
.lw-len__total { font-weight: 700; border-top: 2px solid var(--lw-ink) !important; }

.lw-len__unobserved { margin-top: var(--lw-space-4); }

.lw-len__relations,
.lw-len__facilities {
  list-style: none;
  margin: var(--lw-space-3) 0 0;
  padding: 0;
}

.lw-len__relations li,
.lw-len__facilities li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0 var(--lw-space-3);
  align-items: center;
  padding-bottom: var(--lw-space-2);
  border-top: 1px solid var(--lw-rule);
  overflow-wrap: anywhere;
}

.lw-len__relations .lw-time,
.lw-len__facilities .lw-time { grid-column: 1 / -1; grid-row: 2; }
.lw-len__owed { grid-column: 2; grid-row: 1; font-variant-numeric: tabular-nums; text-align: right; }

.lw-len__link {
  min-height: var(--lw-target);
  padding: 0;
  border: 0;
  background: none;
  color: var(--lw-link);
  font: inherit;
  font-weight: 600;
  text-align: left;
  text-decoration: underline;
  cursor: pointer;
}
</style>

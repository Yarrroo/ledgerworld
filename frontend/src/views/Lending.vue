<template>
  <ScreenShell title="Lending" headline="Capacity you can rely on." :subtitle="subtitle" :lead="lead"
               :reading="state" :refresh="refresh" :stale="stale">
    <template #action>
      <Tip v-if="fundingTarget" text="Compare ways to cover a cash gap. Nothing is lent from this page.">
        <RouterLink class="lw-button" :to="fundingTarget" data-test="fund">Compare funding plans<Arrow /></RouterLink>
      </Tip>
      <Tip v-else :text="fundingWhy" test="fund-why">
        <button type="button" class="lw-button" disabled data-test="fund">Compare funding plans</button>
      </Tip>
    </template>

    <template #default="{ body }">
      <div class="lw-len">
        <div class="lw-len__main">
          <!-- the one figure -->
          <section class="lw-len__capacity" aria-labelledby="capacity-heading" data-test="capacity">
            <h2 id="capacity-heading" class="lw-len__label">Available pool capacity</h2>
            <div class="lw-len__big" data-test="capacity-value">
              <Tip test="tip-capacity">{{ capacityText }}<template #tip>
                <span class="lw-len__tipline">{{ poolName }}: settled known − committed undrawn − pledged − pool obligations due − pool floor.</span>
                <span class="lw-len__tipline" data-test="capacity-status">{{ metricStatus(capacity.K_p) }}</span>
                <span class="lw-len__tipline">Source time {{ formatTime(capacity.K_p.as_of || body.as_of).utc }}, GET /api/v1/lending.</span>
                <span v-if="leadSeen" class="lw-len__tipline" data-test="lead-stale">{{ leadSeen }}</span>
              </template></Tip>
            </div>
            <p class="lw-len__basis" data-test="capacity-basis">
              <Tip :text="`Balance authority ${capacity.authority}: ${reduced ? 'some of the pool’s balances could not be read, so only the money we can see counts' : 'every pool cash account was read'}.`">
                <span :class="reduced ? 'lw-status lw-status--warn' : ''"><span v-if="reduced" aria-hidden="true">! </span>{{ capital(capacity.authority) }} balance authority</span>
              </Tip>
              <span aria-hidden="true"> · </span>
              <Tip :text="metricStatus(capacity.K_p)"><span>{{ fundsWord }}</span></Tip>
              <HowWeKnow test="how-lending">
                <span class="lw-len__tipline">Snapshot {{ body.snapshot_id }} · {{ capacity.K_p.currency }}</span>
                <span :class="['lw-len__tipline', 'lw-status', `lw-status--${reduced ? 'warn' : 'muted'}`]" data-test="authority">
                  <span aria-hidden="true">{{ reduced ? '!' : '●' }}</span> Balance authority {{ capacity.authority }}
                </span>
                <span class="lw-len__tipline">Source time {{ formatTime(capacity.K_p.as_of || body.as_of).utc }}</span>
                <span class="lw-len__tipline">The pool's lender capacity K_p, GET /api/v1/lending: settled known − committed
                  undrawn − pledged − pool obligations due in the horizon − pool reserve floor.</span>
              </HowWeKnow>
            </p>
            <p v-if="notCurrent.length" class="lw-len__unread" data-test="not-current">
              <span>Not counted:</span>
              <span v-for="f in notCurrent" :key="f.id" class="lw-len__unread-item">{{ f.name }} ·
                <Tip :text="`${f.text} (${f.id})`"><span :class="['lw-status', `lw-status--${f.tone}`]"><span
                  aria-hidden="true">{{ f.icon }}</span> {{ f.word }}</span></Tip>
              </span>
            </p>
          </section>

          <!-- the bridge, as arithmetic -->
          <section class="lw-len__bridge" aria-labelledby="bridge-heading" data-test="bridge">
            <h2 id="bridge-heading">Capacity bridge</h2>
            <ol class="lw-len__terms" aria-label="Capacity bridge" data-test="parts">
              <li v-for="(p, i) in bridge" :key="p.key" :data-part="p.key" class="lw-len__term">
                <span v-if="i > 0" class="lw-len__op" aria-hidden="true">−</span>
                <span class="lw-len__term-body">
                  <Tip>
                    <span :class="['lw-len__amount', { 'is-minus': i > 0 }]"><span v-if="i > 0" class="lw-visually-hidden">minus </span>{{ metricText(p.metric) }}</span>
                    <template #tip>
                      <span class="lw-len__tipline">{{ p.about }}</span>
                      <span class="lw-len__tipline">{{ metricStatus(p.metric) }}</span>
                      <span v-if="p.key === 'settled_known'" class="lw-len__tipline" data-test="evidence">
                        Counted: settled known {{ metricText(p.metric) }}<template
                          v-if="poolAccounts.length"> on {{ poolAccounts.join(', ') }}</template>.
                        Not counted: {{ notCurrent.length ? notCurrent.map((f) => `${f.text} (${f.id})`).join('; ') : 'none; every pool cash account was observed' }}.
                        Balances per account are not itemised by GET /api/v1/lending.
                      </span>
                    </template>
                  </Tip>
                  <span class="lw-len__term-label">{{ p.label }}</span>
                </span>
              </li>
              <li class="lw-len__term" data-part="K_p">
                <span class="lw-len__op" aria-hidden="true">=</span>
                <span class="lw-len__term-body">
                  <Tip test="expand-calculation">
                    <span class="lw-len__amount is-total"><span class="lw-visually-hidden">equals </span>{{ metricText(capacity.K_p) }}</span>
                    <template #tip>
                      <span class="lw-len__tipline" data-test="calculation">In {{ capacity.K_p.currency }}, from the API: {{ calculation }}</span>
                      <span class="lw-len__tipline">settled known − committed undrawn − pledged − pool obligations due − pool floor = K_p</span>
                      <span v-if="hiddenZero.length" class="lw-len__tipline">{{ hiddenZero.join(', ') }}: $0, listed in the breakdown.</span>
                    </template>
                  </Tip>
                  <span class="lw-len__term-label">Available capacity</span>
                </span>
              </li>
            </ol>
          </section>

          <!-- the shared exposure map -->
          <section class="lw-len__map" aria-labelledby="map-heading" data-test="exposure">
            <h2 id="map-heading">Shared exposure map</h2>
            <p class="lw-len__sub">Key relationships and cash flows</p>
            <div ref="diagram" class="lw-len__diagram" :style="{ '--cols': map.columns }" data-test="map">
              <svg class="lw-len__lines" :viewBox="`0 0 ${lines.w} ${lines.h}`" aria-hidden="true">
                <defs>
                  <marker id="lw-len-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
                          orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" /></marker>
                </defs>
                <line v-for="l in lines.list" :key="l.id" :x1="l.x1" :y1="l.y1" :x2="l.x2" :y2="l.y2"
                      marker-end="url(#lw-len-arrow)" :data-edge="l.id" />
              </svg>
              <Tip v-for="n in map.nodes" :key="n.id"
                   :class="['lw-len__node', `lw-len__node--${n.kind}`]" :style="n.place"
                   data-test="map-node" :data-node="n.id">
                <span class="lw-len__node-body">
                  <span class="lw-len__node-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
                         stroke-linejoin="round"><path :d="ICON[n.kind]" /></svg>
                  </span>
                  <span>
                    <b :data-test="n.kind === 'pool' ? 'pool' : undefined">{{ n.name }}</b>
                    <small>{{ n.sub }}</small>
                    <strong v-if="n.value" class="lw-len__node-value">{{ n.value }}</strong>
                  </span>
                </span>
                <template #tip><span v-for="line in n.tip" :key="line" class="lw-len__tipline">{{ line }}</span></template>
              </Tip>
              <Tip v-for="e in map.edges" :key="e.id" :class="['lw-len__edge', { 'is-flat': e.flat }]" :style="e.place"
                   data-test="map-edge" :data-edge="e.id">
                <span class="lw-len__edge-text"><span class="lw-visually-hidden">{{ e.fromName }} to {{ e.toName }}: </span>{{ e.label }} <strong
                  v-if="e.amount">{{ e.amount }}</strong></span>
                <template #tip><span v-for="line in e.tip" :key="line" class="lw-len__tipline">{{ line }}</span></template>
              </Tip>
            </div>
            <ul class="lw-len__relations" aria-label="Relationships" data-test="relations">
              <li v-for="e in map.edges" :key="e.id" :data-edge="e.id">
                <Tip>
                  <span class="lw-len__relation">{{ e.fromShort }} → {{ e.toShort }} · {{ e.label }}{{ e.amount ? ` ${e.amount}` : '' }}</span>
                  <template #tip><span v-for="line in e.tip" :key="line" class="lw-len__tipline">{{ line }}</span></template>
                </Tip>
              </li>
            </ul>
          </section>
        </div>

        <aside class="lw-len__side">
          <!-- the breakdown -->
          <section aria-labelledby="breakdown-heading" data-test="breakdown">
            <h2 id="breakdown-heading">Capacity breakdown</h2>
            <table class="lw-len__table">
              <thead><tr><th scope="col">Item</th><th scope="col" class="lw-num">Amount</th></tr></thead>
              <tbody>
                <tr v-for="r in breakdown" :key="r.key" :data-row="r.key">
                  <th scope="row">{{ r.label }}</th>
                  <td class="lw-num">
                    <Tip :text="`${r.about} ${metricStatus(r.metric)}`">
                      <span :class="{ 'is-minus': r.minus }">{{ r.minus ? '−' : '' }}{{ metricText(r.metric) }}</span>
                    </Tip>
                  </td>
                </tr>
                <tr class="lw-len__total-row" data-row="K_p">
                  <th scope="row">Available capacity</th>
                  <td class="lw-num">
                    <Tip :text="`What the pool can still lend: the rows above, combined by the API. ${metricStatus(capacity.K_p)}`">
                      <span>{{ metricText(capacity.K_p) }}</span>
                    </Tip>
                  </td>
                </tr>
              </tbody>
            </table>
          </section>

          <!-- the venue freeze -->
          <section aria-labelledby="freeze-heading" data-test="freeze">
            <h2 id="freeze-heading">Venue freeze scenario</h2>
            <div :class="['lw-len__freeze', { 'is-now': reduced }]">
              <span class="lw-len__freeze-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"
                     stroke-linecap="round"><path d="M12 3L2 21h20zM12 10v5M12 18v.5" /></svg>
              </span>
              <div>
                <Tip :text="reduced ? 'Happening now: this is the current reading, not a rehearsal.' : 'What-if: nothing here has happened. A rehearsal changes no figure on this page.'">
                  <span class="lw-len__tag" data-test="hypothetical">{{ reduced ? 'Happening now' : 'Hypothetical' }}</span>
                </Tip>
                <p v-if="reduced">{{ notCurrent.map((f) => f.name).join('; ') }}: Unknown, not zero. Only known funds count,
                  and new lending pauses.</p>
                <p v-else>If the venue balance becomes Unknown, only known funds count and new lending pauses.</p>
              </div>
            </div>
            <Tip v-if="freezeTarget" class="lw-len__wide"
                 :text="`Opens the simulation on the prepared venue-freeze scenario${venueAccount ? ` (venue account ${venueAccount})` : ''}. Nothing is lent.`">
              <RouterLink class="lw-button lw-button--quiet lw-len__outline" :to="freezeTarget" data-test="rehearse-freeze">
                Rehearse venue freeze<Arrow />
              </RouterLink>
            </Tip>
            <Tip v-else class="lw-len__wide" :text="freezeWhy" test="freeze-why">
              <button type="button" class="lw-button lw-button--quiet lw-len__outline" disabled
                      data-test="rehearse-freeze">Rehearse venue freeze</button>
            </Tip>
          </section>
        </aside>
      </div>

      <!-- the facility terms -->
      <section class="lw-len__terms-section" aria-labelledby="facilities-heading" data-test="facility-terms">
        <div class="lw-len__terms-head">
          <div>
            <h2 id="facilities-heading">Facility terms</h2>
            <p class="lw-len__sub">Terms, not proof of disbursement. Repayment uses observed revenue only.</p>
          </div>
          <Tip :text="body.facilities.length ? 'What each facility still owes and the revenue observed to repay it.' : 'No facilities, so no repayments'">
            <button type="button" class="lw-len__go" data-test="view-repayments" :disabled="!body.facilities.length"
                    :aria-expanded="repayments ? 'true' : 'false'" aria-controls="lw-len-repayments"
                    @click="repayments = !repayments">{{ repayments ? 'Hide repayment schedule' : 'View repayment schedule' }}<Arrow v-if="!repayments" /></button>
          </Tip>
        </div>
        <div class="lw-table-wrap lw-len__table-wrap" tabindex="0" role="region" aria-label="Facilities">
          <table class="lw-table" data-test="facilities">
            <thead>
              <tr><th scope="col">Facility</th><th scope="col">From</th><th scope="col">To</th>
                <th scope="col" class="lw-num">Principal</th><th scope="col" class="lw-num">Fee</th>
                <th scope="col" class="lw-num">Total owed</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in body.facilities" :key="f.facility_id" :data-facility="f.facility_id">
                <td>
                  <Tip :text="`${f.facility_id} · ${f.kind} · ${f.state}`">
                    <span :data-test="`facility-${f.facility_id}`">{{ f.facility_id }}</span>
                  </Tip>
                </td>
                <td>{{ plain(body.pool) }}</td>
                <td>{{ plain(f.borrower) }}</td>
                <td class="lw-num"><Tip :text="`Principal of ${f.facility_id} (${kindText(f.kind)}), GET /api/v1/lending`">{{ money(f.principal) }}</Tip></td>
                <td class="lw-num"><Tip :text="`Fee on ${f.facility_id}, from the lending read`">{{ money(f.fee) }}</Tip></td>
                <td class="lw-num"><Tip :text="`Principal plus fee on ${f.facility_id}. Outstanding ${money(f.outstanding)} · observed revenue ${metricText(f.observed_revenue)}`">{{ money(f.owed) }}</Tip></td>
              </tr>
              <tr v-if="!body.facilities.length"><td colspan="6">No facilities</td></tr>
            </tbody>
          </table>
        </div>
        <div v-if="repayments" id="lw-len-repayments" class="lw-len__repayments" role="region"
             aria-label="Repayment schedule" data-test="repayments">
          <dl v-for="f in body.facilities" :key="f.facility_id">
            <div><dt>Facility</dt><dd>{{ f.facility_id }} · {{ f.state }}</dd></div>
            <div><dt>Outstanding</dt><dd>{{ money(f.outstanding) }}</dd></div>
            <div><dt>Observed revenue</dt><dd>{{ metricText(f.observed_revenue) }}<template
              v-if="f.observed_revenue.as_of">, as of {{ formatTime(f.observed_revenue.as_of).utc }}</template></dd></div>
          </dl>
          <p class="lw-len__sub">Receipts are not itemised by GET /api/v1/lending. Repayment is computed from observed
            revenue only, never from a forecast.</p>
        </div>
      </section>
    </template>
  </ScreenShell>
</template>

<script setup>
/**
 * Lending as mockup 03 (prp/2026-10-29-ux-pass/MATCH.md, 03 Lending): the hero and Compare
 * funding plans; the pool's available capacity K_p as one big figure with its authority; the
 * capacity bridge as arithmetic; the shared exposure map (the pool, its borrowers, the treasury and
 * the venue they share) as a node diagram; the capacity breakdown; the venue freeze as a labelled
 * hypothetical; the facility terms. Capacity and its parts come from one Lending read; the pool
 * accounts K_p could not count come from Lending itself (`capacity.unobserved`), never from the
 * overview. The overview of the same context gives the demonstration run and the relations the
 * map draws (with their amounts); the treasury read, when it answers in the same context, names
 * the treasury's expected venue withdrawal. No amount is computed here.
 *
 * Left out for want of an API field: the venue-freeze capacity figure (no read serves capacity
 * under a frozen venue) and the facilities' revenue share.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Arrow from '../components/Arrow.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
import Tip from '../components/Tip.vue'
import { FAMILIES, worldFor } from '../api/world.js'
import {
  ApiError, ScreenShell, amountText, amountWords, contextKey, formatTime, freshness, getLending, getOverview,
  getTreasury, hoursFrom, kindText, lastSeen, listWords, metricStatus, metricText, money, routeExists, staleOf, useReading
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
  return {
    ...lending,
    demo: overview.demo,
    company: overview.company,
    relations: overview.relations ?? [],
    treasuryCash: overview.cash ?? null,
    lenderCapacity: overview.lender_capacity ?? null,
    treasury: sameTreasury
  }
}

const { state, refresh } = useReading(load)
const capacity = computed(() => state.body.capacity)
const reduced = computed(() => capacity.value.authority !== 'full')
const world = computed(() => worldFor(state.body?.snapshot_id))

const capital = (s) => String(s ?? '').charAt(0).toUpperCase() + String(s ?? '').slice(1)
const strip = (name) => String(name ?? '').replace(/\s*\(synthetic\)\s*$/i, '')

/** A party's name: the world file's, else the overview's relations', else its id. */
function plain (id) {
  const actor = world.value?.actors.find((a) => a.id === id)
  if (actor) return actor.label
  for (const r of state.body?.relations ?? []) {
    if (r.source?.entity_id === id && r.source.name) return strip(r.source.name)
    if (r.target?.entity_id === id && r.target.name) return strip(r.target.name)
  }
  return id
}
const poolName = computed(() => {
  const name = plain(state.body.pool)
  return name === state.body.pool ? name : `${name} (${state.body.pool})`
})

const capacityText = computed(() => {
  const text = metricText(capacity.value.K_p)
  return reduced.value && capacity.value.K_p.minor !== null ? `${text} (known funds only)` : text
})
const fundsWord = computed(() => {
  const kp = capacity.value.K_p
  if (reduced.value) return 'Known funds only'
  return { known: 'Known funds', stale: 'Stale funds', unknown: 'Unknown funds' }[kp.status] ?? 'Not assessed'
})

/** The finance lead's answer (COPY.md): the API's K_p, then how it is worked out. */
const lead = computed(() => {
  if (!state.body) return ''
  const kp = capacity.value.K_p
  if (kp.minor === null) return 'What your lender can still lend is unknown right now; here is what we can see.'
  if (kp.minor <= 0) return 'Your lender cannot lend you anything right now; here is how that number is worked out.'
  const known = reduced.value ? ' from the money we can see' : ''
  return `Your lender can still lend you up to ${amountWords(kp)}${known}; here is how that number is worked out.`
})
const leadSeen = computed(() => lastSeen(capacity.value.K_p))
const subtitle = computed(() => (state.body ? `${plain(state.body.pool)} / Observed snapshot` : ''))

const PARTS = [
  ['settled_known', 'Settled known', 'Settled cash the pool holds on accounts it could read.'],
  ['committed_undrawn', 'Committed undrawn', 'Lines promised to borrowers and not yet drawn.'],
  ['pledged', 'Pledged', 'Pledged as collateral.'],
  ['obligations_due', 'Pool obligations', "The pool's own obligations due in the horizon."],
  ['floor', 'Reserve floor', "The pool's own safety minimum."]
]
const parts = computed(() => PARTS.map(([key, label, about], i) =>
  ({ key, label, about, metric: capacity.value.parts[key], zero: i > 0 && capacity.value.parts[key].minor === 0 })))
/** The bridge: settled known, then every part that takes something away (a $0 part sits in the breakdown). */
const bridge = computed(() => parts.value.filter((p) => !p.zero))
const hiddenZero = computed(() => parts.value.filter((p) => p.zero).map((p) => p.label))
const breakdown = computed(() => parts.value.map((p, i) => ({ ...p, minus: i > 0 && !p.zero && p.metric.minor !== null })))

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

// ------------------------------------------------------------------------ the map

const BANK = 'M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18'
const ICON = {
  pool: BANK,
  treasury: BANK,
  borrower: 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5.5a3 3 0 0 1 0 5.5M18 14.5c1.8.8 3 2.6 3 4.5',
  venue: 'M5 20v-6M10 20V9M15 20v-8M20 20V5'
}

/**
 * The pool on top; along the bottom its borrowers, the treasury and the venue they share. Edges:
 * each facility (pool → borrower), what the pool can lend the treasury, and each venue exposure the
 * overview's relations state, with the amount the API gives. The bottom row is a grid whose
 * columns alternate node, gap; a gap carrying a horizontal edge is wide enough for its label.
 */
const map = computed(() => {
  const b = state.body
  if (!b) return { nodes: [], edges: [], columns: 'minmax(0, 1fr)' }
  const pool = b.pool
  const me = b.company?.entity_id ?? 'treasury'
  const nodes = [{
    id: pool, kind: 'pool', name: plain(pool), sub: 'Available capacity', value: metricText(capacity.value.K_p),
    tip: [`${poolName.value}, the lender pool.`, `What it can still lend: ${metricText(capacity.value.K_p)} (${metricStatus(capacity.value.K_p)}).`]
  }]
  const bottom = []
  const edges = []
  // each party is one node, the treasury included when it is also a borrower
  const treasuryNode = () => {
    if (!bottom.some((n) => n.id === me)) {
      const firm = strip(b.company?.name) || 'The treasury'
      bottom.push({ id: me, kind: 'treasury', name: 'Treasury', sub: 'Settled cash', value: b.treasuryCash ? metricText(b.treasuryCash) : '',
        tip: b.treasuryCash ? [`${firm}: settled cash ${metricText(b.treasuryCash)}.`, metricStatus(b.treasuryCash)] : [`${firm}.`] })
    }
    return bottom.find((n) => n.id === me)
  }
  const node = (id) => (id === me ? treasuryNode()
    : bottom.find((n) => n.id === id) ?? bottom[bottom.push({ id, kind: 'borrower', name: plain(id), sub: 'Borrower', tip: [] }) - 1])
  // one link per pair of parties: a second facility to the same borrower joins the first
  const link = (e) => {
    const same = edges.find((x) => x.from === e.from && x.to === e.to)
    if (!same) return edges.push({ ...e, count: 1 })
    same.count += 1
    same.label = `${same.count} links`
    same.amount = ''
    same.tip.push(...e.tip)
  }
  for (const f of b.facilities) {
    node(f.borrower).tip.push(`${f.facility_id}: ${kindText(f.kind)}, ${f.state}, outstanding ${money(f.outstanding)}.`)
    link({ id: `facility:${f.facility_id}`, from: pool, to: f.borrower, label: capital(kindText(f.kind)), amount: money(f.principal),
      tip: [`${f.facility_id} · ${kindText(f.kind)} · ${f.state}`, `Principal ${money(f.principal)}, outstanding ${money(f.outstanding)}.`, 'Source: facility, GET /api/v1/lending.'] })
  }
  const venues = b.relations.filter((r) => r.kind === 'venue_exposure' && r.target)
  const treasuryRel = venues.find((r) => r.source.entity_id === me)
  if (b.treasuryCash || treasuryRel) {
    treasuryNode()
    if (b.lenderCapacity) {
      link({ id: `capacity:${me}`, from: pool, to: me, label: 'Can lend you', amount: '',
        tip: [`What ${plain(pool)} can still lend the treasury: ${metricText(b.lenderCapacity)}.`, 'A relationship is a dependency, not a payment. Source: GET /api/v1/overview.'] })
    }
  }
  for (const r of venues) {
    const venue = r.target.entity_id
    if (!bottom.some((n) => n.id === venue)) {
      bottom.push({ id: venue, kind: 'venue', name: strip(r.target.name) || plain(venue), sub: 'Exchange venue',
        tip: [`${strip(r.target.name) || venue}: the exchange venue shared by ${listWords(unique(venues.filter((v) => v.target.entity_id === venue).map((v) => plain(v.source.entity_id)))) || 'no party recorded'}.`] })
    }
    const from = r.source.entity_id
    if (from !== pool && from !== me) continue
    const amount = r.amount ? money(r.amount) : 'not observed'
    if (from === me) {
      // the overview's relation names no flow: an expected withdrawal is named only when there is exactly one
      const withdrawals = (b.treasury?.accounts ?? []).flatMap((a) => a.buckets.pending_in).filter((x) => x.kind === 'exchange_withdrawal')
      const flow = withdrawals.length === 1 ? withdrawals[0] : null
      link({ id: `exposure:${r.ref}:${from}`, from, to: venue, label: flow ? 'Expected withdrawal' : 'Venue exposure',
        amount: flow ? money(flow.amount) : amount,
        tip: flow
          ? [`${flow.flow_id}: ${money(flow.amount)} expected ${hoursFrom(b.treasury.as_of, flow.expected_at)}.`, 'An expected venue withdrawal, not settled cash. Source: GET /api/v1/treasury.']
          : [`Exposure ${r.ref}: ${amount}.`, 'Source: GET /api/v1/overview.'] })
    } else {
      const account = venueAccount.value
      const unread = notCurrent.value.find((f) => f.id === account)
      link({ id: `exposure:${r.ref}:${from}`, from, to: venue, label: 'Venue balance',
        amount: unread ? `${unread.icon} ${unread.word}` : amount,
        tip: [`Exposure ${r.ref}${account ? ` on ${account}` : ''}: ${unread ? unread.text : amount}.`,
          unread ? 'An unknown balance is excluded from capacity, never counted as zero.' : 'Counted in available capacity.', 'Source: GET /api/v1/overview.'] })
    }
  }
  // the bottom row: borrowers, the treasury, the venue — each a node column, with gaps between
  const order = { borrower: 0, treasury: 1, venue: 2 }
  bottom.sort((x, y) => order[x.kind] - order[y.kind])
  const col = new Map(bottom.map((n, i) => [n.id, 2 * i + 1]))
  const flat = (e) => col.has(e.from) && col.has(e.to)
  const cols = []
  bottom.forEach((n, i) => {
    if (i > 0) {
      const wide = edges.some((e) => flat(e) && Math.abs(col.get(e.from) - col.get(e.to)) === 2 && Math.min(col.get(e.from), col.get(e.to)) === 2 * i - 1)
      cols.push(wide ? 'minmax(7.5rem, auto)' : 'minmax(1rem, 0.25fr)')
    }
    cols.push('minmax(0, 1fr)')
  })
  nodes[0].place = { '--col': '1 / -1', '--row': '1' }
  for (const n of bottom) n.place = { '--col': String(col.get(n.id)), '--row': '3' }
  const name = (id) => nodes.concat(bottom).find((n) => n.id === id)?.name ?? plain(id)
  for (const e of edges) {
    e.fromName = name(e.from)
    e.toName = name(e.to)
    // the list names the pool and the treasury by role: their names are on the cards above it
    const short = (id) => (id === pool ? 'Pool' : id === me ? 'Treasury' : name(id))
    e.fromShort = short(e.from)
    e.toShort = short(e.to)
    e.place = flat(e)
      ? { '--col': String(Math.min(col.get(e.from), col.get(e.to)) + 1), '--row': '3' }
      : { '--col': String(col.get(e.to) ?? 1), '--row': '2' }
    e.flat = flat(e)
  }
  return { nodes: nodes.concat(bottom), edges, columns: cols.join(' ') || 'minmax(0, 1fr)' }
})

const unique = (items) => [...new Set(items)]

// the arrows, measured from the drawn nodes
const diagram = ref(null)
const lines = reactive({ w: 100, h: 100, list: [] })
function measure () {
  const el = diagram.value
  if (!el) return
  const box = el.getBoundingClientRect()
  lines.w = Math.max(1, box.width)
  lines.h = Math.max(1, box.height)
  const rect = (id) => el.querySelector(`[data-node="${String(id).replace(/["\\]/g, '\\$&')}"] .lw-len__node-body`)?.getBoundingClientRect()
  const list = []
  for (const e of map.value.edges) {
    const a = rect(e.from)
    const z = rect(e.to)
    if (!a || !z) continue
    if (e.flat) {
      const y = (Math.max(a.top, z.top) + Math.min(a.bottom, z.bottom)) / 2 - box.top
      const [l, r] = a.left < z.left ? [a, z] : [z, a]
      const x1 = l.right - box.left + 2
      const x2 = r.left - box.left - 2
      list.push(a === l ? { id: e.id, x1, y1: y, x2, y2: y } : { id: e.id, x1: x2, y1: y, x2: x1, y2: y })
    } else {
      const zx = (z.left + z.right) / 2 - box.left
      const ax = Math.min(Math.max(zx, a.left - box.left + 16), a.right - box.left - 16)
      list.push({ id: e.id, x1: ax, y1: a.bottom - box.top + 2, x2: zx, y2: z.top - box.top - 2 })
    }
  }
  lines.list = list
}
let observer = null
onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') observer = new ResizeObserver(() => measure())
  else window.addEventListener('resize', measure)
})
watch(diagram, (el, old) => {
  if (old) observer?.unobserve(old)
  if (el) {
    observer?.observe(el)
    nextTick(measure)
  }
})
watch(() => map.value, () => nextTick(measure))
onBeforeUnmount(() => {
  observer?.disconnect()
  window.removeEventListener('resize', measure)
})

const repayments = ref(false)

// a prepared venue-freeze scenario, when the world has one
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
.lw-len {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(0, 1fr);
  gap: var(--lw-space-8);
  padding-bottom: var(--lw-space-6);
}

.lw-len__main,
.lw-len__side {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
  gap: var(--lw-space-6);
  min-width: 0;
}

.lw-len__side {
  padding-left: var(--lw-space-8);
  border-left: 1px solid var(--lw-rule);
}

.lw-len__main > section + section,
.lw-len__side > section + section {
  padding-top: var(--lw-space-6);
  border-top: 1px solid var(--lw-rule);
}

.lw-len h2,
.lw-len__terms-section h2 {
  margin: 0 !important;
  font-size: 26px !important;
  line-height: 34px !important;
  font-weight: 500 !important;
}

.lw-len__tipline { display: block; }

.lw-len__sub {
  margin: 0;
  color: var(--lw-ink-muted);
  font-size: 15px;
}

/* the one figure */
.lw-len .lw-len__label {
  font-family: var(--lw-font-text) !important;
  font-size: 17px !important;
  line-height: 24px !important;
  font-weight: 400 !important;
  color: var(--lw-ink-muted);
}

.lw-len__big {
  font-family: var(--lw-font-heading);
  font-size: 84px;
  line-height: 92px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--lw-brand);
}

.lw-len__basis {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--lw-space-1);
  margin: var(--lw-space-1) 0 0;
  font-size: 17px;
  color: var(--lw-ink-muted);
}

.lw-len__unread {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-1) var(--lw-space-3);
  margin: var(--lw-space-2) 0 0;
}

/* the bridge */
.lw-len__terms {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--lw-space-3) var(--lw-space-4);
  margin: var(--lw-space-3) 0 0;
  padding: 0;
  list-style: none;
}

.lw-len__term {
  display: flex;
  align-items: flex-start;
  gap: var(--lw-space-4);
}

.lw-len__term-body {
  display: grid;
  justify-items: center;
  text-align: center;
  max-width: 8.5em;
}

.lw-len__op {
  font-size: 26px;
  line-height: 36px;
  color: var(--lw-ink-muted);
}

.lw-len__amount {
  font-family: var(--lw-font-heading);
  font-size: 28px;
  line-height: 36px;
  font-weight: 600;
  white-space: nowrap;
}

.is-minus { color: var(--lw-bad-text); }
.lw-len__amount.is-total { color: var(--lw-brand); }

.lw-len__term-label {
  color: var(--lw-ink-muted);
  font-size: 15px;
  line-height: 20px;
}

/* the map */
.lw-len__map { display: grid; gap: var(--lw-space-1); }

.lw-len__diagram {
  position: relative;
  display: grid;
  grid-template-columns: var(--cols);
  grid-template-rows: auto 3.5rem auto;
  align-items: center;
  margin-top: var(--lw-space-3);
}

.lw-len__lines {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
}

.lw-len__lines line {
  stroke: var(--lw-ink-muted);
  stroke-width: 1.4;
}

.lw-len__lines marker path { fill: var(--lw-ink-muted); }

.lw-len__node,
.lw-len__edge {
  position: relative;
  grid-column: var(--col);
  grid-row: var(--row);
  min-width: 0;
}

.lw-len__node--pool { justify-self: center; min-width: 14rem; }

.lw-len__node-body {
  display: flex;
  align-items: center;
  gap: var(--lw-space-3);
  padding: var(--lw-space-3);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  font-size: 14px;
  line-height: 18px;
}

.lw-len__node--pool .lw-len__node-body,
.lw-len__node--treasury .lw-len__node-body {
  background: var(--lw-selected);
  border-color: var(--lw-brand);
}

.lw-len__node-body > span:last-child { min-width: 0; }
.lw-len__node-body b { display: block; font-weight: 600; overflow-wrap: break-word; }
.lw-len__node-body small { display: block; color: var(--lw-ink-muted); font-size: 12px; }
.lw-len__node-value { display: block; margin-top: 2px; font-size: 15px; }

.lw-len__node-icon { flex: none; color: var(--lw-brand); }
.lw-len__node-icon svg { display: block; width: 28px; height: 28px; }

.lw-len__edge {
  justify-self: center;
  z-index: 1;
  padding: 0 var(--lw-space-1);
  background: var(--lw-surface);
  color: var(--lw-ink-muted);
  font-size: 12px;
  line-height: 15px;
  text-align: center;
}

.lw-len__edge-text strong { display: block; color: var(--lw-ink); font-weight: 600; }
.lw-len__edge.is-flat { align-self: start; margin-top: var(--lw-space-2); }

.lw-len__relations { display: none; }

/* the right column */
.lw-len__table {
  width: 100%;
  margin-top: var(--lw-space-3);
  border-collapse: collapse;
  font-size: 16px;
}

.lw-len__table th,
.lw-len__table td {
  padding: var(--lw-space-2) var(--lw-space-3);
  border-bottom: 1px solid var(--lw-rule);
  text-align: left;
  font-weight: 400;
}

.lw-len__table thead th {
  background: var(--lw-selected);
  color: var(--lw-ink-muted);
  font-size: 14px;
}

.lw-len__table .lw-num,
.lw-len__terms-section .lw-num { text-align: right; font-variant-numeric: tabular-nums; }

.lw-len__total-row th,
.lw-len__total-row td {
  background: var(--lw-selected);
  font-size: 18px;
  font-weight: 600 !important;
}

.lw-len__freeze {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--lw-space-3);
  margin-top: var(--lw-space-3);
  padding: var(--lw-space-4);
  border-radius: var(--lw-radius);
  background: #FDF1E3;
  color: #3D2A12;
}

.lw-len__freeze p { margin: var(--lw-space-1) 0 0; }
.lw-len__freeze-icon { color: #B86A00; }
.lw-len__freeze-icon svg { display: block; width: 28px; height: 28px; }

.lw-len__tag {
  color: #8A4B00;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.lw-len__wide { display: block; margin-top: var(--lw-space-3); }
.lw-len__outline { width: 100%; justify-content: center; border: 1px solid var(--lw-brand); }

/* the facility terms */
.lw-len__terms-section {
  display: grid;
  gap: var(--lw-space-3);
  padding-top: var(--lw-space-6);
  border-top: 1px solid var(--lw-rule);
}

.lw-len__terms-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--lw-space-2) var(--lw-space-6);
}

.lw-len__go {
  display: inline-flex;
  align-items: center;
  min-height: var(--lw-target);
  padding: 0;
  border: 0;
  background: none;
  color: var(--lw-link);
  font: inherit;
  font-size: 16px;
  cursor: pointer;
}

.lw-len__go:disabled { color: var(--lw-ink-muted); cursor: default; }

.lw-len__table-wrap { border: 0; background: none; }
.lw-len__table-wrap .lw-table { font-size: 15px; }
.lw-len__table-wrap thead th { background: var(--lw-selected); }

.lw-len__repayments {
  display: grid;
  gap: var(--lw-space-2);
  padding: var(--lw-space-4);
  border: 1px dashed var(--lw-rule);
  border-radius: var(--lw-radius);
}

.lw-len__repayments dl {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-1) var(--lw-space-6);
  margin: 0;
}

.lw-len__repayments dt { color: var(--lw-ink-muted); font-size: 13px; }
.lw-len__repayments dd { margin: 0; }

@media (prefers-color-scheme: dark) {
  .lw-len__freeze { background: #3A2A14; color: #F3E3CC; }
  .lw-len__freeze-icon { color: #F0B35C; }
  .lw-len__tag { color: #F0B35C; }
}

@media (max-width: 1199px) {
  .lw-len { grid-template-columns: minmax(0, 1fr); }

  .lw-len__side {
    padding: var(--lw-space-6) 0 0;
    border-left: 0;
    border-top: 1px solid var(--lw-rule);
  }
}

@media (max-width: 767px) {
  .lw-len__big {
    font-size: 56px;
    line-height: 64px;
  }

  .lw-len h2,
  .lw-len__terms-section h2 {
    font-size: 22px !important;
    line-height: 28px !important;
  }

  .lw-len__term { gap: var(--lw-space-2); }
  .lw-len__amount { font-size: 22px; line-height: 30px; }
  .lw-len__op { font-size: 22px; line-height: 30px; }

  /* the map as cards and a list of its relationships */
  .lw-len__diagram {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-rows: none;
    gap: var(--lw-space-2);
  }

  .lw-len__lines,
  .lw-len__edge { display: none; }

  .lw-len__node { grid-column: auto; grid-row: auto; }
  .lw-len__node--pool { grid-column: 1 / -1; justify-self: stretch; min-width: 0; }
  .lw-len__node-body { height: 100%; box-sizing: border-box; }

  .lw-len__relations {
    display: grid;
    gap: var(--lw-space-1);
    margin: var(--lw-space-2) 0 0;
    padding: 0;
    list-style: none;
    font-size: 14px;
  }

  .lw-len__relations li { padding: var(--lw-space-1) 0; border-top: 1px solid var(--lw-rule); }
}
</style>

<template>
  <ScreenShell title="Lending" :headline="headline" :subtitle="subtitle" :lead="lead"
               :reading="state" :refresh="refresh" :stale="stale">
    <template #action>
      <div :class="['lw-len-act', 'lw-len-act--hero', { 'is-whole': whole }]">
        <template v-if="fundingTarget">
          <RouterLink class="lw-button" :to="fundingTarget" data-test="fund">Compare funding plans<Arrow /></RouterLink>
          <small class="lw-len-act__why">Compare ways to cover a cash gap. Nothing is lent from this page.</small>
        </template>
        <template v-else>
          <Tip :text="fundingWhy" test="fund-why">
            <button type="button" class="lw-button" disabled data-test="fund">Compare funding plans</button>
          </Tip>
          <small class="lw-len-act__why">{{ fundingWhy }}</small>
        </template>
      </div>
    </template>

    <template #default="{ body }">
      <!-- the main object: what the capacity rests on -->
      <section class="lw-len__object" aria-labelledby="capacity-heading" data-test="capacity">
        <h2 v-if="whole" id="capacity-heading" class="lw-len__h">What the {{ capacityText }} rests on<span
          class="lw-len__wide-only"> · {{ parties }}</span></h2>
        <h2 v-else id="capacity-heading" class="lw-len__h">Available pool capacity</h2>
        <p class="lw-len__prov" data-test="capacity-basis">
          {{ plain(body.pool) }} / Observed snapshot ·
          <span :class="reduced ? 'lw-status lw-status--warn' : ''"><span v-if="reduced" aria-hidden="true">! </span>Balance
            authority {{ capacity.authority }}</span>
          · {{ fundsWord }}<span class="lw-len__wide-only"> · as of {{ formatTime(capacity.K_p.as_of || body.as_of).utc }}</span>
        </p>

        <CapacityLoop v-if="whole" :model="loop" />
        <template v-else>
          <div class="lw-len__big" data-test="capacity-value">
            <Tip test="tip-capacity">{{ capacityText }}<template #tip>
              <span class="lw-len__tipline">{{ poolName }}: settled known − committed undrawn − pledged − pool obligations due − pool floor.</span>
              <span class="lw-len__tipline" data-test="capacity-status">{{ metricStatus(capacity.K_p) }}</span>
              <span class="lw-len__tipline">Source time {{ formatTime(capacity.K_p.as_of || body.as_of).utc }}, GET /api/v1/lending.</span>
              <span v-if="leadSeen" class="lw-len__tipline" data-test="lead-stale">{{ leadSeen }}</span>
            </template></Tip>
          </div>
          <p v-if="notCurrent.length" class="lw-len__unread" data-test="not-current">
            <span>Not counted:</span>
            <span v-for="f in notCurrent" :key="f.id" class="lw-len__unread-item">{{ f.name }} ·
              <Tip :text="`${f.text} (${f.id})`"><span :class="['lw-status', `lw-status--${f.tone}`]"><span
                aria-hidden="true">{{ f.icon }}</span> {{ f.word }}</span></Tip>
            </span>
          </p>
        </template>

        <!-- on a phone, the one action sits under the object it acts on -->
        <div v-if="whole" class="lw-len-act lw-len-act--phone">
          <RouterLink v-if="fundingTarget" class="lw-button" :to="fundingTarget" data-test="fund-phone">Compare funding plans<Arrow /></RouterLink>
          <button v-else type="button" class="lw-button" disabled data-test="fund-phone">Compare funding plans</button>
          <small class="lw-len-act__why">{{ fundingTarget ? 'Compare ways to cover a cash gap. Nothing is lent from this page.' : fundingWhy }}</small>
        </div>

        <!-- the drawing's text alternative; without a drawing, the relationships in words -->
        <ul :class="whole ? 'lw-visually-hidden' : 'lw-len__relations'" aria-label="Relationships" data-test="relations">
          <li v-for="e in edges" :key="e.id" :data-edge="e.id">{{ e.fromShort }} → {{ e.toShort }} · {{ e.label }}{{ e.amount ? ` ${e.amount}` : '' }}. {{ e.tip.join(' ') }}</li>
        </ul>
      </section>

      <div class="lw-len__readings">
        <!-- the facility terms, at the committed line's cut -->
        <section class="lw-len__reading" aria-labelledby="facilities-heading" data-test="facility-terms">
          <p v-if="committedTo" class="lw-len__kick">At the {{ committedTo }} cut</p>
          <h2 id="facilities-heading" class="lw-len__h">Facility terms</h2>
          <p class="lw-len__text">Terms, not proof of disbursement. Repayment uses observed revenue only.</p>
          <div data-test="facilities">
            <dl v-for="f in body.facilities" :key="f.facility_id" class="lw-len__facility" :data-facility="f.facility_id">
              <div><dt class="is-head">{{ f.facility_id }} · {{ kindText(f.kind) }}</dt><dd>{{ f.state }}</dd></div>
              <div><dt>From → To</dt><dd>{{ plain(body.pool) }} → {{ plain(f.borrower) }}</dd></div>
              <div><dt>Principal</dt><dd>{{ money(f.principal) }}</dd></div>
              <div><dt>Fee · Total owed · Outstanding</dt><dd>{{ money(f.fee) }} · {{ money(f.owed) }} · {{ money(f.outstanding) }}</dd></div>
              <div><dt>Observed revenue</dt><dd>{{ metricText(f.observed_revenue) }}<template
                v-if="f.observed_revenue.status !== 'known'"> · expected revenue is not a receipt</template></dd></div>
            </dl>
            <p v-if="!body.facilities.length" class="lw-len__text">No facilities</p>
          </div>
          <button type="button" class="lw-len__go" data-test="view-repayments" :disabled="!body.facilities.length"
                  :aria-expanded="repayments ? 'true' : 'false'" aria-controls="lw-len-repayments"
                  @click="repayments = !repayments">{{ repayments ? 'Hide repayment schedule' : 'View repayment schedule' }}<Arrow v-if="!repayments" /></button>
          <div v-if="repayments" id="lw-len-repayments" class="lw-len__repayments" role="region"
               aria-label="Repayment schedule" data-test="repayments">
            <dl v-for="f in body.facilities" :key="f.facility_id">
              <div><dt>Facility</dt><dd>{{ f.facility_id }} · {{ f.state }}</dd></div>
              <div><dt>Outstanding</dt><dd>{{ money(f.outstanding) }}</dd></div>
              <div><dt>Observed revenue</dt><dd>{{ metricText(f.observed_revenue) }}<template
                v-if="f.observed_revenue.as_of">, as of {{ formatTime(f.observed_revenue.as_of).utc }}</template></dd></div>
            </dl>
            <p class="lw-len__text">Receipts are not itemised by GET /api/v1/lending. Repayment is computed from observed
              revenue only, never from a forecast.</p>
          </div>
        </section>

        <!-- the venue freeze, at the venue's corner: a hypothetical, its reason in words -->
        <section class="lw-len__reading" aria-labelledby="freeze-heading" data-test="freeze">
          <p v-if="loop?.venue" class="lw-len__kick">At the {{ loop.venue.name }} corner</p>
          <h2 id="freeze-heading" class="lw-len__h">If the venue froze <span :class="['lw-len__tag', { 'is-now': reduced }]"
            data-test="hypothetical">{{ reduced ? 'Happening now' : 'Hypothetical' }}</span></h2>
          <p v-if="reduced" class="lw-len__text">{{ notCurrent.map((f) => f.name).join('; ') }}: Unknown, not zero. Only known
            funds count, and new lending pauses.</p>
          <template v-else>
            <p class="lw-len__text">If the venue balance becomes Unknown, only known funds count and new lending pauses.</p>
            <p class="lw-len__note">What-if: nothing here has happened. A rehearsal changes no figure on this page. An unknown
              balance is excluded from capacity, never counted as zero, and no capacity-under-freeze figure is served.</p>
          </template>
          <RouterLink v-if="freezeTarget" class="lw-button lw-button--quiet lw-len__outline" :to="freezeTarget"
                      data-test="rehearse-freeze">Rehearse venue freeze<Arrow /></RouterLink>
          <template v-else>
            <button type="button" class="lw-button lw-button--quiet lw-len__outline" disabled aria-describedby="lw-len-freeze-why"
                    data-test="rehearse-freeze">Rehearse venue freeze</button>
            <p id="lw-len-freeze-why" class="lw-len__reason" data-test="freeze-why"><span class="lw-len__mark"
              aria-hidden="true">i</span>{{ freezeWhy }}</p>
          </template>
        </section>
      </div>

      <!-- the depth, folded -->
      <div class="lw-len__depth">
        <details class="lw-len__fold" data-test="breakdown">
          <summary>Capacity breakdown</summary>
          <table class="lw-len__table">
            <caption>{{ plain(body.pool) }} · {{ capacity.K_p.currency }} · in the API’s order</caption>
            <thead><tr><th scope="col">Item</th><th scope="col" class="lw-num">Amount</th><th scope="col">Status</th></tr></thead>
            <tbody>
              <tr v-for="r in breakdown" :key="r.key" :data-row="r.key">
                <th scope="row">{{ r.label }}</th>
                <td class="lw-num"><span :class="{ 'is-minus': r.minus }">{{ r.minus ? '−' : '' }}{{ metricText(r.metric) }}</span></td>
                <td>{{ stateWord(r.metric) }}</td>
              </tr>
              <tr class="lw-len__total-row" data-row="K_p">
                <th scope="row">Available capacity (the API’s figure)</th>
                <td class="lw-num">{{ metricText(capacity.K_p) }}</td>
                <td>{{ stateWord(capacity.K_p) }}</td>
              </tr>
            </tbody>
          </table>
          <p data-test="calculation">In {{ capacity.K_p.currency }}, from the API: {{ calculation }}. The equation explains
            the available capacity; it is the API’s figure, not recomputed here.</p>
          <p data-test="evidence">
            Counted: settled known {{ metricText(capacity.parts.settled_known) }}<template
              v-if="poolAccounts.length"> on {{ poolAccounts.join(', ') }}</template>.
            Not counted: {{ notCurrent.length ? notCurrent.map((f) => `${f.text} (${f.id})`).join('; ') : 'none; every pool cash account was observed' }}.
            Balances per account are not itemised by GET /api/v1/lending<template v-if="loop?.venue">; the venue balance is
              counted, and which claim it backs is not itemised</template>.
          </p>
        </details>
        <details class="lw-len__fold" data-test="how-lending">
          <summary>Source and authority</summary>
          <p>Snapshot {{ body.snapshot_id }} · {{ capacity.K_p.currency }} ·
            <span :class="['lw-status', `lw-status--${reduced ? 'warn' : 'muted'}`]" data-test="authority"><span
              aria-hidden="true">{{ reduced ? '!' : '●' }}</span> Balance authority {{ capacity.authority }}</span>:
            {{ reduced ? 'some of the pool’s balances could not be read, so only the money we can see counts' : 'every pool cash account was read' }}.
            <template v-if="whole">Available capacity <span data-test="capacity-status">{{ metricStatus(capacity.K_p) }}</span>.</template>
            Source time {{ formatTime(capacity.K_p.as_of || body.as_of).utc }}.</p>
          <p>The pool's lender capacity K_p, GET /api/v1/lending: settled known − committed undrawn − pledged − pool
            obligations due in the horizon − pool reserve floor.</p>
          <p>“Can lend you” is a dependency, not a payment.<template v-if="loop?.venue?.flow"> The treasury’s
            {{ loop.venue.flow }} is an expected venue withdrawal, not settled cash.</template></p>
        </details>
        <details class="lw-len__fold">
          <summary>When the reading changes</summary>
          <p>With reduced balance authority, capacity reads “(known funds only)”, unread accounts are listed as “Not counted:
            &lt;name&gt; · Unknown”, never zero, and Compare funding plans is disabled: “Balance authority reduced; refresh
            observed evidence before funding”.</p>
          <p>Not loaded: “Loading”. On error: “Last loaded, not current; reload before funding”.</p>
        </details>
      </div>
    </template>
  </ScreenShell>
</template>

<script setup>
/**
 * Lending as one answer (board item 177): the headline is what the lender can still lend you (the
 * API's K_p), the subtitle what it is not and why; the main object (`CapacityLoop`) draws what
 * that figure rests on — the pool's settled known cash cut into the parts the API takes away, the
 * dependency to you, and the venue under both the pool's counted cash and your expected
 * withdrawal. Compare funding plans is the one action. The facility terms and the venue freeze (a
 * labelled hypothetical, its disabled reason in words) read the object; the breakdown, the source
 * and authority, and what changes the reading fold below.
 *
 * Capacity and its parts come from one Lending read; the pool accounts K_p could not count come
 * from Lending itself (`capacity.unobserved`), never from the overview. The overview of the same
 * context gives the demonstration run, the company, its cash and the relations (with their
 * amounts); the treasury read, when it answers in the same context, names the treasury's expected
 * venue withdrawal. No amount is computed here. The drawing needs a whole reading: full
 * authority, nothing unobserved, every part Known and the API's parts adding up to settled known;
 * any other reading shows the figure with its status, the basis and the accounts not counted.
 *
 * Left out for want of an API field: the venue-freeze capacity figure (no read serves capacity
 * under a frozen venue) and the facilities' revenue share.
 */
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Arrow from '../components/Arrow.vue'
import CapacityLoop from '../components/CapacityLoop.vue'
import Tip from '../components/Tip.vue'
import { FAMILIES, worldFor } from '../api/world.js'
import {
  ApiError, ScreenShell, amountText, amountWords, contextKey, formatTime, freshness, getLending, getOverview,
  getTreasury, hoursFrom, kindText, lastSeen, listWords, longDate, metricStatus, metricText, money, routeExists, staleOf, stateOf,
  useReading
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
const stateWord = (m) => (m ? stateOf(m.status).word : 'Unavailable')

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

/** The answer as the headline: the lead's first clause, by the same branches. */
const headline = computed(() => (state.body ? `${lead.value.split(';')[0]}.` : ''))

const PARTS = [
  ['settled_known', 'Settled known', 'Settled cash the pool holds on accounts it could read.'],
  ['committed_undrawn', 'Committed undrawn', 'Lines promised to borrowers and not yet drawn.'],
  ['pledged', 'Pledged', 'Pledged as collateral.'],
  ['obligations_due', 'Pool obligations', "The pool's own obligations due in the horizon."],
  ['floor', 'Reserve floor', "The pool's own safety minimum."]
]
const parts = computed(() => PARTS.map(([key, label, about], i) =>
  ({ key, label, about, metric: capacity.value.parts[key], zero: i > 0 && capacity.value.parts[key].minor === 0 })))
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

// ------------------------------------------------------------------ the main object

/**
 * Whether the reading can be drawn to scale: full authority, nothing unobserved, K_p and every
 * part Known in one currency, K_p above zero, and the API's parts adding up to settled known.
 * The sum checks the API's own figures against each other; no figure shown comes from it.
 */
const whole = computed(() => {
  if (!state.body || reduced.value || capacity.value.unobserved.length) return false
  const { K_p: kp, parts: p } = capacity.value
  const all = [kp, ...PARTS.map(([key]) => p[key])]
  if (all.some((m) => m?.status !== 'known' || !Number.isSafeInteger(m.minor) || m.currency !== kp.currency)) return false
  const taken = PARTS.slice(1).map(([key]) => p[key].minor)
  if (kp.minor <= 0 || taken.some((x) => x < 0)) return false
  return kp.minor + taken.reduce((a, b) => a + b, 0) === p.settled_known.minor
})

const me = computed(() => state.body?.company?.entity_id ?? 'treasury')
/** The overview's venue exposures, each a party → venue relation. */
const venueRelations = computed(() => (state.body?.relations ?? []).filter((r) => r.kind === 'venue_exposure' && r.target))
/** The active committed lines: the API's committed undrawn part is the sum of what they leave undrawn. */
const committedLines = computed(() => (state.body?.facilities ?? []).filter((f) => f.kind === 'committed_line' && f.state === 'active'))
/** The committed part names its borrower when exactly one line makes it up. */
const committedTo = computed(() => (whole.value && committedLines.value.length === 1 &&
  capacity.value.parts.committed_undrawn.minor > 0 ? plain(committedLines.value[0].borrower) : ''))

/** The one expected exchange withdrawal the treasury read names, when there is exactly one. */
const withdrawal = computed(() => {
  const flows = (state.body?.treasury?.accounts ?? []).flatMap((a) => a.buckets.pending_in).filter((x) => x.kind === 'exchange_withdrawal')
  return flows.length === 1 ? flows[0] : null
})

const loop = computed(() => {
  if (!whole.value) return null
  const b = state.body
  const p = capacity.value.parts
  const lines = committedLines.value
  const borrower = lines.length === 1 && lines[0].borrower !== me.value ? lines[0].borrower : undefined
  const who = committedTo.value || 'borrowers'
  const zeros = PARTS.slice(1).filter(([key]) => p[key].minor === 0).map(([key, label]) => `${label} ${money(p[key])}`)
  const segments = []
  if (p.committed_undrawn.minor > 0) {
    segments.push({ key: 'committed_undrawn', minor: p.committed_undrawn.minor, borrower,
      label: `−${money(p.committed_undrawn)} promised to ${who}`, short: `−${money(p.committed_undrawn)} ${who}`,
      sub: 'committed line, undrawn · Known' })
  }
  if (p.pledged.minor > 0) {
    segments.push({ key: 'pledged', minor: p.pledged.minor, label: `−${money(p.pledged)} pledged as collateral`,
      short: `−${money(p.pledged)} pledged`, sub: 'Known' })
  }
  if (p.obligations_due.minor > 0) {
    segments.push({ key: 'obligations_due', minor: p.obligations_due.minor, label: `−${money(p.obligations_due)} the pool’s obligations due`,
      short: `−${money(p.obligations_due)} pool obligations`, sub: 'Known' })
  }
  if (p.floor.minor > 0) {
    segments.push({ key: 'floor', minor: p.floor.minor, label: `−${money(p.floor)} the pool’s own reserve floor · Known`,
      short: `−${money(p.floor)} the pool’s own floor`, sub: '' })
  }
  // the parts at $0, said once in words under the last part drawn
  if (zeros.length && segments.length) {
    const last = segments[segments.length - 1]
    last.sub = [last.sub, zeros.join(' · ')].filter(Boolean).join(' · ')
  }

  const cash = b.treasuryCash
  const you = {
    id: me.value,
    name: strip(b.company?.name) || 'the treasury',
    cash: cash ? (cash.status === 'known' ? `${money(cash)} · Known` : metricText(cash)) : ''
  }

  let venue = null
  const pooled = venueRelations.value.find((r) => r.source?.entity_id === b.pool)
  if (pooled) {
    const id = pooled.target.entity_id
    const yourRel = venueRelations.value.find((r) => r.source?.entity_id === me.value && r.target.entity_id === id)
    // the treasury's withdrawal is named under this venue only when the treasury is exposed to it
    const flow = yourRel ? withdrawal.value : null
    const at = flow ? longDate(flow.expected_at).replace(/, \d{4}$/, '') : ''
    // drawn at the column's scale only in its currency and inside the settled known it is counted in
    const a = pooled.amount
    const scaled = a && a.currency === p.settled_known.currency && a.minor >= 0 && a.minor <= p.settled_known.minor
    venue = {
      id,
      name: strip(pooled.target.name) || plain(id),
      minor: scaled ? a.minor : null,
      pool: pooled.amount ? `${money(pooled.amount)} balance, counted` : 'balance counted, not itemised',
      yours: flow ? `${money(flow.amount)} withdrawal expected` : yourRel ? `${yourRel.amount ? money(yourRel.amount) : 'an amount not served'} venue exposure` : '',
      when: flow ? `${at} (${formatTime(flow.expected_at).utc}), not settled` : '',
      whenShort: flow ? `${at}, not settled` : '',
      flow: flow ? `${money(flow.amount)} from ${strip(pooled.target.name) || plain(id)} (${flow.flow_id}, expected ${formatTime(flow.expected_at).utc})` : ''
    }
  }
  return {
    pool: { id: b.pool, name: plain(b.pool) },
    settled: money(p.settled_known),
    settledMinor: p.settled_known.minor,
    capacity: money(capacity.value.K_p),
    kpMinor: capacity.value.K_p.minor,
    segments,
    you,
    venue
  }
})

const parties = computed(() => (loop.value?.venue ? 'three parties, one loop' : 'the pool and you'))

/** Not the settled figure, and why: each part the API takes away, in words. */
const subtitle = computed(() => {
  if (!state.body) return ''
  if (!whole.value) return `${plain(state.body.pool)} / Observed snapshot`
  const p = capacity.value.parts
  const said = []
  if (p.committed_undrawn.minor > 0) said.push(`${money(p.committed_undrawn)} is promised to ${committedTo.value || 'borrowers'}`)
  if (p.pledged.minor > 0) said.push(`${money(p.pledged)} is pledged`)
  if (p.obligations_due.minor > 0) said.push(`${money(p.obligations_due)} is the pool’s own obligations due`)
  if (p.floor.minor > 0) said.push(`${money(p.floor)} is the pool’s own floor`)
  return said.length ? `Not ${money(p.settled_known)}: ${listWords(said)}.` : `All of the pool’s settled ${money(p.settled_known)}.`
})

// ------------------------------------------------------------------ the relations, in words

/**
 * Every link the drawing stands for, as a list a screen reader reads: each facility (pool →
 * borrower, a second facility to the same borrower joining the first), what the pool can lend the
 * treasury, and each venue exposure the overview's relations state, with the amount the API gives.
 */
const edges = computed(() => {
  const b = state.body
  if (!b) return []
  const pool = b.pool
  const list = []
  const link = (e) => {
    const same = list.find((x) => x.from === e.from && x.to === e.to)
    if (!same) return list.push({ ...e, count: 1 })
    same.count += 1
    same.label = `${same.count} links`
    same.amount = ''
    same.tip.push(...e.tip)
  }
  for (const f of b.facilities) {
    link({ id: `facility:${f.facility_id}`, from: pool, to: f.borrower, label: capital(kindText(f.kind)), amount: money(f.principal),
      tip: [`${f.facility_id} · ${kindText(f.kind)} · ${f.state}`, `Principal ${money(f.principal)}, outstanding ${money(f.outstanding)}.`] })
  }
  const venues = venueRelations.value
  if (b.lenderCapacity && (b.treasuryCash || venues.some((r) => r.source.entity_id === me.value))) {
    link({ id: `capacity:${me.value}`, from: pool, to: me.value, label: 'Can lend you', amount: '',
      tip: ['A relationship is a dependency, not a payment.'] })
  }
  for (const r of venues) {
    const from = r.source.entity_id
    if (from !== pool && from !== me.value) continue
    const venue = r.target.entity_id
    const amount = r.amount ? money(r.amount) : 'not observed'
    if (from === me.value) {
      const flow = withdrawal.value
      link({ id: `exposure:${r.ref}:${from}`, from, to: venue, label: flow ? 'Expected withdrawal' : 'Venue exposure',
        amount: flow ? money(flow.amount) : amount,
        tip: flow ? [`${flow.flow_id} expected ${hoursFrom(b.treasury.as_of, flow.expected_at)}; not settled cash.`] : [`Exposure ${r.ref}.`] })
    } else {
      const unread = notCurrent.value.find((f) => f.id === venueAccount.value)
      link({ id: `exposure:${r.ref}:${from}`, from, to: venue, label: 'Venue balance',
        amount: unread ? `${unread.icon} ${unread.word}` : amount,
        tip: [unread ? 'An unknown balance is excluded from capacity, never counted as zero.' : 'Counted in available capacity; which claim it backs is not itemised.'] })
    }
  }
  const short = (id) => (id === pool ? 'Pool' : id === me.value ? 'Treasury' : plain(id))
  return list.map((e) => ({ ...e, fromShort: short(e.from), toShort: short(e.to) }))
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
.lw-len__object {
  display: grid;
  gap: var(--lw-space-2);
  padding-top: var(--lw-space-2);
  border-top: 1px solid var(--lw-rule);
}

.lw-len__h {
  margin: 0 !important;
  font-family: var(--lw-font-text) !important;
  font-size: 15px !important;
  line-height: 20px !important;
  font-weight: 600 !important;
}

.lw-len__h .lw-len__wide-only { font-weight: 400; color: var(--lw-ink-muted); }

.lw-len__prov {
  margin: 0;
  color: var(--lw-ink-muted);
  font-size: 13px;
  line-height: 18px;
}

.lw-len__tipline { display: block; }

.lw-len__big {
  font-family: var(--lw-font-heading);
  font-size: 56px;
  line-height: 64px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--lw-brand);
}

.lw-len__unread {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-1) var(--lw-space-3);
  margin: 0;
}

/* the one action: in the hero on a wide screen, under the object on a phone */
.lw-len-act { display: grid; gap: var(--lw-space-1); justify-items: end; max-width: 20rem; }
.lw-len-act__why { color: var(--lw-ink-muted); font-size: 13px; line-height: 18px; text-align: right; }
.lw-len-act--phone { display: none; }

/* the readings of the object: the facility terms and the venue freeze, side by side */
.lw-len__readings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--lw-space-6) var(--lw-space-8);
  margin-top: var(--lw-space-6);
}

.lw-len__reading {
  display: grid;
  align-content: start;
  gap: var(--lw-space-2);
  padding-top: var(--lw-space-3);
  border-top: 1px solid var(--lw-rule);
}

.lw-len__kick { margin: 0; color: var(--lw-ink-muted); font-size: 13px; line-height: 18px; }
.lw-len__text { margin: 0; font-size: 15px; max-width: 60ch; }
.lw-len__note { margin: 0; color: var(--lw-ink-muted); font-size: 13.5px; max-width: 60ch; }

.lw-len__tag {
  display: inline-flex;
  align-items: center;
  margin-left: var(--lw-space-2);
  padding: 3px 7px;
  border: 1.5px dashed var(--lw-ink);
  border-radius: 4px;
  font-size: 12px;
  line-height: 14px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  vertical-align: 2px;
}

.lw-len__tag.is-now { border-style: solid; border-color: var(--lw-warn); color: var(--lw-warn-text); }

.lw-len__outline { width: 100%; justify-content: center; border: 1px solid var(--lw-brand); }
.lw-len__outline:disabled { border: 1.5px dashed var(--lw-rule); }

.lw-len__reason {
  display: flex;
  gap: var(--lw-space-2);
  align-items: flex-start;
  margin: 0;
  font-size: 14px;
  line-height: 20px;
}

.lw-len__mark {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  border: 1.5px solid var(--lw-ink-muted);
  border-radius: 50%;
  color: var(--lw-ink-muted);
  font-size: 11px;
  font-weight: 700;
}

.lw-len__facility { margin: var(--lw-space-1) 0 0; border-top: 1px solid var(--lw-rule); }

.lw-len__facility > div {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--lw-space-3);
  min-height: 38px;
  border-bottom: 1px solid var(--lw-rule);
  font-size: 15px;
}

.lw-len__facility dt { color: var(--lw-ink-muted); }
.lw-len__facility dt.is-head { color: var(--lw-ink); font-weight: 600; }
.lw-len__facility dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }

.lw-len__go {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  min-height: var(--lw-target);
  padding: 0;
  border: 0;
  background: none;
  color: var(--lw-link);
  font: inherit;
  font-size: 15px;
  cursor: pointer;
}

.lw-len__go:disabled { color: var(--lw-ink-muted); cursor: default; }

.lw-len__repayments {
  display: grid;
  gap: var(--lw-space-2);
  padding: var(--lw-space-4);
  border: 1px dashed var(--lw-rule);
  border-radius: var(--lw-radius);
}

.lw-len__repayments dl { display: flex; flex-wrap: wrap; gap: var(--lw-space-1) var(--lw-space-6); margin: 0; }
.lw-len__repayments dt { color: var(--lw-ink-muted); font-size: 13px; }
.lw-len__repayments dd { margin: 0; }

/* the depth, folded */
.lw-len__depth { margin-top: var(--lw-space-6); border-top: 1px solid var(--lw-rule); }
.lw-len__fold { border-bottom: 1px solid var(--lw-rule); }

.lw-len__fold summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 48px;
  cursor: pointer;
  list-style: none;
  font-size: 15.5px;
}

.lw-len__fold summary::-webkit-details-marker { display: none; }
.lw-len__fold summary::after { content: "+"; color: var(--lw-ink-muted); font-size: 22px; }
.lw-len__fold[open] summary::after { content: "−"; }
.lw-len__fold p { margin: 0 0 var(--lw-space-3); max-width: 64ch; font-size: 15px; }

.lw-len__table { width: 100%; margin-bottom: var(--lw-space-3); border-collapse: collapse; font-size: 14px; }
.lw-len__table caption { padding-bottom: var(--lw-space-2); color: var(--lw-ink-muted); font-size: 13px; text-align: left; }

.lw-len__table th,
.lw-len__table td {
  padding: var(--lw-space-2) var(--lw-space-2) var(--lw-space-2) 0;
  border-bottom: 1px solid var(--lw-rule);
  text-align: left;
  font-weight: 400;
}

.lw-len__table thead th { color: var(--lw-ink-muted); font-size: 13px; font-weight: 600; }
.lw-len__table .lw-num { text-align: right; font-variant-numeric: tabular-nums; }
.lw-len__total-row th,
.lw-len__total-row td { border-top: 1.5px solid var(--lw-ink); font-weight: 600 !important; }

.is-minus { color: var(--lw-bad-text); }

.lw-len__relations { display: grid; gap: var(--lw-space-1); margin: var(--lw-space-2) 0 0; padding: 0; list-style: none; font-size: 14px; }
.lw-len__relations li { padding: var(--lw-space-1) 0; border-top: 1px solid var(--lw-rule); }

@media (max-width: 1199px) {
  .lw-len-act { justify-items: start; }
  .lw-len-act__why { text-align: left; }
}

@media (max-width: 767px) {
  .lw-len-act { max-width: none; justify-items: stretch; }
  .lw-len-act__why { text-align: left; }
  .lw-len-act--hero.is-whole { display: none; }
  .lw-len-act--phone { display: grid; }
  .lw-len__object { gap: 6px; }
  .lw-len__wide-only { display: none; }
  .lw-len__readings { grid-template-columns: minmax(0, 1fr); }
  .lw-len__facility > div { align-items: flex-start; padding: var(--lw-space-2) 0; }
}
</style>

<template>
  <ScreenShell title="Overview" :headline="answer" :subtitle="condition" :lead="lead" :reading="state" :refresh="refresh"
               :stale="stale">
    <!-- settled − reserved = spendable: an equation, beside the answer -->
    <template #action>
      <dl class="lw-ov-sum" aria-label="Why only part of settled cash is spendable" data-test="equation">
        <div v-for="(term, n) in terms" :key="term.key" :class="['lw-ov-sum__term', { 'is-total': term.key === 'spendable' }]"
             :data-test="term.key">
          <dt><span class="lw-ov-sum__op" aria-hidden="true">{{ n === 0 ? '' : term.key === 'spendable' ? '=' : term.sign }}</span><i
            v-if="term.swatch" :class="['lw-ov-sum__sw', `is-${term.swatch}`]" aria-hidden="true" />{{ term.label }}</dt>
          <dd>
            <Tip v-if="term.tip" :test="`tip-${term.key}`">
              <span class="lw-figure">{{ term.figure }}</span>
              <template #tip><span v-for="line in term.tip" :key="line" class="lw-ov-tipline">{{ line }}</span></template>
            </Tip>
            <span v-else class="lw-figure">{{ term.figure }}</span>
          </dd>
        </div>
      </dl>
    </template>

    <template #default="{ body }">
      <p v-if="body.completeness.status === 'partial'" class="lw-note" data-test="partial">
        Partial: not current — {{ notCurrent }}.
      </p>
      <!-- the 72-hour cash path against the reserve floor, and the what-if under it -->
      <section class="lw-ov-stage" aria-label="72-hour cash path against the reserve floor" data-test="outlook">
        <CashPath :points="body.outlook || []" :late="latePoints" :show-late="showLate" :floor="body.coverage.floor"
                  :low-at="body.coverage.at" :as-of="body.as_of" :currency="body.cash.currency" :cash="body.cash"
                  :spendable="body.spendable" :link-of="linkOf" />

        <div class="lw-ov-iflate" data-test="scenario">
          <div class="lw-ov-iflate__tag">
            <span class="lw-ov-tag" data-test="hypothetical">
              <svg viewBox="0 0 22 6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="currentColor" stroke-width="2"
                stroke-dasharray="5 3" /></svg>Hypothetical{{ latePoints.length ? ' · dashed path' : '' }}
            </span>
            <button v-if="latePoints.length" type="button" class="lw-ov-ghost" data-test="toggle-late"
                    @click="showLate = !showLate">{{ showLate ? 'Hide path' : 'Show path' }}</button>
          </div>
          <h2 class="lw-ov-iflate__h">{{ teaser }}</h2>
          <p class="lw-ov-iflate__why" data-test="what-if-why">{{ why }}</p>
          <table class="lw-ov-cmp" data-test="what-if">
            <caption class="lw-visually-hidden">Lowest projected cash as planned and in the what-if</caption>
            <thead><tr><th scope="col">Low point</th><th scope="col">Cash</th><th scope="col">vs floor</th></tr></thead>
            <tbody>
              <tr data-test="coverage">
                <td>As planned<span v-if="lowHour !== null" class="lw-ov-cmp__h">, h{{ lowHour }}</span></td>
                <td>{{ metricText(body.coverage.min_projected) }}</td>
                <td :class="{ 'is-bad': floor === 'breached' }">
                  <Tip test="tip-coverage">
                    <span class="lw-figure">{{ headroomText }}</span>
                    <template #tip>
                      <span class="lw-ov-tipline">Lowest projected cash over the horizon less the reserve floor{{ body.coverage.at ? `, at ${formatTime(body.coverage.at).utc}` : '' }}.</span>
                      <span class="lw-ov-tipline">lowest point ahead {{ metricText(body.coverage.min_projected) }} ·
                        safety minimum {{ metricText(body.coverage.floor) }}</span>
                      <span :class="['lw-status', `lw-status--${STATES[floor].tone}`]" data-test="floor-status">
                        <span aria-hidden="true">{{ STATES[floor].icon }}</span> {{ FLOOR_WORDS[floor] }}
                      </span>
                    </template>
                  </Tip>
                  <span v-if="floor !== 'kept'" :class="['lw-status', `lw-status--${STATES[floor].tone}`]" data-test="floor-alert">
                    <span aria-hidden="true">{{ STATES[floor].icon }}</span> {{ FLOOR_WORDS[floor] }}</span>
                </td>
              </tr>
              <tr v-if="lateLow" data-test="late-row">
                <td>If late<span class="lw-visually-hidden"> (hypothetical)</span><span class="lw-ov-cmp__h">, h{{ lateLow.hours }}</span></td>
                <td :class="{ 'is-bad': lateLow.state === 'breached' }">{{ lateLow.money }}</td>
                <td :class="{ 'is-bad': lateLow.state === 'breached' }">{{ lateLow.against }}</td>
              </tr>
            </tbody>
          </table>
          <div class="lw-ov-iflate__act">
            <Tip v-if="simulationTarget" text="Plays the prepared what-if round by round. Opening it moves no money.">
              <RouterLink class="lw-button" :to="simulationTarget" data-test="open-simulation">Open simulation<Arrow /></RouterLink>
            </Tip>
            <Tip v-else :text="simulationWhy" test="open-simulation-why">
              <button type="button" class="lw-button" disabled data-test="open-simulation">Open simulation</button>
            </Tip>
            <small>{{ latePoints.length ? 'Rehearse the late receipt. Nothing is executed.' : 'Nothing is executed.' }}</small>
          </div>
        </div>
      </section>

      <!-- depth, one tap away -->
      <div class="lw-ov-depth">
        <details class="lw-ov-fold" data-test="cash-data">
          <summary>View cash data</summary>
          <div class="lw-ov-fold__body lw-ov-tablewrap">
            <table class="lw-ov-data">
              <caption class="lw-visually-hidden">Projected cash by hour, as planned and in the what-if</caption>
              <thead><tr><th scope="col">Hour</th><th scope="col">Event</th><th scope="col">As planned</th>
                <th v-if="latePoints.length" scope="col">If late (hypothetical)</th></tr></thead>
              <tbody>
                <tr v-for="r in rows" :key="r.t">
                  <td>{{ r.hours }}</td><td>{{ r.event }}</td><td>{{ r.planned }}</td>
                  <td v-if="latePoints.length" :class="{ 'is-bad': r.lateBad }">{{ r.late }}</td>
                </tr>
              </tbody>
            </table>
            <p v-if="body.coverage.floor.minor !== null">Reserve floor {{ metricText(body.coverage.floor) }} throughout. Cash holds its level between events.</p>
          </div>
        </details>

        <!-- the next obligation -->
        <details class="lw-ov-fold" data-test="next-obligation">
          <summary>Next obligation<span v-if="next" class="lw-ov-fold__hint">{{ capital(kindText(next.kind)) }} {{ money(next.amount) }}</span></summary>
          <div class="lw-ov-fold__body">
            <div v-if="next" class="lw-ov-next__card">
              <div class="lw-ov-next__kind">{{ capital(kindText(next.kind)) }}</div>
              <Tip :text="`Paid from ${next.account ? `${accountName(next.account, { currency: next.amount.currency })} (${next.account})` : 'an account the API does not name'} · obligation ${next.obligation_id}`">
                <div class="lw-figure" data-test="next-amount">{{ money(next.amount) }}</div>
              </Tip>
              <dl class="lw-ov-next__facts">
                <div>
                  <dt>Due in</dt>
                  <dd>
                    <Tip>{{ hoursShort(body.as_of, next.due_at) }}<template #tip><span data-test="due">due {{ due.utc }} · {{ due.local }}</span></template></Tip>
                  </dd>
                </div>
                <div>
                  <dt>Reserved</dt>
                  <dd>
                    <Tip :text="next.reserved ? `Held by reservation ${next.reservation_id || 'on the account'}` : 'No reservation holds it yet'">
                      {{ next.reserved ? 'Yes' : 'No' }}
                    </Tip>
                  </dd>
                </div>
              </dl>
              <span class="lw-visually-hidden" data-test="paid-from">{{ next.account ? accountName(next.account, { currency: next.amount.currency }) : 'Not named by the API' }}</span>
            </div>
            <p v-else class="lw-ov-sub" data-test="no-obligation">No open obligation</p>
            <RouterLink class="lw-ov-go" data-test="open-treasury"
                        :to="next ? rowLink('/treasury', `obligation:${next.obligation_id}`, body.snapshot_id) : { path: '/treasury', query: { snapshot: body.snapshot_id } }">
              Open Treasury<span v-if="next" class="lw-visually-hidden">, {{ next.kind }}</span><Arrow />
            </RouterLink>
          </div>
        </details>

        <!-- the world around the treasury -->
        <details class="lw-ov-fold" data-test="exposure">
          <summary>World exposure</summary>
          <div class="lw-ov-fold__body">
            <p class="lw-ov-sub">Key relationships for your cash position. A relationship is a dependency, not a payment.</p>
            <div class="lw-ov-world" data-test="relations">
              <svg class="lw-ov-world__edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <line v-for="n in world.around" :key="n.id" :x1="n.cx" :y1="n.cy" x2="50" y2="50" />
              </svg>
              <Tip v-for="n in world.nodes" :key="n.id" :class="['lw-ov-node', `lw-ov-node--${n.slot}`]"
                   :data-test="n.slot === 'centre' ? 'treasury-node' : 'relation'">
                <span class="lw-ov-node__body">
                  <span class="lw-ov-node__icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
                         stroke-linejoin="round"><path :d="n.icon" /></svg>
                  </span>
                  <span><b>{{ n.name }}</b><small>{{ n.sub }}</small></span>
                </span>
                <template #tip>
                  <span v-for="line in n.tip" :key="line" class="lw-ov-tipline">{{ line }}</span>
                </template>
              </Tip>
            </div>
            <RouterLink v-if="simulationTarget" class="lw-ov-go" :to="simulationTarget" data-test="explore-world">Explore world<Arrow /></RouterLink>
            <Tip v-else :text="simulationWhy" test="explore-why"><span class="lw-ov-sub">Explore world</span></Tip>
          </div>
        </details>

        <!-- the prepared scenario as it was run, read-only -->
        <details class="lw-ov-fold" data-test="scenario-about">
          <summary>Source &amp; scenario</summary>
          <div class="lw-ov-fold__body" role="region" aria-label="Scenario, read-only" data-test="scenario-preview">
            <p>{{ body.scenario ? body.scenario.about : 'No prepared run, so no what-if to preview.' }}
              The what-if path is a prepared hypothetical, not a forecast; a reserve breach is not a missed payment.</p>
            <dl v-if="body.scenario" class="lw-ov-preview__facts">
              <div><dt>Family</dt><dd>{{ body.scenario.family }}</dd></div>
              <div v-for="p in scenarioParams" :key="p.name"><dt>{{ p.name }}</dt><dd>{{ p.value }}</dd></div>
              <div v-if="delayed"><dt>Timing</dt><dd data-test="scenario-timing">{{ delayed }}</dd></div>
            </dl>
          </div>
        </details>
      </div>
    </template>
  </ScreenShell>
</template>

<script setup>
/**
 * Overview as one payroll decision around the 72-hour cash path (the 2026-10-31 Overview design,
 * prp/2026-11-03-overview-cash-path): the answer as the headline with its condition under it
 * (where cash is lowest, how far above the reserve floor, and the receipt that depends on), the
 * equation settled − reserved = spendable beside it, the cash path with the floor as its horizon
 * and the prepared what-if's own path dashed, a short what-if table and Open simulation; the cash
 * data, the next obligation, the world exposure and the scenario as run fold under it. Every
 * figure is the API's (the what-if path is its `scenario.outlook`); the browser formats and picks,
 * never recomputes.
 */
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Arrow from '../components/Arrow.vue'
import CashPath from '../components/CashPath.vue'
import Tip from '../components/Tip.vue'
import {
  FLOOR_WORDS, STATES, ScreenShell, accountName, againstFloor, amountWords, dayText, floorState, formatAmount, formatMoney,
  formatTime, freshness, getOverview, hoursWords, kindText, lastSeen, metricStatus, metricText, money,
  pendingFlows, pointAt, routeExists, rowLink, signedMoney, staleOf, useReading
} from '../api/v1.js'

const router = useRouter()
const { state, refresh } = useReading(() => getOverview())

const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1)
/** Whole simulated hours from the reading's as_of to `at`. */
const hoursAt = (asOf, at) => Math.round((Date.parse(at) - Date.parse(asOf)) / 3_600_000)
/** "in 40h", "now", "3h ago": whole simulated hours from the reading's as_of. */
function hoursShort (asOf, at) {
  const h = hoursAt(asOf, at)
  if (Number.isNaN(h)) return 'unknown'
  if (h === 0) return 'now'
  return h > 0 ? `in ${h}h` : `${-h}h ago`
}

const next = computed(() => state.body?.upcoming_outflows[0] ?? null)
const due = computed(() => formatTime(next.value?.due_at))
const floor = computed(() => floorState(state.body?.coverage.headroom))
const notCurrent = computed(() =>
  state.body?.completeness.accounts.map((a) => freshness(a).text).join('; '))
const stale = computed(() => staleOf(state.body?.completeness.accounts))

const runId = computed(() => state.body?.demo.run_id ?? null)
const simulationTarget = computed(() => {
  if (!runId.value || state.status !== 'loaded' || !routeExists(router, '/simulation')) return null
  return { path: '/simulation', query: { run_id: runId.value } }
})
const simulationWhy = computed(() => {
  if (state.status === 'loading') return 'Loading the current overview'
  if (state.status === 'error') return 'Last loaded, not current: reload first'
  if (!runId.value) return 'No demonstration run is prepared'
  return 'The simulation screen is not part of this build'
})

/**
 * The finance lead's answer (COPY.md), the condition's tooltip: covered until the next
 * obligation, or the day the floor breaks; every amount is an API metric, formatted.
 */
const lead = computed(() => {
  const b = state.body
  if (!b) return ''
  const cov = b.coverage
  const minimum = amountWords(cov.floor)
  const seen = lastSeen(b.spendable, cov.floor, cov.min_projected, cov.headroom)
  const tail = seen ? ` ${seen}` : ''
  if (floor.value === 'breached') {
    const short = formatMoney(-cov.headroom.minor, cov.headroom.currency)
    return `Heads up: on ${dayText(cov.at)} you dip ${short} below your ${minimum} safety minimum.${tail}`
  }
  const s = b.spendable
  const free = s.minor !== null && s.minor < 0
    ? `nothing free now (${formatMoney(-s.minor, s.currency)} short)`
    : `${amountWords(s)} free now`
  if (floor.value !== 'kept') {
    return `${floor.value === 'unassessed' ? 'Your safety minimum is not assessed yet' : "We can't tell yet whether you stay above your safety minimum"}; ${free}.${tail}`
  }
  const ahead = `${free}, and your lowest point ahead is ${amountWords(cov.min_projected)} — ` +
    `${amountWords(cov.headroom)} above your ${minimum} safety minimum.`
  const n = next.value
  return (n ? `You're covered until ${kindText(n.kind)} on ${dayText(n.due_at)}: ${ahead}` : `Nothing falls due: ${ahead}`) + tail
})

// --------------------------------------------------------------------------- the answer

/** The headline: the answer to "is the next obligation covered?", from the floor's state. */
const answer = computed(() => {
  if (!state.body) return ''
  const end = state.body.outlook?.at(-1)?.t
  const inside = next.value && end && Date.parse(next.value.due_at) <= Date.parse(end)
  const what = inside ? capital(kindText(next.value.kind)) : null
  if (floor.value === 'kept') return what ? `${what} is covered.` : 'Cash stays above the reserve floor.'
  if (floor.value === 'breached') return 'Cash falls below the reserve floor.'
  return floor.value === 'unassessed' ? 'No reserve floor is assessed yet.' : 'Coverage is unknown.'
})

const lowHour = computed(() => (state.body?.coverage.at ? hoursAt(state.body.as_of, state.body.coverage.at) : null))
const atHour = (h) => (h ? `at hour ${h}` : 'now')

/** The prepared what-if's path, the API's: empty when there is no scenario or it moves no flow. */
const latePoints = computed(() => state.body?.scenario?.outlook ?? [])
const showLate = ref(true)
/** The scenario's flow, when it names one the overview's accounts carry. */
const scenarioFlow = computed(() => {
  const id = state.body?.scenario?.params?.flow_id
  if (!id) return null
  return (state.body.accounts ?? []).flatMap(pendingFlows).find((f) => f.flow_id === id) ?? null
})

/**
 * The headline's condition: where cash is lowest and how far from the floor, and, when the
 * prepared what-if delays a receipt that lands before that low point, that it depends on it.
 */
const condition = computed(() => {
  const b = state.body
  if (!b) return ''
  const cov = b.coverage
  if (floor.value === 'unknown') return 'Projected cash is unknown: a balance is not observed.'
  if (floor.value === 'unassessed') return `Cash is lowest ${atHour(lowHour.value)}, at ${amountWords(cov.min_projected)}.`
  const gap = floor.value === 'kept'
    ? `${amountWords(cov.headroom)} above the reserve floor`
    : `${formatMoney(-cov.headroom.minor, cov.headroom.currency)} below the reserve floor`
  const f = scenarioFlow.value
  const fh = f ? hoursAt(b.as_of, f.expected_at) : null
  const hinge = f && f.direction === 'in' && lateLow.value?.state === 'breached' && fh <= lowHour.value
    ? `, as long as the ${money(f.amount)} ${kindText(f.kind)} lands ${atHour(fh)}`
    : ''
  return `Cash dips to ${amountWords(cov.min_projected)} ${atHour(lowHour.value)}, ${gap}${hinge}.`
})

const fa = (m, c) => formatAmount(m.minor, c)
const arrived = (f, asOf) => Date.parse(f.expected_at) <= Date.parse(asOf)

/**
 * The equation: settled, each term the API's buckets take from it, = spendable now. With one
 * account its terms are that account's buckets; with several, settled and spendable stand alone
 * and each account's terms are in the spendable tooltip.
 */
const terms = computed(() => {
  const b = state.body
  if (!b) return []
  const accounts = b.accounts ?? []
  const n = next.value
  const settledTip = accounts.map((a) => `${accountName(a.id, { currency: a.currency })}: ${a.buckets.settled ? money(a.buckets.settled) : 'Unknown'} settled`)
  const spendableTip = accounts.map((a) => {
    const c = a.currency
    const k = a.buckets
    const parts = [k.settled ? `${fa(k.settled, c)} settled` : 'Unknown settled',
      `− ${fa(k.reserved, c)} reserved`, `− ${fa(k.pledged, c)} pledged`,
      ...k.pending_out.map((f) => `− ${fa(f.amount, c)} ${kindText(f.kind)}`),
      ...k.pending_in.filter((f) => arrived(f, b.as_of)).map((f) => `+ ${fa(f.amount, c)} ${kindText(f.kind)}`)]
    return `${parts.join(' ')} = ${metricText(a.spendable)}`
  })
  const middle = []
  if (accounts.length === 1) {
    const k = accounts[0].buckets
    middle.push({ key: 'reserved', sign: '−', swatch: 'reserved', figure: money(k.reserved),
      label: n?.reserved ? `${capital(kindText(n.kind))} reserve` : 'Reserved' })
    if (k.pledged.minor) middle.push({ key: 'pledged', sign: '−', figure: money(k.pledged), label: 'Pledged' })
    for (const f of k.pending_out) middle.push({ key: `out-${f.flow_id}`, sign: '−', figure: money(f.amount), label: capital(kindText(f.kind)) })
    for (const f of k.pending_in.filter((x) => arrived(x, b.as_of))) {
      middle.push({ key: `in-${f.flow_id}`, sign: '+', figure: money(f.amount), label: capital(kindText(f.kind)) })
    }
  }
  return [
    { key: 'settled', label: 'Settled', figure: metricText(b.cash),
      tip: ['Settled balances on the treasury\'s cash accounts.', ...settledTip, metricStatus(b.cash)] },
    ...middle,
    { key: 'spendable', label: 'Spendable now', swatch: 'spendable', figure: metricText(b.spendable),
      tip: ['Settled − reserved − pledged − pending out + pending in arrived by now.', ...spendableTip, metricStatus(b.spendable)] }
  ]
})

const headroomText = computed(() => {
  const h = state.body?.coverage.headroom
  if (!h || h.minor === null || h.status === 'unassessed') return metricText(h)
  return `${signedMoney(h.minor, h.currency)}${h.status === 'stale' ? ' · stale' : ''}`
})

/** The what-if's lowest point, first reached, against the floor. */
const lateLow = computed(() => {
  const b = state.body
  const pts = latePoints.value.filter((p) => p.value.minor !== null)
  if (!b || !pts.length) return null
  const p = pts.reduce((x, y) => (y.value.minor < x.value.minor ? y : x))
  const { state: where, gap } = againstFloor(p.value, b.coverage.floor)
  const against = gap === null ? FLOOR_WORDS[where] : signedMoney(gap, p.value.currency)
  return { hours: hoursAt(b.as_of, p.t), money: metricText(p.value), state: where, against }
})

const teaser = computed(() => {
  const f = scenarioFlow.value
  if (f && latePoints.value.length) return `If the ${money(f.amount)} ${kindText(f.kind)} arrives late`
  if (f) return `What if your ${money(f.amount)} ${kindText(f.kind)} arrives late?`
  const s = state.body?.scenario
  return s ? `What if: ${s.family.replace(/-/g, ' ')}?` : 'What if a payment arrives late?'
})
const why = computed(() => {
  const low = lateLow.value
  if (!state.body?.scenario) return 'No prepared run, so no what-if to draw.'
  if (!low) return 'The prepared what-if moves no flow on this account, so no path is drawn.'
  if (low.state !== 'breached') return 'The reserve floor still holds.'
  const n = next.value
  return `${n?.reserved ? `${capital(kindText(n.kind))} is still paid from its reserve. ` : ''}The reserve floor is what breaks.`
})

/** An obligation under the axis opens its Treasury row. */
const linkOf = (e) => (e.direction === 'out' && state.body?.upcoming_outflows.some((o) => o.obligation_id === e.ref)
  ? rowLink('/treasury', `obligation:${e.ref}`, state.body.snapshot_id)
  : null)

/** The cash data: each point as planned and, at the same time, in the what-if. */
const rows = computed(() => {
  const b = state.body
  if (!b) return []
  const late = latePoints.value
  const planned = b.outlook ?? []
  const words = (events) => events.map((e) => `${capital(kindText(e.kind))} ${e.direction === 'in' ? '+' : '−'}${money(e.amount)}`).join(', ')
  // every time either path moves: a flow the what-if delays inside the horizon has its own row
  const times = [...new Set([...planned, ...late].map((p) => p.t))].sort((x, y) => Date.parse(x) - Date.parse(y))
  return times.map((t, n) => {
    const own = planned.find((p) => p.t === t)
    // the what-if's own move at t: its events the planned point does not carry
    const ownRefs = new Set(own?.events.map((e) => e.ref))
    const movedEvents = late.find((p) => p.t === t)?.events.filter((e) => !ownRefs.has(e.ref)) ?? []
    const p = pointAt(planned, t)
    const l = pointAt(late, t)
    return {
      t, hours: hoursAt(b.as_of, t), planned: p ? metricText(p.value) : '',
      event: [own?.events.length ? words(own.events) : '', movedEvents.length ? `${words(movedEvents)} (if late)` : '']
        .filter(Boolean).join('; ') || (n === 0 ? 'Now' : 'End of window'),
      late: l ? metricText(l.value) : '',
      lateBad: l ? againstFloor(l.value, b.coverage.floor).state === 'breached' : false
    }
  })
})

// ----------------------------------------------------------------------- the world

const BANK = 'M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18'
const ICON = {
  treasury: BANK,
  lender: BANK,
  payee: 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5.5a3 3 0 0 1 0 5.5M18 14.5c1.8.8 3 2.6 3 4.5',
  venue: 'M5 20v-6M10 20V9M15 20v-8M20 20V5',
  other: 'M4 20V8l8-4 8 4v12zM9 20v-5h6v5'
}
const plainName = (party) => (party?.name ?? party?.entity_id ?? '').replace(/\s*\(synthetic\)\s*$/i, '')
/** Where each node sits around the treasury, and the centre of that slot in the 100 x 100 drawing. */
const SLOTS = [
  { slot: 'tl', cx: 17, cy: 17 }, { slot: 'tr', cx: 83, cy: 17 },
  { slot: 'bl', cx: 17, cy: 83 }, { slot: 'br', cx: 83, cy: 83 }
]

/**
 * The treasury and the parties it depends on, as the API's relations state them: whom it owes
 * (an obligation), the venues it holds cash at, and the lender with what it can still lend. A
 * relation that does not touch the treasury (the lender's own lines) is told in that lender's
 * tooltip, never drawn as a link to the treasury.
 */
const world = computed(() => {
  const b = state.body
  if (!b) return { nodes: [], around: [] }
  const me = b.company?.entity_id ?? 'treasury'
  const parties = new Map()
  const party = (p, role) => {
    if (!parties.has(p.entity_id)) parties.set(p.entity_id, { id: p.entity_id, name: plainName(p), role, sub: '', tip: [] })
    return parties.get(p.entity_id)
  }
  for (const r of b.relations ?? []) {
    const amount = r.amount ? money(r.amount) : 'amount not observed'
    if (r.source.entity_id === me && r.target) {
      const kind = r.kind === 'venue_exposure' ? 'venue' : r.kind === 'obligation' ? 'payee' : 'other'
      const node = party(r.target, kind)
      node.links = (node.links ?? 0) + 1
      // one relation reads its amount; several read their count, each amount in the tooltip
      node.sub = node.links > 1
        ? `${node.links} ${r.kind === 'obligation' ? 'obligations owed' : 'links'}`
        : r.kind === 'obligation' ? `${amount} owed` : r.kind === 'venue_exposure' ? `${amount} held` : amount
      node.tip.push(r.kind === 'obligation' ? `You owe ${amount}: ${kindText(r.ref)}.` : `${capital(kindText(r.kind))} ${r.ref}: ${amount}.`)
    } else if (r.source.entity_id !== me) {
      const node = party(r.source, 'lender')
      const to = r.target ? plainName(r.target) : 'a party not recorded'
      node.tip.push(r.kind === 'credit_line' ? `Committed line to ${to}: ${amount}.` : `${capital(kindText(r.kind))} at ${to}: ${amount}.`)
    }
  }
  for (const node of parties.values()) {
    if (node.role === 'lender') {
      node.sub = b.lender_capacity?.minor != null ? `Can lend ${metricText(b.lender_capacity)}` : 'Capacity unknown'
      node.tip.unshift(`What it can still lend you: ${metricText(b.lender_capacity)}. A relationship is a dependency, not a payment.`)
    }
  }
  const order = { lender: 0, payee: 1, venue: 2, other: 3 }
  const around = [...parties.values()].sort((x, y) => order[x.role] - order[y.role]).slice(0, SLOTS.length)
    .map((n, i) => ({ ...n, ...SLOTS[i], icon: ICON[n.role] }))
  const centre = {
    id: me, slot: 'centre', name: 'Treasury', sub: `${metricText(b.cash)} settled`, icon: ICON.treasury,
    tip: [`${plainName(b.company) || 'The treasury'}, observed snapshot ${b.snapshot_id}.`]
  }
  return { nodes: [centre, ...around], around }
})


// ---------------------------------------------------------------------- the scenario as run

const delayed = computed(() => {
  const f = scenarioFlow.value
  const hours = state.body?.scenario?.params?.delay_h
  if (!f || !Number.isInteger(hours)) return ''
  const from = hoursShort(state.body.as_of, f.expected_at)
  return `${kindText(f.kind)} expected ${from}, ${hours < 0 ? `early by ${hoursWords(-hours)}` : `delayed ${hoursWords(hours)}`}`
})
/** The scenario's parameters as text: an `<x>_minor` amount in its currency, never raw units. */
const scenarioParams = computed(() => {
  const params = state.body?.scenario?.params ?? {}
  const currency = typeof params.currency === 'string' ? params.currency : state.body?.cash.currency
  return Object.entries(params).map(([name, value]) => (name.endsWith('_minor') && Number.isSafeInteger(value)
    ? { name: name.slice(0, -'_minor'.length), value: formatMoney(value, currency) }
    : { name, value: typeof value === 'object' ? JSON.stringify(value) : String(value) }))
})
</script>

<style scoped>
.lw-ov-sub {
  margin: 0;
  color: var(--lw-ink-muted);
  font-size: 16px;
}

.lw-ov-tipline {
  display: block;
}

/* the answer's condition reads as part of the answer */
:deep(.lw-hero__sub) {
  max-width: 40ch;
  color: var(--lw-ink);
  font-family: var(--lw-font-heading);
}

:deep(.lw-hero__action) {
  width: 330px;
}

/* settled − reserved = spendable: rows on a wide screen, one line on a phone */
.lw-ov-sum {
  display: grid;
  margin: 0;
}

.lw-ov-sum__term {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--lw-space-3);
  min-height: var(--lw-target);
  border-bottom: 1px solid var(--lw-rule);
}

.lw-ov-sum__term.is-total {
  border-bottom: 0;
  border-top: 1.5px solid var(--lw-ink);
  margin-top: -1px;
}

.lw-ov-sum dt {
  color: var(--lw-ink-muted);
  font-size: 15px;
  white-space: nowrap;
}

.lw-ov-sum dd {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
}

.lw-ov-sum__op {
  display: inline-block;
  width: 18px;
}

.lw-ov-sum__sw {
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 6px;
  border-radius: 2px;
}

.lw-ov-sum__sw.is-reserved {
  background: var(--lw-ink-muted);
  opacity: 0.4;
}

.lw-ov-sum__sw.is-spendable {
  background: var(--lw-brand);
}

/* the stage: the chart, then the what-if inside the floor's zone */
.lw-ov-stage {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--lw-space-2);
}

.lw-ov-iflate {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 380px) auto;
  grid-template-areas: 'tag tag .' 'h tbl act' 'why tbl act';
  column-gap: var(--lw-space-8);
  align-items: start;
}

.lw-ov-iflate__tag {
  grid-area: tag;
  display: flex;
  align-items: center;
  gap: var(--lw-space-4);
}

.lw-ov-iflate__h {
  grid-area: h;
  margin: var(--lw-space-2) 0 var(--lw-space-1) !important;
  font-size: 25px !important;
  line-height: 30px !important;
  font-weight: 600 !important;
}

.lw-ov-iflate__why {
  grid-area: why;
  margin: 0;
  max-width: 60ch;
}

.lw-ov-cmp {
  grid-area: tbl;
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.lw-ov-cmp th,
.lw-ov-cmp td {
  padding: 5px 0;
  border-bottom: 1px solid var(--lw-rule);
  text-align: right;
  white-space: nowrap;
}

.lw-ov-cmp th:first-child,
.lw-ov-cmp td:first-child {
  text-align: left;
}

.lw-ov-cmp thead th {
  color: var(--lw-ink-muted);
  font-size: 13px;
  font-weight: 400;
}

.lw-ov-cmp__h {
  color: var(--lw-ink-muted);
}

.lw-ov-cmp .is-bad,
.lw-ov-data .is-bad {
  color: var(--lw-warn);
  font-weight: 600;
}

.lw-ov-sum .lw-figure,
.lw-ov-cmp .lw-figure {
  font-size: inherit;
  font-weight: inherit;
}

.lw-ov-cmp .lw-status {
  display: block;
  font-size: 13px;
}

.lw-ov-iflate__act {
  grid-area: act;
  align-self: end;
  display: grid;
  justify-items: end;
  gap: var(--lw-space-2);
}

.lw-ov-iflate__act .lw-button {
  min-height: 52px;
  min-width: 240px;
  justify-content: center;
  font-size: 17px;
}

.lw-ov-iflate__act small {
  color: var(--lw-ink-muted);
  font-size: 13px;
}

.lw-ov-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--lw-space-2);
  padding: 6px 8px;
  border: 1px dashed var(--lw-ink);
  border-radius: 4px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.lw-ov-tag svg {
  width: 22px;
  height: 6px;
}

.lw-ov-ghost {
  min-height: var(--lw-target);
  min-width: var(--lw-target);
  padding: 0 4px;
  border: 0;
  background: none;
  color: var(--lw-ink);
  font: inherit;
  font-size: 14px;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

/* depth: one tap away */
.lw-ov-depth {
  margin-top: var(--lw-space-8);
  border-top: 1px solid var(--lw-rule);
}

.lw-ov-fold {
  border-bottom: 1px solid var(--lw-rule);
}

.lw-ov-fold summary {
  display: flex;
  align-items: center;
  gap: var(--lw-space-3);
  min-height: 48px;
  cursor: pointer;
  font-size: 15.5px;
}

.lw-ov-fold summary {
  list-style: none;
}

.lw-ov-fold summary::-webkit-details-marker {
  display: none;
}

.lw-ov-fold summary::after {
  content: '+';
  margin-left: auto;
  color: var(--lw-ink-muted);
  font-size: 22px;
}

.lw-ov-fold[open] summary::after {
  content: '−';
}

.lw-ov-fold__hint {
  color: var(--lw-ink-muted);
  font-size: 14px;
}

.lw-ov-fold__body {
  display: grid;
  gap: var(--lw-space-3);
  padding: var(--lw-space-1) 0 var(--lw-space-6);
  font-size: 15px;
}

.lw-ov-fold__body p {
  margin: 0;
  max-width: 62ch;
}

.lw-ov-tablewrap {
  overflow-x: auto;
}

.lw-ov-data {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.lw-ov-data th,
.lw-ov-data td {
  padding: 8px 6px;
  border-bottom: 1px solid var(--lw-rule);
  text-align: right;
}

.lw-ov-data th:nth-child(-n + 2),
.lw-ov-data td:nth-child(-n + 2) {
  text-align: left;
}

.lw-ov-data thead th {
  color: var(--lw-ink-muted);
  font-size: 13px;
  font-weight: 600;
}

.lw-ov-next__card {
  display: grid;
  gap: var(--lw-space-1);
}

.lw-ov-next__card .lw-figure {
  font-family: var(--lw-font-heading);
  font-size: 32px;
  line-height: 40px;
  font-weight: 600;
}

.lw-ov-next__facts {
  display: grid;
  gap: var(--lw-space-1);
  margin: 0;
}

.lw-ov-next__facts div,
.lw-ov-preview__facts div {
  display: grid;
  grid-template-columns: 8em minmax(0, 1fr);
}

.lw-ov-next__facts dt,
.lw-ov-preview__facts dt {
  color: var(--lw-ink-muted);
}

.lw-ov-next__facts dd,
.lw-ov-preview__facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.lw-ov-preview__facts {
  display: grid;
  gap: var(--lw-space-1);
  margin: 0;
  font-size: 14px;
}

.lw-ov-go {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  min-height: var(--lw-target);
  font-size: 16px;
  text-decoration: none;
}

.lw-ov-world {
  max-width: 560px;
}

/* the node graph: the treasury in the middle, the parties at the corners */
.lw-ov-world {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  grid-template-rows: auto auto auto;
  grid-template-areas: 'tl . tr' '. centre .' 'bl . br';
  gap: var(--lw-space-2) var(--lw-space-1);
  margin-top: var(--lw-space-2);
}

.lw-ov-world__edges {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.lw-ov-world__edges line {
  stroke: var(--lw-ink-muted);
  stroke-width: 1.2;
  vector-effect: non-scaling-stroke;
}

.lw-ov-node {
  position: relative;
  min-width: 0;
}

.lw-ov-node--tl { grid-area: tl; }
.lw-ov-node--tr { grid-area: tr; }
.lw-ov-node--bl { grid-area: bl; }
.lw-ov-node--br { grid-area: br; }
.lw-ov-node--centre { grid-area: centre; }

.lw-ov-node__body {
  display: flex;
  align-items: center;
  gap: var(--lw-space-2);
  height: 100%;
  padding: var(--lw-space-2);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  font-size: 13px;
  line-height: 16px;
}

.lw-ov-node--centre .lw-ov-node__body {
  background: var(--lw-selected);
  border-color: var(--lw-brand);
}

.lw-ov-node__body > span:last-child {
  min-width: 0;
}

.lw-ov-node__body b {
  display: block;
  font-weight: 600;
  overflow-wrap: break-word;
}

.lw-ov-node__icon {
  flex: none;
}

.lw-ov-node__body small {
  display: block;
  color: var(--lw-ink-muted);
  font-size: 12px;
}

.lw-ov-node__icon svg {
  display: block;
  width: 22px;
  height: 22px;
}

@media (max-width: 1199px) {
  .lw-ov-iflate {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'tag tag' 'h act' 'why act' 'tbl tbl';
  }

  .lw-ov-cmp {
    max-width: 420px;
    margin-top: var(--lw-space-3);
  }
}

@media (max-width: 767px) {
  :deep(.lw-hero) {
    gap: var(--lw-space-3);
    margin-top: var(--lw-space-2);
    margin-bottom: var(--lw-space-3);
  }

  :deep(.lw-hero__action) {
    width: 100%;
    padding-top: 0;
  }

  .lw-ov-sum {
    grid-template-columns: repeat(auto-fit, minmax(0, auto));
    justify-content: space-between;
    gap: 0 var(--lw-space-2);
    padding-top: var(--lw-space-2);
    border-top: 1px solid var(--lw-rule);
  }

  .lw-ov-sum__term,
  .lw-ov-sum__term.is-total {
    display: grid;
    align-content: end;
    gap: 0;
    min-height: 0;
    margin: 0;
    border: 0;
  }

  .lw-ov-sum dt {
    font-size: 13px;
  }

  .lw-ov-sum dd {
    font-size: 17px;
  }

  .lw-ov-sum__op {
    width: auto;
    margin-right: 4px;
  }

  .lw-ov-iflate {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'tag' 'h' 'act' 'why' 'tbl';
  }

  .lw-ov-iflate__h {
    font-size: 21px !important;
    line-height: 26px !important;
  }

  .lw-ov-iflate__act {
    justify-items: stretch;
    margin: var(--lw-space-1) 0 var(--lw-space-3);
  }

  .lw-ov-iflate__act .lw-button {
    width: 100%;
    min-width: 0;
  }
}
</style>

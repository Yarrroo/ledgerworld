<template>
  <ScreenShell title="Overview" headline="Know your cash. Rehearse the risk."
               :subtitle="subtitle" :lead="lead" :reading="state" :refresh="refresh" :stale="stale">
    <template #action>
      <Tip v-if="simulationTarget" text="Plays the prepared what-if round by round. Opening it moves no money.">
        <RouterLink class="lw-button" :to="simulationTarget" data-test="open-simulation">Open simulation<Arrow /></RouterLink>
      </Tip>
      <Tip v-else :text="simulationWhy" test="open-simulation-why">
        <button type="button" class="lw-button" disabled data-test="open-simulation">Open simulation</button>
      </Tip>
    </template>

    <template #default="{ body }">
      <p v-if="body.completeness.status === 'partial'" class="lw-note" data-test="partial">
        Partial: not current — {{ notCurrent }}.
      </p>

      <!-- the four figures -->
      <section class="lw-ov-strip" aria-label="Cash today" data-test="strip">
        <article v-for="m in metrics" :key="m.key" class="lw-ov-metric" :data-test="m.key">
          <span class="lw-ov-metric__label">{{ m.label }}</span>
          <Tip :test="`tip-${m.key}`">
            <span class="lw-ov-metric__value"><span class="lw-figure">{{ m.figure }}</span><span v-if="m.sub"
              class="lw-ov-metric__sub" :data-test="m.subTest"> · {{ m.sub }}</span></span>
            <template #tip>
              <span v-for="line in m.tip" :key="line" class="lw-ov-tipline">{{ line }}</span>
              <span v-if="m.key === 'coverage'" class="lw-ov-tipline">lowest point ahead {{ metricText(body.coverage.min_projected) }} ·
                safety minimum {{ metricText(body.coverage.floor) }}</span>
              <span v-if="m.key === 'coverage'" :class="['lw-status', `lw-status--${STATES[floor].tone}`]" data-test="floor-status">
                <span aria-hidden="true">{{ STATES[floor].icon }}</span> {{ FLOOR_WORDS[floor] }}
              </span>
            </template>
          </Tip>
          <span v-if="m.key === 'coverage' && floor !== 'kept'" :class="['lw-status', `lw-status--${STATES[floor].tone}`]"
                data-test="floor-alert"><span aria-hidden="true">{{ STATES[floor].icon }}</span> {{ FLOOR_WORDS[floor] }}</span>
        </article>
      </section>

      <div class="lw-ov-grid">
        <!-- the 72-hour cash outlook -->
        <section class="lw-ov-outlook" aria-labelledby="ov-outlook" data-test="outlook">
          <h2 id="ov-outlook">{{ horizon }}-hour cash outlook</h2>
          <p class="lw-ov-sub">Observed snapshot · {{ horizon }}-hour projection</p>
          <CashOutlook :points="body.outlook || []" :floor="body.coverage.floor" :low-at="body.coverage.at" :as-of="body.as_of"
                       :currency="body.cash.currency" />
        </section>

        <aside class="lw-ov-side">
          <!-- the next obligation -->
          <section class="lw-ov-next" aria-labelledby="ov-next" data-test="next-obligation">
            <h2 id="ov-next">Next obligation</h2>
            <div v-if="next" class="lw-ov-next__card">
              <span class="lw-ov-next__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round">
                  <path d="M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 15h5M10 18h3" />
                </svg>
              </span>
              <div>
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
            </div>
            <p v-else class="lw-ov-sub" data-test="no-obligation">No open obligation</p>
            <RouterLink class="lw-ov-go" data-test="open-treasury"
                        :to="next ? rowLink('/treasury', `obligation:${next.obligation_id}`, body.snapshot_id) : { path: '/treasury', query: { snapshot: body.snapshot_id } }">
              Open Treasury<span v-if="next" class="lw-visually-hidden">, {{ next.kind }}</span><Arrow />
            </RouterLink>
          </section>

          <!-- the world around the treasury -->
          <section class="lw-ov-exposure" aria-labelledby="ov-exposure" data-test="exposure">
            <h2 id="ov-exposure">World exposure</h2>
            <p class="lw-ov-sub">Key relationships for your cash position</p>
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
          </section>
        </aside>
      </div>

      <!-- the hypothetical -->
      <section class="lw-ov-scenario" aria-labelledby="ov-scenario" data-test="scenario">
        <span class="lw-ov-tag" data-test="hypothetical">Hypothetical</span>
        <div class="lw-ov-scenario__text">
          <h2 id="ov-scenario">{{ teaser }}</h2>
          <p class="lw-ov-sub">Rehearse a delay before it becomes a reserve breach.</p>
        </div>
        <Tip :text="body.scenario ? 'Shows the prepared what-if, read-only. A what-if changes no figure on this page.' : 'No prepared run, so no what-if to preview'"
             test="preview-why">
          <button type="button" class="lw-button" data-test="preview-scenario" :disabled="!body.scenario"
                  :aria-expanded="preview ? 'true' : 'false'" aria-controls="scenario-preview" @click="preview = !preview">
            {{ preview ? 'Hide scenario' : 'Preview scenario' }}<Arrow v-if="!preview" />
          </button>
        </Tip>
        <div v-if="preview && body.scenario" id="scenario-preview" class="lw-ov-preview" role="region"
             aria-label="Scenario, read-only" data-test="scenario-preview">
          <p>{{ body.scenario.about }}</p>
          <dl class="lw-ov-preview__facts">
            <div><dt>Family</dt><dd>{{ body.scenario.family }}</dd></div>
            <div v-for="p in scenarioParams" :key="p.name"><dt>{{ p.name }}</dt><dd>{{ p.value }}</dd></div>
            <div v-if="delayed"><dt>Timing</dt><dd data-test="scenario-timing">{{ delayed }}</dd></div>
          </dl>
        </div>
      </section>
    </template>
  </ScreenShell>
</template>

<script setup>
/**
 * Overview as mockup 01 (prp/2026-10-29-ux-pass/MATCH.md, 01 Overview): the hero and Open
 * simulation; four figures (settled cash, spendable now, the next obligation with its hours,
 * reserve headroom), each with its inputs in a tooltip; the annotated 72-hour cash outlook; the
 * next obligation; the world around the treasury as a small node graph; and the hypothetical
 * what-if. Every figure is the API's; the browser formats and never recomputes. An element the
 * API has no field for is left out (the mockup's public-feed node: the API serves no relation
 * for it).
 */
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Arrow from '../components/Arrow.vue'
import CashOutlook from '../components/CashOutlook.vue'
import Tip from '../components/Tip.vue'
import {
  FLOOR_WORDS, STATES, ScreenShell, accountName, amountWords, companyName, dayText, floorState, formatAmount, formatMoney,
  formatTime, freshness, getOverview, hoursWords, kindText, lastSeen, metricStatus, metricText, money,
  pendingFlows, routeExists, rowLink, staleOf, useReading
} from '../api/v1.js'

const router = useRouter()
const { state, refresh } = useReading(() => getOverview())

const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1)
/** "in 40h", "now", "3h ago": whole simulated hours from the reading's as_of. */
function hoursShort (asOf, at) {
  const h = Math.round((Date.parse(at) - Date.parse(asOf)) / 3_600_000)
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
const horizon = computed(() => {
  const last = state.body?.outlook?.at(-1)
  return last ? Math.round((Date.parse(last.t) - Date.parse(state.body.as_of)) / 3_600_000) : 72
})

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

const subtitle = computed(() => {
  const firm = companyName(state.body?.company)
  return `${firm ? firm.treasury : 'Treasury'} / Observed snapshot`
})

/**
 * The finance lead's answer (COPY.md), the subtitle's tooltip: covered until the next
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

// --------------------------------------------------------------------------- the strip

const fa = (m, c) => formatAmount(m.minor, c)
const arrived = (f, asOf) => Date.parse(f.expected_at) <= Date.parse(asOf)

/** The four figures, each with the inputs the API served for it, for its tooltip. */
const metrics = computed(() => {
  const b = state.body
  if (!b) return []
  const accounts = b.accounts ?? []
  const n = next.value
  const settled = accounts.map((a) => `${accountName(a.id, { currency: a.currency })}: ${a.buckets.settled ? money(a.buckets.settled) : 'Unknown'} settled`)
  const spendable = accounts.map((a) => {
    const c = a.currency
    const k = a.buckets
    const terms = [k.settled ? `${fa(k.settled, c)} settled` : 'Unknown settled',
      `− ${fa(k.reserved, c)} reserved`, `− ${fa(k.pledged, c)} pledged`,
      ...k.pending_out.map((f) => `− ${fa(f.amount, c)} ${kindText(f.kind)}`),
      ...k.pending_in.filter((f) => arrived(f, b.as_of)).map((f) => `+ ${fa(f.amount, c)} ${kindText(f.kind)}`)]
    return `${terms.join(' ')} = ${metricText(a.spendable)}`
  })
  return [
    { key: 'settled', label: 'Settled cash', figure: metricText(b.cash),
      tip: ['Settled balances on the treasury\'s cash accounts.', ...settled, metricStatus(b.cash)] },
    { key: 'spendable', label: 'Spendable now', figure: metricText(b.spendable),
      tip: ['Settled − reserved − pledged − pending out + pending in arrived by now.', ...spendable, metricStatus(b.spendable)] },
    n
      ? { key: 'next-due', label: `${capital(kindText(n.kind))} due`, figure: money(n.amount), sub: hoursShort(b.as_of, n.due_at), subTest: 'next-due-at',
          tip: [`The earliest open obligation, due ${formatTime(n.due_at).utc} (${hoursWords(Math.round((Date.parse(n.due_at) - Date.parse(b.as_of)) / 3_600_000))} of simulated time).`,
            n.reserved ? 'Reserved: the money is set aside.' : 'Not reserved yet.'] }
      : { key: 'next-due', label: 'Next obligation', figure: 'None open', tip: ['Nothing you owe falls due from now.'] },
    { key: 'coverage', label: 'Reserve headroom', figure: metricText(b.coverage.headroom),
      tip: [`Lowest projected cash over the horizon less the reserve floor${b.coverage.at ? `, at ${formatTime(b.coverage.at).utc}` : ''}.`] }
  ]
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

// ---------------------------------------------------------------------- the what-if

/** The scenario's flow, when it names one the overview's accounts carry. */
const scenarioFlow = computed(() => {
  const id = state.body?.scenario?.params?.flow_id
  if (!id) return null
  return (state.body.accounts ?? []).flatMap(pendingFlows).find((f) => f.flow_id === id) ?? null
})
const teaser = computed(() => {
  const f = scenarioFlow.value
  if (f) return `What if your ${money(f.amount)} ${kindText(f.kind)} arrives late?`
  const s = state.body?.scenario
  return s ? `What if: ${s.family.replace(/-/g, ' ')}?` : 'What if a payment arrives late?'
})
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
const preview = ref(false)
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

/* the four figures, separated by thin rules, no boxes */
.lw-ov-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  padding-bottom: var(--lw-space-6);
  border-bottom: 1px solid var(--lw-rule);
}

.lw-ov-metric {
  display: grid;
  align-content: start;
  gap: var(--lw-space-1);
  min-width: 0;
  padding: 0 var(--lw-space-6);
  border-left: 1px solid var(--lw-rule);
}

.lw-ov-metric:first-child {
  padding-left: 0;
  border-left: 0;
}

.lw-ov-metric__label {
  color: var(--lw-ink-muted);
  font-size: 16px;
}

.lw-ov-metric .lw-figure,
.lw-ov-next .lw-figure {
  font-family: var(--lw-font-heading);
  font-size: 40px;
  line-height: 48px;
  font-weight: 600;
  overflow-wrap: normal;
}

.lw-ov-metric__sub {
  font-family: var(--lw-font-heading);
  font-size: 26px;
  font-weight: 500;
  white-space: nowrap;
}

.lw-ov-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(0, 1fr);
  gap: var(--lw-space-8);
  padding: var(--lw-space-6) 0;
}

.lw-ov-grid h2,
.lw-ov-scenario h2 {
  margin: 0 !important;
  font-size: 30px !important;
  line-height: 38px !important;
  font-weight: 500 !important;
}

.lw-ov-outlook {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
  gap: var(--lw-space-2);
  min-width: 0;
}

.lw-ov-side {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
  gap: var(--lw-space-6);
  min-width: 0;
  padding-left: var(--lw-space-6);
  border-left: 1px solid var(--lw-rule);
}

.lw-ov-next__card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--lw-space-6);
  padding: var(--lw-space-4) 0;
  margin-top: var(--lw-space-3);
  border-top: 1px solid var(--lw-rule);
  border-bottom: 1px solid var(--lw-rule);
}

.lw-ov-next__icon {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--lw-selected);
  color: var(--lw-ink);
}

.lw-ov-next__icon svg {
  width: 30px;
  height: 30px;
}

.lw-ov-next__kind {
  font-size: 18px;
}

.lw-ov-next__facts {
  display: grid;
  gap: var(--lw-space-1);
  margin: var(--lw-space-2) 0 0;
}

.lw-ov-next__facts div {
  display: grid;
  grid-template-columns: 8em minmax(0, 1fr);
}

.lw-ov-next__facts dt {
  color: var(--lw-ink-muted);
}

.lw-ov-next__facts dd {
  margin: 0;
}

.lw-ov-go {
  display: inline-flex;
  align-items: center;
  min-height: var(--lw-target);
  font-size: 16px;
  text-decoration: none;
}

.lw-ov-exposure {
  display: grid;
  gap: var(--lw-space-2);
  padding-top: var(--lw-space-6);
  border-top: 1px solid var(--lw-rule);
}

.lw-ov-exposure .lw-ov-go {
  justify-self: center;
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

/* the hypothetical, full width at the foot */
.lw-ov-scenario {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--lw-space-3) var(--lw-space-6);
  padding-top: var(--lw-space-6);
  border-top: 1px solid var(--lw-rule);
}

.lw-ov-scenario h2 {
  font-size: 26px !important;
  line-height: 34px !important;
}

.lw-ov-tag {
  justify-self: start;
  padding: var(--lw-space-1) var(--lw-space-3);
  border-radius: var(--lw-radius);
  background: #E3ECFB;
  color: #1C4FB0;
  font-size: 14px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.lw-ov-preview {
  grid-column: 1 / -1;
  padding: var(--lw-space-4);
  border: 1px dashed var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
}

.lw-ov-preview p {
  margin: 0;
}

.lw-ov-preview__facts {
  display: grid;
  gap: var(--lw-space-1);
  margin: var(--lw-space-3) 0 0;
  font-size: 14px;
}

.lw-ov-preview__facts div {
  display: grid;
  grid-template-columns: 8em minmax(0, 1fr);
}

.lw-ov-preview__facts dt {
  color: var(--lw-ink-muted);
}

.lw-ov-preview__facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

@media (prefers-color-scheme: dark) {
  .lw-ov-tag {
    background: #1C2C4A;
    color: #A9C4F7;
  }
}

@media (max-width: 1199px) {
  .lw-ov-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    row-gap: var(--lw-space-4);
  }

  .lw-ov-metric:nth-child(3) {
    padding-left: 0;
    border-left: 0;
  }

  .lw-ov-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .lw-ov-side {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--lw-space-6);
    padding: var(--lw-space-6) 0 0;
    border-left: 0;
    border-top: 1px solid var(--lw-rule);
  }

  .lw-ov-exposure {
    padding-top: 0;
    border-top: 0;
  }
}

@media (max-width: 767px) {
  .lw-ov-metric {
    padding: 0 var(--lw-space-3);
  }

  .lw-ov-metric .lw-figure,
  .lw-ov-next .lw-figure {
    font-size: 28px;
    line-height: 34px;
  }

  .lw-ov-metric__sub {
    display: block;
    font-size: 18px;
  }

  .lw-ov-side {
    grid-template-columns: minmax(0, 1fr);
  }

  .lw-ov-exposure {
    padding-top: var(--lw-space-6);
    border-top: 1px solid var(--lw-rule);
  }

  .lw-ov-grid h2 {
    font-size: 24px !important;
    line-height: 30px !important;
  }

  .lw-ov-scenario {
    grid-template-columns: minmax(0, 1fr);
  }

  .lw-ov-scenario .lw-button {
    width: 100%;
  }
}
</style>

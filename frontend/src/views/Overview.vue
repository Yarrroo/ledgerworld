<template>
  <ScreenShell title="Overview" headline="Know your cash. Rehearse the risk."
               :subtitle="subtitle" :lead="lead" :reading="state" :refresh="refresh" :stale="stale">
    <template #action>
      <RouterLink v-if="simulationTarget" class="lw-button" :to="simulationTarget" data-test="open-simulation">
        Open simulation<Arrow />
      </RouterLink>
      <Tip v-else :text="simulationWhy" test="open-simulation-why">
        <button type="button" class="lw-button" disabled data-test="open-simulation">Open simulation</button>
      </Tip>
    </template>
    <template #default="{ body }">
    <p v-if="body.completeness.status === 'partial'" class="lw-note" data-test="partial">
      Partial: not current — {{ notCurrent }}.
    </p>

    <!-- O2 cash strip -->
    <section class="lw-ov-strip-panel" aria-labelledby="ov-strip" data-panel="Cash today">
      <h2 id="ov-strip" class="lw-visually-hidden">Cash today</h2>
      <div class="lw-ov-strip">
        <article v-for="m in metrics" :key="m.key" :class="['lw-ov-metric', { 'is-selected': selected === m.key }]"
                 :data-test="m.key">
          <button type="button" class="lw-ov-metric__pick" :aria-expanded="selected === m.key ? 'true' : 'false'"
                  aria-controls="metric-inputs" :data-test="`pick-${m.key}`" @click="pick(m.key)">
            <span class="lw-tile__label">{{ m.label }}</span>
            <span class="lw-figure">{{ m.figure }}</span>
            <span v-if="m.sub" class="lw-ov-metric__sub" :data-test="m.subTest">{{ m.sub }}</span>
            <span class="lw-time">{{ m.fresh }}</span>
          </button>
          <div v-if="m.key === 'settled' && body.cash.status === 'stale'" class="lw-time" data-test="as-of">
            as of {{ formatTime(body.cash.as_of).utc }}
          </div>
          <template v-if="m.key === 'coverage'">
            <div class="lw-time">
              lowest point ahead {{ metricText(body.coverage.min_projected) }} ·
              safety minimum {{ metricText(body.coverage.floor) }}
            </div>
            <div :class="['lw-status', `lw-status--${STATES[floor].tone}`]" data-test="floor-status">
              <span aria-hidden="true">{{ STATES[floor].icon }}</span>
              <span>{{ FLOOR_WORDS[floor] }}</span>
            </div>
          </template>
        </article>
      </div>

      <div v-if="inputs" id="metric-inputs" class="lw-ov-inputs" role="region" :aria-label="`Inputs: ${inputs.title}`"
           data-test="metric-inputs">
        <h3>{{ inputs.title }}</h3>
        <p class="lw-time">{{ inputs.rule }}</p>
        <ul>
          <li v-for="line in inputs.lines" :key="line.key" data-test="metric-input">
            <span>{{ line.text }}</span>
            <RouterLink v-if="line.to" :to="line.to" data-test="metric-link">{{ line.link }}</RouterLink>
          </li>
        </ul>
        <p class="lw-ov-inputs__result">API result: <b>{{ inputs.result }}</b></p>
      </div>
    </section>

    <div class="lw-ov-grid">
      <!-- O3 cash outlook -->
      <section class="lw-ov-outlook" aria-labelledby="ov-outlook" data-panel="Cash ahead" data-test="outlook">
        <h2 id="ov-outlook">Your cash over the next {{ horizon }} hours</h2>
        <p class="lw-time">Where your cash is heading if nothing unexpected happens.</p>
        <CashOutlook :points="body.outlook || []" :floor="body.coverage.floor" :low-at="body.coverage.at" :as-of="body.as_of"
                     :currency="body.cash.currency" />
        <HowWeKnow test="how-outlook">
          <p>Observed snapshot {{ body.snapshot_id }} · projected cash P from the API, no shock; the
            dashed line is the reserve floor.</p>
        </HowWeKnow>
      </section>

      <!-- O4 next obligation -->
      <section class="lw-ov-next" aria-labelledby="ov-next" data-panel="Next payment" data-test="next-obligation">
        <h2 id="ov-next">Next payment due</h2>
        <template v-if="next">
          <div class="lw-tile__label">{{ kindText(next.kind) }}</div>
          <div class="lw-figure">{{ money(next.amount) }}</div>
          <dl class="lw-ov-facts lw-ov-facts--stack">
            <div><dt>Due</dt><dd class="lw-time" data-test="due">due {{ due.utc }} · {{ due.local }} · {{ hoursFrom(body.as_of, next.due_at) }}</dd></div>
            <div><dt>Set aside</dt><dd>{{ next.reserved ? 'Yes, the money is set aside' : 'Not set aside' }}</dd></div>
            <div><dt>Paid from</dt><dd data-test="paid-from">{{ next.account ? accountName(next.account, { currency: next.amount.currency }) : 'Not named by the API' }}</dd></div>
          </dl>
          <HowWeKnow test="how-next">
            <dl class="lw-ov-facts lw-ov-facts--stack">
              <div><dt>Obligation</dt><dd>{{ next.kind }} · {{ next.obligation_id }}</dd></div>
              <div><dt>Reservation</dt><dd>{{ next.reserved ? `reserved · ${next.reservation_id || 'hold'}` : 'not reserved' }}</dd></div>
              <div><dt>State</dt><dd>Open</dd></div>
              <div><dt>Funding account</dt><dd>{{ next.account || 'Not named by the API' }}</dd></div>
            </dl>
          </HowWeKnow>
          <RouterLink class="lw-ov-go" :to="rowLink('/treasury', `obligation:${next.obligation_id}`, body.snapshot_id)"
                      data-test="open-treasury">Open Treasury<span class="lw-visually-hidden">, {{ next.kind }} {{ next.obligation_id }}</span> →</RouterLink>
        </template>
        <template v-else>
          <div class="lw-figure lw-figure--small" data-test="no-obligation">No open obligation</div>
          <p class="lw-time">Nothing you owe falls due from now.</p>
          <RouterLink class="lw-ov-go" :to="{ path: '/treasury', query: { snapshot: body.snapshot_id } }"
                      data-test="open-treasury">Obligations on Treasury →</RouterLink>
        </template>
      </section>

      <!-- O5 exposure preview -->
      <section class="lw-ov-exposure" aria-labelledby="ov-exposure" data-panel="Partners" data-test="exposure">
        <h2 id="ov-exposure">Who your cash depends on</h2>
        <p class="lw-time">The partners around {{ body.company ? body.company.name : 'the treasury' }}.
          A relationship is a dependency, not a payment; no public post moves money.</p>
        <ul v-if="relations.length" class="lw-ov-relations" data-test="relations">
          <li v-for="r in relations" :key="`${r.kind}:${r.ref}:${r.source.entity_id}`" data-test="relation">
            <span class="lw-ov-relations__who">
              <b>{{ r.source.name }}</b>
              <span aria-hidden="true"> → </span><span class="lw-visually-hidden"> to </span>
              <b>{{ r.target ? r.target.name : 'payee not recorded' }}</b>
            </span>
            <span class="lw-visually-hidden">: </span>
            <span class="lw-time">{{ r.what }}</span>
          </li>
        </ul>
        <p v-else class="lw-time" data-test="no-relations">The snapshot records no relationship around the treasury.</p>
        <div class="lw-ov-capacity" data-test="lender-capacity">
          <span class="lw-tile__label">What the lender can still lend</span>
          <span class="lw-figure lw-figure--small">{{ metricText(body.lender_capacity) }}</span>
          <RouterLink to="/lending">How it is worked out, on Lending</RouterLink>
        </div>
        <RouterLink v-if="simulationTarget" class="lw-ov-go" :to="simulationTarget" data-test="explore-world">Explore the partners →</RouterLink>
        <p v-else class="lw-time" data-test="explore-why">{{ simulationWhy }}</p>
        <HowWeKnow test="how-exposure">
          <p>Relationships recorded on observed snapshot {{ body.snapshot_id }}, each with its obligation,
            credit line or venue reference. The lender's figure is lender capacity K_p, as on Lending.</p>
        </HowWeKnow>
      </section>
    </div>

    <!-- O6 scenario entry -->
    <section class="lw-ov-scenario" aria-labelledby="ov-scenario" data-panel="What-if" data-test="scenario">
      <span class="lw-ov-tag" data-test="hypothetical">What-if</span>
      <div class="lw-ov-scenario__text">
        <h2 id="ov-scenario">{{ teaser }}</h2>
        <p class="lw-time">Try it before it takes you below your safety minimum. A what-if changes no
          figure on this page.</p>
      </div>
      <div class="lw-actions">
        <button type="button" class="lw-button lw-button--quiet" data-test="preview-scenario"
                :disabled="!body.scenario" :aria-expanded="preview ? 'true' : 'false'" aria-controls="scenario-preview"
                :aria-describedby="body.scenario ? undefined : 'preview-why'" @click="preview = !preview">
          {{ preview ? 'Hide the what-if' : 'Preview the what-if' }}
        </button>
        <span v-if="!body.scenario" id="preview-why" class="lw-time" data-test="preview-why">No prepared run, so no what-if to preview</span>
      </div>
      <div v-if="preview && body.scenario" id="scenario-preview" class="lw-ov-preview" role="region"
           aria-label="Scenario, read-only" data-test="scenario-preview">
        <p>{{ body.scenario.about }}</p>
        <dl class="lw-ov-facts lw-ov-facts--stack">
          <div><dt>Family</dt><dd>{{ body.scenario.family }}</dd></div>
          <div v-for="p in scenarioParams" :key="p.name"><dt>{{ p.name }}</dt><dd>{{ p.value }}</dd></div>
          <div v-if="delayed"><dt>Timing</dt><dd data-test="scenario-timing">{{ delayed }}</dd></div>
          <div><dt>Run</dt><dd>{{ body.demo.run_id }} (prepared)</dd></div>
        </dl>
        <p class="lw-time">Read-only. Starting a new run is an operator action on Simulation.</p>
      </div>
    </section>
    </template>
  </ScreenShell>
</template>

<script setup>
/**
 * Overview, panels O1–O6 of the UX handoff (prp/2026-10-29-ux-pass/HANDOFF.md): context, the
 * cash strip (a metric opens the inputs the API served for it, and links to its row on
 * Treasury), the cash outlook, the next obligation, the exposure preview and a hypothetical
 * scenario entry. Every figure is the API's; the browser formats and never recomputes.
 */
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Arrow from '../components/Arrow.vue'
import CashOutlook from '../components/CashOutlook.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
import Tip from '../components/Tip.vue'
import {
  AGENTS, FLOOR_WORDS, companyName, LABELS, PLAIN, STATES, ScreenShell, accountName, amountWords, dayText, floorState, formatAmount, formatMoney,
  formatTime, freshness, getOverview, hoursFrom, hoursWords, kindText, lastSeen, metricStatus, metricText, modelSource, money,
  pendingFlows, routeExists, rowLink, staleOf, useReading
} from '../api/v1.js'

const router = useRouter()
const { state, refresh } = useReading(() => getOverview())
const model = ref(null)
modelSource().then((m) => { model.value = m })

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

/**
 * The finance lead's answer, first (COPY.md): covered until the next obligation, or the day the
 * floor breaks; every amount is an API metric, formatted, never computed here.
 */
const lead = computed(() => {
  const b = state.body
  if (!b) return ''
  const cov = b.coverage
  const minimum = amountWords(cov.floor)
  if (floor.value === 'breached') {
    const short = formatMoney(-cov.headroom.minor, cov.headroom.currency)
    return `Heads up: on ${dayText(cov.at)} you dip ${short} below your ${minimum} safety minimum.`
  }
  const s = b.spendable
  const free = s.minor !== null && s.minor < 0
    ? `nothing free now (${formatMoney(-s.minor, s.currency)} short)`
    : `${amountWords(s)} free now`
  if (floor.value !== 'kept') {
    return `${floor.value === 'unassessed' ? 'Your safety minimum is not assessed yet' : "We can't tell yet whether you stay above your safety minimum"}; ${free}.`
  }
  const ahead = `${free}, and your lowest point ahead is ${amountWords(cov.min_projected)} — ` +
    `${amountWords(cov.headroom)} above your ${minimum} safety minimum.`
  const n = next.value
  return n ? `You're covered until ${kindText(n.kind)} on ${dayText(n.due_at)}: ${ahead}` : `Nothing falls due: ${ahead}`
})

const subtitle = computed(() => {
  const firm = companyName(state.body?.company)
  return `${firm ? firm.treasury : 'Treasury'} / Observed snapshot`
})

const leadSeen = computed(() => {
  const b = state.body
  return b ? lastSeen(b.spendable, b.coverage.floor, b.coverage.min_projected, b.coverage.headroom) : ''
})

// --------------------------------------------------------------------------- O2 strip

const metrics = computed(() => {
  const b = state.body
  if (!b) return []
  const n = next.value
  return [
    { key: 'settled', label: 'Cash in the bank', figure: metricText(b.cash), fresh: metricStatus(b.cash) },
    { key: 'spendable', label: 'Free to spend now', figure: metricText(b.spendable), fresh: metricStatus(b.spendable) },
    n
      ? { key: 'next-due', label: `Next ${n.kind} due`, figure: money(n.amount), sub: `due ${hoursFrom(b.as_of, n.due_at)}`, subTest: 'next-due-at', fresh: `● ${n.reserved ? 'Reserved' : 'Not reserved'}` }
      : { key: 'next-due', label: 'Next obligation', figure: 'None open', fresh: 'Nothing falls due' },
    { key: 'coverage', label: 'Room above your minimum', figure: metricText(b.coverage.headroom), fresh: metricStatus(b.coverage.headroom) }
  ]
})

const selected = ref(null)
function pick (key) {
  selected.value = selected.value === key ? null : key
}

const fa = (m, c) => formatAmount(m.minor, c)
const arrived = (f, asOf) => Date.parse(f.expected_at) <= Date.parse(asOf)

/** The inputs the API served for the selected metric, each line with its row on Treasury. */
const inputs = computed(() => {
  const b = state.body
  if (!b || !selected.value) return null
  const accounts = b.accounts ?? []
  const toAccount = (a) => rowLink('/treasury', `account:${a.id}`, b.snapshot_id)
  const none = [{ key: 'none', text: 'The API served no account inputs for this figure.' }]
  switch (selected.value) {
    case 'settled':
      return {
        title: 'Cash in the bank',
        rule: 'Sum of settled balances on the treasury\'s cash accounts in one currency.',
        lines: accounts.length
          ? accounts.map((a) => ({
            key: a.id, to: toAccount(a), link: 'Open on Treasury',
            text: `${a.id}: ${a.buckets.settled ? money(a.buckets.settled) : 'Unknown'} settled · as of ${formatTime(a.as_of).utc}`
          }))
          : none,
        result: metricText(b.cash)
      }
    case 'spendable':
      return {
        title: 'Free to spend now',
        rule: 'S = settled − reserved − pledged − pending out + pending in arrived by now.',
        lines: accounts.length
          ? accounts.map((a) => {
            const c = a.currency
            const k = a.buckets
            const terms = [k.settled ? `${fa(k.settled, c)} settled` : 'Unknown settled',
              `− ${fa(k.reserved, c)} reserved`, `− ${fa(k.pledged, c)} pledged`,
              ...k.pending_out.map((f) => `− ${fa(f.amount, c)} ${f.kind}`),
              ...k.pending_in.filter((f) => arrived(f, b.as_of)).map((f) => `+ ${fa(f.amount, c)} ${f.kind}`)]
            return {
              key: a.id, to: toAccount(a), link: 'Open on Treasury',
              text: `${a.id} (${c}): ${terms.join(' ')} = ${metricText(a.spendable)}`
            }
          })
          : none,
        result: metricText(b.spendable)
      }
    case 'next-due': {
      const n = next.value
      if (!n) return { title: 'Next obligation', rule: 'Open obligations due from now.', lines: [{ key: 'none', text: 'No open obligation.' }], result: 'None open' }
      const t = formatTime(n.due_at)
      return {
        title: `Next ${n.kind} due`,
        rule: 'The earliest open obligation due from now.',
        lines: [
          { key: 'id', text: `${n.kind} ${n.obligation_id}: ${money(n.amount)}` },
          { key: 'due', text: `due ${t.utc} · ${t.local} · ${hoursFrom(b.as_of, n.due_at)}` },
          { key: 'res', text: n.reserved ? `reserved by ${n.reservation_id || 'a hold'}` : 'not reserved' },
          { key: 'acct', text: `paid from ${n.account || 'an account the API does not name'}`, to: rowLink('/treasury', `obligation:${n.obligation_id}`, b.snapshot_id), link: 'Open on Treasury' }
        ],
        result: money(n.amount)
      }
    }
    case 'coverage': {
      const cov = b.coverage
      return {
        title: 'Room above your minimum',
        rule: 'Headroom = lowest projected cash P over the horizon − reserve floor; the floor is kept at zero or more.',
        lines: [
          { key: 'min', text: `lowest P ${metricText(cov.min_projected)}${cov.at ? ` at ${formatTime(cov.at).utc} (${hoursFrom(b.as_of, cov.at)})` : ''}` },
          { key: 'floor', text: `reserve floor ${metricText(cov.floor)}` },
          ...accounts.map((a) => ({ key: a.id, text: `P by account: ${a.id}`, to: toAccount(a), link: 'Open on Treasury' }))
        ],
        result: `${metricText(cov.headroom)} · ${FLOOR_WORDS[floor.value]}`
      }
    }
    default:
      return null
  }
})

// ---------------------------------------------------------------------- O5 and O6

const RELATION = {
  obligation: (r) => `obligation ${r.ref}${r.amount ? `, ${money(r.amount)} owed` : ''}`,
  credit_line: (r) => `committed line ${r.ref}${r.amount ? `, limit ${money(r.amount)}` : ''}`,
  venue_exposure: (r) => `shared venue ${r.ref}${r.amount ? `, ${money(r.amount)} exposed` : ', amount not observed'}`
}
const relations = computed(() => (state.body?.relations ?? []).map((r) => ({
  ...r, what: (RELATION[r.kind] ?? ((x) => `${x.kind} ${x.ref}`))(r)
})))

/** The scenario's flow, when it names one the overview's accounts carry. */
const scenarioFlow = computed(() => {
  const id = state.body?.scenario?.params?.flow_id
  if (!id) return null
  return (state.body.accounts ?? []).flatMap(pendingFlows).find((f) => f.flow_id === id) ?? null
})
const teaser = computed(() => {
  const f = scenarioFlow.value
  if (f) return `What if the ${money(f.amount)} ${kindText(f.kind)} arrives late?`
  const s = state.body?.scenario
  return s ? `What if: ${s.family.replace(/-/g, ' ')}?` : 'What if a payment arrives late?'
})
const delayed = computed(() => {
  const f = scenarioFlow.value
  const hours = state.body?.scenario?.params?.delay_h
  if (!f || !Number.isInteger(hours)) return ''
  const from = hoursFrom(state.body.as_of, f.expected_at)
  return `${f.flow_id} expected ${from}, ${hours < 0 ? `early by ${hoursWords(-hours)}` : `delayed ${hoursWords(hours)}`}`
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
.lw-ov-context {
  display: grid;
  gap: var(--lw-space-3);
}

.lw-ov-lead {
  margin: 0 !important;
}

.lw-ov-labels {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2);
}

.lw-ov-lead span {
  color: var(--lw-ink-muted);
  font-weight: 400;
}

.lw-ov-context .lw-button {
  justify-self: start;
}

.lw-ov-facts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2) var(--lw-space-6);
  margin: 0;
  font-size: 14px;
}

.lw-ov-facts div {
  display: flex;
  gap: var(--lw-space-2);
  min-width: 0;
}

.lw-ov-facts dt {
  color: var(--lw-ink-muted);
}

.lw-ov-facts dd {
  margin: 0;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.lw-ov-facts--stack {
  display: grid;
  gap: var(--lw-space-1);
  margin: var(--lw-space-3) 0;
}

.lw-ov-facts--stack div {
  display: grid;
  grid-template-columns: 9.5em minmax(0, 1fr);
}

.lw-ov-strip-panel {
  margin-top: var(--lw-space-6);
  border-top: 1px solid var(--lw-rule);
  border-bottom: 1px solid var(--lw-rule);
}

.lw-ov-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.lw-ov-metric {
  min-width: 0;
  padding: var(--lw-space-4);
  border-left: 1px solid var(--lw-rule);
}

.lw-ov-metric:first-child {
  border-left: 0;
}

.lw-ov-metric.is-selected {
  background: var(--lw-selected);
}

.lw-ov-metric__pick {
  display: grid;
  gap: var(--lw-space-1);
  width: 100%;
  min-height: var(--lw-target);
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.lw-ov-metric__sub {
  font-weight: 600;
}

.lw-ov-inputs {
  padding: var(--lw-space-4);
  background: var(--lw-surface-raised);
  border-top: 1px solid var(--lw-rule);
}

.lw-ov-inputs h3 {
  margin: 0 0 var(--lw-space-1);
  font-size: 16px;
}

.lw-ov-inputs ul {
  display: grid;
  gap: var(--lw-space-2);
  list-style: none;
  padding: 0;
  margin: var(--lw-space-3) 0;
  font-size: 14px;
  overflow-wrap: anywhere;
}

.lw-ov-inputs li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--lw-space-3);
}

.lw-ov-inputs li a,
.lw-ov-go,
.lw-ov-capacity a {
  display: inline-flex;
  align-items: center;
  min-height: var(--lw-target);
  font-weight: 600;
}

.lw-ov-inputs__result {
  margin: 0;
}

.lw-ov-grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  grid-template-areas: 'outlook next' 'outlook exposure';
  gap: var(--lw-space-6) var(--lw-space-8);
  margin-top: var(--lw-space-6);
}

.lw-ov-outlook { grid-area: outlook; min-width: 0; }
.lw-ov-next { grid-area: next; min-width: 0; }
.lw-ov-exposure { grid-area: exposure; min-width: 0; }

.lw-ov-next,
.lw-ov-exposure {
  border-left: 1px solid var(--lw-rule);
  padding-left: var(--lw-space-6);
}

.lw-ov-grid h2 {
  margin-top: 0 !important;
}

.lw-ov-metric__pick .lw-figure,
.lw-ov-next .lw-figure {
  font-family: var(--lw-font-heading);
  font-size: 30px;
  line-height: 36px;
}

.lw-ov-relations {
  display: grid;
  gap: var(--lw-space-2);
  list-style: none;
  padding: 0;
  margin: var(--lw-space-3) 0;
}

.lw-ov-relations li {
  display: grid;
  padding: var(--lw-space-2) var(--lw-space-3);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  overflow-wrap: anywhere;
}

.lw-ov-capacity {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--lw-space-3);
}

.lw-ov-scenario {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--lw-space-3) var(--lw-space-6);
  margin-top: var(--lw-space-8);
  padding-top: var(--lw-space-6);
  border-top: 1px solid var(--lw-rule);
}

.lw-ov-scenario h2 {
  margin: 0 !important;
}

.lw-ov-scenario .lw-actions {
  margin: 0;
}

.lw-ov-tag {
  justify-self: start;
  padding: var(--lw-space-1) var(--lw-space-2);
  border-radius: var(--lw-radius);
  background: #E3ECFB;
  color: #1C4FB0;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.06em;
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

@media (prefers-color-scheme: dark) {
  .lw-ov-tag {
    background: #1C2C4A;
    color: #A9C4F7;
  }
}

@media (max-width: 1199px) {
  .lw-ov-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .lw-ov-metric:nth-child(3) {
    border-left: 0;
  }

  .lw-ov-metric:nth-child(n + 3) {
    border-top: 1px solid var(--lw-rule);
  }

  .lw-ov-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'outlook' 'next' 'exposure';
  }

  .lw-ov-next,
  .lw-ov-exposure {
    border-left: 0;
    padding-left: 0;
    border-top: 1px solid var(--lw-rule);
    padding-top: var(--lw-space-6);
  }
}

@media (max-width: 767px) {
  .lw-ov-metric {
    padding: var(--lw-space-3);
  }

  .lw-ov-metric__pick .lw-figure,
  .lw-ov-next .lw-figure {
    font-size: 20px;
    line-height: 26px;
  }

  .lw-ov-grid {
    grid-template-areas: 'next' 'outlook' 'exposure';
  }

  .lw-ov-next {
    border-top: 0;
    padding-top: 0;
  }

  .lw-ov-outlook {
    border-top: 1px solid var(--lw-rule);
    padding-top: var(--lw-space-6);
  }

  .lw-ov-scenario {
    grid-template-columns: minmax(0, 1fr);
  }

  .lw-ov-facts--stack div {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

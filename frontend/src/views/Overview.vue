<template>
  <ScreenShell v-slot="{ body, busy }" title="Overview" :reading="state" :refresh="refresh" :stale="stale">
    <!-- O1 context -->
    <section class="lw-ov-context" aria-labelledby="ov-context" data-panel="Context" data-test="context-panel">
      <h2 id="ov-context" class="lw-ov-lead">
        {{ body.company ? body.company.name : 'Treasury' }} <span>/ observed snapshot</span>
      </h2>
      <dl class="lw-ov-facts">
        <div><dt>Snapshot</dt><dd data-test="context-snapshot">{{ body.snapshot_id }}</dd></div>
        <div><dt>Currency</dt><dd data-test="context-currency">{{ body.cash.currency }}</dd></div>
        <div><dt>Company</dt><dd>{{ body.company ? body.company.name : 'Not named by the API' }}</dd></div>
        <div><dt>Provider</dt><dd>{{ LABELS[body.mode] || body.mode }}</dd></div>
        <div><dt>Model</dt><dd>{{ model || 'Not reported' }}</dd></div>
        <div><dt>As of</dt><dd data-test="context-time">{{ formatTime(body.as_of).utc }} · {{ formatTime(body.as_of).local }}</dd></div>
      </dl>
      <button type="button" class="lw-button lw-button--quiet" data-test="context-refresh" :disabled="busy"
              @click="refresh()">Read context again</button>
      <p v-if="body.completeness.status === 'partial'" class="lw-note" data-test="partial">
        Partial: not current — {{ notCurrent }}.
        A stale account was observed and keeps its last value, and the figures that include it
        say Stale; an unknown one has no value. Lender capacity counts known balances only.
      </p>
    </section>

    <!-- O2 cash strip -->
    <section class="lw-ov-strip-panel" aria-labelledby="ov-strip" data-panel="Cash strip">
      <h2 id="ov-strip" class="lw-visually-hidden">Cash strip</h2>
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
              {{ metricText(body.coverage.min_projected) }} minimum projected cash /
              {{ metricText(body.coverage.floor) }} floor
            </div>
            <div :class="['lw-status', `lw-status--${STATES[floor].tone}`]" data-test="floor-status">
              <span aria-hidden="true">{{ STATES[floor].icon }}</span>
              <span>{{ STATES[floor].word }}</span>
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
      <section class="lw-ov-outlook" aria-labelledby="ov-outlook" data-panel="Cash outlook" data-test="outlook">
        <h2 id="ov-outlook">{{ horizon }}-hour cash outlook</h2>
        <p class="lw-time">Observed snapshot {{ body.snapshot_id }} · projected cash P from the API, no shock</p>
        <CashOutlook :points="body.outlook || []" :floor="body.coverage.floor" :low-at="body.coverage.at" :as-of="body.as_of"
                     :currency="body.cash.currency" />
      </section>

      <!-- O4 next obligation -->
      <section class="lw-ov-next" aria-labelledby="ov-next" data-panel="Next obligation" data-test="next-obligation">
        <h2 id="ov-next">Next obligation</h2>
        <template v-if="next">
          <div class="lw-tile__label">{{ next.kind }} · {{ next.obligation_id }}</div>
          <div class="lw-figure">{{ money(next.amount) }}</div>
          <dl class="lw-ov-facts lw-ov-facts--stack">
            <div><dt>Due</dt><dd class="lw-time" data-test="due">due {{ due.utc }} · {{ due.local }} · {{ hoursFrom(body.as_of, next.due_at) }} from as of</dd></div>
            <div><dt>Reservation</dt><dd>{{ next.reserved ? `reserved · ${next.reservation_id || 'hold'}` : 'not reserved' }}</dd></div>
            <div><dt>State</dt><dd>Open</dd></div>
            <div><dt>Funding account</dt><dd>{{ next.account || 'Not named by the API' }}</dd></div>
          </dl>
          <RouterLink class="lw-ov-go" :to="rowLink('/treasury', `obligation:${next.obligation_id}`, body.snapshot_id)"
                      data-test="open-treasury">Open Treasury<span class="lw-visually-hidden">, {{ next.kind }} {{ next.obligation_id }}</span> →</RouterLink>
        </template>
        <template v-else>
          <div class="lw-figure lw-figure--small" data-test="no-obligation">No open obligation</div>
          <p class="lw-time">Nothing the observed snapshot records falls due from now.</p>
          <RouterLink class="lw-ov-go" :to="{ path: '/treasury', query: { snapshot: body.snapshot_id } }"
                      data-test="open-treasury">Obligations on Treasury →</RouterLink>
        </template>
      </section>

      <!-- O5 exposure preview -->
      <section class="lw-ov-exposure" aria-labelledby="ov-exposure" data-panel="Exposure preview" data-test="exposure">
        <h2 id="ov-exposure">World exposure</h2>
        <p class="lw-time">What the observed snapshot records around {{ body.company ? body.company.name : 'the treasury' }}.
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
          <span class="lw-tile__label">Lender capacity (K_p)</span>
          <span class="lw-figure lw-figure--small">{{ metricText(body.lender_capacity) }}</span>
          <RouterLink to="/lending">Its parts on Lending</RouterLink>
        </div>
        <RouterLink v-if="simulationTarget" class="lw-ov-go" :to="simulationTarget" data-test="explore-world">Explore world →</RouterLink>
        <p v-else class="lw-time" data-test="explore-why">{{ simulationWhy }}</p>
      </section>
    </div>

    <!-- O6 scenario entry -->
    <section class="lw-ov-scenario" aria-labelledby="ov-scenario" data-panel="Scenario entry" data-test="scenario">
      <span class="lw-ov-tag" data-test="hypothetical">Hypothetical</span>
      <div class="lw-ov-scenario__text">
        <h2 id="ov-scenario">{{ teaser }}</h2>
        <p class="lw-time">Rehearse it before it becomes a reserve breach. A scenario changes no observed
          figure on this page.</p>
      </div>
      <div class="lw-actions">
        <button type="button" class="lw-button lw-button--quiet" data-test="preview-scenario"
                :disabled="!body.scenario" :aria-expanded="preview ? 'true' : 'false'" aria-controls="scenario-preview"
                :aria-describedby="body.scenario ? undefined : 'preview-why'" @click="preview = !preview">
          {{ preview ? 'Hide scenario' : 'Preview scenario' }}
        </button>
        <span v-if="!body.scenario" id="preview-why" class="lw-time" data-test="preview-why">No prepared run, so no scenario to preview</span>
        <RouterLink v-if="simulationTarget" class="lw-button" :to="simulationTarget"
                    data-test="open-simulation">Open simulation</RouterLink>
        <template v-else>
          <button type="button" class="lw-button" disabled data-test="open-simulation"
                  aria-describedby="open-simulation-why">Open simulation</button>
          <span id="open-simulation-why" class="lw-time" data-test="open-simulation-why">{{ simulationWhy }}</span>
        </template>
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
import CashOutlook from '../components/CashOutlook.vue'
import {
  LABELS, STATES, ScreenShell, floorState, formatAmount, formatMoney, formatTime, freshness, getOverview,
  hoursFrom, metricStatus, metricText, modelSource, money, pendingFlows, routeExists, rowLink, staleOf,
  useReading
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

// --------------------------------------------------------------------------- O2 strip

const metrics = computed(() => {
  const b = state.body
  if (!b) return []
  const n = next.value
  return [
    { key: 'settled', label: 'Settled cash', figure: metricText(b.cash), fresh: metricStatus(b.cash) },
    { key: 'spendable', label: 'Spendable now (S)', figure: metricText(b.spendable), fresh: metricStatus(b.spendable) },
    n
      ? { key: 'next-due', label: `Next ${n.kind} due`, figure: money(n.amount), sub: `due ${hoursFrom(b.as_of, n.due_at)}`, subTest: 'next-due-at', fresh: `● ${n.reserved ? 'Reserved' : 'Not reserved'}` }
      : { key: 'next-due', label: 'Next obligation', figure: 'None open', fresh: 'Nothing falls due' },
    { key: 'coverage', label: 'Reserve headroom', figure: metricText(b.coverage.headroom), fresh: metricStatus(b.coverage.headroom) }
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
        title: 'Settled cash',
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
        title: 'Spendable now (S)',
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
          { key: 'due', text: `due ${t.utc} · ${t.local} · ${hoursFrom(b.as_of, n.due_at)} from as of` },
          { key: 'res', text: n.reserved ? `reserved by ${n.reservation_id || 'a hold'}` : 'not reserved' },
          { key: 'acct', text: `paid from ${n.account || 'an account the API does not name'}`, to: rowLink('/treasury', `obligation:${n.obligation_id}`, b.snapshot_id), link: 'Open on Treasury' }
        ],
        result: money(n.amount)
      }
    }
    case 'coverage': {
      const cov = b.coverage
      return {
        title: 'Reserve headroom',
        rule: 'Headroom = lowest projected cash P over the horizon − reserve floor; the floor is kept at zero or more.',
        lines: [
          { key: 'min', text: `lowest P ${metricText(cov.min_projected)}${cov.at ? ` at ${formatTime(cov.at).utc} (${hoursFrom(b.as_of, cov.at)})` : ''}` },
          { key: 'floor', text: `reserve floor ${metricText(cov.floor)}` },
          ...accounts.map((a) => ({ key: a.id, text: `P by account: ${a.id}`, to: toAccount(a), link: 'Open on Treasury' }))
        ],
        result: `${metricText(cov.headroom)} · ${STATES[floor.value].word}`
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
  if (f) return `What if the ${money(f.amount)} ${f.kind.replace(/_/g, ' ')} arrives late?`
  const s = state.body?.scenario
  return s ? `What if: ${s.family.replace(/-/g, ' ')}?` : 'What if a payment arrives late?'
})
const delayed = computed(() => {
  const f = scenarioFlow.value
  const hours = state.body?.scenario?.params?.delay_h
  if (!f || !Number.isInteger(hours)) return ''
  const from = hoursFrom(state.body.as_of, f.expected_at)
  return `${f.flow_id} expected ${from}, delayed ${hours} h`
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

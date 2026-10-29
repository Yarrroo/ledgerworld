<template>
  <ScreenShell v-slot="{ body }" title="Treasury" :reading="state" :refresh="refresh">
    <p class="lw-source">
      Which funds can we use, and when. Spendable now (S) and projected cash (P) are separate
      measures; the reserve floor is checked on P. Every figure is one account's, in its own currency.
    </p>

    <p v-if="moved" class="lw-note" role="status" data-test="snapshot-moved">
      The link was made on snapshot {{ moved }}; this is snapshot {{ body.snapshot_id }}.
    </p>

    <section class="lw-tre__accounts" aria-labelledby="accounts-heading" data-panel="Accounts" data-test="accounts">
      <h2 id="accounts-heading">Account</h2>
      <p v-if="!accounts.length" class="lw-note" data-test="no-accounts">
        The API returned no treasury cash account for {{ body.snapshot_id }}: nothing to show.
      </p>
      <div v-else class="lw-tre__choices" role="radiogroup" aria-labelledby="accounts-heading" data-test="account-selector">
        <label v-for="a in accounts" :key="a.id" class="lw-tre__choice"
               :class="{ 'is-selected': a.id === account?.id, 'lw-row--focus': focus === `account:${a.id}` }"
               :data-test="`account-${a.id}`" :data-focus="`account:${a.id}`" tabindex="-1">
          <input type="radio" name="treasury-account" :value="a.id" :checked="a.id === account?.id"
                 @change="chosen = a.id">
          <span class="lw-tre__choice-id">{{ a.id }}</span>
          <span class="lw-time">{{ a.currency }} · {{ a.observability === 'known' ? 'observed' : 'balance not observable' }}
            · as of {{ formatTime(a.as_of).utc }}</span>
        </label>
      </div>
      <p v-if="currencies > 1" class="lw-time" data-test="mixed">
        These accounts hold {{ currencies }} currencies; no figure here adds them together.
      </p>
    </section>

    <div v-if="account" class="lw-tre" :data-account="account.id">
      <!-- T3: the answer first on every width -->
      <section class="lw-tre__answer" aria-labelledby="spend-heading" data-panel="Spendable now">
        <h2 id="spend-heading">Spendable now (S)</h2>
        <article class="lw-tile" data-test="spendable">
          <div class="lw-tile__label">{{ account.id }} · {{ account.currency }}</div>
          <div class="lw-figure">{{ metricText(account.spendable) }}</div>
          <div class="lw-time">authority {{ account.authority }} · as of {{ formatTime(account.spendable.as_of || account.as_of).utc }}</div>
          <p v-if="account.observability !== 'known'" class="lw-note">
            Balance not observable: settled reads Unknown and adds nothing; authority is reduced.
          </p>
          <details class="lw-calc" data-test="spend-calc">
            <summary>View calculation</summary>
            <div class="lw-calc__body" data-test="spend-calculation">
              <p>S(now) in {{ account.currency }}, terms from the API's buckets:</p>
              <p>{{ spend.line }}</p>
              <p v-if="spend.excluded">{{ spend.excluded }}</p>
              <p>S = settled − reserved − pledged − pending out due by now + pending in arrived by now.
                The result is the API's; this screen does not recompute it.</p>
            </div>
          </details>
        </article>
      </section>

      <!-- T2 + T4: the account's data -->
      <div class="lw-tre__main">
        <section aria-labelledby="buckets-heading" data-panel="Cash buckets" data-test="buckets">
          <h2 id="buckets-heading">Cash buckets</h2>
          <ul class="lw-tre__buckets">
            <li v-for="b in buckets" :key="b.key" :data-test="`bucket-${b.key}`">
              <details class="lw-tre__bucket">
                <summary>
                  <span class="lw-tre__bucket-name">{{ b.label }}</span>
                  <span class="lw-tre__bucket-value">{{ b.value }}</span>
                </summary>
                <dl class="lw-tre__inputs" data-test="bucket-inputs">
                  <dt>Input</dt><dd>{{ b.input }}</dd>
                  <dt>Account</dt><dd>{{ account.id }} ({{ account.currency }})</dd>
                  <dt>Source</dt><dd>ledger bucket, GET /api/v1/treasury</dd>
                  <dt>Source time</dt><dd>{{ formatTime(account.as_of).utc }}</dd>
                  <template v-if="b.note"><dt>Note</dt><dd>{{ b.note }}</dd></template>
                </dl>
              </details>
            </li>
          </ul>
        </section>

        <section aria-labelledby="rows-heading" data-panel="Obligations and arrivals">
          <h2 id="rows-heading">Obligations and arrivals</h2>
          <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Obligations and arrivals">
            <table class="lw-table lw-tre__rows" data-test="obligations">
              <thead>
                <tr><th scope="col">Item</th><th scope="col">Direction</th><th scope="col">Amount</th>
                  <th scope="col">When (UTC)</th><th scope="col">Reservation</th><th scope="col">Status</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in rows" :key="r.key" :data-row="r.id" :data-test="r.obligation ? `obligation-${r.id}` : undefined"
                    :data-focus="r.obligation ? `obligation:${r.id}` : `flow:${r.id}`" tabindex="-1"
                    :class="{ 'is-open': r.key === openRow, 'lw-row--focus': focus === (r.obligation ? `obligation:${r.id}` : `flow:${r.id}`) }">
                  <td data-label="Item">
                    <button type="button" class="lw-tre__open" :data-test="`row-${r.id}`" @click="openRow = r.key">
                      {{ r.kind }} · {{ r.id }}{{ r.mandatory ? ' · mandatory' : '' }}
                    </button>
                  </td>
                  <td data-label="Direction">{{ r.direction }}</td>
                  <td data-label="Amount" class="lw-num">{{ money(r.amount) }}</td>
                  <td data-label="When">{{ formatTime(r.at).utc }} ({{ hoursFrom(body.as_of, r.at) }})</td>
                  <td data-label="Reservation">{{ r.reservation || 'not reserved' }}</td>
                  <td data-label="Status">{{ r.status }}</td>
                </tr>
                <tr v-if="!rows.length"><td colspan="6">No obligation or pending flow on {{ account.id }}</td></tr>
              </tbody>
            </table>
          </div>
          <p class="lw-time">t is whole hours from the snapshot's as of; deadlines are simulated time. A row opens its details; it is not a payment action.</p>
        </section>
      </div>

      <!-- T5 + T6: the coverage inspector -->
      <div class="lw-tre__inspector">
        <section aria-labelledby="cover-heading" data-panel="Reserve coverage" data-test="coverage">
          <h2 id="cover-heading">Reserve coverage on P</h2>
          <article class="lw-tile" data-test="floor">
            <div class="lw-tile__label">Projected cash P, not spendable now</div>
            <div :class="['lw-status', `lw-status--${STATES[account.floorCheck.state].tone}`]" data-test="floor-status">
              <span aria-hidden="true">{{ STATES[account.floorCheck.state].icon }}</span>
              <span>{{ STATES[account.floorCheck.state].word }}</span>
            </div>
            <div v-if="account.floorCheck.state === 'breached'" class="lw-figure" data-test="shortfall">
              {{ formatMoney(-account.floorCheck.gap, account.currency) }} at {{ hoursFrom(body.as_of, account.low.t) }}
            </div>
            <div v-else-if="account.low" class="lw-figure lw-figure--small" data-test="minimum">
              lowest {{ metricText(account.low.value) }} at {{ hoursFrom(body.as_of, account.low.t) }}
            </div>
            <div class="lw-time" data-test="floor-line">
              floor {{ account.floor ? metricText(account.floor) : 'Not assessed' }}<template
                v-if="account.floorCheck.state === 'kept'"> · headroom {{ formatMoney(account.floorCheck.gap, account.currency) }}</template>
            </div>
            <details v-if="account.low" class="lw-calc">
              <summary>How the minimum is calculated</summary>
              <div class="lw-calc__body" data-test="calculation">
                <p>P({{ hoursFrom(body.as_of, account.low.t) }}) in {{ account.currency }}, terms from the API:</p>
                <p>{{ account.calc.line }}</p>
                <p v-if="account.calc.excluded">{{ account.calc.excluded }}</p>
                <p>P counts settled cash, arrivals and outflows due by t, and every obligation due by
                  t whether reserved or not. Result as served by the API.</p>
              </div>
            </details>
          </article>

          <CashChart :points="account.projected" :as-of="body.as_of" :floor="account.floor" :selected="pointT"
                     :label="`Projected cash P of ${account.id} against its reserve floor`" @select="pointT = $event" />
          <p class="lw-tre__point" role="status" aria-live="polite" data-test="point-calculation">
            <template v-if="point">
              <strong>{{ hoursFrom(body.as_of, point.t) }} · {{ formatTime(point.t).utc }}:</strong>
              {{ pointCalc.line }}<template v-if="pointCalc.excluded"> · {{ pointCalc.excluded }}</template>
            </template>
          </p>

          <div class="lw-table-wrap" tabindex="0" role="region" :aria-label="`Projected cash, ${account.id}`">
            <table class="lw-table" data-test="timeline">
              <caption class="lw-visually-hidden">Projected cash at each flow or deadline, against the reserve floor; the chart draws these points</caption>
              <thead><tr><th scope="col">t</th><th scope="col">UTC</th><th scope="col">P</th><th scope="col">Against the floor</th></tr></thead>
              <tbody>
                <tr v-for="p in account.points" :key="p.t" :class="{ 'lw-row--floor': p.lowest, 'is-selected': p.t === pointT }">
                  <td>
                    <button type="button" class="lw-tre__open" :aria-pressed="p.t === pointT ? 'true' : 'false'"
                            data-test="timeline-point" @click="pointT = p.t">{{ hoursFrom(body.as_of, p.t) }}</button>
                  </td>
                  <td>{{ formatTime(p.t).utc }}</td>
                  <td class="lw-num">{{ metricText(p.value) }}</td>
                  <td>{{ p.against }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section aria-labelledby="handoff-heading" data-panel="Scenario handoff">
          <h2 id="handoff-heading">Rehearse a cash shock</h2>
          <p class="lw-time">Opens the prepared run in Live simulation with {{ account.id }} and snapshot
            {{ body.snapshot_id }}. It changes no observed figure here.</p>
          <div class="lw-actions">
            <RouterLink v-if="rehearse" class="lw-button" :to="rehearse" data-test="rehearse">Rehearse a cash shock</RouterLink>
            <template v-else>
              <button type="button" class="lw-button" disabled aria-describedby="rehearse-why" data-test="rehearse">
                Rehearse a cash shock
              </button>
              <span id="rehearse-why" class="lw-time" data-test="rehearse-why">{{ rehearseWhy }}</span>
            </template>
          </div>
        </section>
      </div>
    </div>

    <DetailSheet :open="Boolean(detail)" :title="detail ? `${detail.kind} · ${detail.id}` : 'Details'" test="row-detail"
                 @close="openRow = null">
      <template v-if="detail">
        <dl>
          <dt>Kind</dt><dd>{{ detail.what }}</dd>
          <dt>Amount</dt><dd>{{ money(detail.amount) }} · {{ detail.direction }}</dd>
          <dt>{{ detail.obligation ? 'Deadline' : 'Expected' }}</dt>
          <dd>{{ formatTime(detail.at).utc }} · {{ formatTime(detail.at).local }} · {{ hoursFrom(body?.as_of, detail.at) }}</dd>
          <dt>Reservation</dt><dd>{{ detail.reservation || 'not reserved' }}</dd>
          <dt>Account</dt><dd>{{ account?.id }}</dd>
          <dt>Source</dt><dd>{{ detail.source }}</dd>
          <dt>Current state</dt><dd data-test="row-state">{{ detail.status }}</dd>
        </dl>
        <p class="lw-time">Read-only: this screen makes no payment, edit or import.</p>
      </template>
    </DetailSheet>
  </ScreenShell>
</template>

<script setup>
/**
 * Treasury (handoff T1–T6). One account is selected at a time and every panel shows that
 * account: its buckets, its spendable S, its obligations and arrivals, and its projected cash P
 * against its floor, drawn and tabulated from the same API points. Nothing is summed across
 * accounts, so mixed currencies never meet. The scenario handoff reads the prepared run from the
 * overview of the same context; without one it names the prerequisite.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import CashChart from '../components/CashChart.vue'
import DetailSheet from '../components/DetailSheet.vue'
import {
  STATES, ScreenShell, againstFloor, contextKey, formatAmount, formatMoney, formatTime, getOverview,
  getTreasury, hoursFrom, metricText, money, pendingFlows, projectionTerms, routeExists, useFocusTarget,
  useReading
} from '../api/v1.js'

const route = useRoute()
const router = useRouter()

/** The treasury read, and the prepared run of the same context when the overview answers. */
async function load () {
  const [treasury, overview] = await Promise.all([
    getTreasury(),
    getOverview().catch((error) => ({ error }))
  ])
  let demo = { run_id: null, why: 'Could not read the prepared run from the overview; Refresh' }
  if (!overview.error) {
    demo = contextKey(overview) === contextKey(treasury)
      ? { run_id: overview.demo?.run_id ?? null, why: 'No demonstration run is prepared: prepare one with the operator command first' }
      : { run_id: null, why: 'The overview answered for another snapshot or mode; Refresh' }
  }
  return { ...treasury, demo }
}

const { state, refresh } = useReading(load)
// a deep link (Overview's cash, spendable, next obligation) names an account or an obligation row
const { focus, moved } = useFocusTarget(state)

/** The account's lowest API point P, first reached; null when any point has no value. */
function lowest (projected) {
  if (!projected.length || projected.some((p) => p.value.minor === null)) return null
  return projected.reduce((low, p) => (p.value.minor < low.value.minor ? p : low))
}

function againstText (value, floorMetric) {
  const { state: s, gap } = againstFloor(value, floorMetric)
  if (s === 'kept') return `✓ floor kept, ${formatMoney(gap, floorMetric.currency)} above`
  if (s === 'breached') return `✕ below floor, short ${formatMoney(-gap, floorMetric.currency)}`
  return s === 'unassessed' ? 'No floor assessed' : 'Unknown'
}

const accounts = computed(() => {
  const body = state.body
  if (!body) return []
  return body.accounts.map((a) => {
    const low = lowest(a.projected)
    return {
      ...a,
      low,
      floorCheck: againstFloor(low?.value, a.floor),
      points: a.projected.map((p) => ({
        ...p, lowest: p === low, against: againstText(p.value, a.floor)
      })),
      calc: low ? projectionTerms(a, low.t, body.obligations, body.as_of) : null
    }
  })
})
const currencies = computed(() => new Set(accounts.value.map((a) => a.currency)).size)

// T1: the operating account by default, or the one the URL names (?account=, or a deep link to
// an account or to an obligation, which selects the account the obligation is on); a reload
// keeps the choice.
function linked () {
  const q = route.query
  if (typeof q.account === 'string') return q.account
  const f = typeof q.focus === 'string' ? q.focus : ''
  if (f.startsWith('account:')) return f.slice('account:'.length)
  if (f.startsWith('obligation:')) {
    const id = f.slice('obligation:'.length)
    return state.body?.obligations.find((o) => o.obligation_id === id)?.account ?? null
  }
  return null
}
const chosen = ref(null)
watch(() => [state.status, route.query.focus, route.query.account], () => {
  if (state.status === 'loaded' && linked()) chosen.value = linked()
}, { immediate: true })
const account = computed(() => {
  const list = accounts.value
  return list.find((a) => a.id === chosen.value) ??
    list.find((a) => a.id.endsWith('/operating')) ?? list[0] ?? null
})

// T5: the instant whose terms are shown; the account's lowest point until one is chosen.
const pointT = ref(null)
watch(() => account.value?.id, () => { pointT.value = null; openRow.value = null })
const point = computed(() => {
  const a = account.value
  if (!a) return null
  return a.projected.find((p) => p.t === pointT.value) ?? a.low ?? a.projected[0] ?? null
})
const pointCalc = computed(() => (point.value
  ? projectionTerms(account.value, point.value.t, state.body.obligations, state.body.as_of)
  : null))

/** S's terms beside the API's own S: buckets now, and the flows that are not yet due named. */
const spend = computed(() => {
  const a = account.value
  const c = a.currency
  const now = Date.parse(state.body.as_of)
  const b = a.buckets
  const terms = [b.settled ? `${formatAmount(b.settled.minor, c)} settled` : 'Unknown settled',
    `- ${formatAmount(b.reserved.minor, c)} reserved`, `- ${formatAmount(b.pledged.minor, c)} pledged`]
  const later = []
  for (const f of pendingFlows(a)) {
    const sign = f.direction === 'in' ? '+' : '-'
    if (Date.parse(f.expected_at) <= now) terms.push(`${sign} ${formatAmount(f.amount.minor, c)} ${f.kind}`)
    else later.push(`${f.kind} ${f.flow_id} ${f.direction} (expected ${hoursFrom(state.body.as_of, f.expected_at)})`)
  }
  return {
    line: `${terms.join(' ')} = ${metricText(a.spendable)} (API)`,
    excluded: later.length ? `not yet due, so not in S: ${later.join(', ')}` : ''
  }
})

const flowList = (flows) => (flows.length
  ? flows.map((f) => `${money(f.amount)} ${f.kind} (${hoursFrom(state.body.as_of, f.expected_at)})`).join('; ')
  : 'None pending')

// T2: the ledger's buckets; pending inflows are expected, never settled.
const buckets = computed(() => {
  const a = account.value
  const b = a.buckets
  return [
    { key: 'settled', label: 'Settled', value: b.settled ? money(b.settled) : 'Unknown',
      input: 'settled balance', note: b.settled ? '' : 'Balance not observable: Unknown has no numeric value and adds nothing' },
    { key: 'reserved', label: 'Reserved', value: money(b.reserved), input: 'reservations held against obligations' },
    { key: 'pledged', label: 'Pledged', value: money(b.pledged), input: 'balances pledged as collateral' },
    { key: 'pending-out', label: 'Pending out', value: flowList(b.pending_out), input: 'outflows not yet settled' },
    { key: 'pending-in', label: 'Pending in, expected', value: flowList(b.pending_in),
      input: 'arrivals not yet settled', note: 'Expected, not settled: never counted in S before it arrives' }
  ]
})

// T4: the account's arrivals, outflows and obligations, in time order.
const rows = computed(() => {
  const a = account.value
  if (!a) return []
  const flows = pendingFlows(a).map((f) => ({
    key: `flow:${f.flow_id}`, id: f.flow_id, kind: f.kind, what: `pending ${f.direction === 'in' ? 'arrival' : 'outflow'}`,
    direction: f.direction, amount: f.amount, at: f.expected_at, reservation: f.reservation_id,
    status: f.direction === 'in' ? 'expected, not settled' : 'pending, not settled',
    source: 'ledger pending flow, GET /api/v1/treasury', obligation: false, mandatory: false
  }))
  const owed = state.body.obligations.filter((o) => o.account === a.id).map((o) => ({
    key: `obligation:${o.obligation_id}`, id: o.obligation_id, kind: o.kind, what: 'obligation',
    direction: 'out', amount: o.amount, at: o.due_at, reservation: o.reservation_id,
    status: o.state || 'open', source: 'ledger obligation, GET /api/v1/treasury', obligation: true,
    mandatory: o.mandatory !== false
  }))
  return [...flows, ...owed].sort((x, y) => Date.parse(x.at) - Date.parse(y.at))
})
const openRow = ref(null)
const detail = computed(() => rows.value.find((r) => r.key === openRow.value) ?? null)

// T6: the prepared run, carrying the account and snapshot.
const rehearse = computed(() => {
  const body = state.body
  if (state.status !== 'loaded' || !body.demo.run_id || !routeExists(router, '/simulation')) return null
  return { path: '/simulation', query: { run_id: body.demo.run_id, account: account.value.id, snapshot: body.snapshot_id } }
})
const rehearseWhy = computed(() => {
  if (state.status === 'loading') return 'Loading'
  if (state.status === 'error') return 'Last loaded, not current; Refresh first'
  if (!state.body.demo.run_id) return state.body.demo.why
  return 'The simulation screen is not part of this build'
})
</script>

<style scoped>
.lw-tre__choices {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-3);
}

.lw-tre__choice {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: var(--lw-space-2);
  align-items: center;
  min-height: var(--lw-target);
  padding: var(--lw-space-2) var(--lw-space-4);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  cursor: pointer;
  min-width: 0;
}

.lw-tre__choice input { width: 20px; height: 20px; margin: 0; accent-color: var(--lw-brand); }
.lw-tre__choice .lw-time { grid-column: 2; }
.lw-tre__choice.is-selected { background: var(--lw-selected); border-color: var(--lw-brand); }
.lw-tre__choice:focus-within { outline: 3px solid var(--lw-focus); outline-offset: 2px; }
.lw-tre__choice-id { font-weight: 700; overflow-wrap: anywhere; }

.lw-tre {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--lw-space-6);
  margin-top: var(--lw-space-6);
}

@media (min-width: 1200px) {
  .lw-tre {
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    grid-template-areas: 'main answer' 'main inspector';
    grid-template-rows: auto 1fr;
    align-items: start;
  }

  .lw-tre__answer { grid-area: answer; }
  .lw-tre__main { grid-area: main; }
  .lw-tre__inspector { grid-area: inspector; }
}

.lw-tre__main,
.lw-tre__inspector {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--lw-space-6);
  min-width: 0;
}

.lw-tre > *,
.lw-tre__main > *,
.lw-tre__inspector > * { min-width: 0; }

.lw-tre__buckets {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--lw-rule);
}

.lw-tre__buckets li { border-bottom: 1px solid var(--lw-rule); }

.lw-tre__bucket summary {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--lw-space-2) var(--lw-space-4);
  align-items: center;
  min-height: var(--lw-target);
  padding: var(--lw-space-2) 0;
  cursor: pointer;
}

.lw-tre__bucket-name { font-weight: 600; }
.lw-tre__bucket-value { font-variant-numeric: tabular-nums; text-align: right; overflow-wrap: anywhere; }

.lw-tre__inputs {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  gap: var(--lw-space-1) var(--lw-space-4);
  margin: 0 0 var(--lw-space-3);
  font-size: 14px;
}

.lw-tre__inputs dt { color: var(--lw-ink-muted); }
.lw-tre__inputs dd { margin: 0; overflow-wrap: anywhere; }

.lw-tre__open {
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

.lw-tre__rows tr.is-open td,
.lw-table tr.is-selected td { background: var(--lw-selected); }

.lw-tre__point {
  min-height: 1.5em;
  margin: var(--lw-space-2) 0 var(--lw-space-3);
  font-size: 14px;
  overflow-wrap: anywhere;
}

/* Phone: obligations and arrivals as labelled stacked rows; amount, status and deadline stay. */
@media (max-width: 767px) {
  .lw-tre__rows thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .lw-tre__rows,
  .lw-tre__rows tbody,
  .lw-tre__rows tr,
  .lw-tre__rows td { display: block; }
  .lw-tre__rows tr { padding: var(--lw-space-2) 0; border-bottom: 1px solid var(--lw-rule); }

  .lw-tre__rows td {
    display: flex;
    justify-content: space-between;
    gap: var(--lw-space-3);
    border: 0;
    padding: var(--lw-space-1) var(--lw-space-3);
    white-space: normal;
    text-align: right;
    overflow-wrap: anywhere;
  }

  .lw-tre__rows td::before {
    content: attr(data-label);
    color: var(--lw-ink-muted);
    font-size: 13px;
    text-align: left;
  }

  .lw-tre__rows td[data-label='Item']::before { content: none; }
}
</style>

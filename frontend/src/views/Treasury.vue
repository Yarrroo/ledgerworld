<template>
  <ScreenShell title="Treasury" :body="body" :busy="state.status === 'loading'" :refresh="refresh">
    <p class="lw-source">
      Cash by account and bucket, deadlines and reservations. Spendable now (S) and projected
      cash (P) are separate measures; the reserve floor is checked on P.
    </p>

    <div v-if="state.error" class="lw-alert" role="alert" data-test="error">
      <strong>{{ STATES.error.icon }} {{ body ? STATES.error.word : 'Could not load' }}.</strong>
      {{ state.error.message }}
      <button type="button" class="lw-button lw-button--quiet" @click="refresh">Retry</button>
    </div>
    <p v-if="state.contextChanged" class="lw-note" role="status" data-test="context-changed">
      The provider mode or snapshot changed; every figure below was reloaded for
      {{ LABELS[body.mode] || body.mode }}, snapshot {{ body.snapshot_id }}.
    </p>

    <div v-if="!body" class="lw-strip">
      <article class="lw-tile"><span class="lw-skeleton" aria-label="Loading" /></article>
    </div>

    <section v-for="a in accounts" :key="a.id" :aria-label="`Account ${a.id}`"
             :data-test="`account-${a.id}`">
      <h2>{{ a.id }} · {{ a.currency }}</h2>
      <p v-if="a.observability !== 'known'" class="lw-note">
        Balance not observable: settled reads Unknown and adds nothing; authority is reduced.
      </p>

      <div class="lw-strip">
        <article class="lw-tile" data-test="floor">
          <div class="lw-tile__label">Reserve floor on P</div>
          <div :class="['lw-status', `lw-status--${STATES[a.floorState].tone}`]" data-test="floor-status">
            <span aria-hidden="true">{{ STATES[a.floorState].icon }}</span>
            <span>{{ STATES[a.floorState].word }}</span>
          </div>
          <div v-if="a.short" class="lw-figure" data-test="shortfall">
            {{ formatMoney(a.short.minor, a.currency) }} at {{ a.short.t }}
          </div>
          <div v-else-if="a.low" class="lw-figure lw-figure--small">
            lowest {{ metricText(a.low.value) }} at {{ hoursFrom(body.as_of, a.low.t) }}
          </div>
          <div class="lw-time">floor {{ metricText(a.floor) }}</div>
          <details v-if="a.low" class="lw-calc">
            <summary>How this is calculated</summary>
            <div class="lw-calc__body" data-test="calculation">
              <p>P({{ hoursFrom(body.as_of, a.low.t) }}) in {{ a.currency }}, terms from the API:</p>
              <p>{{ a.calc.line }}</p>
              <p v-if="a.calc.excluded">{{ a.calc.excluded }}</p>
              <p>P counts settled cash, arrivals and outflows due by t, and every obligation due by
                t whether reserved or not. Result as served by the API.</p>
            </div>
          </details>
        </article>

        <article class="lw-tile" data-test="spendable">
          <div class="lw-tile__label">Spendable now (S)</div>
          <div class="lw-figure">{{ metricText(a.spendable) }}</div>
          <div class="lw-time">authority {{ a.authority }}</div>
        </article>

        <article class="lw-tile" data-test="settled">
          <div class="lw-tile__label">Settled</div>
          <div class="lw-figure">
            {{ a.buckets.settled ? formatMoney(a.buckets.settled.minor, a.currency) : 'Unknown' }}
          </div>
          <div class="lw-time">
            reserved {{ formatMoney(a.buckets.reserved.minor, a.currency) }} ·
            pledged {{ formatMoney(a.buckets.pledged.minor, a.currency) }}
          </div>
          <div class="lw-time">as of {{ formatTime(a.as_of).utc }}</div>
        </article>
      </div>

      <h2>Projected cash P and the floor</h2>
      <div class="lw-table-wrap" tabindex="0" role="region" :aria-label="`Projected cash, ${a.id}`">
        <table class="lw-table" data-test="timeline">
          <caption class="lw-visually-hidden">Projected cash at each flow or deadline, against the reserve floor</caption>
          <thead><tr><th scope="col">t</th><th scope="col">UTC</th><th scope="col">P</th><th scope="col">Against the floor</th></tr></thead>
          <tbody>
            <tr v-for="p in a.projected" :key="p.t" :class="{ 'lw-row--floor': a.short && p.t === a.low.t }">
              <td>{{ hoursFrom(body.as_of, p.t) }}</td>
              <td>{{ formatTime(p.t).utc }}</td>
              <td class="lw-num">{{ metricText(p.value) }}</td>
              <td>{{ againstFloor(p.value, a.floor) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>Pending flows</h2>
      <div class="lw-table-wrap" tabindex="0" role="region" :aria-label="`Pending flows, ${a.id}`">
        <table class="lw-table" data-test="flows">
          <thead><tr><th scope="col">Flow</th><th scope="col">Direction</th><th scope="col">Amount</th><th scope="col">Expected</th></tr></thead>
          <tbody>
            <tr v-for="f in a.flows" :key="f.flow_id">
              <td>{{ f.kind }} · {{ f.flow_id }}</td>
              <td>{{ f.direction }}</td>
              <td class="lw-num">{{ formatMoney(f.amount.minor, f.amount.currency) }}</td>
              <td>{{ formatTime(f.expected_at).utc }} ({{ hoursFrom(body.as_of, f.expected_at) }})</td>
            </tr>
            <tr v-if="!a.flows.length"><td colspan="4">No pending flows</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <template v-if="body">
      <h2>Obligations and reservations</h2>
      <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Obligations">
        <table class="lw-table" data-test="obligations">
          <thead>
            <tr><th scope="col">Obligation</th><th scope="col">Amount</th><th scope="col">Due (UTC)</th>
              <th scope="col">Due (local)</th><th scope="col">Reservation</th><th scope="col">State</th></tr>
          </thead>
          <tbody>
            <tr v-for="o in body.obligations" :key="o.obligation_id">
              <td>{{ o.kind }} · {{ o.obligation_id }}{{ o.mandatory === false ? '' : ' · mandatory' }}</td>
              <td class="lw-num">{{ formatMoney(o.amount.minor, o.amount.currency) }}</td>
              <td>{{ formatTime(o.due_at).utc }} ({{ hoursFrom(body.as_of, o.due_at) }})</td>
              <td>{{ formatTime(o.due_at).local }}</td>
              <td>{{ o.reservation_id || 'not reserved' }}</td>
              <td>{{ o.state || 'open' }}</td>
            </tr>
            <tr v-if="!body.obligations.length"><td colspan="6">No obligations</td></tr>
          </tbody>
        </table>
      </div>
      <p class="lw-time">t is whole hours from the snapshot's as of; deadlines are simulated time.</p>
    </template>
  </ScreenShell>
</template>

<script setup>
import { computed } from 'vue'
import {
  LABELS, STATES, ScreenShell, formatAmount, formatMoney, formatTime, getTreasury, hoursFrom,
  metricText, useReading
} from '../api/v1.js'

const { state, refresh } = useReading(() => getTreasury())
const body = computed(() => state.body)

const due = (iso, t) => Date.parse(iso) <= Date.parse(t)

/** The account's lowest API point P, first reached; null when any point is not a value. */
function lowest (projected) {
  if (!projected.length || projected.some((p) => p.value.minor === null)) return null
  return projected.reduce((low, p) => (p.value.minor < low.value.minor ? p : low))
}

/** The API's terms of P at ``t``, shown beside the API's result; nothing is summed here. */
function calculation (a, t, obligations, asOf) {
  const c = a.currency
  const terms = [a.buckets.settled ? `${formatAmount(a.buckets.settled.minor, c)} settled` : 'Unknown settled']
  const excluded = []
  const take = (flows, sign, direction) => {
    for (const f of flows) {
      if (due(f.expected_at, t)) terms.push(`${sign} ${formatAmount(f.amount.minor, c)} ${f.kind}`)
      else excluded.push(`${f.kind} ${f.flow_id} ${direction} (expected ${hoursFrom(asOf, f.expected_at)})`)
    }
  }
  take(a.buckets.pending_in, '+', 'in')
  take(a.buckets.pending_out, '-', 'out')
  for (const o of obligations) {
    if (due(o.due_at, t)) terms.push(`- ${formatAmount(o.amount.minor, c)} ${o.kind}`)
  }
  const result = a.projected.find((p) => p.t === t).value
  const value = result.minor === null ? metricText(result) : formatAmount(result.minor, c)
  return {
    line: `${terms.join(' ')} = ${value}`,
    excluded: excluded.length ? `excluded at ${hoursFrom(asOf, t)}: ${excluded.join(', ')}` : ''
  }
}

const accounts = computed(() => {
  if (!body.value) return []
  const asOf = body.value.as_of
  return body.value.accounts.map((a) => {
    const obligations = body.value.obligations.filter(
      (o) => o.account === a.id && (o.state ?? 'open') === 'open')
    const low = lowest(a.projected)
    let floorState = 'unassessed'
    let short = null
    if (a.floor && a.floor.status !== 'unassessed') {
      if (!low) floorState = 'unknown'
      else if (low.value.minor >= a.floor.minor) floorState = 'kept'
      else {
        floorState = 'breached'
        short = { minor: a.floor.minor - low.value.minor, t: hoursFrom(asOf, low.t) }
      }
    }
    const flows = [
      ...a.buckets.pending_in.map((f) => ({ ...f, direction: 'in' })),
      ...a.buckets.pending_out.map((f) => ({ ...f, direction: 'out' }))
    ].sort((x, y) => Date.parse(x.expected_at) - Date.parse(y.expected_at))
    return {
      ...a, low, short, floorState, flows,
      calc: low ? calculation(a, low.t, obligations, asOf) : null
    }
  })
})

function againstFloor (value, floor) {
  if (!floor || floor.minor === null) return 'No floor assessed'
  if (value.minor === null) return metricText(value)
  const gap = value.minor - floor.minor
  return gap >= 0
    ? `✓ floor kept, ${formatMoney(gap, floor.currency)} above`
    : `✕ below floor, short ${formatMoney(-gap, floor.currency)}`
}
</script>

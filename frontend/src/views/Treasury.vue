<template>
  <ScreenShell v-slot="{ body }" title="Treasury" :reading="state" :refresh="refresh">
    <p class="lw-source">
      Cash by account and bucket, deadlines and reservations. Spendable now (S) and projected
      cash (P) are separate measures; the reserve floor is checked on P.
    </p>

    <section v-for="a in accounts" :key="a.id" :aria-label="`Account ${a.id}`"
             :data-test="`account-${a.id}`">
      <h2>{{ a.id }} · {{ a.currency }}</h2>
      <p v-if="a.observability !== 'known'" class="lw-note">
        Balance not observable: settled reads Unknown and adds nothing; authority is reduced.
      </p>

      <div class="lw-strip">
        <article class="lw-tile" data-test="floor">
          <div class="lw-tile__label">Reserve floor on P</div>
          <div :class="['lw-status', `lw-status--${STATES[a.floorCheck.state].tone}`]" data-test="floor-status">
            <span aria-hidden="true">{{ STATES[a.floorCheck.state].icon }}</span>
            <span>{{ STATES[a.floorCheck.state].word }}</span>
          </div>
          <div v-if="a.floorCheck.state === 'breached'" class="lw-figure" data-test="shortfall">
            {{ formatMoney(-a.floorCheck.gap, a.currency) }} at {{ hoursFrom(body.as_of, a.low.t) }}
          </div>
          <div v-else-if="a.low" class="lw-figure lw-figure--small">
            lowest {{ metricText(a.low.value) }} at {{ hoursFrom(body.as_of, a.low.t) }}
          </div>
          <div class="lw-time">floor {{ a.floor ? metricText(a.floor) : 'Not assessed' }}</div>
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
          <div class="lw-figure">{{ a.buckets.settled ? money(a.buckets.settled) : 'Unknown' }}</div>
          <div class="lw-time">
            reserved {{ money(a.buckets.reserved) }} · pledged {{ money(a.buckets.pledged) }}
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
            <tr v-for="p in a.points" :key="p.t" :class="{ 'lw-row--floor': p.lowest }">
              <td>{{ hoursFrom(body.as_of, p.t) }}</td>
              <td>{{ formatTime(p.t).utc }}</td>
              <td class="lw-num">{{ metricText(p.value) }}</td>
              <td>{{ p.against }}</td>
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
              <td class="lw-num">{{ money(f.amount) }}</td>
              <td>{{ formatTime(f.expected_at).utc }} ({{ hoursFrom(body.as_of, f.expected_at) }})</td>
            </tr>
            <tr v-if="!a.flows.length"><td colspan="4">No pending flows</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <h2>Obligations and reservations</h2>
    <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Obligations">
      <table class="lw-table" data-test="obligations">
        <thead>
          <tr><th scope="col">Obligation</th><th scope="col">Amount</th><th scope="col">Due (UTC)</th>
            <th scope="col">Due (local)</th><th scope="col">Reservation</th><th scope="col">State</th></tr>
        </thead>
        <tbody>
          <tr v-for="o in obligations" :key="o.obligation_id">
            <td>{{ o.kind }} · {{ o.obligation_id }}{{ o.mandatory === false ? '' : ' · mandatory' }}</td>
            <td class="lw-num">{{ money(o.amount) }}</td>
            <td>{{ o.due.utc }} ({{ hoursFrom(body.as_of, o.due_at) }})</td>
            <td>{{ o.due.local }}</td>
            <td>{{ o.reservation_id || 'not reserved' }}</td>
            <td>{{ o.state || 'open' }}</td>
          </tr>
          <tr v-if="!obligations.length"><td colspan="6">No obligations</td></tr>
        </tbody>
      </table>
    </div>
    <p class="lw-time">t is whole hours from the snapshot's as of; deadlines are simulated time.</p>
  </ScreenShell>
</template>

<script setup>
import { computed } from 'vue'
import {
  STATES, ScreenShell, againstFloor, formatMoney, formatTime, getTreasury, hoursFrom,
  metricText, money, pendingFlows, projectionTerms, useReading
} from '../api/v1.js'

const { state, refresh } = useReading(() => getTreasury())

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
      flows: pendingFlows(a),
      calc: low ? projectionTerms(a, low.t, body.obligations, body.as_of) : null
    }
  })
})

const obligations = computed(() =>
  (state.body?.obligations ?? []).map((o) => ({ ...o, due: formatTime(o.due_at) })))
</script>

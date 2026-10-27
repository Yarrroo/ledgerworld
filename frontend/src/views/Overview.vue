<template>
  <ScreenShell v-slot="{ body }" title="Overview" :reading="state" :refresh="refresh">
    <p class="lw-source">
      Observed state: settled cash, the next deadline and the lowest projected cash against the
      reserve floor. Each figure comes from the API; open a tile to see its inputs.
    </p>
    <p v-if="body.completeness.status === 'partial'" class="lw-note" data-test="partial">
      Partial: not current — {{ notCurrent }}.
      A stale account was observed and keeps its last value; an unknown one has no value.
    </p>

    <section class="lw-strip" aria-label="Answer">
      <article class="lw-tile" data-test="settled">
        <div class="lw-tile__label">Settled cash</div>
        <div class="lw-figure">{{ metricText(body.cash) }}</div>
        <div v-if="body.cash.status === 'stale'" class="lw-time" data-test="as-of">
          as of {{ formatTime(body.cash.as_of).utc }}
        </div>
        <details class="lw-calc">
          <summary>How this is calculated</summary>
          <div class="lw-calc__body">
            <p>Sum of settled balances on the treasury's cash accounts, from the API.</p>
            <p>{{ statusLine(body.cash) }}</p>
          </div>
        </details>
      </article>

      <article class="lw-tile" data-test="spendable">
        <div class="lw-tile__label">Spendable now (S)</div>
        <div class="lw-figure">{{ metricText(body.spendable) }}</div>
        <div v-if="body.spendable.status === 'stale'" class="lw-time">
          as of {{ formatTime(body.spendable.as_of).utc }}
        </div>
        <details class="lw-calc">
          <summary>How this is calculated</summary>
          <div class="lw-calc__body">
            <p>S = settled − reserved − pledged − pending out + pending in arrived by now.</p>
            <p>API result: {{ metricText(body.spendable) }}. {{ statusLine(body.spendable) }}</p>
            <p><RouterLink to="/treasury">Buckets by account on Treasury</RouterLink></p>
          </div>
        </details>
      </article>

      <article class="lw-tile" data-test="next-obligation">
        <div class="lw-tile__label">Next obligation</div>
        <template v-if="next">
          <div class="lw-figure">{{ money(next.amount) }}</div>
          <div>{{ next.kind }} · {{ next.reserved ? 'reserved' : 'not reserved' }}</div>
          <div class="lw-time" data-test="due">
            due {{ due.utc }} · {{ due.local }} · {{ hoursFrom(body.as_of, next.due_at) }} from as of
          </div>
        </template>
        <div v-else class="lw-figure lw-figure--small">No open obligation</div>
      </article>

      <article class="lw-tile" data-test="coverage">
        <div class="lw-tile__label">Minimum projected cash vs floor</div>
        <div class="lw-figure lw-figure--small">
          {{ metricText(body.coverage.min_projected) }} minimum projected cash /
          {{ metricText(body.coverage.floor) }} floor
        </div>
        <div :class="['lw-status', `lw-status--${STATES[floor].tone}`]" data-test="floor-status">
          <span aria-hidden="true">{{ STATES[floor].icon }}</span>
          <span>{{ STATES[floor].word }}</span>
        </div>
        <details class="lw-calc">
          <summary>How this is calculated</summary>
          <div class="lw-calc__body">
            <p>
              Lowest projected cash P over the horizon: {{ metricText(body.coverage.min_projected) }}
              <template v-if="body.coverage.at">
                at {{ formatTime(body.coverage.at).utc }} ({{ hoursFrom(body.as_of, body.coverage.at) }})
              </template>
            </p>
            <p>Reserve floor: {{ metricText(body.coverage.floor) }}</p>
            <p>Headroom (P minimum − floor): {{ metricText(body.coverage.headroom) }}</p>
            <p>The floor is kept when the headroom is zero or more.</p>
          </div>
        </details>
      </article>

      <article class="lw-tile" data-test="lender-capacity">
        <div class="lw-tile__label">Lender capacity (K_p)</div>
        <div class="lw-figure">{{ metricText(body.lender_capacity) }}</div>
        <details class="lw-calc">
          <summary>How this is calculated</summary>
          <div class="lw-calc__body">
            <p>K_p = settled known − committed undrawn − pledged − pool obligations due − pool floor.</p>
            <p><RouterLink to="/lending">Its parts on Lending</RouterLink></p>
          </div>
        </details>
      </article>
    </section>

    <div class="lw-actions">
      <RouterLink v-if="simulationTarget" class="lw-button" :to="simulationTarget"
                  data-test="open-simulation">Open simulation</RouterLink>
      <template v-else>
        <button type="button" class="lw-button" disabled data-test="open-simulation"
                aria-describedby="open-simulation-why">Open simulation</button>
        <span id="open-simulation-why" class="lw-time" data-test="open-simulation-why">{{ simulationWhy }}</span>
      </template>
    </div>
  </ScreenShell>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import {
  STATES, ScreenShell, floorState, formatTime, freshness, getOverview, hoursFrom, metricText,
  money, routeExists, stateOf, useReading
} from '../api/v1.js'

const router = useRouter()
const { state, refresh } = useReading(() => getOverview())

const next = computed(() => state.body?.upcoming_outflows[0] ?? null)
const due = computed(() => formatTime(next.value?.due_at))
const floor = computed(() => floorState(state.body?.coverage.headroom))
const notCurrent = computed(() =>
  state.body?.completeness.accounts.map((a) => freshness(a).text).join('; '))

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

function statusLine (metric) {
  const s = stateOf(metric.status)
  const at = metric.as_of ? ` as of ${formatTime(metric.as_of).utc}` : ''
  return `${s.icon} ${s.word}${at}`
}
</script>

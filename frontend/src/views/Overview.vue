<template>
  <ScreenShell title="Overview" :body="body" :busy="state.status === 'loading'" :refresh="refresh">
    <p class="lw-source">
      Observed state: settled cash, the next deadline and the lowest projected cash against the
      reserve floor. Each figure comes from the API; open a tile to see its inputs.
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
    <p v-if="body && body.completeness.status === 'partial'" class="lw-note" data-test="partial">
      Partial: not observed — {{ body.completeness.missing.join(', ') }}. Figures that depend on
      them read Unknown, not zero.
    </p>

    <section class="lw-strip" aria-label="Answer">
      <article class="lw-tile" data-test="settled">
        <div class="lw-tile__label">Settled cash</div>
        <div class="lw-figure">
          <span v-if="!body" class="lw-skeleton" aria-label="Loading" />
          <template v-else>{{ metricText(body.cash) }}</template>
        </div>
        <div v-if="body?.cash.status === 'stale'" class="lw-time" data-test="as-of">
          as of {{ formatTime(body.cash.as_of).utc }}
        </div>
        <details v-if="body" class="lw-calc">
          <summary>How this is calculated</summary>
          <div class="lw-calc__body">
            <p>Sum of settled balances on the treasury's cash accounts, from the API.</p>
            <p>{{ statusLine(body.cash) }}</p>
          </div>
        </details>
      </article>

      <article class="lw-tile" data-test="spendable">
        <div class="lw-tile__label">Spendable now (S)</div>
        <div class="lw-figure">
          <span v-if="!body" class="lw-skeleton" aria-label="Loading" />
          <template v-else>{{ metricText(body.spendable) }}</template>
        </div>
        <div v-if="body?.spendable.status === 'stale'" class="lw-time">
          as of {{ formatTime(body.spendable.as_of).utc }}
        </div>
        <details v-if="body" class="lw-calc">
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
          <div class="lw-figure">{{ formatMoney(next.amount.minor, next.amount.currency) }}</div>
          <div>{{ next.kind }} · {{ next.reserved ? 'reserved' : 'not reserved' }}</div>
          <div class="lw-time" data-test="due">
            due {{ formatTime(next.due_at).utc }} · {{ formatTime(next.due_at).local }}
            · {{ hoursFrom(body.as_of, next.due_at) }} from as of
          </div>
        </template>
        <div v-else-if="body" class="lw-figure lw-figure--small">No open obligation</div>
        <div v-else class="lw-figure"><span class="lw-skeleton" aria-label="Loading" /></div>
      </article>

      <article class="lw-tile" data-test="coverage">
        <div class="lw-tile__label">Minimum projected cash vs floor</div>
        <template v-if="body">
          <div class="lw-figure lw-figure--small">{{ coverageText }}</div>
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
        </template>
        <div v-else class="lw-figure"><span class="lw-skeleton" aria-label="Loading" /></div>
      </article>

      <article class="lw-tile" data-test="lender-capacity">
        <div class="lw-tile__label">Lender capacity (K_p)</div>
        <div class="lw-figure">
          <span v-if="!body" class="lw-skeleton" aria-label="Loading" />
          <template v-else>{{ metricText(body.lender_capacity) }}</template>
        </div>
        <details v-if="body" class="lw-calc">
          <summary>How this is calculated</summary>
          <div class="lw-calc__body">
            <p>K_p = settled known − committed undrawn − pledged − pool obligations due − pool floor.</p>
            <p><RouterLink to="/lending">Its parts on Lending</RouterLink></p>
          </div>
        </details>
      </article>
    </section>

    <div class="lw-actions">
      <RouterLink
        v-if="simulationTarget"
        class="lw-button"
        :to="simulationTarget"
        data-test="open-simulation"
      >Open simulation</RouterLink>
      <template v-else>
        <button type="button" class="lw-button" disabled data-test="open-simulation"
                aria-describedby="open-simulation-why">Open simulation</button>
        <span id="open-simulation-why" class="lw-time">{{ simulationWhy }}</span>
      </template>
    </div>
  </ScreenShell>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import {
  LABELS, STATES, ScreenShell, floorState, formatMoney, formatTime, getOverview, hoursFrom,
  metricText, routeExists, useReading
} from '../api/v1.js'

const router = useRouter()
const { state, refresh } = useReading(() => getOverview())
const body = computed(() => state.body)

const next = computed(() => body.value?.upcoming_outflows[0] ?? null)
const floor = computed(() => floorState(body.value?.coverage.headroom))
const coverageText = computed(() => {
  const c = body.value.coverage
  return `${metricText(c.min_projected)} minimum projected cash / ${metricText(c.floor)} floor`
})

const runId = computed(() => body.value?.demo.run_id ?? null)
const simulationTarget = computed(() => {
  if (!runId.value || state.status !== 'loaded' || !routeExists(router, '/simulation')) return null
  return { path: '/simulation', query: { run_id: runId.value } }
})
const simulationWhy = computed(() => {
  if (!body.value) return 'Waiting for the overview'
  if (state.status === 'error') return 'Last loaded, not current: reload first'
  if (!runId.value) return 'No demonstration run is prepared'
  return 'The simulation screen is not part of this build'
})

function statusLine (metric) {
  const s = STATES[metric.status] || STATES.unassessed
  const at = metric.as_of ? ` as of ${formatTime(metric.as_of).utc}` : ''
  return `${s.icon} ${s.word}${at}`
}
</script>

<template>
  <ScreenShell v-slot="{ body }" title="Lending" :reading="state" :refresh="refresh">
    <p class="lw-source">
      The lender pool's usable capacity K_p, its parts, and each facility's principal, fee,
      observed revenue and outstanding balance.
    </p>

      <section class="lw-strip" aria-label="Answer">
        <article class="lw-tile" data-test="capacity">
          <div class="lw-tile__label">Pool capacity K_p · {{ body.pool }}</div>
          <div class="lw-figure" data-test="capacity-value">{{ capacityText }}</div>
          <div :class="['lw-status', `lw-status--${reduced ? 'warn' : 'muted'}`]" data-test="authority">
            <span aria-hidden="true">{{ reduced ? '!' : '●' }}</span>
            <span>Balance authority {{ capacity.authority }}</span>
          </div>
          <details class="lw-calc">
            <summary>How this is calculated</summary>
            <div class="lw-calc__body" data-test="calculation">
              <p>In {{ capacity.K_p.currency }}, parts from the API:</p>
              <p>{{ calculation }}</p>
              <p>settled known − committed undrawn − pledged − pool obligations due − pool floor = K_p</p>
            </div>
          </details>
        </article>

        <article v-if="notCurrent.length" class="lw-tile" data-test="not-current">
          <div class="lw-tile__label">Not current, not counted</div>
          <template v-for="a in notCurrent" :key="a.account_id">
            <div class="lw-figure lw-figure--small">
              {{ a.account_id }} ·
              <span :class="['lw-status', `lw-status--${stateOf(a.status).tone}`]">
                <span aria-hidden="true">{{ stateOf(a.status).icon }}</span>
                {{ stateOf(a.status).word }}
              </span>
            </div>
            <div v-if="a.status === 'stale'" class="lw-time">as of {{ formatTime(a.as_of).utc }}</div>
          </template>
        </article>
      </section>

      <h2>Capacity parts</h2>
      <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Capacity parts">
        <table class="lw-table" data-test="parts">
          <thead><tr><th scope="col">Part</th><th scope="col">Amount</th><th scope="col">State</th></tr></thead>
          <tbody>
            <tr v-for="p in parts" :key="p.key">
              <td>{{ p.label }}</td>
              <td class="lw-num">{{ metricText(p.metric) }}</td>
              <td>{{ stateOf(p.metric.status).word }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <details class="lw-calc" data-test="facility-terms">
        <summary>Open facility terms</summary>
        <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Facilities">
          <table class="lw-table" data-test="facilities">
            <thead>
              <tr><th scope="col">Facility</th><th scope="col">Borrower</th><th scope="col">Principal</th>
                <th scope="col">Fee</th><th scope="col">Owed</th><th scope="col">Observed revenue</th>
                <th scope="col">Outstanding</th><th scope="col">State</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in body.facilities" :key="f.facility_id">
                <td>{{ f.facility_id }} · {{ f.kind }}</td>
                <td>{{ f.borrower }}</td>
                <td class="lw-num">{{ money(f.principal) }}</td>
                <td class="lw-num">{{ money(f.fee) }}</td>
                <td class="lw-num">{{ money(f.owed) }}</td>
                <td class="lw-num">{{ metricText(f.observed_revenue) }}</td>
                <td class="lw-num">{{ money(f.outstanding) }}</td>
                <td>{{ f.state }}</td>
              </tr>
              <tr v-if="!body.facilities.length"><td colspan="8">No facilities</td></tr>
            </tbody>
          </table>
        </div>
        <p class="lw-time">Repayment is computed from observed revenue only, never from a forecast.</p>
      </details>

      <div class="lw-actions">
        <RouterLink v-if="fundingTarget" class="lw-button" :to="fundingTarget" data-test="fund">
          Fund from the pool
        </RouterLink>
        <template v-else>
          <button type="button" class="lw-button" disabled aria-describedby="fund-why" data-test="fund">
            Fund from the pool
          </button>
          <span id="fund-why" class="lw-time" data-test="fund-why">{{ fundingWhy }}</span>
        </template>
      </div>
  </ScreenShell>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import {
  ApiError, ScreenShell, amountText, contextKey, formatTime, getLending, getOverview, metricText,
  money, routeExists, stateOf, useReading
} from '../api/v1.js'

const router = useRouter()

/** Lending, and the same snapshot's completeness: C6 Lending lists no pool accounts, so the
 * accounts that are not current (each stale or unknown) are read from the overview of the same
 * context. */
async function load () {
  const [lending, overview] = await Promise.all([getLending(), getOverview()])
  if (contextKey(lending) !== contextKey(overview)) {
    throw new ApiError(0, 'context_mismatch',
      'lending and overview answered for different snapshots or modes; reload')
  }
  return { ...lending, notCurrent: overview.completeness.accounts, demo: overview.demo }
}

const { state, refresh } = useReading(load)
const capacity = computed(() => state.body.capacity)
const reduced = computed(() => capacity.value.authority !== 'full')

const capacityText = computed(() => {
  const text = metricText(capacity.value.K_p)
  return reduced.value && capacity.value.K_p.minor !== null ? `${text} (known funds only)` : text
})

const PARTS = [
  ['settled_known', 'Settled, known'],
  ['committed_undrawn', 'Committed, undrawn'],
  ['pledged', 'Pledged'],
  ['obligations_due', 'Pool obligations due in horizon'],
  ['floor', 'Pool reserve floor']
]
const parts = computed(() => PARTS.map(([key, label]) => ({
  key, label, metric: capacity.value.parts[key]
})))

const calculation = computed(() => {
  const terms = PARTS.map(([key]) => amountText(capacity.value.parts[key]))
  return `${terms.join(' - ')} = ${amountText(capacity.value.K_p)}`
})

const notCurrent = computed(() =>
  state.body.notCurrent.filter((a) => a.account_id.startsWith(`${state.body.pool}/`)))

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

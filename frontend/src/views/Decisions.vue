<template>
  <ScreenShell v-slot="{ body }" title="Decisions" :reading="state" :refresh="refresh">
    <p class="lw-source" data-test="cohort">
      Run {{ body.run_id }} · checkpoint round {{ body.checkpoint_round }} · cohort {{ body.cohort }} ·
      {{ body.weight_kind }} · a scenario comparison, not a probability.
    </p>

    <p v-if="body.status === 'pending'" class="lw-note" role="status" data-test="pending">
      The comparison is still running; nothing is selected yet.
    </p>

    <section v-if="body.status === 'all_infeasible'" class="lw-alert" role="alert" data-test="escalation">
      <h2>No feasible plan: escalate, nothing can be approved</h2>
      <p>Earliest unmet: {{ body.escalation.earliest_unmet }}</p>
      <p>Binding constraint: {{ body.escalation.binding }}</p>
      <p>Escalate to: <strong>{{ body.escalation.contact }}</strong></p>
    </section>

    <section :aria-labelledby="search ? 'search-heading' : 'policies-heading'"
             :data-test="search ? 'search' : 'policies'">
      <h2 v-if="search" id="search-heading">{{ LABELS.search }}</h2>
      <h2 v-else id="policies-heading">
        Policies side by side<template v-if="body.status === 'all_infeasible'"> · ranking shown, not executable</template>
      </h2>
      <div class="lw-strip">
        <article v-for="p in policies" :key="p.policy" class="lw-tile" :data-test="`policy-${p.policy}`">
          <div class="lw-tile__label">{{ NAMES[p.policy] }}</div>
          <div v-if="body.selected === p.policy" class="lw-status lw-status--ok" data-test="selected">
            <span aria-hidden="true">✓</span><span>Selected</span>
          </div>
          <dl class="lw-terms">
            <dt>Obligations unmet</dt><dd>{{ p.unmet }}</dd>
            <dt>Reserve floor</dt>
            <dd>{{ p.breached ? `breached in ${p.breached} of ${p.rows.length} scenarios` : `kept in all ${p.rows.length} scenarios` }}</dd>
            <dt>Scenario-set cost</dt><dd data-test="cost">{{ p.cost }}</dd>
          </dl>
          <p class="lw-time" data-test="weight">{{ body.weight_kind }} · cohort {{ body.cohort }}</p>
          <ul class="lw-scenarios" :aria-label="`${NAMES[p.policy]} by scenario`">
            <li v-for="r in p.rows" :key="r.branch_id" data-test="scenario">
              <div class="lw-scenarios__head">
                <strong>{{ r.scenario_id }}</strong>
                <span :class="['lw-status', `lw-status--${STATES[floorOf(r)].tone}`]">
                  <span aria-hidden="true">{{ STATES[floorOf(r)].icon }}</span>
                  {{ r.floor_kept ? 'Floor kept' : 'Floor breached' }}
                </span>
              </div>
              <div>Min cash {{ metricText(r.min_cash) }} · unmet {{ r.obligations_unmet }} ·
                funding {{ money(r.funding_cost) }}</div>
              <div class="lw-time">{{ r.replay ? `${LABELS.replay} · ` : '' }}{{ LABELS.branch }} {{ r.branch_id }}</div>
            </li>
          </ul>
        </article>
      </div>
      <p v-if="replayed" class="lw-note" data-test="replay">
        Results marked Replay come from an earlier run of that branch, not from this session.
      </p>
    </section>

    <p class="lw-source">
      A branch result is never an approval: the selected policy is re-decided on the current
      observed snapshot, and its terms are reviewed before anything is approved.
    </p>
    <div class="lw-actions">
      <RouterLink v-if="reviewable" class="lw-button" data-test="review-plan"
                  :to="{ path: '/execution', query: { run_id: body.run_id, review: '1' } }">Review plan</RouterLink>
      <RouterLink v-if="routeExists(router, '/execution')" class="lw-button lw-button--quiet"
                  data-test="view-execution"
                  :to="{ path: '/execution', query: { run_id: body.run_id } }">View execution</RouterLink>
    </div>
  </ScreenShell>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  ApiError, LABELS, STATES, ScreenShell, formatMoney, getOverview, metricText, money, request,
  routeExists, useReading
} from '../api/v1.js'

const ORDER = ['no-action', 'fixed-reserve', 'integrated']
const NAMES = { 'no-action': 'No action', 'fixed-reserve': 'Fixed reserve', integrated: 'Integrated' }

const route = useRoute()
const router = useRouter()
const { state, refresh } = useReading(async () => {
  const runId = route.query.run_id || (await getOverview()).demo.run_id
  if (!runId) throw new ApiError(404, 'no_demo_run', 'No demonstration run is prepared')
  return request(`/decisions/${encodeURIComponent(runId)}`)
})

/** A reverse-stress search finds a breaking path: not a forecast, and not a decision. */
const search = computed(() => /reverse[_-]stress/.test(state.body?.cohort ?? ''))
const replayed = computed(() => state.body?.results.some((r) => r.replay))
const reviewable = computed(() => state.status === 'loaded' && state.body.status === 'selected' &&
  !search.value && routeExists(router, '/execution'))

const floorOf = (r) => (r.floor_kept ? 'kept' : 'breached')

/** One policy's funding cost summed over its scenarios: integers, one currency, or say so. */
function scenarioCost (rows) {
  const currency = rows[0].funding_cost.currency
  if (rows.some((r) => r.funding_cost.currency !== currency)) return 'Mixed currencies; not summed'
  const total = rows.reduce((sum, r) => sum + r.funding_cost.minor, 0)
  return `${formatMoney(total, currency)} across ${rows.length} scenarios; not the current execution fee`
}

const policies = computed(() => {
  const results = state.body?.results ?? []
  return ORDER.map((policy) => {
    const rows = results.filter((r) => r.policy === policy)
    return {
      policy,
      rows,
      unmet: rows.reduce((n, r) => n + r.obligations_unmet, 0),
      breached: rows.filter((r) => !r.floor_kept).length,
      cost: rows.length ? scenarioCost(rows) : ''
    }
  }).filter((p) => p.rows.length)
})
</script>

<style scoped>
.lw-terms {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--lw-space-1) var(--lw-space-3);
  margin: var(--lw-space-2) 0;
}
.lw-terms dt { color: var(--lw-ink-muted); }
.lw-terms dd { margin: 0; }
.lw-scenarios {
  list-style: none;
  margin: var(--lw-space-2) 0 0;
  padding: 0;
}
.lw-scenarios li {
  padding: var(--lw-space-2) 0;
  border-top: 1px solid var(--lw-rule);
  overflow-wrap: anywhere;
}
.lw-scenarios__head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2);
  align-items: baseline;
}
</style>

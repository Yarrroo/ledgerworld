<template>
  <ScreenShell v-slot="{ body }" title="Decisions" :reading="state" :refresh="refresh">
    <section class="lw-dec__context" aria-label="The plans compared" data-panel="The plans compared">
      <p class="lw-lead" data-test="lead">{{ lead }}</p>
      <div class="lw-labels" data-test="labels">
        <span class="lw-tag" data-test="plain-mode">{{ PLAIN[body.mode] || LABELS[body.mode] || body.mode }}</span>
        <span class="lw-tag" data-test="hypothetical">{{ PLAIN.branch }}</span>
      </div>
      <p class="lw-time">
        Each plan faced the same shock in its own what-if; a count of what-ifs is a count, never odds.
        <RouterLink v-if="routeExists(router, '/simulation')" data-test="open-simulation"
                    :to="{ path: '/simulation', query: { run_id: body.run_id } }">Open simulation</RouterLink>
      </p>
      <HowWeKnow test="how-decisions">
        <p class="lw-source" data-test="cohort">
          Run {{ body.run_id }} · checkpoint round {{ body.checkpoint_round }} · cohort {{ body.cohort }} ·
          {{ body.weight_kind }} · a scenario comparison, not a probability.
        </p>
        <p><template v-if="family">Scenario family {{ family.id }}. </template>Every policy (no-action,
          fixed-reserve, integrated) ran in a fresh branch from round {{ body.checkpoint_round }} of snapshot
          {{ body.snapshot_id }}. The shortfall in the sentence above is No action's lowest minimum cash
          against the operating account's reserve floor; its day is the first payment due on that account.
          The fee is the selected policy's branch funding cost.</p>
      </HowWeKnow>
    </section>

    <p v-if="body.status === 'pending'" class="lw-note" role="status" data-test="pending">
      The comparison is still running; nothing is selected yet.
    </p>

    <section v-if="body.status === 'all_infeasible'" class="lw-alert" role="alert" data-test="escalation" data-panel="No feasible plan">
      <h2>No feasible plan: escalate, nothing can be approved</h2>
      <p>Earliest unmet: {{ body.escalation.earliest_unmet }}</p>
      <p>Binding constraint: {{ body.escalation.binding }}</p>
      <p>Escalate to: <strong>{{ body.escalation.contact }}</strong></p>
    </section>

    <div class="lw-dec">
      <section v-if="!search" class="lw-dec__gap" aria-labelledby="gap-heading" data-panel="Where the cash falls short" data-test="gap">
        <h2 id="gap-heading">Where the cash falls short</h2>
        <article class="lw-tile">
          <div class="lw-tile__label">If you {{ PLANS['no-action'].toLowerCase() }}</div>
          <template v-if="gap">
            <p class="lw-dec__line" data-test="gap-summary">
              Lowest point <strong>{{ metricText(gap.min) }}</strong> against your safety minimum of
              <strong>{{ gap.floor ? metricText(gap.floor) : 'Not assessed' }}</strong>
              <template v-if="gap.check.state === 'breached'">: <strong>{{ formatMoney(-gap.check.gap, gap.min.currency) }}</strong> short</template>
              <template v-else-if="gap.check.state === 'kept'">: you stay above it</template>.
              {{ gap.unmet ? `${gap.unmet} obligation${gap.unmet === 1 ? '' : 's'} unmet.` : 'Every obligation met.' }}
            </p>
            <div :class="['lw-status', `lw-status--${STATES[gap.check.state].tone}`]">
              <span aria-hidden="true">{{ STATES[gap.check.state].icon }}</span><span>{{ FLOOR_WORDS[gap.check.state] }}</span>
            </div>
          </template>
          <p v-else class="lw-time">No result for {{ PLANS['no-action'] }} in this comparison yet.</p>

          <div v-if="explained" class="lw-dec__explain" role="status" aria-live="polite" data-test="explanation">
            <div class="lw-tile__label">With {{ PLANS[explained.policy] }}</div>
            <p class="lw-dec__line">
              Lowest point {{ explained.min }}; safety minimum
              {{ explained.breached ? `broken in ${explained.breached} of ${explained.rows.length} what-ifs` : `kept in all ${explained.rows.length} what-ifs` }};
              {{ explained.unmet }} obligation{{ explained.unmet === 1 ? '' : 's' }} unmet; {{ explained.cost }}.
            </p>
            <p class="lw-time">Choosing a plan here only changes this explanation. It approves nothing.</p>
          </div>

          <details class="lw-calc" data-test="timing">
            <summary>When the money moves</summary>
            <div class="lw-calc__body">
              <ol v-if="timing.length" class="lw-dec__timing">
                <li v-for="t in timing" :key="t.key" :data-at="t.h"><strong>h{{ t.h }}</strong> · {{ t.what }}</li>
              </ol>
              <p v-else>The treasury read did not answer for this snapshot; timing is not shown.</p>
              <p>Simulated hours from the snapshot's observation. The minimum is read from each branch's realised ledger.</p>
            </div>
          </details>
        </article>
      </section>

      <section :aria-labelledby="search ? 'search-heading' : 'policies-heading'" class="lw-dec__policies"
               :data-test="search ? 'search' : 'policies'" :data-panel="search ? 'Search results' : 'Plans side by side'">
        <h2 v-if="search" id="search-heading">{{ LABELS.search }}</h2>
        <h2 v-else id="policies-heading">
          Three plans side by side<template v-if="body.status === 'all_infeasible'"> · ranking shown, not executable</template>
        </h2>
        <div class="lw-dec__rows" :role="search ? undefined : 'radiogroup'" :aria-labelledby="search ? undefined : 'policies-heading'">
          <article v-for="p in policies" :key="p.policy" class="lw-dec__row" :class="{ 'is-chosen': p.policy === chosen }"
                   :data-test="`policy-${p.policy}`">
            <label class="lw-dec__head">
              <input v-if="!search" type="radio" name="policy" :value="p.policy" :checked="p.policy === chosen"
                     :disabled="body.status === 'pending'" @change="chosen = p.policy">
              <span class="lw-dec__name">{{ PLANS[p.policy] }}</span>
              <span v-if="body.selected === p.policy" class="lw-status lw-status--ok" data-test="selected">
                <span aria-hidden="true">✓</span><span>Selected</span>
              </span>
            </label>
            <dl class="lw-terms">
              <dt>Obligations unmet</dt><dd>{{ p.unmet }}</dd>
              <dt>Safety minimum</dt>
              <dd>{{ p.breached ? `broken in ${p.breached} of ${p.rows.length} what-ifs` : `kept in all ${p.rows.length} what-ifs` }}</dd>
              <dt>Largest shortfall</dt><dd>{{ p.short }}</dd>
              <dt>Fees across what-ifs</dt><dd data-test="cost">{{ p.cost }}</dd>
            </dl>
            <HowWeKnow :test="`how-${p.policy}`">
              <p data-test="weight">Policy {{ p.policy }} · {{ body.weight_kind }} · cohort {{ body.cohort }}</p>
              <ul class="lw-scenarios" :aria-label="`${PLANS[p.policy]} by scenario`">
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
                  <div>{{ r.replay ? `${LABELS.replay} · ` : '' }}{{ LABELS.branch }} {{ r.branch_id }}</div>
                </li>
              </ul>
            </HowWeKnow>
          </article>
        </div>
        <p v-if="replayed" class="lw-note" data-test="replay">
          Results marked Replay come from an earlier run of that branch, not from this session.
        </p>
        <div class="lw-actions">
          <button type="button" class="lw-button lw-button--quiet" data-test="compare-details" @click="details = true">
            Compare the what-ifs in detail
          </button>
        </div>
      </section>
    </div>

    <section class="lw-dec__review" aria-label="Review handoff" data-panel="Review the plan">
      <p class="lw-source">
        A what-if never approves anything: the chosen plan is worked out again on today's real
        figures, and you check its terms before any money moves.
      </p>
      <div class="lw-actions">
        <RouterLink v-if="reviewable" class="lw-button" data-test="review-plan"
                    :to="{ path: '/execution', query: { run_id: body.run_id, review: '1' } }">Review the plan</RouterLink>
        <RouterLink v-if="routeExists(router, '/execution')" class="lw-button lw-button--quiet"
                    data-test="view-execution"
                    :to="{ path: '/execution', query: { run_id: body.run_id } }">View execution</RouterLink>
      </div>
    </section>

    <DetailSheet :open="details" title="Scenario details" test="details-sheet" @close="details = false">
      <p class="lw-time">One row per scenario and policy, from each branch's realised ledger. Funding is that
        branch's scenario fee, not the current plan's fee, which is set at review.</p>
      <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Scenario details">
        <table class="lw-table" data-test="details-table">
          <thead>
            <tr><th scope="col">Scenario</th><th scope="col">Plan</th><th scope="col">Min cash</th>
              <th scope="col">Floor</th><th scope="col">Unmet</th><th scope="col">Funding</th><th scope="col">Provenance</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in body?.results ?? []" :key="r.branch_id">
              <td>{{ r.scenario_id }}</td>
              <td>{{ PLANS[r.policy] }}</td>
              <td class="lw-num">{{ metricText(r.min_cash) }}</td>
              <td>{{ r.floor_kept ? '✓ kept' : '✕ breached' }}</td>
              <td class="lw-num">{{ r.obligations_unmet }}</td>
              <td class="lw-num">{{ money(r.funding_cost) }}</td>
              <td>{{ r.replay ? LABELS.replay : 'Fresh' }} · {{ r.branch_id }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </DetailSheet>
  </ScreenShell>
</template>

<script setup>
/**
 * Decisions (handoff D1–D6). The comparison is the API's: the backend decides feasibility and
 * the selection, marked Selected. The policies are a radio group; choosing one only changes the
 * explanation beside it and approves nothing. The gap explanation reads No action's minimum cash
 * against the treasury's floor, and its timing from the treasury read and the scenario family's
 * delay; without that read it says so. A reverse-stress search is listed as search results, with
 * no selection and no review.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DetailSheet from '../components/DetailSheet.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
import { familyOf, observedBy, worldFor } from '../api/world.js'
import {
  FLOOR_WORDS, LABELS, OWED, PLAIN, PLANS, PLANS_DOING, STATES, ScreenShell, againstFloor, dayText,
  feesAcross, formatMoney, getOverview, getTreasury, metricText, money, noDemoRun, request, routeExists, useReading
} from '../api/v1.js'

const ORDER = ['no-action', 'fixed-reserve', 'integrated']

const route = useRoute()
const router = useRouter()
const { state, refresh } = useReading(async () => {
  const runId = route.query.run_id || (await getOverview()).demo.run_id
  if (!runId) throw noDemoRun()
  // one after the other: the offline app's SQLite refuses a ledger read beside a job-store read
  const decisions = await request(`/decisions/${encodeURIComponent(runId)}`)
  const treasury = await getTreasury().catch(() => null)
  // the run's own snapshot (a prepared demo's money screens read the world's h0, the snapshot a
  // run starts from), or one the run observed from it
  const same = treasury && treasury.mode === decisions.mode &&
    (treasury.snapshot_id === decisions.snapshot_id || observedBy(treasury.snapshot_id, decisions.run_id))
  return { ...decisions, treasury: same ? treasury : null }
})
// The view is reused across query-only navigation: another run is another reading.
watch(() => route.query.run_id, () => refresh())

/** A reverse-stress search finds a breaking path: not a forecast, and not a decision. */
const search = computed(() => /reverse[_-]stress/.test(state.body?.cohort ?? ''))
const replayed = computed(() => state.body?.results.some((r) => r.replay))
const reviewable = computed(() => state.status === 'loaded' && state.body.status === 'selected' &&
  !search.value && routeExists(router, '/execution'))
const family = computed(() => familyOf(state.body?.cohort))

const floorOf = (r) => (r.floor_kept ? 'kept' : 'breached')

/** The treasury's operating account, whose floor the policies are judged against. */
const account = computed(() => {
  const accounts = state.body?.treasury?.accounts ?? []
  return accounts.find((a) => a.id.endsWith('/operating')) ?? accounts[0] ?? null
})

/** A policy's lowest minimum cash across its scenarios, the API's own metric; Unknown when any
 * scenario's is, since the lowest of them cannot then be known. */
function lowestOf (rows) {
  if (!rows.length) return null
  if (rows.some((r) => r.min_cash?.minor == null)) {
    return { minor: null, currency: rows[0].min_cash?.currency, status: 'unknown', as_of: null }
  }
  return rows.reduce((a, b) => (b.min_cash.minor < a.min_cash.minor ? b : a)).min_cash
}

/** The treasury floor, when it is in ``currency``; a floor in another currency is not compared. */
const floorIn = (currency) => {
  const floor = account.value?.floor ?? null
  return floor && floor.currency === currency ? floor : null
}

/**
 * The largest shortfall against the floor, over the scenarios whose floor the API says broke
 * (`floor_kept` is the branch's own verdict; this screen never overrules it), or why there is none.
 */
function largestShort (rows) {
  const floor = floorIn(rows[0].min_cash?.currency)
  if (!floor) return 'Not assessed'
  const broke = rows.filter((r) => !r.floor_kept)
  if (!broke.length) return 'None'
  const gaps = broke.map((r) => againstFloor(r.min_cash, floor))
  if (gaps.some((g) => g.state !== 'breached')) return 'Unknown'
  return formatMoney(-Math.min(...gaps.map((g) => g.gap)), floor.currency)
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
      cost: rows.length ? feesAcross(rows) : '',
      short: rows.length ? largestShort(rows) : '',
      min: rows.length ? metricText(lowestOf(rows)) : ''
    }
  }).filter((p) => p.rows.length)
})

// The row being explained: the backend's selection until another is chosen; none while pending.
const chosen = ref(null)
watch(() => [state.body?.run_id, state.body?.selected, state.body?.status], () => {
  chosen.value = state.body?.status === 'pending' ? null : (state.body?.selected ?? null)
}, { immediate: true })
const explained = computed(() => policies.value.find((p) => p.policy === chosen.value) ?? null)

const gap = computed(() => {
  const rows = (state.body?.results ?? []).filter((r) => r.policy === 'no-action')
  if (!rows.length) return null
  const min = lowestOf(rows)
  const floor = floorIn(min?.currency)
  return { min, floor, check: againstFloor(min, floor), unmet: rows.reduce((n, r) => n + r.obligations_unmet, 0) }
})

/**
 * " on 2 Jan": the first payment still owed on the operating account from the treasury's as of on
 * (a missing state is open, as in projectionTerms), by time, not by string; '' when none is read.
 */
const firstDue = computed(() => {
  const t = state.body?.treasury
  const a = account.value
  const from = Date.parse(t?.as_of)
  const due = (t?.obligations ?? [])
    .filter((o) => o.account === a?.id && OWED.has(o.state ?? 'open'))
    .map((o) => Date.parse(o.due_at)).filter((at) => Number.isFinite(at) && !(at < from)).sort((x, y) => x - y)
  return due.length ? ` on ${dayText(new Date(due[0]).toISOString())}` : ''
})

/** The selected plan's fee in a sentence ("a USD 800.00 fee"): one what-if's, or the largest of several. */
function feeWords (rows) {
  const currency = rows[0].funding_cost.currency
  if (rows.some((r) => r.funding_cost.currency !== currency)) return 'a fee in several currencies'
  const top = Math.max(...rows.map((r) => r.funding_cost.minor))
  if (top === 0) return 'no fee'
  return rows.length > 1 ? `a fee of up to ${formatMoney(top, currency)}` : `a ${formatMoney(top, currency)} fee`
}

/**
 * The finance lead's answer, first (COPY.md, Decisions): what doing nothing costs them against
 * their safety minimum, then the plan the backend selected and its fee. Every amount is an API
 * figure (No action's lowest minimum cash against the treasury floor; the branch funding cost).
 */
const lead = computed(() => {
  const b = state.body
  if (!b) return ''
  if (search.value) return 'This search looks for a path that breaks your safety minimum; it is not a forecast.'
  if (b.status === 'pending') return 'The plans are still being tried on this shock; nothing is chosen yet.'
  if (b.status === 'all_infeasible') return 'No plan keeps you above your safety minimum here; this needs a person to decide.'
  const g = gap.value
  let first = ''
  if (g?.check.state === 'breached') {
    first = `Doing nothing leaves you ${formatMoney(-g.check.gap, g.min.currency)} under your safety minimum${firstDue.value}.`
  } else if (g?.check.state === 'kept') {
    first = 'Doing nothing keeps you above your safety minimum.'
  } else if (g) {
    first = "We can't tell yet whether doing nothing keeps you above your safety minimum."
  }
  const chosen = policies.value.find((p) => p.policy === b.selected)
  if (!chosen) return first || 'No plan is chosen yet.'
  // the backend's pick is the best ranked, not always a covering one: its own rows say which
  const n = chosen.rows.length
  let second
  if (chosen.policy === 'no-action') {
    second = chosen.breached || chosen.unmet ? 'No plan does better.' : 'No plan needs to move money.'
  } else if (chosen.breached) {
    second = `${PLANS[chosen.policy]} is best, yet short in ${chosen.breached} of ${n} what-if${n === 1 ? '' : 's'}.`
  } else if (chosen.unmet) {
    second = `${PLANS[chosen.policy]} is best, yet misses ${chosen.unmet} payment${chosen.unmet === 1 ? '' : 's'}.`
  } else {
    second = `${PLANS_DOING[chosen.policy]} keeps you covered for ${feeWords(chosen.rows)}.`
  }
  return `${first} ${second}`.trim()
})

const hoursAt = (asOf, at) => Math.round((Date.parse(at) - Date.parse(asOf)) / 3_600_000)
const timed = (row) => Number.isFinite(row.h) // a time that does not parse is left out, never "hNaN"

/**
 * The cash observed, each deadline and arrival of the account, and the delayed receipt the family
 * moves, in whole hours from the world's epoch (h0) when the world file describes this snapshot,
 * else from the account's observation.
 */
const timing = computed(() => {
  const t = state.body?.treasury
  const a = account.value
  if (!t || !a) return []
  const h0 = worldFor(t.snapshot_id)?.epoch ?? a.as_of
  const rows = [{ key: 'cash', h: hoursAt(h0, a.as_of), what: `${a.buckets.settled ? money(a.buckets.settled) : 'Unknown'} settled cash observed on ${a.id}` }]
  for (const o of t.obligations.filter((x) => x.account === a.id)) {
    rows.push({ key: `o:${o.obligation_id}`, h: hoursAt(h0, o.due_at), what: `${o.kind} ${money(o.amount)} due (${o.obligation_id})` })
  }
  const delay = family.value?.params ?? {}
  for (const f of a.buckets.pending_in) {
    const h = hoursAt(h0, f.expected_at)
    if (delay.flow_id === f.flow_id && Number.isInteger(delay.delay_h)) {
      rows.push({ key: `f:${f.flow_id}`, h: h + delay.delay_h,
        what: `${f.kind} ${money(f.amount)} arrives late in this scenario (h${h} + ${delay.delay_h} h)` })
    } else {
      rows.push({ key: `f:${f.flow_id}`, h, what: `${f.kind} ${money(f.amount)} arrives (${f.flow_id})` })
    }
  }
  return rows.filter(timed).sort((x, y) => x.h - y.h)
})

const details = ref(false)
</script>

<style scoped>
.lw-dec {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--lw-space-6);
}

@media (min-width: 1200px) {
  .lw-dec { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; }
}

.lw-dec > * { min-width: 0; }

.lw-dec__line { margin: var(--lw-space-2) 0; }

.lw-dec__explain {
  margin-top: var(--lw-space-4);
  padding: var(--lw-space-3);
  border-left: 4px solid var(--lw-brand);
  background: var(--lw-selected);
}

.lw-dec__timing {
  margin: 0 0 var(--lw-space-2);
  padding-left: var(--lw-space-4);
}

.lw-dec__rows {
  display: grid;
  gap: var(--lw-space-3);
}

.lw-dec__row {
  padding: var(--lw-space-3) var(--lw-space-4);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  min-width: 0;
}

.lw-dec__row.is-chosen {
  border-color: var(--lw-brand);
  box-shadow: inset 4px 0 0 var(--lw-brand);
  background: var(--lw-selected);
}

.lw-dec__head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2) var(--lw-space-3);
  align-items: center;
  min-height: var(--lw-target);
  cursor: pointer;
}

.lw-dec__head input { width: 20px; height: 20px; margin: 0; accent-color: var(--lw-brand); }
.lw-dec__head:focus-within { outline: 3px solid var(--lw-focus); outline-offset: 2px; border-radius: var(--lw-radius); }
.lw-dec__name { font-weight: 700; font-size: 18px; }

.lw-terms {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--lw-space-1) var(--lw-space-3);
  margin: var(--lw-space-2) 0;
}
.lw-terms dt { color: var(--lw-ink-muted); }
.lw-terms dd { margin: 0; overflow-wrap: anywhere; }
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

.lw-dec__review { margin-top: var(--lw-space-6); }
</style>

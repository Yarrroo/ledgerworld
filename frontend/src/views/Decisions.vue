<template>
  <ScreenShell title="Decisions" headline="Protect payroll. Preserve your reserve."
               :subtitle="subtitle" :lead="lead" :reading="state" :refresh="refresh">
    <template #default="{ body }">
    <p v-if="body.status === 'pending'" class="lw-note" role="status" data-test="pending">
      The comparison is still running; nothing is selected yet.
    </p>

    <section v-if="body.status === 'all_infeasible'" class="lw-alert" role="alert" data-test="escalation" data-panel="No feasible plan">
      <h2>No feasible plan: escalate, nothing can be approved</h2>
      <p>Earliest unmet: {{ body.escalation.earliest_unmet }}</p>
      <p>Binding constraint: {{ body.escalation.binding }}</p>
      <p>Escalate to: <strong>{{ body.escalation.contact }}</strong></p>
    </section>

    <ol v-if="!search" class="lw-dec__steps" aria-label="Decision progress" data-test="decision-steps">
      <li><span>1</span> Rehearse</li><li aria-current="step"><span>2</span> Compare</li><li><span>3</span> Review</li>
    </ol>
    <div class="lw-dec">
      <section v-if="!search" class="lw-dec__gap" aria-labelledby="gap-heading" data-panel="The gap we need to close" data-test="gap">
        <h2 id="gap-heading">The gap we need to close</h2>
        <div v-if="gap" data-test="gap-summary">
          <Tip :text="`${lead} Lowest point ${metricText(gap.min)}. ${floorTip}`" test="gap-tip">
            <strong :class="['lw-dec__figure', { 'is-bad': gap.check.state === 'breached' }]" data-test="gap-amount">{{ gap.check.state === 'breached' ? formatMoney(-gap.check.gap, gap.min.currency) : gap.check.state === 'kept' ? formatMoney(0, gap.min.currency) : 'Not assessed' }}</strong>
          </Tip>
          <p>{{ gapSentence }}</p>
        </div>
        <p v-else class="lw-time">No result for No action in this comparison yet.</p>

        <section class="lw-dec__waterfall" aria-labelledby="waterfall-heading" data-test="waterfall">
          <h3 id="waterfall-heading">Cash waterfall (before plan)</h3>
          <div v-if="waterfall" class="lw-dec__plot">
            <svg viewBox="0 0 560 280" role="img" aria-label="Observed starting cash, net cash change and No action's lowest remaining cash">
              <g class="lw-dec__axis">
                <g v-for="tick in waterfall.ticks" :key="tick">
                  <text x="70" :y="waterfall.y(tick) + 4" text-anchor="end">{{ formatMoney(tick, waterfall.currency) }}</text>
                </g>
                <line x1="82" x2="548" :y1="waterfall.y(0)" :y2="waterfall.y(0)" />
                <line x1="82" x2="82" y1="28" y2="230" />
              </g>
              <line v-if="waterfall.floor !== null" x1="82" x2="548" :y1="waterfall.y(waterfall.floor)" :y2="waterfall.y(waterfall.floor)" class="lw-dec__floor" data-test="waterfall-floor" />
              <g v-for="(bar, i) in waterfall.bars" :key="bar.label" :data-test="`waterfall-bar-${i}`">
                <rect :x="106 + i * 144" :y="waterfall.y(Math.max(bar.from, bar.to))" width="84" :height="Math.max(1, Math.abs(waterfall.y(bar.from) - waterfall.y(bar.to)))" :class="['lw-dec__bar', { 'is-out': bar.value < 0, 'is-remaining': i === 2 }]" />
                <text :x="148 + i * 144" :y="waterfall.y(Math.max(bar.from, bar.to)) - 9" text-anchor="middle" class="lw-dec__value">{{ formatMoney(bar.value, waterfall.currency) }}</text>
                <text :x="148 + i * 144" y="258" text-anchor="middle">{{ bar.label }}</text>
              </g>
            </svg>
            <Tip v-for="(bar, i) in waterfall.bars" :key="bar.label" class="lw-dec__mark" :style="{ left: `${(106 + i * 144) / 5.6}%` }" toggle>
              <button type="button" :aria-label="`${bar.label}: ${formatMoney(bar.value, waterfall.currency)}`" data-test="waterfall-point" />
              <template #tip>{{ bar.label }} · {{ formatMoney(bar.value, waterfall.currency) }}. {{ waterfall.source }}</template>
            </Tip>
          </div>
          <p v-else class="lw-time" data-test="waterfall-unavailable">Matching observed cash is unavailable; no waterfall is drawn.</p>
          <Tip v-if="gap?.floor" :text="floorTip" test="waterfall-floor-tip"><span class="lw-dec__floor-key">Reserve floor {{ metricText(gap.floor) }}</span></Tip>
          <Tip v-if="gap?.check.state === 'breached'" text="Reserve floor minus No action's lowest branch cash."><span class="lw-dec__chart-gap is-bad">↕ {{ formatMoney(-gap.check.gap, gap.min.currency) }} gap</span></Tip>
        </section>

        <section class="lw-dec__timing" data-test="timing" aria-labelledby="timing-heading">
          <h3 id="timing-heading">Key timing in this scenario</h3>
          <table v-if="timing.length" class="lw-table">
            <tbody><tr v-for="t in timing" :key="t.key" :data-at="t.h">
              <th scope="row"><Tip :text="`Simulated hour ${t.h} from the snapshot's observation${t.ref ? ` · ${t.ref}` : ''}.`">{{ t.h === 0 ? 'Now' : `In ${t.h}h` }}</Tip></th>
              <td>{{ t.what }}</td>
            </tr></tbody>
          </table>
          <p v-else class="lw-time">No matching treasury timing is available.</p>
        </section>
      </section>

      <section :aria-labelledby="search ? 'search-heading' : 'policies-heading'" class="lw-dec__policies"
               :data-test="search ? 'search' : 'policies'" :data-panel="search ? 'Search results' : 'Three ways forward'">
        <h2 v-if="search" id="search-heading">{{ LABELS.search }}</h2>
        <h2 v-else id="policies-heading">Three ways forward</h2>
        <div class="lw-dec__rows" :role="search ? undefined : 'radiogroup'" :aria-labelledby="search ? undefined : 'policies-heading'">
          <article v-for="p in policies" :key="p.policy" class="lw-dec__row" :class="{ 'is-chosen': p.policy === chosen }" :data-test="`policy-${p.policy}`">
            <label class="lw-dec__head">
              <input v-if="!search" type="radio" name="policy" :value="p.policy" :checked="p.policy === chosen" :disabled="body.status === 'pending'" @change="chosen = p.policy">
              <span><span class="lw-dec__name">{{ NAMES[p.policy] }}</span><span class="lw-dec__description">{{ DESCRIPTIONS[p.policy] }}</span></span>
              <Tip v-if="body.selected === p.policy" text="The comparison ranked this plan first. Selecting approves nothing.">
                <span class="lw-status lw-status--ok" data-test="selected" aria-label="Backend-selected plan">✓ Selected</span>
              </Tip>
            </label>
            <dl class="lw-dec__terms">
              <div><dt>Reserve outcome</dt><dd><Tip :text="`${p.breached ? `broken in ${p.breached} of ${p.rows.length} what-ifs` : `kept in all ${p.rows.length} what-ifs`}; lowest point ${p.min}; largest shortfall ${p.short}.`"><span :class="p.breached ? 'is-bad' : 'is-ok'">{{ p.rows.length === 1 ? (p.breached ? (['Not assessed', 'Unknown'].includes(p.short) ? '✕ Floor breached' : `✕ Breached by ${p.short}`) : '✓ Floor held') : (p.breached ? `✕ Broken in ${p.breached} of ${p.rows.length}` : `✓ Held in all ${p.rows.length}`) }}</span></Tip></dd></div>
              <div><dt>Funding cost</dt><dd data-test="cost"><Tip text="Each branch's scenario funding cost; the current plan's fee is set at review.">{{ p.cost }}</Tip></dd></div>
              <div><dt>Obligations unmet</dt><dd><Tip :text="`Payments missed, summed over ${p.rows.length} what-if${p.rows.length === 1 ? '' : 's'}.`">{{ p.unmet }}</Tip></dd></div>
            </dl>
          </article>
        </div>
        <div v-if="explained && !search" class="lw-dec__minimum" data-test="explanation" role="status" aria-live="polite">
          <h3>Minimum projected cash</h3>
          <Tip :text="`With ${NAMES[explained.policy]}. Lowest minimum cash across ${explained.rows.length} scenarios, from the branch ledgers; this choice approves nothing.`" test="minimum-tip">
            <strong :class="['lw-dec__figure', 'lw-dec__figure--minimum', { 'is-bad': minimumRelation === '<' }]">{{ explained.min }}</strong>
          </Tip>
          <Tip :text="floorTip"><span>{{ minimumRelation }} reserve floor {{ gap?.floor ? metricText(gap.floor) : 'Not assessed' }}</span></Tip>
        </div>
        <Tip v-if="reviewable" text="The backend-selected policy is worked out again on today's observed figures. You check bound terms before any money moves.">
          <RouterLink class="lw-button lw-dec__review-button" data-test="review-plan" :to="{ path: '/execution', query: { run_id: body.run_id, review: '1' } }">Review current plan<Arrow /></RouterLink>
        </Tip>
        <div class="lw-actions lw-dec__links">
          <Tip text="One row per scenario and plan, from each branch's realised ledger."><button type="button" class="lw-link" data-test="compare-details" @click="details = true">Compare scenario details<Arrow /></button></Tip>
          <Tip v-if="routeExists(router, '/simulation')" text="The run these plans branched from, round by round."><RouterLink data-test="open-simulation" :to="{ path: '/simulation', query: { run_id: body.run_id } }">Open simulation<Arrow /></RouterLink></Tip>
        </div>
        <p class="lw-time lw-dec__footnote">Scenario counts are not probabilities. Selection creates no approval.</p>
      </section>
    </div>
    <details class="lw-calc lw-dec__evidence" data-test="how-decisions">
      <summary>Source evidence</summary>
      <div class="lw-how__body">
        <p class="lw-source" data-test="cohort">Run {{ body.run_id }} · checkpoint round {{ body.checkpoint_round }} · cohort {{ body.cohort }} · {{ body.weight_kind }} · a scenario comparison, not a probability.</p>
        <p>Each plan faced the same shock in its own what-if. Selection creates no approval. The chart compares observed starting cash to No action's lowest cash; Cash change is their net difference, not a list of executed payments.</p>
        <table v-if="waterfall" class="lw-table" data-test="waterfall-table"><caption>Cash waterfall values</caption><tbody><tr v-for="bar in waterfall.bars" :key="bar.label"><th scope="row">{{ bar.label }}</th><td>{{ formatMoney(bar.value, waterfall.currency) }}</td></tr></tbody></table>
        <p v-if="replayed" data-test="replay">Replay · Results come from an earlier run of that branch, not from this session.</p>
        <section v-for="p in policies" :key="p.policy">
          <p data-test="weight">Policy {{ p.policy }} · {{ body.weight_kind }} · cohort {{ body.cohort }}</p>
          <ul class="lw-scenarios"><li v-for="r in p.rows" :key="r.branch_id" data-test="scenario">
            {{ r.scenario_id }} · {{ r.floor_kept ? 'Floor kept' : 'Floor breached' }} · Min cash {{ metricText(r.min_cash) }} · unmet {{ r.obligations_unmet }} · funding {{ money(r.funding_cost) }} · {{ r.replay ? `${LABELS.replay} · ` : '' }}{{ LABELS.branch }} {{ r.branch_id }}
          </li></ul>
        </section>
        <RouterLink v-if="routeExists(router, '/execution')" data-test="view-execution" :to="{ path: '/execution', query: { run_id: body.run_id } }">View execution</RouterLink>
      </div>
    </details>
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
    </template>
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
import Arrow from '../components/Arrow.vue'
import DetailSheet from '../components/DetailSheet.vue'
import Tip from '../components/Tip.vue'
import { familyOf, observedBy, worldFor } from '../api/world.js'
import {
  LABELS, OWED, PLANS, PLANS_DOING, ScreenShell, againstFloor, dayText,
  feesAcross, formatMoney, formatTime, getOverview, getTreasury, kindText, metricText, money, noDemoRun, replayed as replayedIn, request,
  routeExists, useReading
} from '../api/v1.js'

const ORDER = ['no-action', 'fixed-reserve', 'integrated']
const NAMES = { 'no-action': 'No action', 'fixed-reserve': 'Fixed reserve', integrated: 'Integrated plan' }
const DESCRIPTIONS = { 'no-action': 'Let the scenario play out.', 'fixed-reserve': 'Use existing cash buffer.', integrated: 'Draw eligible funding when needed.' }

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
const replayed = computed(() => replayedIn(state.body))
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
  if (rows.some((r) => r.min_cash?.minor == null || r.min_cash.currency !== rows[0].min_cash?.currency || r.min_cash.status !== 'known')) {
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
      cost: rows.length === 1 ? money(rows[0].funding_cost) : rows.length ? feesAcross(rows) : '',
      short: rows.length ? largestShort(rows) : '',
      minimum: lowestOf(rows),
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

/** The hero's one line, in the mockup's words: what kind of comparison this is, and of which shock. */
const subtitle = computed(() => {
  if (search.value) return LABELS.search
  const shock = family.value ? family.value.id.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase()) : ''
  const last = state.body?.status === 'pending' ? 'Still running' : 'Same shock for all plans'
  return ['Hypothetical comparison', shock, last].filter(Boolean).join(' · ')
})

/** The floor's source, for the tooltip on the safety minimum. */
const floorTip = computed(() => {
  const a = account.value
  if (!gap.value?.floor) return 'No reserve floor in this currency was read from the treasury.'
  return `Reserve floor of ${a.id}, from the treasury read as of ${formatTime(state.body.treasury.as_of).utc}.`
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
  const rows = [{ key: 'cash', h: hoursAt(h0, a.as_of), what: `${a.buckets.settled ? money(a.buckets.settled) : 'Unknown'} settled cash observed`, ref: a.id }]
  for (const o of t.obligations.filter((x) => x.account === a.id)) {
    rows.push({ key: `o:${o.obligation_id}`, h: hoursAt(h0, o.due_at), what: `${o.kind} ${money(o.amount)} due`, ref: o.obligation_id })
  }
  const delay = family.value?.params ?? {}
  for (const f of a.buckets.pending_in) {
    const h = hoursAt(h0, f.expected_at)
    if (delay.flow_id === f.flow_id && Number.isInteger(delay.delay_h)) {
      rows.push({ key: `f:${f.flow_id}`, h: h + delay.delay_h,
        what: `${f.kind} ${money(f.amount)} arrives late in this scenario`, ref: `h${h} + ${delay.delay_h} h · ${f.flow_id}` })
    } else {
      rows.push({ key: `f:${f.flow_id}`, h, what: `${kindText(f.kind)} ${money(f.amount)} arrives`, ref: f.flow_id })
    }
  }
  return rows.filter(timed).sort((x, y) => x.h - y.h)
})

const gapSentence = computed(() => {
  const g = gap.value
  if (!g || !['breached', 'kept'].includes(g.check.state)) return 'The reserve gap is not assessed from the available figures.'
  const payments = g.unmet ? `${g.unmet} obligation${g.unmet === 1 ? '' : 's'} unmet` : 'Every obligation met'
  return `${payments}, ${g.check.state === 'breached' ? 'but cash falls below your reserve floor' : 'and your reserve floor holds'}.`
})
const minimumRelation = computed(() => {
  const check = againstFloor(explained.value?.minimum, floorIn(explained.value?.minimum?.currency))
  if (!['breached', 'kept'].includes(check.state)) return 'Not assessed against'
  return check.gap === 0 ? '=' : check.gap > 0 ? '>' : '<'
})

/** A bridge between two sourced figures, not a reconstruction of branch payments. Without
 * matching known currency and state there is no bridge; an unknown is never a zero bar. */
const waterfall = computed(() => {
  const start = account.value?.buckets.settled
  const end = gap.value?.min
  const usable = (m) => Number.isSafeInteger(m?.minor) && (!m.status || m.status === 'known')
  if (!usable(start) || !usable(end) || start.currency !== end.currency || search.value || account.value.observability !== 'known') return null
  const delta = end.minor - start.minor
  if (!Number.isSafeInteger(delta)) return null
  const floor = gap.value.floor
  const floorMinor = usable(floor) ? floor.minor : null
  const top = Math.max(0, start.minor, end.minor, floorMinor ?? 0)
  const bottom = Math.min(0, start.minor, end.minor, floorMinor ?? 0)
  const span = top - bottom || 1
  const y = (n) => 230 - (n - bottom) / span * 190
  return {
    currency: start.currency, floor: floorMinor, y,
    ticks: [bottom, bottom + Math.round(span / 2), top].filter((n, i, all) => all.indexOf(n) === i),
    bars: [
      { label: 'Starting cash', from: 0, to: start.minor, value: start.minor },
      { label: 'Cash change', from: start.minor, to: end.minor, value: delta },
      { label: 'Remaining', from: 0, to: end.minor, value: end.minor }
    ],
    source: `Observed cash from ${account.value.id} as of ${formatTime(account.value.as_of).utc}; remaining is No action's lowest branch cash. Cash change is their net difference, not a payment attribution.`
  }
})

const details = ref(false)
</script>

<style scoped>
.lw-dec { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--lw-space-8); }
.lw-dec > * { min-width: 0; }
.lw-dec h2 { margin: 0 0 16px; font-size: 36px; }
.lw-dec h3 { margin: 0 0 16px; font: 600 18px var(--lw-font-text); }
.lw-dec__steps { display: flex; flex-wrap: wrap; gap: 32px; list-style: none; padding: 0; margin: 4px 0 32px; }
.lw-dec__steps li { display: flex; align-items: center; gap: 12px; }
.lw-dec__steps li:not(:last-child)::after { content: ''; width: 64px; border-top: 1px solid var(--lw-rule); margin-left: 12px; }
.lw-dec__steps span { display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid var(--lw-ink-muted); border-radius: 50%; }
.lw-dec__steps [aria-current] { font-weight: 600; }
.lw-dec__steps [aria-current] span { background: var(--lw-brand); color: var(--lw-on-brand); border-color: var(--lw-brand); }
.lw-dec__figure { display: block; font: 600 clamp(56px, 5vw, 80px)/1.1 var(--lw-font-heading); letter-spacing: -0.04em; overflow-wrap: anywhere; }
.is-bad { color: var(--lw-bad-text); }
.is-ok { color: var(--lw-ok-text); }
.lw-dec__waterfall, .lw-dec__timing { margin-top: 32px; }
.lw-dec__plot { position: relative; }
.lw-dec__plot svg { width: 100%; height: auto; display: block; overflow: visible; }
.lw-dec__plot text { fill: var(--lw-ink); font: 14px var(--lw-font-text); }
.lw-dec__plot .lw-dec__axis text { fill: var(--lw-ink-muted); font-size: 12px; }
.lw-dec__axis line { stroke: var(--lw-ink-muted); stroke-width: 1; }
.lw-dec__floor { stroke: var(--lw-ink-muted); stroke-dasharray: 6 6; }
.lw-dec__bar { fill: var(--lw-brand); }
.lw-dec__bar.is-out { fill: var(--lw-bad); }
.lw-dec__bar.is-remaining { fill: var(--lw-ok); opacity: 0.55; }
.lw-dec__plot .lw-dec__value { font-weight: 600; }
.lw-dec__mark { position: absolute; top: 13%; width: 15%; height: 70%; }
.lw-dec__mark button { width: 100%; height: 100%; min-height: 44px; background: transparent; border: 0; cursor: help; }
.lw-dec__floor-key { font-size: 13px; color: var(--lw-ink-muted); }
.lw-dec__floor-key::before { content: ''; display: inline-block; width: 24px; border-top: 1px dashed currentColor; vertical-align: middle; margin-right: 8px; }
.lw-dec__timing th { white-space: nowrap; text-align: left; }
.lw-dec__timing td { color: var(--lw-ink-muted); white-space: normal; overflow-wrap: anywhere; }
.lw-dec__row { padding: 16px 12px; border-top: 1px solid var(--lw-rule); min-width: 0; }
.lw-dec__row.is-chosen { background: var(--lw-selected); }
.lw-dec__head { display: flex; gap: 16px; align-items: flex-start; min-height: 44px; cursor: pointer; }
.lw-dec__head input { width: 24px; height: 24px; margin: 6px 0 0; flex-shrink: 0; accent-color: var(--lw-brand); }
.lw-dec__head:focus-within { outline: 3px solid var(--lw-focus); outline-offset: 2px; }
.lw-dec__name { display: block; font: 600 26px/1.15 var(--lw-font-heading); }
.lw-dec__description { display: block; margin-top: 4px; color: var(--lw-ink-muted); font-size: 14px; }
.lw-dec__terms { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 12px; margin: 16px 0 0 40px; font-size: 13px; }
.lw-dec__terms > div { min-width: 0; }
.lw-dec__terms > div + div { padding-left: 12px; border-left: 1px solid var(--lw-rule); }
.lw-dec__terms dt { color: var(--lw-ink-muted); margin-bottom: 6px; }
.lw-dec__terms dd { margin: 0; overflow-wrap: anywhere; }
.lw-dec__minimum { border-top: 1px solid var(--lw-rule); margin-top: 8px; padding-top: 20px; }
.lw-dec__minimum h3 { margin-bottom: 4px; }
.lw-dec__minimum > .lw-tip { display: inline-block; margin-right: 8px; }
.lw-dec__figure--minimum { font-size: 48px; color: var(--lw-brand); }
.lw-dec__review-button { width: 100%; margin-top: 16px; justify-content: center; }
.lw-dec__policies > .lw-tip { display: block; }
.lw-dec__figure--minimum.is-bad { color: var(--lw-bad-text); }
.lw-dec__chart-gap { margin-left: 16px; font-size: 13px; }
.lw-dec__links { justify-content: space-between; margin-top: 12px; }
.lw-dec__links button { padding: 0; border: 0; background: transparent; color: var(--lw-brand); text-decoration: underline; cursor: pointer; }
.lw-dec__links a, .lw-dec__links button { display: inline-flex; gap: 10px; align-items: center; min-height: 44px; font-size: 13px; }
.lw-dec__footnote { border-top: 1px solid var(--lw-rule); padding-top: 12px; margin-top: 12px; font-size: 12px; }
.lw-dec__evidence { margin-top: 24px; }
.lw-scenarios { padding-left: 20px; }
.lw-scenarios li { padding: 8px 0; overflow-wrap: anywhere; }
@media (min-width: 1200px) {
  .lw-dec { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; }
  .lw-dec__policies { border-left: 1px solid var(--lw-rule); padding-left: 28px; }
}
@media (max-width: 599px) {
  .lw-dec h2 { font-size: 30px; }
  .lw-dec__plot text, .lw-dec__plot .lw-dec__axis text { font-size: 20px; }
  .lw-dec__steps { gap: 14px; font-size: 13px; }
  .lw-dec__steps li { gap: 6px; }
  .lw-dec__steps li::after { display: none; }
  .lw-dec__steps span { width: 30px; height: 30px; }
  .lw-dec__terms { margin-left: 0; gap: 8px; font-size: 12px; }
  .lw-dec__terms > div + div { padding-left: 8px; }
}
@media (forced-colors: active) { .lw-dec__bar { fill: CanvasText; } .lw-dec__bar.is-out { fill: GrayText; stroke: CanvasText; stroke-dasharray: 4 2; } }
</style>

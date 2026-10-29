<template>
  <ScreenShell title="Treasury" headline="Every dollar, accounted for." :subtitle="subtitle" :lead="lead"
               :reading="state" :refresh="refresh" :stale="stale">
    <template #action="{ body }">
      <Tip v-if="rehearse" test="rehearse-tip">
        <RouterLink class="lw-button" :to="rehearse" data-test="rehearse">Rehearse a cash shock<Arrow /></RouterLink>
        <template #tip>What if a payment arrives late? See how it ripples through your partners; it changes no
          figure here. Opens the prepared run in Simulation with the
          {{ accountName(account.id).toLowerCase() }} and snapshot {{ body.snapshot_id }}.</template>
      </Tip>
      <Tip v-else :text="rehearseWhy" test="rehearse-why">
        <button type="button" class="lw-button" disabled data-test="rehearse">Rehearse a cash shock</button>
      </Tip>
    </template>
    <template #default="{ body }">
    <p v-if="moved" class="lw-note" role="status" data-test="snapshot-moved">
      The link was made on snapshot {{ moved }}; this is snapshot {{ body.snapshot_id }}.
    </p>

    <p v-if="!accounts.length" class="lw-note" data-test="no-accounts">
      The API returned no treasury cash account for {{ body.snapshot_id }}: nothing to show.
    </p>
    <!-- one account needs no choice (MATCH.md 02): the selector shows only when there are several -->
    <section v-else-if="accounts.length > 1" class="lw-tre__accounts" aria-labelledby="accounts-heading" data-test="accounts">
      <h2 id="accounts-heading" class="lw-visually-hidden">Which account</h2>
      <div class="lw-tre__choices" role="radiogroup" aria-labelledby="accounts-heading" data-test="account-selector">
        <label v-for="a in accounts" :key="a.id" class="lw-tre__choice"
               :class="{ 'is-selected': a.id === account?.id, 'lw-row--focus': focus === `account:${a.id}` }"
               :data-test="`account-${a.id}`" :data-focus="`account:${a.id}`" tabindex="-1">
          <input type="radio" name="treasury-account" :value="a.id" :checked="a.id === account?.id"
                 @change="chosen = a.id">
          <Tip :text="`${a.currency} · ${a.observability === 'known' ? 'observed' : 'balance not observable'} · as of ${formatTime(a.as_of).utc}`">
            <span class="lw-tre__choice-id">{{ accountName(a.id) }}</span>
          </Tip>
        </label>
      </div>
      <p v-if="currencies > 1" class="lw-time" data-test="mixed">
        These accounts hold {{ currencies }} currencies; no figure here adds them together.
      </p>
    </section>

    <div v-if="account" class="lw-tre" :data-account="account.id" :data-focus="`account:${account.id}`"
         :class="{ 'lw-row--focus': focus === `account:${account.id}` }">
      <div class="lw-tre__main">
        <!-- the three figures -->
        <section class="lw-tre-strip" aria-label="Cash today" data-test="strip">
          <article v-for="m in figures" :key="m.key" class="lw-tre-metric" :data-test="m.key">
            <span class="lw-tre-metric__label">{{ m.label }}</span>
            <Tip :test="`tip-${m.key}`">
              <span class="lw-figure">{{ m.figure }}</span>
              <template #tip><span v-for="line in m.tip" :key="line" class="lw-tre-tipline">{{ line }}</span></template>
            </Tip>
          </article>
        </section>

        <!-- the account's buckets -->
        <section aria-labelledby="buckets-heading" data-test="buckets">
          <div class="lw-tre-head">
            <h2 id="buckets-heading">{{ accountName(account.id) }}</h2>
            <HowWeKnow test="how-treasury">
              Snapshot {{ body.snapshot_id }}, GET /api/v1/treasury, account {{ account.id }} in
              {{ account.currency }}. Settled cash is the settled balance; reserved is held by reservations;
              spendable S is settled − reserved − pledged − pending out + pending in arrived by now. The
              minimum is projected cash P; the reserve floor is checked on P.
            </HowWeKnow>
          </div>
          <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Cash buckets">
            <table class="lw-table lw-tre-table">
              <thead><tr><th scope="col">Cash bucket</th><th scope="col">Amount</th><th scope="col">Status</th></tr></thead>
              <tbody>
                <tr v-for="b in buckets" :key="b.key" :data-test="`bucket-${b.key}`">
                  <td>{{ b.label }}</td>
                  <td>
                    <Tip>{{ b.value }}<template #tip><span data-test="bucket-inputs">{{ b.input }} ·
                      {{ accountName(account.id, { currency: account.currency }) }} ({{ account.id }}) · ledger bucket,
                      GET /api/v1/treasury · as of {{ formatTime(account.as_of).utc }}<template v-if="b.note"> · {{ b.note }}</template></span></template></Tip>
                  </td>
                  <td><Tip :text="b.why"><span class="lw-dot" :class="`lw-dot--${b.tone}`">{{ b.status }}</span></Tip></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- obligations and arrivals -->
        <section aria-labelledby="rows-heading" data-test="rows">
          <h2 id="rows-heading">Obligations &amp; arrivals</h2>
          <div class="lw-table-wrap" tabindex="0" role="region" aria-label="Obligations and arrivals">
            <table class="lw-table lw-tre-table lw-tre__rows" data-test="obligations">
              <thead>
                <tr><th scope="col">Event</th><th scope="col">Timing</th><th scope="col">Amount</th><th scope="col">State</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in rows" :key="r.key" :data-row="r.id" :data-test="r.obligation ? `obligation-${r.id}` : undefined"
                    :data-focus="r.obligation ? `obligation:${r.id}` : `flow:${r.id}`" tabindex="-1"
                    :class="{ 'is-open': r.key === openRow, 'lw-row--focus': focus === (r.obligation ? `obligation:${r.id}` : `flow:${r.id}`) }">
                  <td data-label="Event">
                    <Tip :text="`${r.what} ${r.id}${r.mandatory ? ' · mandatory' : ''} · ${r.source}. Opens its details; it pays nothing.`">
                      <button type="button" class="lw-tre__open" :data-test="`row-${r.id}`" @click="openRow = r.key">
                        {{ capital(kindText(r.kind)) }}<span v-if="r.plain" class="lw-tre__plain"> ({{ r.plain }})</span>
                      </button>
                    </Tip>
                  </td>
                  <td data-label="Timing">
                    <Tip :text="`${hoursFrom(body.as_of, r.at)} · ${formatTime(r.at).utc} · ${formatTime(r.at).local}`">{{ hShort(body.as_of, r.at) }}</Tip>
                  </td>
                  <td data-label="Amount" class="lw-num">
                    <Tip :text="`${r.direction === 'in' ? 'Arrives' : 'Pays out'}; amount as served by the API`">{{ r.direction === 'in' ? '+' : '−' }}{{ money(r.amount) }}</Tip>
                  </td>
                  <td data-label="State">
                    <Tip :text="r.reservation ? `Reservation ${r.reservation}: set aside · ledger state: ${r.status}` : `Not set aside · ledger state: ${r.status}`">
                      <span class="lw-dot" :class="`lw-dot--${r.tone}`">{{ r.state }}</span>
                    </Tip>
                  </td>
                </tr>
                <tr v-if="!rows.length"><td colspan="4">No bill or money coming in on the {{ accountName(account.id).toLowerCase() }}</td></tr>
              </tbody>
            </table>
          </div>
          <details class="lw-calc lw-tre-calc" data-test="spend-calc">
            <summary>View calculation</summary>
            <div class="lw-calc__body">
              <div data-test="spend-calculation">
                <p>S(now) in {{ account.currency }}, terms from the API's buckets:</p>
                <p>{{ spend.line }}</p>
                <p v-if="spend.excluded">{{ spend.excluded }}</p>
              </div>
              <div v-if="account.low" data-test="calculation">
                <p>P {{ hoursFrom(body.as_of, account.low.t) }}, the lowest point, in {{ account.currency }}, terms from the API:</p>
                <p>{{ account.calc.line }}</p>
                <p v-if="account.calc.excluded">{{ account.calc.excluded }}</p>
              </div>
              <p>S counts settled, reserved, pledged and pending flows arrived by now; P counts settled cash,
                arrivals and outflows due by t, and every obligation due by t whether reserved or not. The
                results are the API's; this screen does not recompute them.</p>
            </div>
          </details>
        </section>
      </div>

      <aside class="lw-tre__side">
        <!-- spendable is not settled -->
        <section class="lw-tre-bridge" aria-labelledby="spend-heading" data-test="spend-bridge">
          <div class="lw-tre-head">
            <h2 id="spend-heading">Spendable is not settled</h2>
            <HowWeKnow test="how-spendable">
              Spendable S of {{ account.id }} · authority {{ account.authority }} · as of
              {{ formatTime(account.spendable.as_of || account.as_of).utc }}<template
                v-if="account.observability !== 'known'"> · balance not observable, authority reduced</template>.
            </HowWeKnow>
          </div>
          <dl class="lw-tre-list">
            <div v-for="t in bridge" :key="t.label"><dt>{{ t.label }}</dt><dd>{{ t.value }}</dd></div>
          </dl>
          <div class="lw-tre-bridge__result">
            <span>Spendable now</span>
            <Tip :text="`The API's spendable S · as of ${formatTime(account.spendable.as_of || account.as_of).utc}${leadSeen ? ` · ${leadSeen}` : ''}`">
              <span class="lw-figure" data-test="bridge-spendable">{{ metricText(account.spendable) }}</span>
            </Tip>
          </div>
          <p class="lw-tre-note">
            <Tip :text="metricStatus(account.spendable)">
              <span :class="['lw-status', `lw-status--${stateOf(account.spendable.status).tone}`]" data-test="spendable-status">
                {{ stateOf(account.spendable.status).icon }} {{ stateOf(account.spendable.status).word }}</span>
            </Tip>
            <span v-if="protects"> · Reservations protect {{ protects }}.</span>
          </p>
          <p v-if="account.observability !== 'known'" class="lw-note">
            We can't read this account's balance right now: settled cash reads Unknown and adds nothing.
          </p>
        </section>

        <!-- reserve coverage -->
        <section aria-labelledby="cover-heading" data-test="coverage">
          <h2 id="cover-heading">Reserve coverage</h2>
          <dl class="lw-tre-list" data-test="floor">
            <div>
              <dt>Minimum projected<template v-if="account.low"> (at {{ hShort(body.as_of, account.low.t) }})</template></dt>
              <dd>
                <Tip :text="account.low ? `Lowest projected cash P, from the API's points, at ${formatTime(account.low.t).utc}` : 'Lowest projected cash P: a point has no value'">
                  <span data-test="minimum">{{ account.low ? metricText(account.low.value) : 'Unknown' }}</span>
                </Tip>
              </dd>
            </div>
            <div>
              <dt>Reserve floor</dt>
              <dd>
                <Tip :text="account.floor ? `Reserve floor of the ${accountName(account.id).toLowerCase()}` : 'No reserve floor assessed for this account'">
                  <span data-test="floor-line">{{ account.floor ? metricText(account.floor) : 'Not assessed' }}</span>
                </Tip>
              </dd>
            </div>
            <div>
              <dt>Headroom</dt>
              <dd>
                <Tip v-if="account.floorCheck.state === 'breached'"
                     :text="`P at ${formatTime(account.low.t).utc} minus the reserve floor, from the API's points`">
                  <span class="lw-status lw-status--bad" data-test="shortfall">{{ formatMoney(-account.floorCheck.gap, account.currency) }} short on {{ dayText(account.low.t) }} ({{ hoursFrom(body.as_of, account.low.t) }})</span>
                </Tip>
                <Tip v-else text="The minimum less the reserve floor">
                  <span data-test="headroom">{{ account.floorCheck.state === 'kept' ? formatMoney(account.floorCheck.gap, account.currency) : FLOOR_WORDS[account.floorCheck.state] }}</span>
                </Tip>
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <Tip :text="`Lowest projected cash P checked against the reserve floor: ${account.floorCheck.state}`">
                  <span :class="['lw-status', `lw-status--${STATES[account.floorCheck.state].tone}`]" data-test="floor-status">
                    <span aria-hidden="true">{{ STATES[account.floorCheck.state].icon }}</span>
                    <span>{{ FLOOR_WORDS[account.floorCheck.state] }}</span>
                  </span>
                </Tip>
              </dd>
            </div>
          </dl>
        </section>

        <!-- the projected cash path -->
        <section aria-labelledby="path-heading" data-test="outlook">
          <h2 id="path-heading">{{ HORIZON_H }}-hour projected cash path</h2>
          <p class="lw-tre-sub">Observed snapshot · {{ HORIZON_H }}-hour horizon</p>
          <CashOutlook :points="pathPoints" :floor="account.floor" :low-at="account.low?.t ?? null" :as-of="body.as_of"
                       :currency="account.currency" :horizon="HORIZON_H" />
        </section>
      </aside>
    </div>

    <DetailSheet :open="Boolean(detail)" :title="detail ? `${kindText(detail.kind)} · ${detail.id}` : 'Details'" test="row-detail"
                 @close="openRow = null">
      <template v-if="detail">
        <dl>
          <dt>Kind</dt><dd>{{ detail.what }}</dd>
          <dt>Amount</dt><dd>{{ money(detail.amount) }} · {{ detail.direction }}</dd>
          <dt>{{ detail.obligation ? 'Deadline' : 'Expected' }}</dt>
          <dd>{{ formatTime(detail.at).utc }} · {{ formatTime(detail.at).local }} · {{ hoursFrom(body?.as_of, detail.at) }}</dd>
          <dt>Reservation</dt><dd>{{ detail.reservation || 'not reserved' }}</dd>
          <dt>Account</dt><dd>{{ account ? accountName(account.id, { currency: account.currency }) : '' }}</dd>
          <dt>Source</dt><dd>{{ detail.source }}</dd>
          <dt>Current state</dt><dd data-test="row-state">{{ detail.status }}</dd>
        </dl>
        <p class="lw-time">Read-only: this screen makes no payment, edit or import.</p>
      </template>
    </DetailSheet>
    </template>
  </ScreenShell>
</template>

<script setup>
/**
 * Treasury as mockup 02 (prp/2026-10-29-ux-pass/MATCH.md, 02 Treasury): the hero and Rehearse a
 * cash shock; three figures (settled, reserved, spendable now); the account's cash buckets and
 * its obligations and arrivals, each with a status dot, and one View calculation fold; beside
 * them, spendable is not settled (the API's buckets less what is held, to the API's own S), the
 * reserve coverage of the lowest projected point P, and the 72-hour projected cash path. One
 * account is shown at a time; a selector appears only when the API serves several. Every figure
 * is the API's; the browser formats and never recomputes. Nothing is summed across accounts, so
 * mixed currencies never meet.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Arrow from '../components/Arrow.vue'
import CashOutlook from '../components/CashOutlook.vue'
import DetailSheet from '../components/DetailSheet.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
import Tip from '../components/Tip.vue'
import {
  FLOOR_WORDS, OWED, STATES, ScreenShell, accountName, againstFloor, amountWords, contextKey, dataKind, dayText, formatAmount, formatMoney,
  formatTime, getOverview, getTreasury, hoursFrom, kindText, lastSeen, listWords, metricStatus, metricText, money,
  pendingFlows, projectionTerms, routeExists, staleOf, stateOf, useFocusTarget, useReading
} from '../api/v1.js'

const route = useRoute()
const router = useRouter()

/** The API's projection horizon (backend views.HORIZON): P holds flat after its last move. */
const HORIZON_H = 72
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1)
/** "h12": whole simulated hours from the reading's as_of, as the mockup's tables write timing. */
function hShort (asOf, at) {
  const h = Math.round((Date.parse(at) - Date.parse(asOf)) / 3_600_000)
  return Number.isNaN(h) ? 'unknown' : `h${h}`
}

/** The treasury read, and the prepared run of the same context when the overview answers. */
async function load () {
  const [treasury, overview] = await Promise.all([
    getTreasury(),
    getOverview().catch((error) => ({ error }))
  ])
  let demo = { run_id: null, why: 'Could not read the prepared run from the overview; reload the page' }
  if (!overview.error) {
    demo = contextKey(overview) === contextKey(treasury)
      ? { run_id: overview.demo?.run_id ?? null, why: 'No demonstration run is prepared: prepare one with the operator command first' }
      : { run_id: null, why: 'The overview answered for another snapshot or mode; reload the page' }
  }
  return { ...treasury, demo }
}

const { state, refresh } = useReading(load)
// an account whose spendable figure is its last observed value, for the shell's stale band
const stale = computed(() => staleOf((state.body?.accounts ?? [])
  .map((a) => ({ account_id: a.id, status: a.spendable.status, as_of: a.spendable.as_of ?? a.as_of }))))
// a deep link (Overview's cash, spendable, next obligation) names an account or an obligation row
const { focus, moved } = useFocusTarget(state)

/** The account's lowest API point P, first reached; null when any point has no value. */
function lowest (projected) {
  if (!projected.length || projected.some((p) => p.value.minor === null)) return null
  return projected.reduce((low, p) => (p.value.minor < low.value.minor ? p : low))
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
      calc: low ? projectionTerms(a, low.t, body.obligations, body.as_of) : null
    }
  })
})
const currencies = computed(() => new Set(accounts.value.map((a) => a.currency)).size)

// The operating account by default, or the one the URL names (?account=, or a deep link to an
// account or to an obligation, which selects the account the obligation is on); a re-read keeps
// the choice.
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
watch(() => account.value?.id, () => { openRow.value = null })

/** What the account's reservations hold money for: owed obligations, and pending outflows reserved on their own. */
const heldFor = computed(() => {
  const a = account.value
  if (!a) return []
  const owed = state.body.obligations.filter((o) => o.account === a.id && o.reservation_id && OWED.has(o.state ?? 'open'))
  const held = new Set(owed.map((o) => o.reservation_id))
  return [...new Set([...owed, ...a.buckets.pending_out.filter((f) => f.reservation_id && !held.has(f.reservation_id))]
    .map((x) => kindText(x.kind)))]
})
const protects = computed(() => (account.value?.buckets.reserved.minor && heldFor.value.length ? listWords(heldFor.value) : ''))
const reservedLabel = computed(() => (heldFor.value.length ? `Reserved for ${listWords(heldFor.value)}` : 'Reserved'))

const fa = (m, c) => formatAmount(m.minor, c)
const arrived = (f) => Date.parse(f.expected_at) <= Date.parse(state.body.as_of)

/** The three figures, each with the inputs the API served for it, for its tooltip. */
const figures = computed(() => {
  const a = account.value
  const b = a.buckets
  const where = `${accountName(a.id, { currency: a.currency })} (${a.id}) · as of ${formatTime(a.as_of).utc}`
  return [
    { key: 'settled', label: 'Settled cash', figure: b.settled ? money(b.settled) : 'Unknown',
      tip: ['The settled balance, from the ledger.', where] },
    { key: 'reserved', label: reservedLabel.value, figure: money(b.reserved),
      tip: ['Held by reservations against obligations; not spendable.', where] },
    { key: 'spendable', label: 'Spendable now', figure: metricText(a.spendable),
      tip: ['Settled − reserved − pledged − pending out + pending in arrived by now, as served by the API.',
        where, metricStatus(a.spendable), ...(leadSeen.value ? [leadSeen.value] : [])] }
  ]
})

/** S's terms beside the API's own S: buckets now, and the flows that are not yet due named. */
const spend = computed(() => {
  const a = account.value
  const c = a.currency
  const b = a.buckets
  const terms = [b.settled ? `${formatAmount(b.settled.minor, c)} settled` : 'Unknown settled',
    `- ${formatAmount(b.reserved.minor, c)} reserved`, `- ${formatAmount(b.pledged.minor, c)} pledged`]
  const later = []
  for (const f of pendingFlows(a)) {
    const sign = f.direction === 'in' ? '+' : '-'
    if (arrived(f)) terms.push(`${sign} ${formatAmount(f.amount.minor, c)} ${kindText(f.kind)}`)
    else later.push(`${kindText(f.kind)} ${f.flow_id} ${f.direction} (expected ${hoursFrom(state.body.as_of, f.expected_at)})`)
  }
  return {
    line: `${terms.join(' ')} = ${metricText(a.spendable)} (API)`,
    excluded: later.length ? `not yet due, so not in S: ${later.join(', ')}` : ''
  }
})

/** Spendable is not settled: the API's buckets that S takes from settled cash, each non-zero term once. */
const bridge = computed(() => {
  const a = account.value
  const b = a.buckets
  const less = (m) => `−${money(m)}`
  const out = [{ label: 'Settled cash', value: b.settled ? money(b.settled) : 'Unknown' }]
  if (b.reserved.minor || !b.pledged.minor) out.push({ label: `Less: ${reservedLabel.value.toLowerCase()}`, value: less(b.reserved) })
  if (b.pledged.minor) out.push({ label: 'Less: pledged', value: less(b.pledged) })
  for (const f of pendingFlows(a).filter(arrived)) {
    out.push({ label: `${f.direction === 'in' ? 'Plus' : 'Less'}: ${kindText(f.kind)}`, value: f.direction === 'in' ? `+${money(f.amount)}` : less(f.amount) })
  }
  return out
})

// The account's ledger buckets, as mockup 02's table: settled, reserved, pledged, pending out.
const buckets = computed(() => {
  const a = account.value
  const b = a.buckets
  const outs = b.pending_out
  return [
    { key: 'settled', label: 'Settled', value: b.settled ? money(b.settled) : 'Unknown', input: 'settled balance',
      status: b.settled ? 'Known' : 'Unknown', tone: b.settled ? 'ok' : 'warn',
      why: b.settled ? 'Observed balance' : 'Balance not observable: Unknown has no numeric value and adds nothing',
      note: b.settled ? '' : 'Balance not observable' },
    { key: 'reserved', label: reservedLabel.value, value: money(b.reserved), input: 'reservations held against obligations',
      status: b.reserved.minor ? 'Held' : 'Known', tone: b.reserved.minor ? 'held' : 'ok',
      why: b.reserved.minor ? 'Set aside: not spendable until the obligation is paid or released' : 'Nothing is set aside' },
    { key: 'pledged', label: 'Pledged', value: money(b.pledged), input: 'balances pledged as collateral',
      status: 'Known', tone: 'ok', why: 'Pledged as collateral, from the ledger' },
    { key: 'pending-out', label: 'Pending out', value: outs.length ? outs.map((f) => money(f.amount)).join(' · ') : money({ minor: 0, currency: a.currency }),
      input: outs.length ? `outflows not yet settled: ${outs.map((f) => `${kindText(f.kind)} ${f.flow_id}`).join(', ')}` : 'outflows not yet settled: none',
      status: 'Known', tone: 'ok', why: 'Paying out, not yet settled' }
  ]
})

/** A plain word for what a kind is, beside its name (mockup 02: "Receivable (customer payment)"). */
const PLAIN = {
  receivable: 'customer payment',
  payroll: 'employee payments',
  exchange_withdrawal: 'market inflow',
  supplier_payment: 'supplier invoice',
  tax: 'tax authority',
  rent: 'landlord'
}

/** The state a row is in, as a dot and one word. */
function rowState (r) {
  if (!r.obligation) {
    if (r.direction === 'in') return { state: 'Expected', tone: 'ok' }
    return r.reservation ? { state: 'Reserved', tone: 'held' } : { state: 'Pending', tone: 'held' }
  }
  if (r.status === 'missed') return { state: 'Missed', tone: 'bad' }
  if (r.status === 'open') return r.reservation ? { state: 'Reserved', tone: 'held' } : { state: 'Open', tone: 'warn' }
  return { state: capital(kindText(r.status)), tone: 'muted' }
}

// The account's arrivals, outflows and obligations, in time order.
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
    .map((r) => ({ ...r, plain: PLAIN[r.kind] ?? '', ...rowState(r) }))
})
const openRow = ref(null)
const detail = computed(() => rows.value.find((r) => r.key === openRow.value) ?? null)

/**
 * The chart's points: the account's API points, each with what moves P there (a flow or an
 * obligation at that instant; at the first point, those already due and still pending). A label
 * only: P itself is the API's.
 */
const pathPoints = computed(() => {
  const a = account.value
  if (!a) return []
  const first = a.projected[0]?.t
  const moves = rows.value.filter((r) => r.obligation ? OWED.has(r.status) : true)
  return a.projected.map((p) => ({
    ...p,
    events: moves.filter((r) => (p.t === first ? Date.parse(r.at) <= Date.parse(p.t) : r.at === p.t))
      .map((r) => ({ ref: r.id, kind: r.kind, direction: r.direction, amount: r.amount }))
  }))
})

/**
 * The finance lead's answer for the selected account (COPY.md): cash in the bank, what is set
 * aside and for which obligations, and what is free to spend; every amount is the API's.
 */
const lead = computed(() => {
  const a = account.value
  if (!a) return 'There is no cash account to show for this snapshot.'
  const b = a.buckets
  const cash = b.settled ? money(b.settled) : 'An unknown amount'
  const s = a.spendable
  const free = s.minor !== null && s.minor < 0
    ? `so nothing is free to spend: you are ${formatMoney(-s.minor, s.currency)} short.`
    : `so ${amountWords(s)} is free to spend.`
  if (!b.reserved.minor) return `${cash} in the bank; nothing is set aside, ${free}`
  return `${cash} in the bank; ${money(b.reserved)} is set aside for ${heldFor.value.length ? listWords(heldFor.value) : 'upcoming bills'}, ${free}`
})

const leadSeen = computed(() => (account.value ? lastSeen(account.value.spendable) : ''))

/** The hero's one line: what this page holds, and which reading it is (the header names the data kind). */
const subtitle = computed(() => {
  const kind = dataKind(state.body)
  return `Cash, commitments and deadlines / ${kind === 'Synthetic data' ? 'Observed snapshot' : kind}`
})

// The prepared run, carrying the account and snapshot.
const rehearse = computed(() => {
  const body = state.body
  if (state.status !== 'loaded' || !account.value || !body.demo.run_id || !routeExists(router, '/simulation')) return null
  return { path: '/simulation', query: { run_id: body.demo.run_id, account: account.value.id, snapshot: body.snapshot_id } }
})
const rehearseWhy = computed(() => {
  if (state.status === 'loading') return 'Loading'
  if (state.status === 'error') return 'Last loaded, not current; reload the page first'
  if (!account.value) return 'There is no cash account to carry into the simulation'
  if (!state.body.demo.run_id) return state.body.demo.why
  return 'The simulation screen is not part of this build'
})
</script>

<style scoped>
.lw-tre__choices {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-3);
  margin-bottom: var(--lw-space-6);
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
.lw-tre__choice.is-selected { background: var(--lw-selected); border-color: var(--lw-brand); }
.lw-tre__choice:focus-within { outline: 3px solid var(--lw-focus); outline-offset: 2px; }
.lw-tre__choice-id { font-weight: 700; overflow-wrap: anywhere; }

/* two columns at the mockup's width: the account on the left, the answer and the path on the right */
.lw-tre {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--lw-space-8);
}

.lw-tre__main,
.lw-tre__side {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
  gap: var(--lw-space-6);
  min-width: 0;
}

.lw-tre__side > section + section {
  padding-top: var(--lw-space-6);
  border-top: 1px solid var(--lw-rule);
}

@media (min-width: 1200px) {
  .lw-tre { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); }

  .lw-tre__side {
    padding-left: var(--lw-space-6);
    border-left: 1px solid var(--lw-rule);
  }
}

@media (max-width: 1199px) {
  .lw-tre__side {
    padding-top: var(--lw-space-6);
    border-top: 1px solid var(--lw-rule);
  }
}

.lw-tre h2 {
  margin: 0 0 var(--lw-space-3) !important;
  font-size: 30px !important;
  line-height: 38px !important;
  font-weight: 500 !important;
}

.lw-tre-head {
  display: flex;
  align-items: baseline;
  gap: var(--lw-space-2);
}

.lw-tre-sub {
  margin: calc(-1 * var(--lw-space-2)) 0 var(--lw-space-2);
  color: var(--lw-ink-muted);
}

.lw-tre-tipline { display: block; }

/* the three figures, separated by thin rules, no boxes */
.lw-tre-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  padding-bottom: var(--lw-space-6);
  border-bottom: 1px solid var(--lw-rule);
}

.lw-tre-metric {
  display: grid;
  align-content: start;
  gap: var(--lw-space-1);
  min-width: 0;
  padding: 0 var(--lw-space-6);
  border-left: 1px solid var(--lw-rule);
}

.lw-tre-metric:first-child {
  padding-left: 0;
  border-left: 0;
}

.lw-tre-metric__label {
  color: var(--lw-ink-muted);
  font-size: 16px;
}

.lw-tre .lw-figure {
  font-family: var(--lw-font-heading);
  font-size: 40px;
  line-height: 48px;
  font-weight: 600;
  overflow-wrap: normal;
}

/* tables as the mockup: a light header row, amounts and states on one line */
.lw-tre-table th {
  background: var(--lw-surface-raised);
  font-weight: 500;
}

.lw-tre__plain { color: var(--lw-ink-muted); font-weight: 400; }

.lw-dot {
  display: inline-flex;
  align-items: center;
  gap: var(--lw-space-2);
  white-space: nowrap;
}

.lw-dot::before {
  content: '';
  flex: none;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--lw-ink-muted);
}

.lw-dot--ok::before { background: var(--lw-ok); }
.lw-dot--held::before { background: #E0A526; }
.lw-dot--warn::before { background: var(--lw-warn); }
.lw-dot--bad::before { background: var(--lw-bad); }

.lw-tre__open {
  min-height: var(--lw-target);
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.lw-tre__open:hover { text-decoration: underline; }

.lw-tre__rows tr.is-open td { background: var(--lw-selected); }

.lw-tre-calc { margin-top: var(--lw-space-3); }

/* label · value rows, the value right-aligned */
.lw-tre-list {
  display: grid;
  gap: var(--lw-space-1);
  margin: 0;
}

.lw-tre-list div {
  display: flex;
  justify-content: space-between;
  gap: var(--lw-space-4);
}

.lw-tre-list dt { color: var(--lw-ink-muted); }
.lw-tre-list dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }

.lw-tre-bridge__result {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--lw-space-4);
  margin-top: var(--lw-space-3);
  padding-top: var(--lw-space-3);
  border-top: 1px solid var(--lw-rule);
}

.lw-tre-bridge .lw-figure {
  font-size: 32px;
  line-height: 40px;
}

.lw-tre-note {
  margin: var(--lw-space-2) 0 0;
  color: var(--lw-ink-muted);
}

@media (max-width: 767px) {
  .lw-tre .lw-figure {
    font-size: 28px;
    line-height: 34px;
  }

  .lw-tre h2 {
    font-size: 24px !important;
    line-height: 30px !important;
  }

  .lw-tre-metric { padding: 0 var(--lw-space-3); }

  /* obligations and arrivals as labelled stacked rows */
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

  .lw-tre__rows td[data-label='Event']::before { content: none; }
}

@media (max-width: 479px) {
  .lw-tre-strip {
    grid-template-columns: minmax(0, 1fr);
    row-gap: var(--lw-space-3);
  }

  .lw-tre-metric {
    padding: var(--lw-space-3) 0 0;
    border-left: 0;
    border-top: 1px solid var(--lw-rule);
  }

  .lw-tre-metric:first-child { padding-top: 0; border-top: 0; }
}
</style>

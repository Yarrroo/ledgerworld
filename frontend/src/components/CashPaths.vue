<template>
  <section class="lw-live-panel lw-cash-panel" aria-labelledby="cash-title" data-test="cash">
    <h2 id="cash-title">Treasury cash path (72-hour outlook)</h2>
    <p v-if="at === null" class="lw-live-empty" data-test="cash-unloaded">Round not loaded</p>
    <template v-else>
      <div v-if="series.length" class="lw-cash-chart">
        <div ref="frame" class="lw-cash-chart__frame">
          <svg :width="width" height="190" role="img" aria-label="Policy cash paths and reserve floor, hours from the run's start" data-test="policy-chart">
            <g class="lw-cash-chart__axes" aria-hidden="true">
              <g v-for="v in yTicks" :key="v"><line x1="64" :x2="width - 16" :y1="y(v)" :y2="y(v)"/><text x="58" :y="y(v) + 4" text-anchor="end">{{ formatMoney(v, currency) }}</text></g>
              <text v-for="h in [0, 12, 24, 36, 48, 60, 72]" :key="h" :x="x(h)" y="170" text-anchor="middle">{{ h }}</text><text :x="width / 2" y="188" text-anchor="middle">Hours</text>
            </g>
            <line v-if="floorKnown" x1="64" :x2="width - 16" :y1="y(account.floor.minor)" :y2="y(account.floor.minor)" class="lw-cash-chart__floor" data-test="cash-floor" />
            <path v-for="s in series" :key="s.branch_id" :d="pathOf(s.points)" :class="['lw-cash-chart__line', `is-${s.policy ?? 'base'}`]" :data-policy="s.policy ?? 'base'" />
            <line v-if="cursorHour !== null" :x1="x(cursorHour)" :x2="x(cursorHour)" y1="12" y2="148" class="lw-cash-chart__cursor" data-test="cash-cursor" />
          </svg>
          <Tip v-for="p in chartPoints" :key="p.t" class="lw-cash-chart__point" :style="{ left: `${x(hour(p.t))}px`, top: '12px' }" toggle>
            <button type="button" data-test="cash-point" :aria-label="`h${hour(p.t)}: ${p.text}`" />
            <template #tip>h{{ hour(p.t) }} · {{ p.text }}</template>
          </Tip>
        </div>
        <div>
          <ul class="lw-cash-chart__legend" aria-label="Cash paths"><li v-for="s in series" :key="s.branch_id"><span :class="`is-${s.policy ?? 'base'}`" />{{ s.name }}{{ s.replay ? ' · Replay' : '' }}</li><li v-if="floorKnown"><span class="is-floor"/>Reserve floor ({{ money(account.floor) }})</li></ul>
          <p v-if="!floorKnown" class="lw-live-empty" data-test="floor-unavailable">Reserve floor unavailable</p>
          <Tip v-if="shortfall" :text="`No action's lowest known cash ${money(shortfall.low.value)} against reserve floor ${money(account.floor)}. ${shortfall.branch_id}`"><p class="lw-cash-chart__shortfall" data-test="cash-shortfall">! Treasury reserve shortfall without protection: <b>{{ formatMoney(shortfall.minor, currency) }} at h{{ hour(shortfall.low.t) }}</b></p></Tip>
        </div>
      </div>
      <p v-else class="lw-live-empty">No treasury cash path recorded for this run</p>
      <details class="lw-cash-values"><summary>Round {{ round }} values and data</summary><ul class="lw-cash"><li v-for="row in rows" :key="`${row.branch_id}|${row.account_id}`" class="lw-cash__row" :data-branch="row.branch_id"><span class="lw-cash__branch">{{ row.name }}</span><Tip class="lw-cash__value" :text="`${row.branch_id} · ${accountName(row.account_id, { owner: true })} · ${PLAIN.branch}${row.replay ? ` · ${PLAIN.replay}` : ''} · cash at round ${round}`"><span data-test="cash-value">{{ row.text }}</span></Tip></li></ul>
        <table v-if="series.length"><caption>Known policy cash points</caption><thead><tr><th>Policy</th><th>Hour</th><th>Cash</th></tr></thead><tbody><template v-for="s in series" :key="s.branch_id"><tr v-for="p in s.points" :key="p.t"><td>{{ s.name }}</td><td>{{ hour(p.t) }}</td><td>{{ metricText(p.value) }}</td></tr></template></tbody></table>
      </details>
    </template>
  </section>
</template>

<script setup>
/** Run-owned settled cash paths. Unknown points break the line; a shortfall needs a fully
 * known No action path and a same-currency reserve floor. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { PLAIN, PLANS, accountName, formatMoney, metricText, money } from '../api/v1.js'
import Tip from './Tip.vue'

const props = defineProps({
  round: { type: Number, default: null }, at: { type: Number, default: null },
  paths: { type: Array, default: () => [] }, branches: { type: Array, default: () => [] },
  account: { type: Object, default: null }, epoch: { type: Number, default: null }
})
const frame = ref(null)
const width = ref(640)
let observer = null
const measure = () => { if (frame.value?.clientWidth) width.value = Math.max(280, frame.value.clientWidth) }
onMounted(() => {
  if (window.ResizeObserver) observer = new ResizeObserver(measure)
  if (frame.value) observer?.observe(frame.value)
  measure()
})
watch(frame, (el, old) => {
  if (old) observer?.unobserve(old)
  if (el) observer?.observe(el)
  measure()
})
onBeforeUnmount(() => observer?.disconnect())
const meta = computed(() => new Map(props.branches.map((b) => [b.branch_id, b])))
const nameOf = (b) => b?.policy ? PLANS[b.policy] ?? b.policy : 'Base run'
const rows = computed(() => props.paths.map((p) => {
  const b = meta.value.get(p.branch_id)
  const point = p.points.find((x) => Date.parse(x.t) === props.at)
  return { ...p, name: nameOf(b), replay: Boolean(b?.replay), text: point ? metricText(point.value) : `No point at round ${props.round}` }
}))
const primaryPath = computed(() => props.account
  ? props.paths.find((p) => p.account_id === props.account.id)
  : props.paths.find((p) => meta.value.get(p.branch_id)?.parent_branch_id === null) ?? props.paths[0])
const currency = computed(() => props.account?.currency ?? primaryPath.value?.points[0]?.value.currency ?? 'USD')
const series = computed(() => {
  if (!primaryPath.value || props.epoch === null) return []
  const matching = props.paths.filter((p) => p.account_id === primaryPath.value.account_id)
  const policies = matching.filter((p) => meta.value.get(p.branch_id)?.policy)
  return (policies.length ? policies : matching).map((p) => {
    const b = meta.value.get(p.branch_id)
    const first = Math.min(...p.points.map((x) => Date.parse(x.t)))
    const parent = matching.find((q) => q.branch_id === b?.parent_branch_id)
    const prefix = parent?.points.filter((q) => Date.parse(q.t) < first) ?? []
    return { ...p, policy: b?.policy, name: nameOf(b), replay: Boolean(b?.replay), points: [...prefix, ...p.points].filter((x) => Number.isFinite(Date.parse(x.t)) && x.value.currency === currency.value).sort((a, b) => Date.parse(a.t) - Date.parse(b.t)) }
  })
})
const chartPoints = computed(() => {
  const points = new Map()
  for (const s of series.value) for (const p of s.points) {
    const key = Date.parse(p.t)
    const group = points.get(key) ?? { t: p.t, values: [] }
    group.values.push(`${s.name}: ${metricText(p.value)} · ${s.branch_id}${s.replay ? ' · Replay' : ''} · as of ${p.value.as_of ?? p.t}`)
    points.set(key, group)
  }
  return [...points.values()].map((p) => ({ t: p.t, text: p.values.join('; ') }))
})
const floorKnown = computed(() => props.account?.floor?.status === 'known' && Number.isSafeInteger(props.account.floor.minor) && props.account.floor.currency === currency.value)
const hour = (t) => (Date.parse(t) - props.epoch) / 3_600_000
const cursorHour = computed(() => props.at !== null && props.epoch !== null ? (props.at - props.epoch) / 3_600_000 : null)
const range = computed(() => {
  const values = series.value.flatMap((s) => s.points.filter((p) => p.value.minor !== null).map((p) => p.value.minor))
  if (floorKnown.value) values.push(props.account.floor.minor)
  const lo = Math.min(0, ...values), hi = Math.max(1, ...values)
  const step = 10 ** Math.floor(Math.log10(Math.max(1, (hi - lo) / 4)))
  const unit = [1, 2, 5, 10].map((k) => k * step).find((v) => v >= (hi - lo) / 4)
  return { lo: Math.floor(lo / unit) * unit, hi: Math.ceil(hi / unit) * unit, unit }
})
const yTicks = computed(() => Array.from({ length: Math.round((range.value.hi - range.value.lo) / range.value.unit) + 1 }, (_, i) => range.value.lo + i * range.value.unit))
const x = (h) => 64 + Math.max(0, Math.min(72, h)) / 72 * Math.max(1, width.value - 80)
const y = (v) => 148 - (v - range.value.lo) / (range.value.hi - range.value.lo) * 136
function pathOf (points) {
  let out = '', previous = false
  for (const p of points) {
    if (p.value.status !== 'known' || !Number.isSafeInteger(p.value.minor)) { previous = false; continue }
    out += `${previous ? 'H' : 'M'}${x(hour(p.t))}${previous ? 'V' : ','}${y(p.value.minor)} `
    previous = true
  }
  return out
}
const shortfall = computed(() => {
  if (!floorKnown.value) return null
  const s = series.value.find((s) => s.policy === 'no-action')
  if (!s?.points.length || s.points.some((p) => p.value.status !== 'known' || !Number.isSafeInteger(p.value.minor))) return null
  const low = s.points.reduce((a, b) => b.value.minor < a.value.minor ? b : a)
  const minor = props.account.floor.minor - low.value.minor
  return minor > 0 ? { low, minor, branch_id: s.branch_id } : null
})
</script>

<style scoped>
.lw-cash-panel { min-width: 0; }
.lw-cash-panel h2 { font: 600 15px var(--lw-font-text); margin: 0 0 12px; }
.lw-cash-chart { display: grid; gap: 20px; min-width: 0; }
.lw-cash-chart__frame { min-width: 0; position: relative; }
.lw-cash-chart__axes line { stroke: var(--lw-rule); }
.lw-cash-chart__axes text { font: 11px var(--lw-font-text); fill: var(--lw-ink-muted); }
.lw-cash-chart__line { fill: none; stroke-width: 2; stroke: var(--lw-ink-muted); }
.lw-cash-chart__line.is-no-action { stroke: var(--lw-bad-text); stroke-dasharray: 6 3; }
.lw-cash-chart__line.is-fixed-reserve { stroke: var(--lw-brand); stroke-dasharray: 2 3; }
.lw-cash-chart__line.is-integrated { stroke: var(--lw-ok-text); }
.lw-cash-chart__floor { stroke: var(--lw-ink-muted); stroke-dasharray: 6 4; }
.lw-cash-chart__cursor { stroke: var(--lw-ink-muted); stroke-dasharray: 2 4; }
.lw-cash-chart__point { position: absolute; width: 0; height: 0; }
.lw-cash-chart__point button { position: absolute; left: -8px; top: 0; width: 16px; height: 136px; padding: 0; border: 0; border-radius: 50%; background: transparent; cursor: pointer; }
.lw-cash-chart__point button:focus-visible { outline: 3px solid var(--lw-focus); }
.lw-cash-chart__point.is-open button { border-left: 1px dotted var(--lw-ink-muted); }
.lw-cash-chart__legend { display: flex; flex-wrap: wrap; gap: 10px 16px; list-style: none; padding: 0; margin: 0; font-size: 12px; }
.lw-cash-chart__legend li { display: flex; gap: 6px; align-items: center; }
.lw-cash-chart__legend span { width: 20px; border-top: 2px solid var(--lw-ink-muted); }
.lw-cash-chart__legend .is-no-action { border-color: var(--lw-bad-text); border-top-style: dashed; }
.lw-cash-chart__legend .is-fixed-reserve { border-color: var(--lw-brand); border-top-style: dotted; }
.lw-cash-chart__legend .is-integrated { border-color: var(--lw-ok-text); }
.lw-cash-chart__legend .is-floor { border-top-style: dashed; }
.lw-cash-chart__shortfall { background: var(--lw-surface-raised); border-left: 3px solid var(--lw-bad-text); padding: 12px; font-size: 13px; color: var(--lw-bad-text); }
.lw-cash-chart__shortfall b { display: block; }
.lw-cash-values { margin-top: 8px; }
.lw-cash-values summary { min-height: 44px; line-height: 44px; font-size: 12px; color: var(--lw-brand); cursor: pointer; }
.lw-cash { list-style: none; padding: 0; }
.lw-cash__row { display: flex; gap: 20px; justify-content: space-between; }
.lw-cash-values table { font-size: 13px; width: 100%; text-align: left; }
@media (min-width: 1200px) { .lw-cash-chart { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); } }
</style>

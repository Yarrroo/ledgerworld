<template>
  <div class="lw-outlook">
    <p v-if="!points.length" class="lw-note" data-test="outlook-empty">
      Projected cash is Unknown: a balance is not observed, so no path is drawn.
    </p>
    <template v-else>
      <div ref="frame" class="lw-outlook__frame">
        <svg :width="width" :height="height" role="group" :aria-label="`Projected cash P in ${currency}, ${points.length} points`"
             data-test="outlook-chart">
          <g class="lw-outlook__axis" aria-hidden="true">
            <g v-for="tick in yTicks" :key="`y${tick}`">
              <line :x1="M.left" :x2="width - M.right" :y1="y(tick)" :y2="y(tick)" class="lw-outlook__grid" />
              <text :x="M.left - 8" :y="y(tick) + 4" text-anchor="end">{{ short(tick) }}</text>
            </g>
            <text v-for="h in xTicks" :key="`x${h}`" :x="x(h)" :y="height - M.bottom + 20" text-anchor="middle">{{ h }}</text>
            <text :x="width - M.right" :y="height - 4" text-anchor="end">hours from as of</text>
          </g>
          <path :d="area" class="lw-outlook__area" aria-hidden="true" />
          <line v-if="floorY !== null" :x1="M.left" :x2="width - M.right" :y1="floorY" :y2="floorY"
                class="lw-outlook__floor" aria-hidden="true" data-test="outlook-floor" />
          <text v-if="floorY !== null" :x="width - M.right" :y="floorY - 6" text-anchor="end"
                class="lw-outlook__floor-label" aria-hidden="true" data-test="outlook-floor-label">{{ floorText }}</text>
          <path :d="line" class="lw-outlook__line" aria-hidden="true" />
          <g v-for="p in drawn" :key="p.t" class="lw-outlook__point"
             :class="{ 'is-low': p.low, [`is-${lowTone}`]: p.low, 'is-active': active === p.t }"
             tabindex="0" role="img" :aria-label="p.text" data-test="outlook-point" :data-t="p.t"
             @pointerenter="hover($event, p.t)" @pointerleave="hover($event, null)"
             @focus="active = p.t" @blur="active = null" @click="active = p.t">
            <circle :cx="p.px" :cy="p.py" r="22" class="lw-outlook__hit" />
            <circle :cx="p.px" :cy="p.py" :r="p.low ? 7 : 5" class="lw-outlook__dot" />
          </g>
          <text v-if="low" :x="lowLabel.x" :y="lowLabel.y" :text-anchor="lowLabel.anchor"
                class="lw-outlook__low-label" aria-hidden="true" data-test="outlook-low-label">{{ lowLabel.text }}</text>
        </svg>
        <div v-if="tip" class="lw-outlook__tip" aria-hidden="true" data-test="outlook-tip"
             :style="tipStyle">
          <strong>{{ tip.money }}</strong>
          <span>{{ tip.h }} simulated · {{ tip.utc }}</span>
          <span>{{ tip.event }}</span>
        </div>
      </div>
      <ul class="lw-outlook__legend" aria-hidden="true">
        <li><span class="lw-outlook__key lw-outlook__key--line" /> Projected cash P (observed)</li>
        <li v-if="floorY !== null"><span class="lw-outlook__key lw-outlook__key--floor" /> Reserve floor ({{ metricText(floor) }})</li>
        <li v-if="low"><span :class="['lw-outlook__key', 'lw-outlook__key--low', `is-${lowTone}`]" /> Lowest point, {{ STATES[lowState].word.toLowerCase() }}</li>
      </ul>
      <button type="button" class="lw-button lw-button--quiet" :aria-expanded="table ? 'true' : 'false'"
              aria-controls="outlook-data" data-test="outlook-view-data" @click="table = !table">
        {{ table ? 'Hide data' : 'View data' }}
      </button>
      <div v-if="table" id="outlook-data" class="lw-table-wrap" tabindex="0" role="region"
           aria-label="Projected cash, as data" data-test="outlook-table">
        <table class="lw-table">
          <caption class="lw-visually-hidden">Projected cash P at each point the API serves, against the reserve floor</caption>
          <thead>
            <tr><th scope="col">t</th><th scope="col">UTC</th><th scope="col">P</th>
              <th scope="col">What moves it</th><th scope="col">Against the floor</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in drawn" :key="p.t" :class="{ 'lw-row--floor': p.low }">
              <td>{{ p.h }}</td>
              <td>{{ p.utc }}</td>
              <td class="lw-num">{{ p.money }}</td>
              <td>{{ p.event }}</td>
              <td>{{ p.against }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup>
/**
 * O3, the cash outlook: the API's projected-cash points drawn as the step path P is (it moves
 * only at a flow or a deadline), the reserve floor, and the lowest point marked in its floor
 * state (kept is green). Every point takes focus and hover and tells its simulated offset, its
 * UTC time, P and what moves it there; View data shows the same points as a table. Nothing here
 * computes money: positions are geometry, figures are the API's.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { STATES, againstFloor, formatAmount, formatMoney, formatTime, hoursFrom, metricText } from '../api/v1.js'

const props = defineProps({
  points: { type: Array, required: true },
  floor: { type: Object, default: null },
  lowAt: { type: String, default: null }, // the API's coverage.at: where P is lowest, first reached
  asOf: { type: String, required: true },
  currency: { type: String, required: true }
})

const frame = ref(null)
const width = ref(640)
const active = ref(null) // the time of the point whose tip shows
const table = ref(false)
const height = computed(() => (width.value < 520 ? 240 : 300))
const M = { left: 64, right: 20, top: 24, bottom: 44 }
let observer = null

function measure () {
  const w = frame.value?.clientWidth
  if (w) width.value = Math.max(280, Math.floor(w))
}
// the frame exists only once there are points: observe it whenever it appears
onMounted(() => {
  if (window.ResizeObserver) observer = new ResizeObserver(measure)
  if (frame.value) observer?.observe(frame.value)
  measure()
})
watch(frame, (el, gone) => {
  if (gone) observer?.unobserve(gone)
  if (el) observer?.observe(el)
  measure()
})
onBeforeUnmount(() => observer?.disconnect())

const hoursOf = (t) => (Date.parse(t) - Date.parse(props.asOf)) / 3_600_000
const known = computed(() => props.points.filter((p) => p.value.minor !== null))
const floorKnown = computed(() => (props.floor?.minor ?? null) !== null)

/** A round step for the y axis: 1, 2 or 5 × 10^k of the currency's minor units, at least 1. */
function niceStep (span) {
  const raw = Math.max(span / 4, 1)
  const mag = 10 ** Math.floor(Math.log10(raw))
  return [1, 2, 5, 10].map((k) => k * mag).find((s) => s >= raw)
}
/** The y range, from 0 or the lowest P below it to above the highest value, on round steps. */
const yRange = computed(() => {
  const values = [...known.value.map((p) => p.value.minor), floorKnown.value ? props.floor.minor : 0, 0]
  const hi = Math.max(...values)
  const lo = Math.min(...values)
  const step = niceStep((hi - lo) * 1.15)
  return {
    step,
    top: Math.max(step, Math.ceil((hi * 1.15) / step) * step),
    bottom: lo < 0 ? Math.floor((lo * 1.15) / step) * step : 0
  }
})
const yStep = computed(() => yRange.value.step)
const yTop = computed(() => yRange.value.top)
const yBottom = computed(() => yRange.value.bottom)
const yTicks = computed(() => {
  const ticks = []
  for (let v = yBottom.value; v <= yTop.value; v += yStep.value) ticks.push(v)
  return ticks
})
const xEnd = computed(() => Math.max(1, ...props.points.map((p) => hoursOf(p.t))))
const xTicks = computed(() => {
  const step = xEnd.value > 48 ? 12 : 6
  const ticks = []
  for (let h = 0; h <= xEnd.value + 0.01; h += step) ticks.push(h)
  return ticks
})
const x = (h) => M.left + (h / xEnd.value) * (width.value - M.left - M.right)
const y = (v) => height.value - M.bottom -
  ((v - yBottom.value) / (yTop.value - yBottom.value)) * (height.value - M.top - M.bottom)
const floorY = computed(() => (floorKnown.value ? y(props.floor.minor) : null))

/** "70,000" on the axis: whole units, the currency named in the chart's label. */
const short = (minor) => formatAmount(minor, props.currency).replace(/\.0+$/, '')

/** The point the API names as the lowest; none when it names none. */
const lowPoint = computed(() => props.points.find((p) => p.t === props.lowAt) ?? null)
const lowState = computed(() => againstFloor(lowPoint.value?.value, props.floor).state)
const lowTone = computed(() => STATES[lowState.value]?.tone ?? 'muted')

function eventText (p) {
  if (!p.events.length) return Date.parse(p.t) <= Date.parse(props.asOf) ? 'As of: settled cash' : 'Horizon end: nothing moves'
  return p.events.map((e) =>
    `${e.kind.replace(/_/g, ' ')} ${e.ref} ${e.direction === 'in' ? '+' : '−'}${formatMoney(e.amount.minor, e.amount.currency)}`
  ).join('; ')
}

function againstText (value) {
  const { state, gap } = againstFloor(value, props.floor)
  if (state === 'kept') return `✓ kept, ${formatMoney(gap, props.currency)} above`
  if (state === 'breached') return `✕ below, short ${formatMoney(-gap, props.currency)}`
  return state === 'unassessed' ? 'No floor assessed' : 'Unknown'
}

const drawn = computed(() => props.points.map((p) => {
  const h = hoursOf(p.t)
  const utc = formatTime(p.t).utc
  const shown = metricText(p.value)
  const event = eventText(p)
  const at = hoursFrom(props.asOf, p.t)
  return {
    ...p, h: at, utc, money: shown, event, low: p === lowPoint.value,
    px: x(h), py: p.value.minor === null ? y(0) : y(p.value.minor),
    against: againstText(p.value),
    text: `${at}, ${utc}: P ${shown}. ${event}.${p === lowPoint.value ? ' Lowest point.' : ''}`
  }
}))
const low = computed(() => drawn.value.find((p) => p.low) ?? null)
const floorText = computed(() => (floorKnown.value ? `Reserve floor ${short(props.floor.minor)}` : ''))

/** A label's box around its baseline y: 12 px text, a generous glyph width, 3 px to spare. */
const GLYPH = 7.5
function box (text, x, baseline, anchor) {
  const w = text.length * GLYPH
  const left = anchor === 'end' ? x - w : x
  return { left: left - 3, right: left + w + 3, top: baseline - 16, bottom: baseline + 7 }
}
const meets = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom

/** The lowest point's label: below the point unless that crosses the floor line or the floor
 * label, then above it, then a line further out each way; below when nothing clears. */
const lowLabel = computed(() => {
  const p = low.value
  if (!p) return { x: 0, y: 0, anchor: 'start', text: '' }
  const text = `Lowest ${short(p.value.minor)} · ${p.h}`
  const right = p.px > width.value - 160
  const x = p.px + (right ? -10 : 10)
  const anchor = right ? 'end' : 'start'
  const fy = floorY.value
  const floorBox = fy === null ? null : box(floorText.value, width.value - M.right, fy - 6, 'end')
  const clears = (baseline) => {
    if (fy === null) return true
    const b = box(text, x, baseline, anchor)
    return !(fy > b.top && fy < b.bottom) && !meets(b, floorBox)
  }
  const y = [p.py + 24, p.py - 14, p.py + 40, p.py - 30].find(clears) ?? p.py + 24
  return { x, y, anchor, text }
})

const step = (pts) => pts.map((p, n) => (n ? `H${p.px}V${p.py}` : `M${p.px},${p.py}`)).join('')
const valued = computed(() => drawn.value.filter((p) => p.value.minor !== null))
const line = computed(() => step(valued.value))
const area = computed(() => {
  const pts = valued.value
  if (!pts.length) return ''
  const base = y(yBottom.value)
  return `${step(pts)}H${x(xEnd.value)}V${base}H${pts[0].px}Z`
})

/** A mouse or a pen shows the tip while over a point; a touch shows it by tapping (focus and
 * click), and its pointer leaving as the finger lifts does not take it away. */
function hover (event, t) {
  if (event.pointerType !== 'touch') active.value = t
}

/** The tip's point, while a point at that time is still drawn. */
const tip = computed(() => drawn.value.find((p) => p.t === active.value) ?? null)
const tipStyle = computed(() => {
  const p = tip.value
  const left = Math.min(Math.max(p.px, 90), width.value - 90)
  const above = p.py > 90
  return { left: `${left}px`, top: `${above ? p.py - 12 : p.py + 16}px`, transform: `translate(-50%, ${above ? '-100%' : '0'})` }
})
</script>

<style scoped>
.lw-outlook__frame {
  position: relative;
  width: 100%;
}

.lw-outlook svg {
  display: block;
  overflow: visible;
  font-family: var(--lw-font-text);
  font-size: 12px;
}

.lw-outlook__axis text,
.lw-outlook__floor-label {
  fill: var(--lw-ink-muted);
}

.lw-outlook__grid {
  stroke: var(--lw-rule);
  stroke-width: 1;
}

.lw-outlook__area {
  fill: var(--lw-selected);
  opacity: 0.7;
}

.lw-outlook__line {
  fill: none;
  stroke: var(--lw-brand);
  stroke-width: 2.5;
}

.lw-outlook__floor {
  stroke: var(--lw-ink-muted);
  stroke-width: 1.5;
  stroke-dasharray: 6 5;
}

.lw-outlook__hit {
  fill: transparent;
}

.lw-outlook__dot {
  fill: var(--lw-brand);
  stroke: var(--lw-surface-raised);
  stroke-width: 2;
}

.lw-outlook__point {
  cursor: pointer;
  outline: none;
}

.lw-outlook__point.is-ok .lw-outlook__dot { fill: var(--lw-ok); }
.lw-outlook__point.is-bad .lw-outlook__dot { fill: var(--lw-bad); }

.lw-outlook__point:focus-visible .lw-outlook__hit,
.lw-outlook__point.is-active .lw-outlook__hit {
  fill: none;
  stroke: var(--lw-focus);
  stroke-width: 3;
}

.lw-outlook__low-label {
  font-weight: 700;
  fill: var(--lw-ink);
}

.lw-outlook__tip {
  position: absolute;
  z-index: 2;
  display: grid;
  gap: 2px;
  max-width: 240px;
  padding: var(--lw-space-2) var(--lw-space-3);
  background: var(--lw-surface-raised);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.12);
  font-size: 13px;
  line-height: 18px;
  pointer-events: none;
}

.lw-outlook__legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2) var(--lw-space-4);
  list-style: none;
  padding: 0;
  margin: var(--lw-space-3) 0;
  font-size: 13px;
  color: var(--lw-ink-muted);
}

.lw-outlook__key {
  display: inline-block;
  width: 18px;
  vertical-align: middle;
}

.lw-outlook__key--line { border-top: 3px solid var(--lw-brand); }
.lw-outlook__key--floor { border-top: 2px dashed var(--lw-ink-muted); }
.lw-outlook__key--low {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--lw-brand);
}
.lw-outlook__key--low.is-ok { background: var(--lw-ok); }
.lw-outlook__key--low.is-bad { background: var(--lw-bad); }

.lw-outlook .lw-table-wrap {
  margin-top: var(--lw-space-3);
}
</style>

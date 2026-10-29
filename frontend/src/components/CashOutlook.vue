<template>
  <div class="lw-outlook">
    <p v-if="!points.length" class="lw-note" data-test="outlook-empty">
      Projected cash is unknown: a balance is not observed, so no path is drawn.
    </p>
    <template v-else>
      <div ref="frame" class="lw-outlook__frame">
        <svg :width="width" :height="height" role="group" :aria-label="`Projected cash in ${currency}, ${points.length} points`"
             data-test="outlook-chart">
          <g class="lw-outlook__axis" aria-hidden="true">
            <g v-for="tick in yTicks" :key="`y${tick}`">
              <line :x1="M.left" :x2="width - M.right" :y1="y(tick)" :y2="y(tick)" class="lw-outlook__grid" />
              <text :x="M.left - 8" :y="y(tick) + 4" text-anchor="end">{{ short(tick) }}</text>
            </g>
            <line :x1="M.left" :x2="M.left" :y1="M.top" :y2="height - M.bottom" class="lw-outlook__spine" />
            <text v-for="h in xTicks" :key="`x${h}`" :x="x(h)" :y="height - M.bottom + 20" text-anchor="middle">{{ h }}</text>
            <text :x="(M.left + width - M.right) / 2" :y="height - 4" text-anchor="middle">Hours</text>
          </g>
          <path :d="area" class="lw-outlook__area" aria-hidden="true" />
          <line v-if="floorY !== null" :x1="M.left" :x2="width - M.right" :y1="floorY" :y2="floorY"
                class="lw-outlook__floor" aria-hidden="true" data-test="outlook-floor" />
          <text v-if="floorY !== null" :x="width - M.right" :y="floorY - 6" text-anchor="end"
                class="lw-outlook__floor-label" aria-hidden="true" data-test="outlook-floor-label">
            <tspan font-style="italic">Reserve floor</tspan> <tspan>{{ short(floor.minor) }}</tspan>
          </text>
          <path :d="line" class="lw-outlook__line" aria-hidden="true" data-test="outlook-line" />
          <circle v-for="p in valued" :key="`d${p.t}`" :cx="p.px" :cy="p.py" :r="p.low ? 6 : 4.5"
                  :class="['lw-outlook__dot', { [`is-${lowTone}`]: p.low }]" aria-hidden="true" />
          <g v-for="a in notes" :key="`n${a.t}`" class="lw-outlook__note" aria-hidden="true" data-test="outlook-note">
            <line :x1="a.px" :y1="a.py" :x2="a.lx" :y2="a.ly + 4" class="lw-outlook__leader" />
            <text :x="a.lx" :y="a.ly - 30" class="lw-outlook__note-h">{{ a.h }}</text>
            <text :x="a.lx" :y="a.ly - 15">{{ a.what }}</text>
            <text :x="a.lx" :y="a.ly" class="lw-outlook__note-v">{{ a.money }}</text>
          </g>
          <g v-if="low" :class="['lw-outlook__low', `is-${lowTone}`]" aria-hidden="true" data-test="outlook-low-label">
            <rect :x="lowBox.x" :y="lowBox.y" :width="lowBox.w" height="40" rx="4" />
            <text :x="lowBox.x + 10" :y="lowBox.y + 16">Lowest</text>
            <text :x="lowBox.x + 10" :y="lowBox.y + 32" class="lw-outlook__note-v">{{ short(low.value.minor) }} · h{{ low.hours }}</text>
          </g>
        </svg>
        <!-- one control per point, over the drawing: the shared tooltip on hover, focus and tap -->
        <Tip v-for="p in drawn" :key="p.t" class="lw-outlook__pt" :style="{ left: `${p.px}px`, top: `${p.py}px` }" toggle>
          <button type="button" :aria-label="p.text" data-test="outlook-point" :data-t="p.t" />
          <template #tip>
            <span data-test="outlook-tip"><b>{{ p.money }}</b> · h{{ p.hours }} ({{ p.h }})<br>{{ p.event }}<br>
              {{ p.utc }} · {{ p.against }}</span>
          </template>
        </Tip>
      </div>
      <ul class="lw-outlook__legend" aria-hidden="true">
        <li><span class="lw-outlook__key lw-outlook__key--point" /> Projected cash (observed)</li>
        <li v-if="floorY !== null"><span class="lw-outlook__key lw-outlook__key--floor" /> Reserve floor ({{ short(floor.minor) }})</li>
        <li v-if="low"><span :class="['lw-outlook__key', 'lw-outlook__key--low', `is-${lowTone}`]" /> Lowest point</li>
      </ul>
    </template>
  </div>
</template>

<script setup>
/**
 * The 72-hour cash outlook as mockup 01 draws it (prp/2026-10-29-ux-pass/MATCH.md, 01 Overview):
 * the API's projected-cash points as the step path P is (it moves only at a flow or a deadline),
 * a $ axis, the reserve floor, the start and every flow annotated beside its point (hour, what
 * moves, the cash after), the lowest point boxed in its floor state (kept is green), and a
 * legend. Each point is a control with the shared tooltip: its simulated hour, UTC time, P, what
 * moves it and where it stands against the floor. Narrow, the annotations give way to the
 * tooltips. Nothing here computes money: positions are geometry, figures are the API's.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Tip from './Tip.vue'
import { STATES, againstFloor, formatMoney, formatTime, hoursFrom, kindText, metricText } from '../api/v1.js'

const props = defineProps({
  points: { type: Array, required: true },
  floor: { type: Object, default: null },
  lowAt: { type: String, default: null }, // the API's coverage.at: where P is lowest, first reached
  asOf: { type: String, required: true },
  currency: { type: String, required: true }
})

const frame = ref(null)
const width = ref(640)
const wide = computed(() => width.value >= 520)
const height = computed(() => (wide.value ? 380 : 260))
const M = computed(() => ({ left: 72, right: 16, top: wide.value ? 64 : 24, bottom: 44 }))
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
  const raw = Math.max(span / 5, 1)
  const mag = 10 ** Math.floor(Math.log10(raw))
  return [1, 2, 5, 10].map((k) => k * mag).find((s) => s >= raw)
}
/** The y range, from 0 or the lowest P below it to above the highest value, on round steps. */
const yRange = computed(() => {
  const values = [...known.value.map((p) => p.value.minor), floorKnown.value ? props.floor.minor : 0, 0]
  const hi = Math.max(...values)
  const lo = Math.min(...values)
  const step = niceStep((hi - lo) * 1.2)
  return {
    step,
    top: Math.max(step, Math.ceil((hi * 1.2) / step) * step),
    bottom: lo < 0 ? Math.floor((lo * 1.2) / step) * step : 0
  }
})
const yTicks = computed(() => {
  const { step, top, bottom } = yRange.value
  const ticks = []
  for (let v = bottom; v <= top; v += step) ticks.push(v)
  return ticks
})
const xEnd = computed(() => Math.max(1, ...props.points.map((p) => hoursOf(p.t))))
const xTicks = computed(() => {
  const step = xEnd.value > 48 ? 12 : 6
  const ticks = []
  for (let h = 0; h <= xEnd.value + 0.01; h += step) ticks.push(h)
  return ticks
})
const x = (h) => M.value.left + (h / xEnd.value) * (width.value - M.value.left - M.value.right)
const y = (v) => height.value - M.value.bottom -
  ((v - yRange.value.bottom) / (yRange.value.top - yRange.value.bottom)) * (height.value - M.value.top - M.value.bottom)
const floorY = computed(() => (floorKnown.value ? y(props.floor.minor) : null))

/** "$70,000" on the axis and in the notes: the API's amount, formatted. */
const short = (minor) => formatMoney(minor, props.currency)

/** The point the API names as the lowest; none when it names none. */
const lowPoint = computed(() => props.points.find((p) => p.t === props.lowAt) ?? null)
const lowState = computed(() => againstFloor(lowPoint.value?.value, props.floor).state)
const lowTone = computed(() => STATES[lowState.value]?.tone ?? 'muted')

const signed = (e) => `${e.direction === 'in' ? '+' : '-'}${formatMoney(e.amount.minor, e.amount.currency)}`
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1)

function eventText (p) {
  if (!p.events.length) return Date.parse(p.t) <= Date.parse(props.asOf) ? 'Starting cash, settled' : 'Horizon end: nothing moves'
  return p.events.map((e) => `${capital(kindText(e.kind))} ${e.ref} ${signed(e)}`).join('; ')
}

function againstText (value) {
  const { state, gap } = againstFloor(value, props.floor)
  if (state === 'kept') return `${formatMoney(gap, props.currency)} above the floor`
  if (state === 'breached') return `${formatMoney(-gap, props.currency)} below the floor`
  return state === 'unassessed' ? 'No floor assessed' : 'Unknown against the floor'
}

const drawn = computed(() => props.points.map((p) => {
  const h = hoursOf(p.t)
  const utc = formatTime(p.t).utc
  const shown = metricText(p.value)
  const event = eventText(p)
  const at = hoursFrom(props.asOf, p.t)
  const low = p === lowPoint.value
  return {
    ...p, hours: Math.round(h), h: at, utc, money: shown, event, low,
    px: x(h), py: p.value.minor === null ? y(0) : y(p.value.minor),
    against: againstText(p.value),
    text: `h${Math.round(h)}, ${utc}: projected cash ${shown}. ${event}.${low ? ' Lowest point.' : ''}`
  }
}))
const valued = computed(() => drawn.value.filter((p) => p.value.minor !== null))
const low = computed(() => drawn.value.find((p) => p.low) ?? null)

/**
 * The notes beside the points, as the mockup: the start ("$70,000 / Starting cash / h0" read as
 * h0 · Starting cash · $70,000) and each flow that moves cash, except the lowest point, which has
 * its own box. A note sits up and to the right of its point, clear of the plot's top; wide only.
 */
const notes = computed(() => {
  if (!wide.value) return []
  const right = width.value - M.value.right
  return valued.value.filter((p, n) => !p.low && (n === 0 || p.events.length)).map((p) => {
    const what = p.events.length ? p.events.map((e) => `${capital(kindText(e.kind))} ${signed(e)}`).join(', ') : 'Starting cash'
    const w = Math.max(what.length, 8) * 6.6
    const lx = Math.min(p.px + 14, right - w)
    return { t: p.t, px: p.px, py: p.py, lx, ly: Math.max(M.value.top - 6, p.py - 26), h: `h${p.hours}`, what, money: p.money }
  })
})

/** The lowest point's box: above the point, inside the plot. */
const lowBox = computed(() => {
  const p = low.value
  if (!p) return { x: 0, y: 0, w: 0 }
  const w = Math.max(110, (short(p.value.minor).length + 6) * 7.4)
  const xx = Math.min(Math.max(p.px - w / 2, M.value.left + 4), width.value - M.value.right - w)
  const top = p.py - 58
  return { x: xx, y: top < 4 ? p.py + 16 : top, w }
})

const step = (pts) => pts.map((p, n) => (n ? `H${p.px}V${p.py}` : `M${p.px},${p.py}`)).join('')
const line = computed(() => step(valued.value))
const area = computed(() => {
  const pts = valued.value
  if (!pts.length) return ''
  const base = y(yRange.value.bottom)
  return `${step(pts)}H${x(xEnd.value)}V${base}H${pts[0].px}Z`
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
  stroke: transparent;
}

.lw-outlook__spine {
  stroke: var(--lw-ink-muted);
  stroke-width: 1;
}

.lw-outlook__area {
  fill: var(--lw-selected);
  opacity: 0.8;
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

.lw-outlook__dot {
  fill: var(--lw-brand);
  stroke: var(--lw-surface);
  stroke-width: 2;
}

.lw-outlook__dot.is-ok { fill: var(--lw-ok); }
.lw-outlook__dot.is-bad { fill: var(--lw-bad); }

.lw-outlook__note text {
  fill: var(--lw-ink-muted);
  font-size: 13px;
}

.lw-outlook__note .lw-outlook__note-h,
.lw-outlook__note .lw-outlook__note-v {
  fill: var(--lw-ink);
}

.lw-outlook__note-v {
  font-weight: 700;
}

.lw-outlook__leader {
  stroke: var(--lw-ink-muted);
  stroke-width: 1;
}

.lw-outlook__low rect {
  fill: var(--lw-selected);
}

.lw-outlook__low text {
  fill: var(--lw-ink);
  font-size: 13px;
}

.lw-outlook__low.is-ok text:first-of-type { fill: var(--lw-ok-text); }
.lw-outlook__low.is-bad rect { fill: #F7E1DD; }
.lw-outlook__low.is-bad text { fill: #8A2A20; }

/* each point's control: a 32 px target centred on its dot */
.lw-outlook__pt {
  position: absolute;
  width: 0;
  height: 0;
}

.lw-outlook__pt button {
  position: absolute;
  left: -16px;
  top: -16px;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
}

.lw-outlook__pt button:focus-visible,
.lw-outlook__pt.is-open button {
  outline: 3px solid var(--lw-focus);
  outline-offset: -6px;
}

.lw-outlook__legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--lw-space-2) var(--lw-space-6);
  list-style: none;
  padding: 0;
  margin: var(--lw-space-4) 0 0;
  font-size: 13px;
  color: var(--lw-ink-muted);
}

.lw-outlook__key {
  display: inline-block;
  margin-right: var(--lw-space-1);
  vertical-align: middle;
}

.lw-outlook__key--point,
.lw-outlook__key--low {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--lw-brand);
}

.lw-outlook__key--floor {
  width: 22px;
  border-top: 2px dashed var(--lw-ink-muted);
}

.lw-outlook__key--low.is-ok { background: var(--lw-ok); }
.lw-outlook__key--low.is-bad { background: var(--lw-bad); }
</style>

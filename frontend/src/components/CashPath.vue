<template>
  <div class="lw-path">
    <p v-if="!valued.length" class="lw-note" data-test="outlook-empty">
      Projected cash is unknown: a balance is not observed, so no path is drawn.
    </p>
    <template v-else>
      <div ref="frame" class="lw-path__frame">
        <svg :width="width" :height="height" role="group" data-test="outlook-chart"
             :aria-label="`Projected cash in ${currency} over ${xEnd} hours against the reserve floor`">
          <defs>
            <pattern :id="hatchId" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="8" class="lw-path__hatch" />
            </pattern>
          </defs>
          <!-- below the floor: what the what-if rehearses -->
          <g v-if="floorY !== null" aria-hidden="true">
            <rect x="0" :y="floorY" :width="width" :height="Math.max(0, y(range.bottom) - floorY)" class="lw-path__zone" />
            <rect x="0" :y="floorY" :width="width" :height="Math.max(0, y(range.bottom) - floorY)" :fill="`url(#${hatchId})`" />
          </g>
          <g class="lw-path__axis" aria-hidden="true">
            <g v-for="tick in range.ticks" :key="`y${tick}`">
              <line :x1="M.left" :x2="width - M.right" :y1="y(tick)" :y2="y(tick)" class="lw-path__grid" />
              <text :x="M.left - 8" :y="y(tick) + 4" text-anchor="end">{{ compact(tick) }}</text>
            </g>
            <line v-for="e in events.slice(1, -1)" :key="`t${e.t}`" :x1="e.px" :x2="e.px" :y1="y(range.bottom)"
                  :y2="y(range.bottom) + 6" class="lw-path__tick" />
          </g>
          <g v-if="split" aria-hidden="true" data-test="outlook-split">
            <rect :x="split.x" :y="split.cashY" :width="split.w" :height="split.reservedH" class="lw-path__reserved" />
            <rect :x="split.x" :y="split.cashY" :width="split.w" :height="split.spendableH" class="lw-path__spendable" />
          </g>
          <g v-if="floorY !== null" aria-hidden="true">
            <line x1="0" :x2="width" :y1="floorY" :y2="floorY" class="lw-path__floor" data-test="outlook-floor" />
            <text :x="floorAt.x" :y="floorAt.y" :text-anchor="floorAt.anchor" class="lw-path__halo lw-path__strong"
                  data-test="outlook-floor-label">{{ wide ? 'Reserve floor' : 'Floor' }} {{ short(floor.minor) }}</text>
          </g>
          <!-- the hypothetical: dashed, its breach in the warning colour -->
          <g v-if="lateDrawn.length" aria-hidden="true" data-test="late-path">
            <path :d="step(lateDrawn)" class="lw-path__late" />
            <line v-for="s in breaches" :key="`b${s.t}`" :x1="s.x1" :x2="s.x2" :y1="s.y" :y2="s.y" class="lw-path__breach" />
            <template v-if="lateLow">
              <path :d="`M${lateLow.px},${lateLow.py - 6}l6,6l-6,6l-6,-6Z`" :class="['lw-path__diamond', `is-${lateLow.tone}`]" />
              <text v-if="lateLow.from" :x="lateLow.x" :y="lateLow.from + LH + 2" :text-anchor="lateLow.anchor"
                    class="lw-path__halo lw-path__muted">{{ wide ? 'if the receipt is late (hypothetical)' : 'if late (hypothetical)' }}</text>
              <g :class="`is-${lateLow.tone}`" data-test="late-low-label">
                <text :x="lateLow.x" :y="lateLow.py - 3" :text-anchor="lateLow.anchor" class="lw-path__halo lw-path__strong">{{ lateLow.money }} if late</text>
                <text :x="lateLow.x" :y="lateLow.py + LH - 3" :text-anchor="lateLow.anchor" class="lw-path__halo">{{ lateLow.against }}</text>
              </g>
            </template>
          </g>
          <path :d="line" class="lw-path__line" aria-hidden="true" data-test="outlook-line" />
          <g v-for="p in labelled" :key="`v${p.t}`" aria-hidden="true">
            <text :x="p.px + (p.hours ? 7 : (split ? split.w : 0) + 6)" :y="p.py - 9" class="lw-path__halo lw-path__muted"
                  data-test="outlook-value">{{ wide ? p.money : compact(p.value.minor) }}{{ p.hours ? '' : ' now' }}</text>
          </g>
          <g v-if="low" :class="['lw-path__low', `is-${low.tone}`]" aria-hidden="true" data-test="outlook-low-label">
            <circle :cx="low.px" :cy="low.py" r="5" class="lw-path__dot" />
            <text :x="low.at.x" :y="low.at.y[0]" :text-anchor="low.at.anchor" class="lw-path__halo lw-path__strong">{{ low.title }}</text>
            <text :x="low.at.x" :y="low.at.y[1]" :text-anchor="low.at.anchor" class="lw-path__halo">{{ low.against }}</text>
          </g>
        </svg>
        <!-- one control per point, over the drawing: the shared tooltip on hover, focus and tap -->
        <Tip v-for="p in drawn" :key="p.t" class="lw-path__pt" :style="{ left: `${p.px}px`, top: `${p.py}px` }" toggle>
          <button type="button" :aria-label="p.text" data-test="outlook-point" :data-t="p.t" />
          <template #tip>
            <span data-test="outlook-tip"><b>{{ p.money }}</b> · h{{ p.hours }} ({{ p.h }})<br>{{ p.event }}<br>
              {{ p.utc }} · {{ p.against }}<template v-if="p.late"><br>If late (hypothetical): {{ p.late }}</template></span>
          </template>
        </Tip>
      </div>
      <!-- what moves cash, under the axis; an obligation opens its row -->
      <div class="lw-path__events" :style="{ width: `${width}px` }" data-test="outlook-events">
        <component :is="e.to ? RouterLink : 'span'" v-for="e in events" :key="e.t" :to="e.to" :aria-label="e.label"
                   :class="['lw-path__ev', `is-${e.anchor}`, { 'is-link': e.to }]" :style="{ left: `${e.px}px` }" data-test="outlook-event">
          <b>{{ e.when }}</b><span v-for="m in e.moves" :key="m">{{ m }}</span><span v-if="e.what" :class="{ 'lw-path__lk': e.to }">{{ e.what }}</span>
        </component>
      </div>
    </template>
  </div>
</template>

<script setup>
/**
 * The Overview's 72-hour cash path (the 2026-10-31 Overview design, candidate R with the judge's
 * picks): the API's projected cash P as a solid step line from $0, the reserve floor as a
 * full-width horizon with a hatched zone below it, the low point labelled with its distance to
 * the floor, the split of settled cash at "now" (reserved below, spendable on top), and the
 * prepared what-if's own path (the API's `scenario.outlook`) dashed, its breach of the floor in
 * the warning colour. What moves cash is written under the axis; an obligation links to its
 * Treasury row. Each point is a control with the shared tooltip. Nothing here computes money:
 * positions are geometry, figures are the API's, formatted.
 */
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { RouterLink } from 'vue-router'
import Tip from './Tip.vue'
import { againstFloor, formatMoney, formatTime, hoursFrom, kindText, metricText, pointAt } from '../api/v1.js'

const props = defineProps({
  points: { type: Array, required: true },
  late: { type: Array, default: () => [] }, // the what-if's P, hypothetical; drawn when showLate
  showLate: { type: Boolean, default: true },
  floor: { type: Object, default: null },
  lowAt: { type: String, default: null }, // the API's coverage.at: where P is lowest, first reached
  asOf: { type: String, required: true },
  currency: { type: String, required: true },
  cash: { type: Object, default: null }, // settled now, for the split bar at h0
  spendable: { type: Object, default: null },
  /** Where an event opens, or null: (event) => a route. */
  linkOf: { type: Function, default: () => null }
})

const LH = 16
const hatchId = `lw-hatch-${useId()}`
const frame = ref(null)
const width = ref(640)
const wide = computed(() => width.value >= 600)
const height = computed(() => (wide.value ? 340 : 224))
const M = computed(() => (wide.value ? { left: 58, right: 10, top: 24, bottom: 10 } : { left: 42, right: 6, top: 18, bottom: 8 }))
let observer = null

function measure () {
  const w = frame.value?.clientWidth
  if (w) width.value = Math.max(280, Math.floor(w))
}
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
const known = (list) => list.filter((p) => p.value.minor !== null)
const valued = computed(() => known(props.points))
const lateShown = computed(() => (props.showLate ? known(props.late) : []))
const floorKnown = computed(() => (props.floor?.minor ?? null) !== null && props.floor.status !== 'unassessed')

/**
 * The y axis from $0 (or the lowest P below it) to a round top: three gridlines, $0, half and
 * the top, on a step of 1, 2, 2.5 or 5 × 10^k minor units.
 */
const range = computed(() => {
  const values = [...valued.value, ...known(props.late)].map((p) => p.value.minor)
  if (floorKnown.value) values.push(props.floor.minor)
  const hi = Math.max(1, ...values)
  const lo = Math.min(0, ...values)
  // the step reaches the top in two steps, and the span below $0 in at most six more
  const need = Math.max(hi * 0.54, (hi - lo) / 6)
  const mag = 10 ** Math.floor(Math.log10(need))
  const unit = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= need)
  const bottom = lo < 0 ? -Math.ceil(-lo / unit) * unit : 0
  const ticks = []
  for (let v = bottom; v <= 2 * unit; v += unit) ticks.push(v)
  return { top: 2 * unit, bottom, ticks }
})
const xEnd = computed(() => Math.max(1, ...[...props.points, ...props.late].map((p) => Math.round(hoursOf(p.t)))))
const x = (h) => M.value.left + (h / xEnd.value) * (width.value - M.value.left - M.value.right)
const y = (v) => M.value.top + (1 - (v - range.value.bottom) / (range.value.top - range.value.bottom)) *
  (height.value - M.value.top - M.value.bottom)
const floorY = computed(() => (floorKnown.value ? y(props.floor.minor) : null))

const short = (minor) => formatMoney(minor, props.currency)
/** "$50k" on the axis and on a narrow chart: a round figure, shortened. */
const compact = (minor) => short(minor).replace(/,000,000$/, 'M').replace(/,000$/, 'k')
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1)
const signed = (e, brief = false) => `${e.direction === 'in' ? '+' : '−'}${(brief ? compact : short)(e.amount.minor)}`

function againstText (value, brief = false) {
  const { state, gap } = againstFloor(value, props.floor)
  const floor = brief ? 'floor' : 'the floor'
  if (state === 'kept') return `${short(gap)} above ${floor}`
  if (state === 'breached') return `${short(-gap)} below ${floor}`
  return state === 'unassessed' ? 'No floor assessed' : 'Unknown against the floor'
}
const toneOf = (value) => (againstFloor(value, props.floor).state === 'breached' ? 'bad' : 'ok')

function eventText (p) {
  if (!p.events.length) return Date.parse(p.t) <= Date.parse(props.asOf) ? 'Starting cash, settled' : 'Horizon end: nothing moves'
  return p.events.map((e) => `${capital(kindText(e.kind))} ${e.ref} ${signed(e).replace('−', '-')}`).join('; ')
}


const drawn = computed(() => props.points.map((p) => {
  const h = hoursOf(p.t)
  const utc = formatTime(p.t).utc
  const shown = metricText(p.value)
  const event = eventText(p)
  const low = p.t === props.lowAt
  const late = props.showLate ? pointAt(props.late, p.t) : null
  return {
    ...p, hours: Math.round(h), h: hoursFrom(props.asOf, p.t), utc, money: shown, event, low,
    px: x(h), py: p.value.minor === null ? y(0) : y(p.value.minor),
    against: againstText(p.value),
    late: late ? `${metricText(late.value)}, ${againstText(late.value)}` : '',
    text: `h${Math.round(h)}, ${utc}: projected cash ${shown}. ${event}.${low ? ' Lowest point.' : ''}`
  }
}).filter((p) => p.value.minor !== null))

const low = computed(() => {
  const p = drawn.value.find((d) => d.low)
  if (!p) return null
  const title = `${wide.value ? 'Low point' : 'Low'} ${p.money}`
  const against = againstText(p.value, !wide.value)
  return { ...p, title, against, at: lowPlace(p, Math.max(title.length, against.length) * 7.4), tone: toneOf(p.value) }
})
/** The floor's label: under the line at its right end, or over it at its left end when the low
 * point sits just over the floor under that label (that point's label goes under the line). */
const floorW = computed(() => (wide.value ? 150 : 100)) // "Reserve floor $30,000" or "Floor $30,000"
const floorAt = computed(() => {
  const right = width.value - M.value.right
  const p = drawn.value.find((d) => d.low)
  const crowded = p && floorY.value !== null && p.px > right - floorW.value && Math.abs(p.py - floorY.value) < 40
  return crowded
    ? { x: M.value.left + 14, y: floorY.value - 9, anchor: 'start', left: M.value.left + 14, top: floorY.value - LH - 9 }
    : { x: right, y: floorY.value + LH + 1, anchor: 'end', left: right - floorW.value, top: floorY.value }
})

const meets = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
/** A box around a stretch of a line, `pad` px out each way. */
const around = (x1, y1, x2, y2, pad) =>
  ({ left: Math.min(x1, x2) - pad, right: Math.max(x1, x2) + pad, top: Math.min(y1, y2) - pad, bottom: Math.max(y1, y2) + pad })

/**
 * Where the low point's two lines go: left of the point straddling it (the design's place), then
 * both just above it, higher above it, below it, then the same three right of it; the first that stays in the plot
 * and touches neither the step line, the floor line nor the floor label; the design's place when
 * none does.
 */
function lowPlace (p, w) {
  const pts = drawn.value
  const end = x(xEnd.value)
  const marks = [
    ...pts.slice(1).flatMap((q, n) => [around(pts[n].px, pts[n].py, q.px, pts[n].py, 2), around(q.px, pts[n].py, q.px, q.py, 2)]),
    around(pts.at(-1).px, pts.at(-1).py, end, pts.at(-1).py, 2)
  ]
  if (lateLow.value) marks.push(lateLow.value.box) // the what-if's own low-point label
  const fy = floorY.value
  if (fy !== null) {
    marks.push(around(0, fy, width.value, fy, 2))
    marks.push({ left: floorAt.value.left, right: floorAt.value.left + floorW.value, top: floorAt.value.top, bottom: floorAt.value.top + LH + 6 }) // its label
  }
  const rows = [[p.py - LH + 4, p.py + 5], [p.py - LH - 5, p.py - 6], [p.py - 2 * LH, p.py - LH], [p.py + LH + 4, p.py + 2 * LH + 4]]
  const sides = [{ x: p.px - 11, anchor: 'end' }, { x: p.px + 11, anchor: 'start' }]
  const places = sides.flatMap((side) => rows.map((y) => ({ ...side, y })))
  const fits = ({ x: at, anchor, y: [y0, y1] }) => {
    const box = { left: anchor === 'end' ? at - w : at, right: anchor === 'end' ? at : at + w, top: y0 - LH + 3, bottom: y1 + 4 }
    return box.left >= 0 && box.right <= width.value && box.top >= 0 && box.bottom <= height.value - M.value.bottom &&
      marks.every((m) => !meets(box, m))
  }
  return places.find(fits) ?? places[0]
}

/** The start and each point a flow moves, other than the low point, which has its own label. */
const labelled = computed(() => drawn.value.filter((p, n) => !p.low && (n === 0 || p.events.length)))

const step = (pts) => pts.map((p, n) => (n ? `H${p.px}V${p.py}` : `M${p.px},${p.py}`)).join('') +
  (pts.length ? `H${x(xEnd.value)}` : '')
const line = computed(() => step(drawn.value))

const lateDrawn = computed(() => lateShown.value.map((p) => ({ ...p, px: x(hoursOf(p.t)), py: y(p.value.minor) })))
/** The what-if's stretches below the floor, each to the next move or the horizon. */
const breaches = computed(() => {
  if (floorY.value === null) return []
  const pts = lateDrawn.value
  return pts.filter((p) => p.value.minor < props.floor.minor)
    .map((p) => ({ t: p.t, x1: p.px, x2: pts[pts.indexOf(p) + 1]?.px ?? x(xEnd.value), y: p.py }))
})
/** The what-if's lowest point, first reached, and the level it fell from (for its caption). */
const lateLow = computed(() => {
  const pts = lateDrawn.value
  if (!pts.length) return null
  const p = pts.reduce((a, b) => (b.value.minor < a.value.minor ? b : a))
  const before = pts[pts.indexOf(p) - 1]
  const money = metricText(p.value)
  const against = againstText(p.value, !wide.value)
  const w = Math.max(`${money} if late`.length, against.length) * 7.4
  // left of its point, as drawn; right of it when the left would leave the chart
  const left = p.px - 11 - w >= 0
  const x0 = left ? p.px - 11 : p.px + 11
  return {
    ...p, money, against, tone: toneOf(p.value), from: before ? before.py : null,
    x: x0, anchor: left ? 'end' : 'start',
    box: { left: left ? x0 - w : x0, right: left ? x0 : x0 + w, top: p.py - 3 - LH + 3, bottom: p.py + LH - 3 + 4 }
  }
})

/** The split of settled cash at h0: spendable on top, the rest set aside below it (geometry only). */
const split = computed(() => {
  const c = props.cash?.minor
  const s = props.spendable?.minor
  if (c == null || s == null || s < 0 || s > c || c <= 0) return null
  const zero = y(Math.max(0, range.value.bottom))
  return { x: x(0), w: wide.value ? 8 : 6, cashY: y(c), reservedH: zero - y(c), spendableH: zero - y(s) }
})

/**
 * What moves cash, under the axis: now, each flow or deadline, the horizon's end. A label sits
 * centred on its time unless a neighbour is close, then the left one ends at its time and the
 * right one starts there; the first starts and the last ends at their times.
 */
const events = computed(() => {
  const pts = drawn.value
  const near = wide.value ? 130 : 44
  return pts.filter((p, n) => n === 0 || n === pts.length - 1 || p.events.length).map((p, n, all) => {
    const prev = all[n - 1]
    const next = all[n + 1]
    let anchor = 'mid'
    if (!prev) anchor = 'start'
    else if (!next) anchor = 'end'
    else if (next.px - p.px < near) anchor = 'end'
    else if (p.px - prev.px < near) anchor = 'start'
    const first = p.events[0]
    const to = first ? props.linkOf(first) : null
    const kind = first ? kindText(first.kind) : ''
    const what = first ? (wide.value ? kind : kind.split(' ')[0]) : ''
    return {
      t: p.t, px: p.px, anchor, to,
      when: p.hours ? (wide.value ? `Hour ${p.hours}` : `h${p.hours}`) : 'Now',
      moves: p.events.map((e) => signed(e, !wide.value)),
      what: to ? `${what}${wide.value ? ' · inspect' : ''} →` : what,
      label: to ? `${capital(kind)}, ${short(first.amount.minor)} at hour ${p.hours}. Inspect it in Treasury` : undefined
    }
  })
})
</script>

<style scoped>
.lw-path__frame {
  position: relative;
  width: 100%;
}

.lw-path svg {
  display: block;
  overflow: visible;
  font-family: var(--lw-font-text);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.lw-path svg text {
  fill: var(--lw-ink);
}

.lw-path__axis text,
.lw-path svg .lw-path__muted {
  fill: var(--lw-ink-muted);
}

.lw-path svg .lw-path__strong {
  font-weight: 600;
}

.lw-path__halo {
  paint-order: stroke;
  stroke: var(--lw-surface);
  stroke-width: 4px;
  stroke-linejoin: round;
}

.lw-path__grid {
  stroke: var(--lw-rule);
  stroke-width: 1;
}

.lw-path__tick {
  stroke: var(--lw-ink-muted);
}

.lw-path__zone {
  fill: var(--lw-warn);
  opacity: 0.05;
}

.lw-path__hatch {
  stroke: var(--lw-warn);
  stroke-width: 1;
  opacity: 0.2;
}

.lw-path__floor {
  stroke: var(--lw-ink);
  stroke-width: 1.5;
}

.lw-path__reserved {
  fill: var(--lw-ink-muted);
  opacity: 0.4;
}

.lw-path__spendable {
  fill: var(--lw-brand);
}

.lw-path__line {
  fill: none;
  stroke: var(--lw-brand);
  stroke-width: 2.75;
  stroke-linejoin: round;
}

.lw-path__late {
  fill: none;
  stroke: var(--lw-ink-muted);
  stroke-width: 1.75;
  stroke-dasharray: 6 5;
}

.lw-path__breach {
  stroke: var(--lw-warn);
  stroke-width: 2.5;
  stroke-dasharray: 6 4;
}

.lw-path__diamond {
  fill: var(--lw-surface);
  stroke: var(--lw-ink-muted);
  stroke-width: 2;
}

.lw-path__diamond.is-bad {
  stroke: var(--lw-warn);
}

.lw-path svg .is-bad text {
  fill: var(--lw-warn);
}

.lw-path__dot {
  fill: var(--lw-brand);
  stroke: var(--lw-surface);
  stroke-width: 2;
}

.lw-path__low.is-bad .lw-path__dot {
  fill: var(--lw-warn);
}

/* each point's control: a 32 px target centred on its point */
.lw-path__pt {
  position: absolute;
  width: 0;
  height: 0;
}

.lw-path__pt button {
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

.lw-path__pt button:focus-visible,
.lw-path__pt.is-open button {
  outline: 3px solid var(--lw-focus);
  outline-offset: -6px;
}

.lw-path__events {
  position: relative;
  max-width: 100%;
  height: 52px;
}

.lw-path__ev {
  position: absolute;
  top: 2px;
  display: flex;
  flex-direction: column;
  color: var(--lw-ink-muted);
  font-size: 13px;
  line-height: 16px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.lw-path__ev b {
  color: var(--lw-ink);
  font-weight: 600;
}

.lw-path__ev.is-mid {
  transform: translateX(-50%);
  align-items: center;
}

.lw-path__ev.is-end {
  transform: translateX(-100%);
  align-items: flex-end;
}

.lw-path__ev.is-link {
  min-width: 44px;
  min-height: 48px;
  color: var(--lw-ink);
  text-decoration: none;
}

.lw-path__lk {
  text-decoration: underline;
  text-underline-offset: 3px;
}
</style>

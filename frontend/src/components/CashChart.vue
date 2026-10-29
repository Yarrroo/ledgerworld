<template>
  <div ref="box" class="lw-chart" data-test="chart">
    <svg v-if="plot" :width="width" :height="HEIGHT" :viewBox="`0 0 ${width} ${HEIGHT}`" class="lw-chart__svg"
         role="group" :aria-label="label">
      <line v-if="plot.floorY !== null" class="lw-chart__floor" :x1="PAD_L" :x2="width - PAD_R"
            :y1="plot.floorY" :y2="plot.floorY" />
      <text v-if="plot.floorY !== null" class="lw-chart__note" :x="width - PAD_R" :y="plot.floorY + 16"
            text-anchor="end">
        floor {{ floorText }}
      </text>
      <polyline class="lw-chart__line" :points="plot.line" fill="none" />
      <text v-for="p in plot.dots" :key="`x-${p.t}`" class="lw-chart__tick" :x="p.x" :y="HEIGHT - 8"
            text-anchor="middle">{{ p.hours }}</text>
      <g v-for="p in plot.dots" :key="p.t" class="lw-chart__dot" tabindex="0" role="button"
         :class="{ 'is-low': p.lowest, 'is-selected': p.t === selected, [`is-${p.tone}`]: p.lowest }"
         :aria-label="p.aria" :aria-pressed="p.t === selected ? 'true' : 'false'" :data-t="p.t"
         data-test="chart-point" @click="emit('select', p.t)" @focus="emit('select', p.t)"
         @keydown.enter.prevent="emit('select', p.t)" @keydown.space.prevent="emit('select', p.t)">
        <circle :cx="p.x" :cy="p.y" r="16" class="lw-chart__hit" />
        <circle :cx="p.x" :cy="p.y" :r="p.lowest ? 7 : 5" class="lw-chart__mark" />
      </g>
    </svg>
    <p v-else class="lw-time" data-test="chart-empty">No known point to draw; the table lists each one.</p>
  </div>
</template>

<script setup>
/**
 * Projected cash P drawn from the API's own points (handoff T5, the integrity appendix): a step
 * line, since P only moves at a flow's or an obligation's time, the reserve floor, and the lowest
 * point marked green when it holds the floor and red when it does not. Each point is a control:
 * focus or click selects its instant for the caller, who shows P's terms there and keeps the text
 * table of the same points. An unknown value is not drawn and never drawn as zero.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { againstFloor, formatTime, hoursFrom, metricText } from '../api/v1.js'

const props = defineProps({
  points: { type: Array, required: true }, // [{ t, value: metric }]
  asOf: { type: String, required: true },
  floor: { type: Object, default: null },
  selected: { type: String, default: null },
  label: { type: String, default: 'Projected cash P against the reserve floor' }
})
const emit = defineEmits(['select'])

const HEIGHT = 220
const PAD_L = 16
const PAD_R = 24
const PAD_T = 28
const PAD_B = 36

const box = ref(null)
const width = ref(640)
let observer = null
onMounted(() => {
  const measure = () => { width.value = Math.max(280, Math.round(box.value?.clientWidth || 640)) }
  measure()
  if (window.ResizeObserver) {
    observer = new ResizeObserver(measure)
    observer.observe(box.value)
  }
})
onBeforeUnmount(() => observer?.disconnect())

const floorText = computed(() => metricText(props.floor))

const plot = computed(() => {
  const known = props.points
    .filter((p) => p.value?.minor != null)
    .map((p) => ({ ...p, h: (Date.parse(p.t) - Date.parse(props.asOf)) / 3_600_000 }))
  if (!known.length) return null
  const low = known.reduce((a, b) => (b.value.minor < a.value.minor ? b : a))
  const floorMinor = props.floor?.minor ?? null
  const ys = known.map((p) => p.value.minor).concat(floorMinor === null ? [] : [floorMinor])
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)]
  const span = y1 - y0 || Math.max(1, Math.abs(y1))
  const lo = y0 - span * 0.15
  const hi = y1 + span * 0.1
  const hs = known.map((p) => p.h)
  const [h0, h1] = [Math.min(...hs), Math.max(...hs)]
  const w = width.value
  const sx = (h) => (h1 === h0 ? w / 2 : PAD_L + 24 + ((h - h0) / (h1 - h0)) * (w - PAD_L - PAD_R - 48))
  const sy = (y) => PAD_T + (1 - (y - lo) / (hi - lo)) * (HEIGHT - PAD_T - PAD_B)
  const line = []
  known.forEach((p, i) => {
    if (i > 0) line.push(`${sx(p.h).toFixed(1)},${sy(known[i - 1].value.minor).toFixed(1)}`)
    line.push(`${sx(p.h).toFixed(1)},${sy(p.value.minor).toFixed(1)}`)
  })
  const dots = known.map((p) => {
    const lowest = p === low
    const { state } = againstFloor(p.value, props.floor)
    const hours = hoursFrom(props.asOf, p.t)
    return {
      t: p.t,
      x: sx(p.h),
      y: sy(p.value.minor),
      hours,
      lowest,
      tone: state === 'breached' ? 'bad' : state === 'kept' ? 'ok' : 'muted',
      aria: `${hours}, ${formatTime(p.t).utc}: P ${metricText(p.value)}${lowest ? ', the minimum' : ''}`
    }
  })
  return {
    line: line.join(' '),
    dots,
    floorY: floorMinor === null ? null : sy(floorMinor)
  }
})
</script>

<style scoped>
.lw-chart {
  width: 100%;
  min-width: 0;
  contain: inline-size; /* its width is the column's, never its own drawing's */
}

.lw-chart__svg {
  display: block;
  overflow: visible;
}

.lw-chart__line {
  stroke: var(--lw-brand);
  stroke-width: 2.5;
}

.lw-chart__floor {
  stroke: var(--lw-warn);
  stroke-width: 1.5;
  stroke-dasharray: 6 4;
}

.lw-chart__note,
.lw-chart__tick {
  fill: var(--lw-ink-muted);
  font-family: var(--lw-font-text);
  font-size: 12px;
}

.lw-chart__hit { fill: transparent; }

.lw-chart__mark {
  fill: var(--lw-surface-raised);
  stroke: var(--lw-brand);
  stroke-width: 2.5;
}

.lw-chart__dot { cursor: pointer; outline: none; }
.lw-chart__dot.is-low.is-ok .lw-chart__mark { fill: var(--lw-ok); stroke: var(--lw-ok); }
.lw-chart__dot.is-low.is-bad .lw-chart__mark { fill: var(--lw-bad); stroke: var(--lw-bad); }
.lw-chart__dot.is-selected .lw-chart__mark { stroke-width: 4; }

.lw-chart__dot:focus-visible .lw-chart__hit {
  stroke: var(--lw-focus);
  stroke-width: 3;
}
</style>

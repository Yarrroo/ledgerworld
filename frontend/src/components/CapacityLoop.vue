<template>
  <div ref="root" class="lw-loop" data-test="loop">
    <svg :viewBox="`0 0 ${box.W} ${box.H}`" :height="box.H" aria-hidden="true">
      <defs>
        <pattern :id="`${uid}-diag`" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="7" height="7" class="lw-loop__held" /><line x1="0" y1="0" x2="0" y2="7" class="lw-loop__stripe" stroke-width="3" />
        </pattern>
        <pattern :id="`${uid}-flat`" width="5" height="5" patternUnits="userSpaceOnUse">
          <rect width="5" height="5" class="lw-loop__held" /><line x1="0" y1="0.6" x2="5" y2="0.6" class="lw-loop__stripe" stroke-width="1.4" />
        </pattern>
        <marker :id="`${uid}-arrow`" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
                orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="lw-loop__head" /></marker>
      </defs>

      <!-- the pool: its settled cash as a column, drawn to scale -->
      <g data-test="map-node" :data-node="model.pool.id">
        <template v-if="box.phone">
          <text x="0" y="16" font-size="15" class="is-strong">{{ model.pool.name }}</text>
          <text :x="box.W" y="16" :font-size="box.fs" text-anchor="end" class="is-muted">settled known {{ model.settled }}</text>
        </template>
        <text v-else x="0" y="20" font-size="17" class="is-strong">{{ model.pool.name }}<tspan class="is-muted" font-weight="400"
          font-size="14" dx="10">· settled known {{ model.settled }} · Known · drawn to scale</tspan></text>
        <rect x="0" :y="box.top" :width="box.cw" :height="box.kpH" class="lw-loop__free" data-part="K_p" />
        <rect v-for="s in box.segments" :key="s.key" x="0" :y="s.y" :width="box.cw" :height="s.h" :data-part="s.key"
              :fill="`url(#${uid}-${s.key === 'floor' ? 'flat' : 'diag'})`" />
        <line x1="0" :x2="box.cw" :y1="box.capB" :y2="box.capB" class="lw-loop__cut" stroke-width="2" />
        <line x1="0" :x2="box.lx - 8" :y1="box.floorY" :y2="box.floorY" class="lw-loop__ink" stroke-width="2" stroke-dasharray="3 2" />
        <text :x="box.lx" :y="box.capY" :font-size="box.big" class="is-strong" data-test="capacity-value">{{ model.capacity }}</text>
        <template v-if="box.phone || !box.midLabel">
          <text :x="box.lx" :y="box.capY + 20" font-size="14" class="is-strong">Can lend you</text>
          <text :x="box.lx" :y="box.capY + 37" :font-size="box.fs" class="is-muted">the API’s figure · Known</text>
          <text :x="box.lx" :y="box.capY + 53" :font-size="box.fs" class="is-muted">a dependency, not a payment</text>
        </template>
        <text v-else :x="box.lx" :y="box.capY + 26" font-size="14" class="is-muted">available capacity, the API’s figure · Known</text>
      </g>

      <!-- what the pool holds back, each part labelled with whose it is -->
      <g v-for="s in box.segments" :key="`l-${s.key}`" :data-test="s.borrower ? 'map-node' : undefined"
         :data-node="s.borrower || undefined">
        <text :x="box.lx" :y="s.ly" :font-size="box.fl" class="is-strong">{{ box.phone ? s.short : s.label }}</text>
        <text v-if="s.sub" :x="box.lx" :y="s.ly + box.subGap" :font-size="box.fs" class="is-muted">{{ s.sub }}</text>
      </g>

      <!-- can lend you: a dependency, not a payment -->
      <line v-if="box.arrow" :x1="box.arrow.x1" :x2="box.arrow.x2" :y1="box.arrow.y" :y2="box.arrow.y" class="lw-loop__ink"
            stroke-width="2" :marker-end="`url(#${uid}-arrow)`" />
      <template v-if="box.midLabel">
        <text :x="box.midLabel.x" :y="box.arrow.y - 10" font-size="15" text-anchor="middle" class="is-strong">Can lend you up to {{ model.capacity }}</text>
        <text :x="box.midLabel.x" :y="box.arrow.y + 22" font-size="14" text-anchor="middle" class="is-muted">a dependency, not a payment</text>
      </template>
      <g data-test="map-node" :data-node="model.you.id">
        <rect :x="box.you.x" :y="box.you.y" :width="box.you.w - 1" :height="box.you.h" rx="8" class="lw-loop__box" stroke-width="1.5" />
        <template v-if="box.phone">
          <text :x="box.you.x + 12" :y="box.you.y + 24" font-size="15" class="is-strong">You</text>
          <text v-for="(line, i) in box.youLines" :key="line" :x="box.you.x + 12" :y="box.you.y + 42 + 14 * i" :font-size="box.fs"
                class="is-muted">{{ line }}</text>
        </template>
        <template v-else>
          <text :x="box.you.x + 16" :y="box.you.y + 28" font-size="16" class="is-strong">You · {{ model.you.name }}</text>
          <text v-if="model.you.cash" :x="box.you.x + 16" :y="box.you.y + 50" font-size="14">Settled cash {{ model.you.cash }}</text>
          <text :x="box.you.x + 16" :y="box.you.y + 70" font-size="13" class="is-muted">{{ model.venue ? 'borrows from the pool, draws from the venue' : 'borrows from the pool' }}</text>
        </template>
      </g>

      <!-- the venue under both: the pool's counted balance and your expected withdrawal -->
      <g v-if="box.venue" data-test="map-node" :data-node="model.venue.id">
        <path :d="box.venue.link" fill="none" class="lw-loop__ink" stroke-width="1.5" stroke-dasharray="4 3"
              :marker-end="`url(#${uid}-arrow)`" />
        <text :x="box.venue.linkX" :y="box.venue.linkY" font-size="13" :text-anchor="box.phone ? 'start' : 'end'"
              class="is-muted">{{ box.phone ? 'counted inside' : `counted inside the ${model.settled}` }}</text>
        <rect :x="box.venue.x" :y="box.venue.y" :width="box.cw" :height="box.venue.h" class="lw-loop__venue" stroke-width="1.5"
              stroke-dasharray="4 3" />
        <text :x="box.venue.tx" :y="box.venue.ty" :font-size="box.phone ? 15 : 17" class="is-strong">{{ model.venue.name }}{{ box.phone ? '' : ' · venue' }}</text>
        <text :x="box.venue.tx" :y="box.venue.ty + (box.phone ? 18 : 22)" :font-size="box.fs"><tspan class="is-strong">The pool:</tspan>
          {{ model.venue.pool }}</text>
        <text :x="box.venue.tx" :y="box.venue.ty + (box.phone ? 34 : 42)" :font-size="box.fs" class="is-muted is-italic">which claim it backs is not itemised</text>
        <template v-if="model.venue.yours">
          <text ref="owes" :x="box.venue.tx" :y="box.venue.oy" :font-size="box.fs"><tspan class="is-strong">Your treasury:</tspan>
            {{ model.venue.yours }}</text>
          <text v-if="model.venue.when" :x="box.venue.tx" :y="box.venue.oy + (box.phone ? 16 : 20)" :font-size="box.fs"
                class="is-muted">{{ box.phone ? model.venue.whenShort : model.venue.when }}</text>
          <path :d="box.venue.loop" fill="none" class="lw-loop__ink" stroke-width="1.5" :marker-end="`url(#${uid}-arrow)`" />
          <template v-if="!box.phone">
            <text :x="box.venue.rx + 10" :y="box.venue.my" font-size="13" class="is-muted">the same venue</text>
            <text :x="box.venue.rx + 10" :y="box.venue.my + 18" font-size="13" class="is-muted">under both</text>
          </template>
        </template>
      </g>
    </svg>
  </div>
</template>

<script setup>
/**
 * What the pool's lending capacity rests on, as one drawing (Lending, board item 177): the pool's
 * settled known cash as a column at one scale, cut into what it can still lend (the API's K_p, on
 * top) and each part the API takes away (a committed line, the reserve floor, any pledged or due
 * amount), with the parts at $0 named once in words; "Can lend you" as an arrow to the treasury,
 * a dependency and not a payment; and, when the overview relates the pool to a venue, that venue
 * as a block at the same scale, reached from the column (its balance is counted, the claim it
 * backs is not itemised) and from the treasury's expected withdrawal, so one venue is seen under
 * both. Every amount arrives formatted from the API; this component only places it.
 *
 * Two layouts by the drawing's own width: wide (the arrow labelled mid-way, the venue beside the
 * column) and narrow (the labels stacked under the figure, the venue under the column).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'

const props = defineProps({
  /**
   * { pool: {id, name}, settled, capacity, settledMinor, kpMinor,
   *   segments: [{key, minor, label, short, sub, borrower?}] (top to bottom, under K_p),
   *   you: {id, name, cash}, venue: {id, name, minor, pool, yours, when, whenShort} | null }
   */
  model: { type: Object, required: true }
})

const uid = `lw-loop-${useId()}`
const root = ref(null)
const owes = ref(null)
const width = ref(0)
const owesWidth = ref(0)

/** A text's width, estimated until the browser has measured it (jsdom never does). */
const est = (text, size, bold = false) => String(text).length * size * (bold ? 0.6 : 0.54)

const box = computed(() => {
  const m = props.model
  const W = Math.round(width.value) || 1100
  const phone = W < 1000
  const L = phone
    ? { col: 160, cw: 44, top: 30, lx: 56, big: 24, fs: 13, fl: 14, subGap: 15 }
    : { col: 300, cw: 72, top: 44, lx: 96, big: 36, fs: 14, fl: 15.5, subGap: 20 }
  const { col, cw, top, lx, big, fs } = L
  const scale = col / m.settledMinor
  const kpH = m.kpMinor * scale
  const capB = top + kpH

  // the figure and its words, then each part's label below the last, never on top of it
  const capY = top + (phone ? 36 : 58)
  const midRoom = W - 330 - (lx + est(m.capacity, big, true) + 24)
  const midLabel = !phone && midRoom >= 260
  let below = capY + (phone || !midLabel ? 53 : 26) + 6
  let y = capB
  const segments = m.segments.map((s) => {
    const h = s.minor * scale
    const ly = Math.max(y + (phone ? 14 : 22), below + (phone ? 14 : 18))
    below = ly + (s.sub ? L.subGap : 0) + 6
    const seg = { ...s, y, h, ly }
    y += h
    return seg
  })
  const floorB = top + col
  const floorY = segments.find((s) => s.key === 'floor')?.y ?? floorB

  const you = phone
    ? { x: W - 118, y: top + 6, w: 118, h: 62 }
    : { x: W - 330, y: top + 16, w: 330, h: 86 }
  const ax1 = lx + est(m.capacity, big, true) + (phone ? 12 : 24)
  const ay = capY - (phone ? 8 : 12)
  const arrow = you.x - 4 - ax1 >= 24 ? { x1: ax1, x2: you.x - 4, y: ay } : null

  // the phone box names the treasury on up to two lines of about 100 px
  const youLines = []
  for (const word of String(m.you.name).split(' ')) {
    const last = youLines.length - 1
    if (last >= 0 && est(`${youLines[last]} ${word}`, fs) <= 100) youLines[last] += ` ${word}`
    else youLines.push(word)
  }

  let H = Math.max(floorB, below) + 12
  let venue = null
  if (m.venue) {
    const v = m.venue
    const h = v.minor != null && v.minor > 0 ? v.minor * scale : 24
    let vx, vy, tx, link, linkX, linkY
    if (phone) {
      vx = 0
      vy = Math.max(floorB, below) + 26
      tx = lx
      link = `M${cw / 2},${floorB + 2} V${vy - 4}`
      linkX = cw / 2 + 8
      linkY = vy - 10
    } else {
      vx = Math.round(Math.min(W * 0.47, W - 542))
      vy = top + 190
      tx = vx + cw + 20
      const hy = Math.max(floorB + 30, vy + h + 24)
      link = `M${cw / 2},${floorB + 2} V${hy} H${vx + cw / 2} V${vy + h + 6}`
      linkX = vx - 14
      linkY = hy - 8
    }
    const ty = vy + (phone ? 12 : 14)
    const oy = ty + (phone ? 56 : 68)
    const end = tx + (owesWidth.value || est(`Your treasury: ${v.yours ?? ''}`, fs)) + 6
    const rx = phone ? W - 10 : Math.min(W - 112, Math.max(you.x + you.w / 2, end + 24))
    const loop = `M${Math.ceil(end)},${oy - 4} H${rx} V${you.y + you.h + 4}`
    venue = { x: vx, y: vy, h, tx, ty, oy, rx, my: (oy + you.y + you.h) / 2, link, linkX, linkY, loop }
    H = Math.max(H, vy + h + (phone ? 6 : 40), (v.yours ? oy + (v.when ? (phone ? 16 : 20) : 0) : ty + 42) + (phone ? 6 : 12))
  }
  return {
    W, H: Math.ceil(H), phone, ...L, kpH, capB, capY, floorY, segments, you, youLines, arrow,
    midLabel: midLabel && arrow ? { x: (arrow.x1 + arrow.x2) / 2 } : null, venue
  }
})

let observer = null
function measure () {
  width.value = root.value?.clientWidth ?? 0
  nextTick(() => {
    const el = owes.value
    owesWidth.value = el?.getComputedTextLength ? el.getComputedTextLength() : 0
  })
}
onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(measure)
    observer.observe(root.value)
  } else window.addEventListener('resize', measure)
})
watch(() => [props.model, box.value.phone], () => nextTick(measure), { deep: true })
onBeforeUnmount(() => {
  observer?.disconnect()
  window.removeEventListener('resize', measure)
})
</script>

<style scoped>
.lw-loop svg { display: block; width: 100%; overflow: visible; }
.lw-loop text { font-family: var(--lw-font-text); font-variant-numeric: tabular-nums; fill: var(--lw-ink); }
.lw-loop .is-muted { fill: var(--lw-ink-muted); }
.lw-loop .is-strong { font-weight: 600; }
.lw-loop .is-italic { font-style: italic; }
.lw-loop__free { fill: var(--lw-brand); }
.lw-loop__held { fill: #B7C3BA; }
.lw-loop__stripe { stroke: rgba(23, 37, 30, 0.3); }
.lw-loop__cut { stroke: var(--lw-surface); }
.lw-loop__ink { stroke: var(--lw-ink); }
.lw-loop__head { fill: var(--lw-ink); }
.lw-loop__box { fill: var(--lw-surface); stroke: var(--lw-ink); }
.lw-loop__venue { fill: var(--lw-selected); stroke: var(--lw-ink); }

@media (prefers-color-scheme: dark) {
  .lw-loop__held { fill: #4A5E53; }
  .lw-loop__stripe { stroke: rgba(236, 233, 223, 0.26); }
}
</style>

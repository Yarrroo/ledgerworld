<template>
  <div ref="box" class="lw-map" data-test="map">
    <svg v-if="nodes.length" :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" class="lw-map__svg"
         role="group" :aria-label="label">
      <defs>
        <marker v-for="t in [...TYPES, { key: 'causal' }]" :id="`${uid}-${t.key}`" :key="t.key" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" :class="`lw-map__head--${t.key}`" />
        </marker>
      </defs>
      <g v-for="e in drawn" :key="e.id" class="lw-map__edge" :class="[`is-${e.type}`, { 'is-causal': e.causal, 'is-selected': isSel('edge', e.id), 'is-dim': e.dim }]"
         tabindex="0" role="button" :aria-label="e.aria" :aria-pressed="isSel('edge', e.id) ? 'true' : 'false'"
         :data-edge="e.id" data-test="map-edge" @click="pick('edge', e.id)"
         @keydown.enter.prevent="pick('edge', e.id)" @keydown.space.prevent="pick('edge', e.id)">
        <line :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2" class="lw-map__hit" />
        <line :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2" class="lw-map__line" :marker-end="`url(#${uid}-${e.causal ? 'causal' : e.type})`" />
      </g>
      <g v-for="n in placed" :key="n.id" class="lw-map__node" :class="{ 'is-selected': isSel('node', n.id), 'is-dim': n.dim }"
         tabindex="0" role="button" :aria-label="n.aria" :aria-pressed="isSel('node', n.id) ? 'true' : 'false'"
         :data-node="n.id" data-test="map-node" @click="pick('node', n.id)"
         @keydown.enter.prevent="pick('node', n.id)" @keydown.space.prevent="pick('node', n.id)">
        <rect :x="n.x - n.w / 2" :y="n.y - 22" :width="n.w" height="44" rx="6" />
        <svg v-if="n.icon" :x="n.x - n.w / 2 + 8" :y="n.y - 11" width="22" height="22" viewBox="0 0 24 24"
             class="lw-map__icon" aria-hidden="true"><path :d="n.icon" /></svg>
        <text :x="n.tx" :y="n.y + 5 - (n.lines.length - 1) * n.step / 2" text-anchor="middle" data-test="map-node-name"
              :class="{ 'is-tight': n.lines.length > 2 }">
          <tspan v-for="(line, i) in n.lines" :key="i" :x="n.tx" :dy="i ? n.step : 0"
                 :class="{ 'lw-map__sub': n.sub && i === n.lines.length - 1 }">{{ line }}</tspan>
        </text>
      </g>
      <g v-if="showLabels" class="lw-map__labels" aria-hidden="true">
        <text v-for="t in tags" :key="t.id" :x="t.x" :y="t.y" text-anchor="middle" dominant-baseline="central"
              class="lw-map__edge-label" :class="{ 'is-dim': t.dim, 'is-causal': t.causal }" :data-edge="t.id" data-test="map-edge-label">{{ t.text }}</text>
      </g>
    </svg>
    <p v-else class="lw-time" data-test="map-empty">{{ empty }}</p>
    <ul v-if="legend" class="lw-map__legend" aria-label="Edge types">
      <li v-for="t in TYPES" :key="t.key" :class="`is-${t.key}`"><span aria-hidden="true" />{{ t.word }}</li>
    </ul>
  </div>
</template>

<script setup>
/**
 * A relationship map (handoff L3, S2): nodes on a ring around the first one, typed directed
 * edges — financial (a contract or an obligation), exposure (a shared venue), information
 * (prices, posts, citations) and request (asking for funds). An information edge is never drawn
 * as a cash flow. Every node and edge is a keyboard control that emits `select({ kind, id })`;
 * the caller owns the selection and the details. The caller also lists the same nodes and edges
 * as text, so nothing here is the only way to reach them.
 *
 * Optional, for a map drawn as mockup 04 (prp/2026-10-29-ux-pass/MATCH.md): a node's `icon` (a
 * 24-unit path) and `sub` line (a figure under its name); a `layout` placing nodes by id at
 * fractions of the box where it is wide enough (else the ring); an edge marked `causal` drawn as
 * the amber path of what the rounds changed; and the legend left out (`legend` false).
 */
import { computed, ref, useId } from 'vue'
import { useWidth } from './width.js'

const props = defineProps({
  nodes: { type: Array, required: true }, // [{ id, label }]
  edges: { type: Array, required: true }, // [{ id, from, to, type, label, tag? }]: tag is the map's caption
  selected: { type: Object, default: null }, // { kind: 'node' | 'edge', id }
  focus: { type: String, default: null }, // a node whose own edges stay bright
  label: { type: String, default: 'Relationship map' },
  empty: { type: String, default: 'No relationship to draw' },
  layout: { type: Object, default: null }, // { [id]: [fx, fy] }, fractions of the box
  legend: { type: Boolean, default: true }
})
const emit = defineEmits(['select'])

const TYPES = [
  { key: 'financial', word: 'Financial: contract or obligation' },
  { key: 'exposure', word: 'Exposure: shared venue' },
  { key: 'information', word: 'Information: never a cash flow' },
  { key: 'request', word: 'Request for funds' }
]

const uid = `lw-map-${useId()}`
const box = ref(null)
const width = useWidth(box)

const height = computed(() => (width.value < 600 ? 340 : 380))
const fixed = computed(() => Boolean(props.layout) && width.value >= 600)
const showLabels = computed(() => width.value >= 600)

const isSel = (kind, id) => props.selected?.kind === kind && props.selected?.id === id
const pick = (kind, id) => emit('select', { kind, id })

/** `text` cut to `max` characters with an ellipsis. */
const cut = (text, max) => (text.length <= max ? text : `${text.slice(0, max - 1)}…`)

/**
 * A node's name on at most three lines of `max` characters, broken between words; only a word
 * longer than a line, or what is left after the third, is cut. A name is never swapped for its
 * id: the id is not what a reader knows.
 */
function lines (text, max) {
  const words = text.split(' ')
  const out = []
  while (words.length && out.length < 3) {
    let line = cut(words.shift(), max)
    while (words.length && `${line} ${words[0]}`.length <= max) line = `${line} ${words.shift()}`
    out.push(line)
  }
  if (words.length) out[2] = cut(`${out[2]} ${words.join(' ')}`, max)
  return out
}

const placed = computed(() => {
  const w = width.value
  const h = height.value
  const nodeW = Math.min(184, Math.max(88, Math.floor(w / 4.2)))
  const max = Math.floor(nodeW / 7.4)
  const [center, ...ring] = props.nodes
  const rx = w / 2 - nodeW / 2 - 8
  const ry = h / 2 - 30
  const near = new Set(props.focus
    ? props.edges.filter((e) => e.from === props.focus || e.to === props.focus).flatMap((e) => [e.from, e.to])
    : [])
  const at = (n, x, y) => {
    // an icon takes the box's left; the name and its sub line sit centred in what is left
    const room = n.icon ? max - 4 : max
    const named = n.sub ? [...lines(n.label, room).slice(0, 2), n.sub] : lines(n.label, room)
    return {
      ...n, x, y, w: nodeW, tx: n.icon ? x + 13 : x, lines: named, step: named.length > 2 ? 13 : 15,
      aria: `${n.label}${n.role ? `, ${n.role}` : ''}${n.sub ? `, ${n.sub}` : ''}`,
      dim: Boolean(props.focus) && !near.has(n.id)
    }
  }
  if (fixed.value) {
    // the given places, kept inside the box; a node the layout does not name goes on a free ring spot
    const clampX = (fx) => Math.min(w - nodeW / 2 - 4, Math.max(nodeW / 2 + 4, fx * w))
    const clampY = (fy) => Math.min(h - 26, Math.max(26, fy * h))
    const loose = props.nodes.filter((n) => !props.layout[n.id])
    return props.nodes.map((n) => {
      const spot = props.layout[n.id]
      if (spot) return at(n, clampX(spot[0]), clampY(spot[1]))
      const i = loose.indexOf(n)
      const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, loose.length)
      return at(n, w / 2 + rx * Math.cos(a), h / 2 + ry * Math.sin(a))
    })
  }
  return [
    at(center, w / 2, h / 2),
    ...ring.map((n, i) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / ring.length
      return at(n, w / 2 + rx * Math.cos(a), h / 2 + ry * Math.sin(a))
    })
  ]
})

/** Edges between placed nodes, trimmed to the node boxes; parallel edges are offset apart. */
const drawn = computed(() => {
  const where = new Map(placed.value.map((n) => [n.id, n]))
  const seen = new Map()
  const words = Object.fromEntries(TYPES.map((t) => [t.key, t.key]))
  return props.edges.filter((e) => where.has(e.from) && where.has(e.to) && e.from !== e.to).map((e) => {
    const a = where.get(e.from)
    const b = where.get(e.to)
    const pair = [e.from, e.to].sort().join('|')
    const n = seen.get(pair) ?? 0
    seen.set(pair, n + 1)
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len = Math.hypot(dx, dy) || 1
    const off = n === 0 ? 0 : (n % 2 ? 1 : -1) * Math.ceil(n / 2) * 10
    const [ox, oy] = [(-dy / len) * off, (dx / len) * off]
    const trim = (node, sign) => {
      const tx = Math.abs(dx) < 1e-6 ? Infinity : (node.w / 2 + 4) / Math.abs(dx / len)
      const ty = Math.abs(dy) < 1e-6 ? Infinity : 26 / Math.abs(dy / len)
      const t = Math.min(tx, ty)
      return { x: node.x + sign * (dx / len) * t + ox, y: node.y + sign * (dy / len) * t + oy }
    }
    const p = trim(a, 1)
    const q = trim(b, -1)
    const from = a.label
    const to = b.label
    return {
      ...e, x1: p.x, y1: p.y, x2: q.x, y2: q.y, mx: (p.x + q.x) / 2, my: (p.y + q.y) / 2,
      aria: `${words[e.type] ?? e.type} edge, ${from} to ${to}: ${e.label}`,
      dim: Boolean(props.focus) && e.from !== props.focus && e.to !== props.focus
    }
  })
})

/** Edge-label metrics at the label's 12px: a generous character width, so the estimate never runs short. */
const CHAR = 6.8
const TAG_H = 16

/**
 * Each edge's caption, placed where it overlaps no node box, no caption already placed and no
 * edge of the map's frame: tried at the edge's middle, then along it, on either side. A caption
 * with no free place is not drawn; the edge keeps its full label in its accessible name and
 * in the caller's list.
 */
const tags = computed(() => {
  const w = width.value
  const h = height.value
  const pad = 4
  const taken = placed.value.map((n) => ({ x: n.x - n.w / 2 - pad, y: n.y - 22 - pad, w: n.w + 2 * pad, h: 44 + 2 * pad }))
  const free = (b) => b.x >= 0 && b.y >= 0 && b.x + b.w <= w && b.y + b.h <= h &&
    taken.every((o) => b.x + b.w <= o.x || o.x + o.w <= b.x || b.y + b.h <= o.y || o.y + o.h <= b.y)
  const out = []
  for (const e of drawn.value) {
    const text = cut(e.tag ?? e.label, 24)
    const tw = text.length * CHAR + 6
    const dx = e.x2 - e.x1
    const dy = e.y2 - e.y1
    const len = Math.hypot(dx, dy) || 1
    // the normal, and how far a caption's centre sits off the line to clear it
    const [nx, ny] = [-dy / len, dx / len]
    const off = Math.abs(nx) * (tw / 2) + Math.abs(ny) * (TAG_H / 2) + 3
    // only right beside its own line: a caption further out reads as another edge's
    let spot = null
    for (const t of [0.5, 0.38, 0.62, 0.26, 0.74, 0.16, 0.84]) {
      for (const side of [-1, 1]) {
        const cx = e.x1 + dx * t + nx * off * side
        const cy = e.y1 + dy * t + ny * off * side
        const b = { x: cx - tw / 2, y: cy - TAG_H / 2, w: tw, h: TAG_H }
        if (free(b)) { spot = { cx, cy, b }; break }
      }
      if (spot) break
    }
    if (!spot) continue
    taken.push(spot.b)
    out.push({ id: e.id, text, x: spot.cx, y: spot.cy, dim: e.dim, causal: e.causal })
  }
  return out
})
</script>

<style scoped>
.lw-map { width: 100%; min-width: 0; contain: inline-size; }
.lw-map__svg { display: block; overflow: visible; }

.lw-map__node rect {
  fill: var(--lw-surface-raised);
  stroke: var(--lw-ink-muted);
  stroke-width: 1.5;
}

.lw-map__node text {
  fill: var(--lw-ink);
  font-family: var(--lw-font-text);
  font-size: 13px;
  font-weight: 600;
}

.lw-map__node text.is-tight { font-size: 12px; }
.lw-map__node .lw-map__sub { font-size: 12px; font-weight: 400; fill: var(--lw-ink-muted); }
.lw-map__icon path { fill: none; stroke: var(--lw-ink); stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }

.lw-map__node,
.lw-map__edge { cursor: pointer; outline: none; }
.lw-map__node.is-selected rect { fill: var(--lw-selected); stroke: var(--lw-brand); stroke-width: 3; }
.lw-map__node:focus-visible rect { stroke: var(--lw-focus); stroke-width: 3; }
.lw-map__node.is-dim,
.lw-map__edge.is-dim { opacity: 0.35; }

.lw-map__hit { stroke: transparent; stroke-width: 16; }
.lw-map__line { stroke-width: 2; fill: none; }
.lw-map__edge.is-financial .lw-map__line { stroke: var(--lw-brand); }
.lw-map__edge.is-exposure .lw-map__line { stroke: var(--lw-warn); stroke-dasharray: 7 4; }
.lw-map__edge.is-information .lw-map__line { stroke: var(--lw-logo); stroke-dasharray: 2 4; }
.lw-map__edge.is-request .lw-map__line { stroke: var(--lw-ink-muted); stroke-dasharray: 10 3 2 3; }
.lw-map__edge.is-causal .lw-map__line { stroke: var(--lw-warn); stroke-dasharray: 6 4; }
.lw-map__edge.is-selected .lw-map__line { stroke-width: 4; }
.lw-map__edge:focus-visible .lw-map__hit { stroke: var(--lw-focus); stroke-opacity: 0.35; }

.lw-map__head--financial { fill: var(--lw-brand); }
.lw-map__head--exposure { fill: var(--lw-warn); }
.lw-map__head--information { fill: var(--lw-logo); }
.lw-map__head--request { fill: var(--lw-ink-muted); }
.lw-map__head--causal { fill: var(--lw-warn); }

.lw-map__labels { pointer-events: none; }
.lw-map__edge-label.is-dim { opacity: 0.35; }
.lw-map__edge-label.is-causal { fill: var(--lw-warn-text); font-weight: 600; }

.lw-map__edge-label {
  fill: var(--lw-ink-muted);
  font-family: var(--lw-font-text);
  font-size: 12px;
  paint-order: stroke;
  stroke: var(--lw-surface);
  stroke-width: 4px;
}

.lw-map__legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2) var(--lw-space-4);
  margin: var(--lw-space-2) 0 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
  color: var(--lw-ink-muted);
}

.lw-map__legend span {
  display: inline-block;
  width: 22px;
  margin-right: var(--lw-space-1);
  vertical-align: middle;
  border-top: 2px solid var(--lw-brand);
}

.lw-map__legend .is-exposure span { border-top: 2px dashed var(--lw-warn); }
.lw-map__legend .is-information span { border-top: 2px dotted var(--lw-logo); }
.lw-map__legend .is-request span { border-top: 2px dashed var(--lw-ink-muted); }
</style>

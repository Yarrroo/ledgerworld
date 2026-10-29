<template>
  <div ref="box" class="lw-map" data-test="map">
    <svg v-if="nodes.length" :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" class="lw-map__svg"
         role="group" :aria-label="label">
      <defs>
        <marker v-for="t in TYPES" :id="`${uid}-${t.key}`" :key="t.key" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" :class="`lw-map__head--${t.key}`" />
        </marker>
      </defs>
      <g v-for="e in drawn" :key="e.id" class="lw-map__edge" :class="[`is-${e.type}`, { 'is-selected': isSel('edge', e.id), 'is-dim': e.dim }]"
         tabindex="0" role="button" :aria-label="e.aria" :aria-pressed="isSel('edge', e.id) ? 'true' : 'false'"
         :data-edge="e.id" data-test="map-edge" @click="pick('edge', e.id)"
         @keydown.enter.prevent="pick('edge', e.id)" @keydown.space.prevent="pick('edge', e.id)">
        <line :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2" class="lw-map__hit" />
        <line :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2" class="lw-map__line" :marker-end="`url(#${uid}-${e.type})`" />
        <text v-if="showLabels" :x="e.mx" :y="e.my - 6" text-anchor="middle" class="lw-map__edge-label">{{ e.short }}</text>
      </g>
      <g v-for="n in placed" :key="n.id" class="lw-map__node" :class="{ 'is-selected': isSel('node', n.id), 'is-dim': n.dim }"
         tabindex="0" role="button" :aria-label="n.aria" :aria-pressed="isSel('node', n.id) ? 'true' : 'false'"
         :data-node="n.id" data-test="map-node" @click="pick('node', n.id)"
         @keydown.enter.prevent="pick('node', n.id)" @keydown.space.prevent="pick('node', n.id)">
        <rect :x="n.x - n.w / 2" :y="n.y - 22" :width="n.w" height="44" rx="6" />
        <text :x="n.x" :y="n.y + 5" text-anchor="middle">{{ n.short }}</text>
      </g>
    </svg>
    <p v-else class="lw-time" data-test="map-empty">{{ empty }}</p>
    <ul class="lw-map__legend" aria-label="Edge types">
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
 */
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'

const props = defineProps({
  nodes: { type: Array, required: true }, // [{ id, label }]
  edges: { type: Array, required: true }, // [{ id, from, to, type, label }]
  selected: { type: Object, default: null }, // { kind: 'node' | 'edge', id }
  focus: { type: String, default: null }, // a node whose own edges stay bright
  label: { type: String, default: 'Relationship map' },
  empty: { type: String, default: 'No relationship to draw' }
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

const height = computed(() => (width.value < 600 ? 340 : 380))
const showLabels = computed(() => width.value >= 600)

const isSel = (kind, id) => props.selected?.kind === kind && props.selected?.id === id
const pick = (kind, id) => emit('select', { kind, id })

/**
 * The label, else its first two words (two parties often share a first word), else the short
 * id it was given, else cut with an ellipsis: a label never draws past its box.
 */
function short (text, max, id = '') {
  if (text.length <= max) return text
  const two = text.split(' ').slice(0, 2).join(' ')
  if (two.length <= max) return two
  if (id && id.length <= max) return id
  return `${text.slice(0, max - 1)}…`
}

const placed = computed(() => {
  const w = width.value
  const h = height.value
  const nodeW = Math.min(184, Math.max(84, Math.floor(w / 4.2)))
  const max = Math.floor(nodeW / 7.4)
  const [center, ...ring] = props.nodes
  const rx = w / 2 - nodeW / 2 - 8
  const ry = h / 2 - 30
  const near = new Set(props.focus
    ? props.edges.filter((e) => e.from === props.focus || e.to === props.focus).flatMap((e) => [e.from, e.to])
    : [])
  const at = (n, x, y) => ({
    ...n, x, y, w: nodeW, short: short(n.label, max, n.id), aria: `${n.label}${n.role ? `, ${n.role}` : ''}`,
    dim: Boolean(props.focus) && !near.has(n.id)
  })
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
      short: short(e.label, 22),
      aria: `${words[e.type] ?? e.type} edge, ${from} to ${to}: ${e.label}`,
      dim: Boolean(props.focus) && e.from !== props.focus && e.to !== props.focus
    }
  })
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
.lw-map__edge.is-selected .lw-map__line { stroke-width: 4; }
.lw-map__edge:focus-visible .lw-map__hit { stroke: var(--lw-focus); stroke-opacity: 0.35; }

.lw-map__head--financial { fill: var(--lw-brand); }
.lw-map__head--exposure { fill: var(--lw-warn); }
.lw-map__head--information { fill: var(--lw-logo); }
.lw-map__head--request { fill: var(--lw-ink-muted); }

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

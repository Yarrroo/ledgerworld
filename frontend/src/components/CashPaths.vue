<template>
  <section class="lw-live-panel" aria-labelledby="cash-title" data-test="cash">
    <h2 id="cash-title">Cash paths · round {{ round ?? '–' }}</h2>
    <p v-if="at === null" class="lw-live-empty" data-test="cash-unloaded">Round not loaded</p>
    <p v-else-if="!rows.length" class="lw-live-empty">No cash path recorded for this run</p>
    <ul v-else class="lw-cash">
      <li v-for="row in rows" :key="`${row.branch_id}|${row.account_id}`" class="lw-cash__row"
          :data-branch="row.branch_id">
        <div class="lw-cash__who">
          <span class="lw-cash__branch">{{ row.name }}</span>
          <span v-if="row.replay" class="lw-live-tag" data-test="cash-replay">Replay</span>
          <span class="lw-cash__account">{{ row.branch_id }} · {{ row.account_id }} · Hypothetical branch</span>
        </div>
        <div class="lw-cash__value" data-test="cash-value">{{ row.text }}</div>
        <svg v-if="row.line" class="lw-cash__spark" viewBox="0 0 100 24" preserveAspectRatio="none"
             role="img" :aria-label="`${row.name}: ${row.count} known points up to round ${round}`">
          <polyline :points="row.line" fill="none" stroke="currentColor" stroke-width="1.5"
                    vector-effect="non-scaling-stroke" />
        </svg>
      </li>
    </ul>
  </section>
</template>

<script setup>
/**
 * Each branch's cash at the cursor's round, read off its CashPath at exactly the round's instant
 * (`at`, epoch ms). A path with no point there says so; it never shows its latest value instead.
 * The small line is drawn from known points up to the round, nothing after it.
 */
import { computed } from 'vue'
import { metricText } from '../api/v1.js'

const props = defineProps({
  round: { type: Number, default: null },
  at: { type: Number, default: null },
  paths: { type: Array, default: () => [] },
  branches: { type: Array, default: () => [] }
})

function spark (points) {
  if (points.length < 2) return null
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const sx = (x) => (x1 === x0 ? 0 : ((x - x0) / (x1 - x0)) * 100)
  const sy = (y) => (y1 === y0 ? 12 : 22 - ((y - y0) / (y1 - y0)) * 20)
  return points.map((p) => `${sx(p.x).toFixed(2)},${sy(p.y).toFixed(2)}`).join(' ')
}

const rows = computed(() => {
  if (props.at === null) return []
  const meta = new Map(props.branches.map((b) => [b.branch_id, b]))
  return props.paths.map((path) => {
    const b = meta.get(path.branch_id)
    const point = path.points.find((p) => Date.parse(p.t) === props.at)
    const known = path.points
      .filter((p) => Date.parse(p.t) <= props.at && p.value.minor != null)
      .map((p) => ({ x: Date.parse(p.t), y: p.value.minor }))
      .sort((p, q) => p.x - q.x)
    return {
      branch_id: path.branch_id,
      account_id: path.account_id,
      name: b?.policy ?? (b && b.parent_branch_id === null ? 'Base run' : path.branch_id),
      replay: Boolean(b?.replay),
      text: point ? metricText(point.value) : `No point at round ${props.round}`,
      line: spark(known),
      count: known.length
    }
  })
})
</script>

<style scoped>
.lw-cash {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--lw-space-2);
}

.lw-cash__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--lw-space-1) var(--lw-space-3);
  padding: var(--lw-space-2) var(--lw-space-3);
  background: var(--live-raised);
}

.lw-cash__who {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2);
  align-items: baseline;
  min-width: 0;
}

.lw-cash__branch { font-weight: 600; overflow-wrap: anywhere; }

.lw-cash__account {
  color: var(--live-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.lw-cash__value {
  font-family: var(--lw-font-figure);
  font-size: 18px;
  text-align: right;
}

.lw-cash__spark {
  grid-column: 1 / -1;
  width: 100%;
  height: 24px;
  color: var(--live-brand);
}
</style>

<template>
  <div class="lw-scrubber" data-test="scrubber">
    <p class="lw-scrubber__value">
      <Tip v-if="hint" :text="hint"><span data-test="cursor">{{ valueText }}</span></Tip>
      <span v-else data-test="cursor">{{ valueText }}</span>
    </p>
    <slot />
    <div
      class="lw-scrubber__track"
      role="slider"
      tabindex="0"
      :aria-label="label"
      :aria-valuemin="first"
      :aria-valuemax="last"
      :aria-valuenow="modelValue ?? undefined"
      :aria-valuetext="ariaText"
      :aria-disabled="rounds.length ? undefined : 'true'"
      data-test="scrubber-slider"
      @keydown="onKey"
    >
      <template v-for="r in shown" :key="r">
        <button
          v-if="rounds.includes(r)"
          type="button"
          tabindex="-1"
          class="lw-scrubber__tick"
          :class="{ 'is-current': r === modelValue, 'is-unloaded': !loaded.includes(r), 'is-marked': marks[r] }"
          :aria-label="`Round ${r}${loaded.includes(r) ? '' : ', not loaded'}${marks[r] ? `, ${marks[r]}` : ''}`"
          :data-test="`tick-${r}`"
          @click="pick(r)"
        >
          <span v-if="marks[r]" class="lw-scrubber__flag" data-test="tick-mark">{{ marks[r] }}</span>
          <span class="lw-scrubber__mark" aria-hidden="true" />
          <span class="lw-scrubber__num">{{ r }}</span>
        </button>
        <span v-else class="lw-scrubber__tick is-future" :class="{ 'is-marked': marks[r] }" aria-hidden="true"
              :data-test="`future-${r}`">
          <span v-if="marks[r]" class="lw-scrubber__flag" data-test="tick-mark">{{ marks[r] }}</span>
          <span class="lw-scrubber__mark" />
          <span class="lw-scrubber__num">{{ r }}</span>
        </span>
      </template>
    </div>
  </div>
</template>

<script setup>
/**
 * The one committed-round cursor, drawn as mockup 04's round row: "Round N of H", a slot for what
 * sits beside it, then one dot per round of the horizon `horizon` (or of the committed rounds).
 * Only committed rounds are controls; a later round is drawn faded and cannot be chosen. A tick
 * whose round the API did not return is marked not loaded but stays selectable, so the panels can
 * say so instead of showing another round. `marks` labels a round ("Shock event"). Keyboard: ←/→
 * step, Home/End jump, over the committed rounds.
 */
import { computed } from 'vue'
import Tip from './Tip.vue'

const props = defineProps({
  rounds: { type: Array, required: true },
  loaded: { type: Array, default: () => [] },
  modelValue: { type: Number, default: null },
  tHours: { type: Number, default: null },
  label: { type: String, default: 'Committed round' },
  /** How rounds map to simulated time and the keys, on demand (a tooltip on the cursor's words). */
  hint: { type: String, default: '' },
  /** The rounds the run could reach; the dots after the last committed one are drawn, not chosen. */
  horizon: { type: Number, default: 0 },
  /** A word above a round's dot: { [round]: 'Shock event' }. */
  marks: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:modelValue'])

const first = computed(() => props.rounds[0] ?? 0)
const last = computed(() => props.rounds[props.rounds.length - 1] ?? 0)
const of = computed(() => Math.max(props.horizon, last.value))
const shown = computed(() => (props.horizon
  ? Array.from({ length: of.value }, (_, i) => i + 1)
  : props.rounds))
const valueText = computed(() => props.modelValue == null
  ? 'No round committed yet'
  : `Round ${props.modelValue} of ${of.value} · ${props.tHours === null ? 'simulated time not loaded' : props.horizon ? `${props.tHours}h simulated` : `simulated t=${props.tHours} h`}`)
const ariaText = computed(() => props.modelValue == null
  ? valueText.value
  : `${valueText.value} · ${props.tHours === null ? 'simulated time not loaded' : `simulated t=${props.tHours} h`}`)

function pick (r) {
  if (r !== props.modelValue) emit('update:modelValue', r)
}

const STEP = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }

function onKey (event) {
  const n = props.rounds.length
  if (!n) return
  const i = props.rounds.indexOf(props.modelValue)
  let at
  if (event.key === 'Home') at = 0
  else if (event.key === 'End') at = n - 1
  else if (STEP[event.key]) at = Math.min(n - 1, Math.max(0, (i < 0 ? n - 1 : i) + STEP[event.key]))
  else return
  event.preventDefault()
  pick(props.rounds[at])
}
</script>

<style scoped>
.lw-scrubber {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2) var(--lw-space-4);
  align-items: center;
  min-width: 0;
}

.lw-scrubber__value {
  margin: 0;
  font-weight: 600;
  color: var(--live-ink);
  white-space: nowrap;
}

.lw-scrubber__track {
  flex: 1 1 20rem;
  display: flex;
  min-width: 0;
  padding-top: 18px;
  overflow-x: auto;
  border-radius: var(--lw-radius);
}

.lw-scrubber__tick {
  position: relative;
  flex: 1 0 var(--lw-target);
  min-height: var(--lw-target);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--live-muted);
  font: inherit;
  cursor: pointer;
}

/* the line the dots sit on */
.lw-scrubber__tick::before {
  content: '';
  position: absolute;
  top: calc(50% - 9px);
  left: 0;
  right: 0;
  border-top: 1px solid var(--live-rule);
}

.lw-scrubber__mark {
  position: relative;
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--live-muted);
  border-radius: 50%;
  background: var(--live-surface);
  transition: transform 160ms ease, background-color 160ms ease;
}

.lw-scrubber__tick.is-future { cursor: default; opacity: 0.55; }
.lw-scrubber__tick.is-unloaded .lw-scrubber__mark { border-style: dashed; }
.lw-scrubber__tick.is-marked .lw-scrubber__mark { border-color: var(--live-warn); background: var(--live-warn); }

.lw-scrubber__tick.is-current { color: var(--live-ink); font-weight: 700; }
.lw-scrubber__tick.is-current .lw-scrubber__mark {
  transform: scale(1.6);
  border-color: var(--live-brand);
  background: var(--live-brand);
  box-shadow: 0 0 0 3px var(--live-surface), 0 0 0 4px var(--live-brand);
}

.lw-scrubber__flag {
  position: absolute;
  top: -16px;
  white-space: nowrap;
  font-size: 12px;
  color: var(--live-warn);
}

.lw-scrubber__num {
  font-family: var(--lw-font-figure);
  font-size: 12px;
}

.lw-scrubber__track:focus-visible {
  outline: 3px solid var(--live-brand);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .lw-scrubber__mark { transition: none; }
}
</style>

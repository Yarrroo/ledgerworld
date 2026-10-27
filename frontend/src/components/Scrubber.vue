<template>
  <div class="lw-scrubber" data-test="scrubber">
    <div
      class="lw-scrubber__track"
      role="slider"
      tabindex="0"
      :aria-label="label"
      :aria-valuemin="first"
      :aria-valuemax="last"
      :aria-valuenow="modelValue ?? undefined"
      :aria-valuetext="valueText"
      :aria-disabled="rounds.length ? undefined : 'true'"
      data-test="scrubber-slider"
      @keydown="onKey"
    >
      <button
        v-for="r in rounds"
        :key="r"
        type="button"
        tabindex="-1"
        class="lw-scrubber__tick"
        :class="{ 'is-current': r === modelValue, 'is-unloaded': !loaded.includes(r) }"
        :aria-label="`Round ${r}${loaded.includes(r) ? '' : ', not loaded'}`"
        :data-test="`tick-${r}`"
        @click="pick(r)"
      >
        <span class="lw-scrubber__mark" aria-hidden="true" />
        <span class="lw-scrubber__num">{{ r }}</span>
      </button>
    </div>
    <p class="lw-scrubber__value" data-test="cursor">{{ valueText }}</p>
  </div>
</template>

<script setup>
/**
 * The one committed-round cursor. Ticks are committed rounds only; a tick whose round the API did
 * not return is marked not loaded but stays selectable, so the panels can say so instead of
 * showing another round. Keyboard: ←/→ step, Home/End jump.
 */
import { computed } from 'vue'

const props = defineProps({
  rounds: { type: Array, required: true },
  loaded: { type: Array, default: () => [] },
  modelValue: { type: Number, default: null },
  roundHours: { type: Number, default: 4 },
  label: { type: String, default: 'Committed round' }
})
const emit = defineEmits(['update:modelValue'])

const first = computed(() => props.rounds[0] ?? 0)
const last = computed(() => props.rounds[props.rounds.length - 1] ?? 0)
const valueText = computed(() => props.modelValue == null
  ? 'No round committed yet'
  : `Round ${props.modelValue} of ${last.value} · simulated t=${props.modelValue * props.roundHours} h`)

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
.lw-scrubber__track {
  display: flex;
  gap: 2px;
  padding: var(--lw-space-1);
  border: 1px solid var(--live-rule);
  border-radius: var(--lw-radius);
  overflow-x: auto;
}

.lw-scrubber__tick {
  flex: 1 0 var(--lw-target);
  min-height: var(--lw-target);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: 0;
  border-radius: var(--lw-radius);
  background: transparent;
  color: var(--live-muted);
  font: inherit;
  cursor: pointer;
}

.lw-scrubber__mark {
  width: 3px;
  height: 14px;
  background: var(--live-muted);
  transition: height 160ms ease, background-color 160ms ease;
}

.lw-scrubber__tick.is-unloaded .lw-scrubber__mark {
  background: transparent;
  border: 1px dashed var(--live-muted);
}

.lw-scrubber__tick.is-current {
  color: var(--live-ink);
  background: var(--live-raised);
}

.lw-scrubber__tick.is-current .lw-scrubber__mark {
  height: 22px;
  background: var(--live-brand);
}

.lw-scrubber__num {
  font-family: var(--lw-font-figure);
  font-size: 12px;
}

.lw-scrubber__track:focus-visible {
  outline: 3px solid var(--live-brand);
  outline-offset: 2px;
}

.lw-scrubber__value {
  margin: var(--lw-space-2) 0 0;
  font-family: var(--lw-font-figure);
  color: var(--live-ink);
}

@media (prefers-reduced-motion: reduce) {
  .lw-scrubber__mark { transition: none; }
}
</style>

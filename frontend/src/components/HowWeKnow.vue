<template>
  <Tip class="lw-how" :test="test" toggle>
    <button type="button" class="lw-how__icon" aria-label="How we know">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
           aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg>
    </button>
    <template #tip><slot /></template>
  </Tip>
</template>

<script setup>
/**
 * The panel's mechanics, on demand (prp/2026-10-29-ux-pass/COPY.md rule 3, MATCH.md item 2): ids,
 * formulas, sources and raw statuses behind a small (i) control, in a tooltip that opens on hover,
 * focus or tap. Nothing in it is only here: it is where the technical names of the plain words
 * beside it live, and none of it is on the page until asked for.
 */
import Tip from './Tip.vue'

defineProps({ test: { type: String, default: 'how-we-know' } })
</script>

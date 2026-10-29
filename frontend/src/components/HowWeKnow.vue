<template>
  <details class="lw-calc lw-how" :data-test="test">
    <summary>How we know</summary>
    <div class="lw-calc__body">
      <slot />
    </div>
  </details>
</template>

<script setup>
/**
 * The panel's mechanics, one click down (prp/2026-10-29-ux-pass/COPY.md, rule 3): ids, formulas,
 * sources and raw statuses, closed by default and reached by keyboard. Nothing in it is only
 * here: it is where the technical names of the plain words above it live.
 */
defineProps({ test: { type: String, default: 'how-we-know' } })
</script>

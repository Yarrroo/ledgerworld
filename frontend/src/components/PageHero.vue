<template>
  <header class="lw-hero" data-test="hero">
    <div class="lw-hero__text">
      <h1 data-test="hero-headline">{{ headline }}</h1>
      <p v-if="subtitle" class="lw-hero__sub" data-test="hero-subtitle">
        <Tip v-if="lead" :text="lead" test="hero-lead">{{ subtitle }}</Tip>
        <template v-else>{{ subtitle }}</template>
      </p>
    </div>
    <div v-if="$slots.default" class="lw-hero__action" data-test="hero-action"><slot /></div>
  </header>
</template>

<script setup>
/**
 * The page hero every mockup opens with (prp/2026-10-29-ux-pass/MATCH.md, item 1): a one-line serif
 * headline, a one-line grey subtitle, and the one primary button that is the next step of the
 * journey. The screen's data-built lead sentence (COPY.md) is the subtitle's tooltip.
 */
import Tip from './Tip.vue'

defineProps({
  headline: { type: String, required: true },
  subtitle: { type: String, default: '' },
  lead: { type: String, default: '' }
})
</script>

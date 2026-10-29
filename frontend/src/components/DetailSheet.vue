<template>
  <dialog ref="dialog" class="lw-sheet" :aria-labelledby="titleId" :data-test="test"
          @cancel.prevent="close" @click="onBackdrop">
    <div class="lw-sheet__inner">
      <header class="lw-sheet__head">
        <h2 :id="titleId">{{ title }}</h2>
        <button type="button" class="lw-button lw-button--quiet" data-test="sheet-close" @click="close">
          Close
        </button>
      </header>
      <div class="lw-sheet__body">
        <slot />
      </div>
    </div>
  </dialog>
</template>

<script setup>
/**
 * A read-only details surface (the handoff's evidence drawer): a modal dialog drawn as a side
 * drawer from 768 px and as a full-height sheet on a phone. Shown while `open` is true; Escape,
 * Close or the backdrop emit `close`, and focus goes back to the control that opened it. It holds
 * no action, so closing it cancels nothing on the server.
 */
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  test: { type: String, default: 'sheet' }
})
const emit = defineEmits(['close'])

const titleId = `lw-sheet-${useId()}`
const dialog = ref(null)
let opener = null

const close = () => emit('close')

/** A click on the dialog element itself, not on its content, is a click on the backdrop. */
function onBackdrop (event) {
  if (event.target === dialog.value) close()
}

watch(() => props.open, async (open) => {
  await nextTick()
  const el = dialog.value
  if (!el) return
  if (open && !el.open) {
    opener = document.activeElement
    if (el.showModal) el.showModal()
    else el.setAttribute('open', '')
  } else if (!open && el.open) {
    if (el.close) el.close()
    else el.removeAttribute('open')
    opener?.focus?.()
    opener = null
  }
}, { immediate: true })

onBeforeUnmount(() => {
  if (dialog.value?.open) dialog.value.close?.()
})
</script>

<style scoped>
.lw-sheet {
  box-sizing: border-box;
  margin: 0 0 0 auto;
  width: min(480px, 100vw);
  max-width: 100vw;
  height: 100dvh;
  max-height: 100dvh;
  padding: 0;
  border: 0;
  border-left: 1px solid var(--lw-rule);
  background: var(--lw-surface-raised);
  color: var(--lw-ink);
  font-family: var(--lw-font-text);
}

.lw-sheet::backdrop {
  background: rgb(23 37 30 / 40%);
}

.lw-sheet__inner {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.lw-sheet__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--lw-space-3);
  padding: var(--lw-space-4) var(--lw-space-6);
  border-bottom: 1px solid var(--lw-rule);
}

.lw-sheet__head h2 {
  margin: 0;
  font-family: var(--lw-font-heading);
  font-size: 22px;
  line-height: 28px;
  overflow-wrap: anywhere;
}

.lw-sheet__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--lw-space-4) var(--lw-space-6) var(--lw-space-8);
  overflow-wrap: anywhere;
}

.lw-sheet__body :deep(dl) {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  gap: var(--lw-space-2) var(--lw-space-4);
  margin: 0 0 var(--lw-space-4);
}

.lw-sheet__body :deep(dt) { color: var(--lw-ink-muted); }
.lw-sheet__body :deep(dd) { margin: 0; font-variant-numeric: tabular-nums; }

@media (max-width: 767px) {
  .lw-sheet {
    width: 100vw;
    border-left: 0;
  }

  .lw-sheet__head,
  .lw-sheet__body {
    padding-left: var(--lw-space-4);
    padding-right: var(--lw-space-4);
  }

  .lw-sheet__body :deep(dl) { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .lw-sheet__body :deep(dd) { margin-bottom: var(--lw-space-2); }
}

@media (prefers-reduced-motion: no-preference) {
  .lw-sheet[open] { animation: lw-sheet-in 160ms ease-out; }
}

@keyframes lw-sheet-in {
  from { transform: translateX(24px); opacity: 0; }
  to { transform: none; opacity: 1; }
}
</style>

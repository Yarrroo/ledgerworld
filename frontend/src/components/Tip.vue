<template>
  <span ref="root" :class="['lw-tip', { 'is-open': open }]" :data-test="test" @mouseenter="show('hover')"
        @mouseleave="hide('hover')" @focusin="show('focus')" @focusout="onBlur" @keydown.esc.stop="close"
        @click="onTap">
    <slot />
    <span :id="id" ref="bubble" class="lw-tip__bubble" role="tooltip" :hidden="!open" :style="place"
          data-test="tip"><slot name="tip">{{ text }}</slot></span>
  </span>
</template>

<script setup>
/**
 * The one tooltip (prp/2026-10-29-ux-pass/MATCH.md, item 4): the detail that used to be subtext —
 * source, as-of time, formula, ids — on demand. It opens on hover, on keyboard focus and on a tap
 * (a phone has no hover), and closes on Escape, blur, a second tap or a tap elsewhere. The bubble
 * is fixed to the viewport, below the value it explains (above it near the bottom edge), so it
 * never covers that value and never widens the page.
 *
 * The trigger is the default slot. When it holds a link, button or field, that control is named
 * by the bubble (aria-describedby) and a tap still acts; otherwise the wrapper itself takes focus.
 * The bubble stays in the DOM, hidden, so its words are not on the page until asked for.
 */
import { onBeforeUnmount, onMounted, onUpdated, ref, useId } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  /** The trigger is a control that only shows this bubble (an info button): a tap toggles it. */
  toggle: { type: Boolean, default: false },
  test: { type: String, default: undefined }
})

const id = `lw-tip-${useId()}`
const root = ref(null)
const bubble = ref(null)
const open = ref(false)
const place = ref({})
const why = new Set() // what holds it open: hover, focus, tap
let control = null // a link, button or field in the trigger, when there is one
const GAP = 6
const EDGE = 8

function position () {
  const el = root.value
  const tip = bubble.value
  if (!el || !tip) return
  const anchor = (control ?? el).getBoundingClientRect()
  const w = Math.min(tip.offsetWidth || 280, window.innerWidth - 2 * EDGE)
  const left = Math.max(EDGE, Math.min(anchor.left, window.innerWidth - w - EDGE))
  const below = anchor.bottom + GAP
  const h = tip.offsetHeight
  const top = below + h > window.innerHeight - EDGE && anchor.top - GAP - h > EDGE ? anchor.top - GAP - h : below
  place.value = { left: `${left}px`, top: `${top}px`, maxWidth: `${window.innerWidth - 2 * EDGE}px` }
}

function sync () {
  const now = why.size > 0
  if (now === open.value) return
  open.value = now
  if (now) {
    // measured once it is drawn, then kept beside its value while the page moves
    requestAnimationFrame(position)
    window.addEventListener('scroll', position, { passive: true, capture: true })
    window.addEventListener('resize', position)
    document.addEventListener('pointerdown', outside, true)
  } else {
    window.removeEventListener('scroll', position, { capture: true })
    window.removeEventListener('resize', position)
    document.removeEventListener('pointerdown', outside, true)
  }
}

function show (reason) {
  why.add(reason)
  sync()
}
function hide (reason) {
  why.delete(reason)
  sync()
}
function close () {
  why.clear()
  sync()
}
function onBlur (event) {
  if (!root.value?.contains(event.relatedTarget)) {
    why.delete('focus')
    why.delete('tap')
    sync()
  }
}
/** A tap on a plain value toggles it; a tap on a control acts, and the bubble follows focus. */
function onTap (event) {
  if (event.target.closest?.('.lw-tip__bubble')) return
  if (control && control.contains(event.target) && !props.toggle) return
  if (why.has('tap')) close()
  else show('tap')
}
function outside (event) {
  if (!root.value?.contains(event.target)) close()
}

/**
 * Name the trigger by the bubble. A disabled control cannot take focus or a tap, so while it is
 * disabled the wrapper stands in for it (focusable, named by the bubble, and the target of a tap,
 * the control letting pointer events through): the reason it is disabled stays reachable by
 * keyboard and by touch. Re-run on every render, as the control's disabled state can change.
 */
function wire () {
  const el = root.value
  if (!el) return
  control = [...el.children].find((c) => c !== bubble.value && c.matches('a, button, input, select, textarea, summary')) ??
    el.querySelector(':scope > :not(.lw-tip__bubble) :is(a, button, input, select, textarea, summary)')
  const stand = !control || control.disabled === true
  const target = stand ? el : control
  const other = stand ? control : el
  if (stand) el.setAttribute('tabindex', '0')
  else el.removeAttribute('tabindex')
  el.classList.toggle('lw-tip--stands-in', Boolean(control && stand))
  const named = (target.getAttribute('aria-describedby') ?? '').split(' ').filter(Boolean)
  if (!named.includes(id)) target.setAttribute('aria-describedby', [...named, id].join(' '))
  const left = (other?.getAttribute('aria-describedby') ?? '').split(' ').filter((x) => x && x !== id)
  if (other && other !== el && left.length) other.setAttribute('aria-describedby', left.join(' '))
  else if (other && other !== el) other.removeAttribute('aria-describedby')
  else if (other === el) {
    if (left.length) el.setAttribute('aria-describedby', left.join(' '))
    else el.removeAttribute('aria-describedby')
  }
  if (stand && control) control = null // a tap on it is a tap on the wrapper
}
onMounted(wire)
onUpdated(wire)
onBeforeUnmount(close)
</script>

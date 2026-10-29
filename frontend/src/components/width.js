/**
 * The rendered width of an element, followed while it changes: a drawing (WorldMap)
 * lays itself out in real pixels, so its labels stay readable at every width. `min` and
 * `fallback` bound it before the first measurement and where ResizeObserver is absent.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

export function useWidth (box, { min = 280, fallback = 640 } = {}) {
  const width = ref(fallback)
  let observer = null
  onMounted(() => {
    const measure = () => { width.value = Math.max(min, Math.round(box.value?.clientWidth || fallback)) }
    measure()
    if (window.ResizeObserver) {
      observer = new ResizeObserver(measure)
      observer.observe(box.value)
    }
  })
  onBeforeUnmount(() => observer?.disconnect())
  return width
}

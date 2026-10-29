// The one tooltip (MATCH.md item 4): a disabled control's reason stays reachable by keyboard and tap.
import { afterEach, describe, expect, it } from 'vitest'
import { h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'

import Tip from '../../src/components/Tip.vue'

afterEach(() => { document.body.innerHTML = '' })

const bubble = (w) => w.get('[role="tooltip"]')

describe('Tip', () => {
  it('stands in for a disabled control: focusable, named by the bubble, opened by focus and by a tap', async () => {
    const w = mount(Tip, {
      props: { text: 'No prepared run yet' },
      slots: { default: () => h('button', { type: 'button', disabled: true }, 'Open simulation') },
      attachTo: document.body
    })
    await nextTick()
    const wrapper = w.get('.lw-tip')
    const id = bubble(w).attributes('id')
    expect(wrapper.attributes('tabindex')).toBe('0')
    expect(wrapper.attributes('aria-describedby')).toBe(id)
    expect(w.get('button').attributes('aria-describedby')).toBeUndefined()

    await wrapper.trigger('focusin')
    expect(bubble(w).attributes('hidden')).toBeUndefined()
    await wrapper.trigger('keydown', { key: 'Escape' })
    expect(bubble(w).attributes('hidden')).toBe('')

    await wrapper.trigger('click') // a tap passes through the disabled control to the wrapper
    expect(bubble(w).attributes('hidden')).toBeUndefined()
    await wrapper.trigger('click')
    expect(bubble(w).attributes('hidden')).toBe('')
  })

  it('hands the name back to the control once it is enabled', async () => {
    const off = ref(true)
    const w = mount({
      render: () => h(Tip, { text: 'Why' }, () => h('button', { type: 'button', disabled: off.value }, 'Go'))
    }, { attachTo: document.body })
    await nextTick()
    off.value = false
    await nextTick()
    const id = w.get('[role="tooltip"]').attributes('id')
    expect(w.get('.lw-tip').attributes('tabindex')).toBeUndefined()
    expect(w.get('.lw-tip').attributes('aria-describedby')).toBeUndefined()
    expect(w.get('button').attributes('aria-describedby')).toBe(id)
  })
})

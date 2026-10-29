// The panel index on Live simulation marks the panel the reader is on, by where the panels are
// drawn rather than where they sit in the markup. The screen's grid places its four panels out of
// DOM order at two columns (controls; graph beside feed; cash below — feed and cash under the
// graph once it is expanded) and keeps DOM order on a phone. happy-dom lays nothing out, so each
// width's rendered geometry is given here: page offsets (y, x) per panel, as measured on the
// screen at 1440, 834 and 390 px with the demonstration run.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ScreenShell } from '../../src/api/v1.js'

// Simulation.vue's panels, in its DOM order (the phone reading order)
const PANELS = ['Round and controls', 'Cash paths', 'Event feed', 'World map and actors']

const LAYOUTS = {
  'desktop-1440': {
    view: 900, page: 2600,
    at: { 'Round and controls': [200, 280], 'World map and actors': [620, 280], 'Event feed': [620, 900], 'Cash paths': [1320, 280] }
  },
  'tablet-834': {
    view: 1112, page: 2900,
    at: { 'Round and controls': [180, 104], 'World map and actors': [640, 104], 'Event feed': [640, 520], 'Cash paths': [1360, 104] }
  },
  'desktop-1440 graph expanded': {
    view: 900, page: 3400,
    at: { 'Round and controls': [200, 280], 'World map and actors': [620, 280], 'Event feed': [1300, 280], 'Cash paths': [1900, 280] }
  },
  'phone-390': {
    view: 844, page: 3400,
    at: { 'Round and controls': [150, 16], 'Cash paths': [700, 16], 'Event feed': [1250, 16], 'World map and actors': [1900, 16] }
  }
}

let geometry = null
let scrollY = 0

function lay (layout) {
  geometry = layout
  scrollY = 0
  vi.spyOn(window, 'scrollY', 'get').mockImplementation(() => scrollY)
  vi.spyOn(window, 'innerHeight', 'get').mockImplementation(() => geometry.view)
  vi.spyOn(document.documentElement, 'scrollHeight', 'get').mockImplementation(() => geometry.page)
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function () {
    const at = geometry.at[this.dataset?.panel]
    const [y, x] = at ?? [0, 0]
    const top = y - scrollY
    return { top, left: x, bottom: top + 400, right: x + 400, width: 400, height: 400, x, y: top }
  })
}

/** A frame for the shell's batched look at the page. */
const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()))

async function scrollTo (y) {
  scrollY = y
  window.dispatchEvent(new Event('scroll'))
  await frame()
  await nextTick()
}

const mounted = []
async function open () {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, model: 'scripted' }) })))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/simulation', component: { render: () => null } }] })
  await router.push('/simulation')
  await router.isReady()
  const w = mount(ScreenShell, {
    attachTo: document.body,
    props: { title: 'Live simulation', reading: { body: { mode: 'simulated' }, status: 'done' }, refresh: () => {} },
    slots: { default: () => PANELS.map((name) => h('section', { 'data-panel': name }, name)) },
    global: { plugins: [router] }
  })
  mounted.push(w)
  await flushPromises()
  await frame()
  await nextTick()
  return w
}

const marked = (w) => w.findAll('[data-test="panel-link"][aria-current="true"]').map((a) => a.text())
/** Scroll so the panel's top sits just under the top of the view, as when reading it. */
const reading = (name) => geometry.at[name][0] - 4

afterEach(() => {
  while (mounted.length) mounted.pop().unmount()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Simulation panel index follows rendered position', () => {
  for (const [width, layout] of Object.entries(LAYOUTS)) {
    it(`${width}: marks the panel being read, top to bottom, and the bottom-most at the end`, async () => {
      lay(layout)
      const w = await open()
      // the index keeps the screen's own (phone) order
      expect(w.findAll('[data-test="panel-link"]').map((a) => a.text())).toEqual(PANELS)
      expect(marked(w)).toEqual(['Round and controls'])

      const order = Object.entries(layout.at)
        .sort(([, a], [, b]) => a[0] - b[0] || a[1] - b[1]).map(([name]) => name)
      const rows = new Set()
      for (const name of order) {
        const y = layout.at[name][0]
        if (rows.has(y)) continue // a row's left panel is the one marked while that row is read
        rows.add(y)
        await scrollTo(reading(name))
        expect(marked(w), `reading ${name}`).toEqual([name])
      }

      await scrollTo(layout.page - layout.view)
      expect(marked(w), 'at the page end').toEqual([order[order.length - 1]])
    })
  }

  it('desktop-1440: Cash paths stays marked from its top to the page end, never World map and actors', async () => {
    lay(LAYOUTS['desktop-1440'])
    const w = await open()
    for (const y of [1316, 1500, 1700]) {
      await scrollTo(y)
      expect(marked(w), `at ${y}`).toEqual(['Cash paths'])
    }
  })
})

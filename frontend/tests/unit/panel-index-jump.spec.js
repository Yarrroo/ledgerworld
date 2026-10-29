// A panel chosen from the index stays marked through the scroll that brings it into view, and at
// the page end when the end stops the scroll short of it. happy-dom neither lays out nor scrolls,
// so the page here is drawn by hand (five stacked panels on a 2600 px page in a 900 px view) and
// the smooth scroll is played frame by frame: scrollIntoView records the target and the test moves
// the page, as the browser would, from the top to where it stops. Timers are the test's: a
// choice's scroll that the browser does not end is ended by one, and here time moves only when
// the test says so.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ScreenShell } from '../../src/api/v1.js'

const VIEW = 900
const PAGE = 2600
const END = PAGE - VIEW // 1700: as far as the page scrolls
// page offsets; Ledger's top (2000) is below END, so a jump to it stops at the page end
const AT = { Summary: 200, Accounts: 800, Postings: 1400, Ledger: 2000, Sources: 2300 }
const PANELS = Object.keys(AT)

let scrollY = 0
let reduced = false
let jumps = []

function lay () {
  scrollY = 0
  reduced = false
  jumps = []
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  vi.spyOn(window, 'scrollY', 'get').mockImplementation(() => scrollY)
  vi.spyOn(window, 'innerHeight', 'get').mockImplementation(() => VIEW)
  vi.spyOn(document.documentElement, 'scrollHeight', 'get').mockImplementation(() => PAGE)
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function () {
    const top = (AT[this.dataset?.panel] ?? 0) - scrollY
    return { top, left: 0, bottom: top + 300, right: 800, width: 800, height: 300, x: 0, y: top }
  })
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
    matches: query.includes('reduce') ? reduced : false,
    media: query,
    addEventListener () {},
    removeEventListener () {}
  }))
  Element.prototype.scrollIntoView = function (options) { jumps.push({ panel: this.dataset.panel, ...options }) }
}

const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()))

/** One frame of scrolling: the page moves, the browser says so, the shell looks. */
async function scrollTo (y) {
  scrollY = y
  window.dispatchEvent(new Event('scroll'))
  await frame()
  await nextTick()
}

/** The browser's word that the scroll has stopped. */
async function scrollEnd () {
  window.dispatchEvent(new Event('scrollend'))
  await frame()
  await nextTick()
}

/** The reader's hand on the page (wheel, touch, pointer, a key), then the frame after it. */
async function reach (event) {
  (event.target ?? window).dispatchEvent(event.event)
  await frame()
  await nextTick()
}

/** Time passing with no scroll event: a stall mid-scroll, or the page at rest. */
async function idle (ms) {
  vi.advanceTimersByTime(ms)
  await frame()
  await nextTick()
}

const mounted = []
let router = null
async function open () {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, model: 'scripted' }) })))
  router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/treasury', component: { render: () => null } }] })
  await router.push('/treasury')
  await router.isReady()
  const w = mount(ScreenShell, {
    attachTo: document.body,
    props: { title: 'Treasury', reading: { body: { mode: 'simulated' }, status: 'done' }, refresh: () => {} },
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
const choose = (w, name) => w.findAll('[data-test="panel-link"]').find((a) => a.text() === name).trigger('click')

afterEach(() => {
  while (mounted.length) mounted.pop().unmount()
  delete Element.prototype.scrollIntoView
  delete window.onscrollend
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('a panel chosen from the index stays marked', () => {
  it('through every frame of a smooth scroll that the page end stops short of it', async () => {
    lay()
    const w = await open()
    expect(marked(w)).toEqual(['Summary'])
    await choose(w, 'Ledger')
    expect(jumps).toEqual([{ panel: 'Ledger', behavior: 'smooth', block: 'start' }])
    expect(marked(w)).toEqual(['Ledger'])
    // Ledger stays below the view until the last frames; the page passes Accounts and Postings
    for (const y of [150, 500, 900, 1300, 1600, END]) {
      await scrollTo(y)
      expect(marked(w), `at ${y}`).toEqual(['Ledger'])
    }
    await scrollEnd()
    expect(marked(w), 'once the scroll has stopped').toEqual(['Ledger'])
  })

  it('when the browser never says the scroll stopped (no scrollend)', async () => {
    lay()
    const w = await open()
    await choose(w, 'Ledger')
    for (const y of [400, 1000, END]) await scrollTo(y)
    await idle(400)
    expect(marked(w)).toEqual(['Ledger'])
    await scrollTo(END) // a late scroll event at the end changes nothing
    expect(marked(w)).toEqual(['Ledger'])
  })

  it('through a stall mid-scroll where the browser says when the scroll stops', async () => {
    lay()
    window.onscrollend = null // the browser sends scrollend
    const w = await open()
    await choose(w, 'Ledger')
    await scrollTo(500)
    await idle(400) // a long task: no scroll event for 400 ms, Ledger still below the view
    expect(marked(w)).toEqual(['Ledger'])
    for (const y of [1300, END]) {
      await scrollTo(y)
      expect(marked(w), `at ${y}`).toEqual(['Ledger'])
    }
    await scrollEnd()
    expect(marked(w)).toEqual(['Ledger'])
  })

  it('when the reader touches the page without moving it', async () => {
    lay()
    const w = await open()
    await choose(w, 'Ledger')
    await scrollTo(END)
    await scrollEnd()
    const refresh = w.find('[data-test="refresh"]').element
    for (const hand of [
      { event: new Event('wheel') }, // at the end already, or a nested scroller
      { event: new Event('touchmove') }, // a sideways swipe of the index strip
      { event: new Event('pointerdown') },
      { event: new KeyboardEvent('keydown', { key: ' ', bubbles: true }), target: refresh }, // Space on a button
      { event: new KeyboardEvent('keydown', { key: 'End' }) }
    ]) {
      await reach(hand)
      await idle(400)
      window.dispatchEvent(new Event('resize'))
      await frame()
      await nextTick()
      expect(marked(w), hand.event.type).toEqual(['Ledger'])
    }
  })

  it('until the reader drags the scrollbar mid-way', async () => {
    lay()
    const w = await open()
    await choose(w, 'Ledger')
    await scrollTo(500)
    await reach({ event: new Event('pointerdown') })
    await scrollTo(300)
    expect(marked(w)).toEqual(['Summary'])
  })

  it('until the route changes mid-way', async () => {
    lay()
    const w = await open()
    await choose(w, 'Ledger')
    await scrollTo(500)
    await router.push('/treasury?run_id=r2')
    await flushPromises()
    await scrollTo(0)
    expect(marked(w)).toEqual(['Summary'])
  })

  it('with reduced motion: one instant jump to the page end', async () => {
    lay()
    reduced = true
    const w = await open()
    await choose(w, 'Ledger')
    expect(jumps).toEqual([{ panel: 'Ledger', behavior: 'auto', block: 'start' }])
    await scrollTo(END)
    await scrollEnd()
    expect(marked(w)).toEqual(['Ledger'])
  })

  it('until the reader takes over the scroll mid-way: the index follows the page again', async () => {
    lay()
    const w = await open()
    await choose(w, 'Ledger')
    await scrollTo(500)
    window.dispatchEvent(new Event('wheel'))
    await scrollTo(820) // the reader's own scroll: Accounts' top is under the header
    expect(marked(w)).toEqual(['Accounts'])
    await scrollTo(END)
    expect(marked(w), 'at the page end, the bottom panel').toEqual(['Sources'])
  })

  it('until the reader scrolls on their own after the jump', async () => {
    lay()
    const w = await open()
    await choose(w, 'Ledger')
    await scrollTo(END)
    await scrollEnd()
    expect(marked(w)).toEqual(['Ledger'])
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageUp' }))
    await scrollTo(1390)
    expect(marked(w)).toEqual(['Postings'])
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'End' }))
    await scrollTo(END)
    expect(marked(w), 'back at the end, the bottom panel').toEqual(['Sources'])
  })

  it('a jump to a panel the page can reach marks it on arrival, and the page from there', async () => {
    lay()
    const w = await open()
    await choose(w, 'Postings')
    for (const y of [300, 900, 1390]) {
      await scrollTo(y)
      expect(marked(w), `at ${y}`).toEqual(['Postings'])
    }
    await scrollEnd()
    expect(marked(w)).toEqual(['Postings'])
    window.dispatchEvent(new Event('wheel'))
    await scrollTo(790)
    expect(marked(w)).toEqual(['Accounts'])
  })
})

// The cash outlook keeps its tip only while the point it belongs to is still drawn.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import CashOutlook from '../../src/components/CashOutlook.vue'
import baseline from '../../../contracts/examples/c6_api/valid-overview-demo-baseline.json'

const body = baseline.instance
const props = (points) => ({ points, floor: body.coverage.floor, lowAt: body.coverage.at, asOf: body.as_of, currency: 'USD' })

afterEach(() => vi.unstubAllGlobals())

describe('CashOutlook', () => {
  it('drops the tip of a point a refresh no longer serves', async () => {
    const w = mount(CashOutlook, {
      props: props(body.outlook)
    })
    await w.findAll('[data-test="outlook-point"]')[4].trigger('pointerenter', { pointerType: 'mouse' })
    expect(w.find('[data-test="outlook-tip"]').text()).toContain('t=72 h')
    await w.setProps({ points: body.outlook.slice(0, 2) })
    expect(w.findAll('[data-test="outlook-point"]')).toHaveLength(2)
    expect(w.find('[data-test="outlook-tip"]').exists()).toBe(false)
  })
  it('keeps a negative P inside the plot, above the hour labels', async () => {
    const points = body.outlook.map((p, n) => n === 2 ? { ...p, value: { ...p.value, minor: -500000 } } : p)
    const w = mount(CashOutlook, { props: props(points) })
    const bottom = Number(w.get('svg').attributes('height')) - 44
    for (const dot of w.findAll('.lw-outlook__dot')) expect(Number(dot.attributes('cy'))).toBeLessThanOrEqual(bottom)
    expect(w.findAll('.lw-outlook__axis text').map((t) => t.text()).some((t) => t.startsWith('-'))).toBe(true)
  })

  it('follows its width once points arrive after an empty first answer', async () => {
    const watched = []
    vi.stubGlobal('ResizeObserver', class { observe (el) { watched.push(el) } disconnect () {} })
    const w = mount(CashOutlook, { props: props([]) })
    await w.setProps({ points: body.outlook })
    expect(watched).toContain(w.get('.lw-outlook__frame').element)
  })
  it('keeps the tip of a tapped point when the finger lifts', async () => {
    const w = mount(CashOutlook, { props: props(body.outlook) })
    const point = w.findAll('[data-test="outlook-point"]')[1]
    await point.trigger('click')
    await point.trigger('pointerleave', { pointerType: 'touch' })
    expect(w.find('[data-test="outlook-tip"]').text()).toContain('t=12 h')
  })
  it('shows the tip to a hovering pen as to a mouse', async () => {
    const w = mount(CashOutlook, { props: props(body.outlook) })
    await w.findAll('[data-test="outlook-point"]')[2].trigger('pointerenter', { pointerType: 'pen' })
    expect(w.find('[data-test="outlook-tip"]').text()).toContain('t=40 h')
  })

  it('stops watching a frame that is gone', async () => {
    const watched = new Set()
    vi.stubGlobal('ResizeObserver', class {
      observe (el) { watched.add(el) }
      unobserve (el) { watched.delete(el) }
      disconnect () {}
    })
    const w = mount(CashOutlook, { props: props(body.outlook) })
    await w.setProps({ points: [] })
    await w.setProps({ points: body.outlook })
    expect(watched.size).toBe(1)
    expect(watched.has(w.get('.lw-outlook__frame').element)).toBe(true)
  })

  it('puts the baseline\'s low-point label just above its point, not out past the floor line', async () => {
    // below the point crosses the floor; above and right meets the h48 point; above and left is clear
    const w = mount(CashOutlook, { props: props(body.outlook) })
    const dot = w.get('.is-low .lw-outlook__dot')
    const label = w.get('[data-test="outlook-low-label"]')
    expect(Number(label.attributes('y'))).toBe(Number(dot.attributes('cy')) - 14)
    expect(label.attributes('text-anchor')).toBe('end')
  })

  it('labels the y axis with representable amounts when every P is zero', async () => {
    const zero = body.outlook.map((p) => ({ ...p, value: { ...p.value, minor: 0 } }))
    const w = mount(CashOutlook, { props: { ...props(zero), floor: null } })
    const ticks = w.findAll('.lw-outlook__axis g text').map((t) => t.text())
    expect(ticks.length).toBeGreaterThan(1)
    for (const t of ticks) expect(t).toMatch(/^-?[\d,]+(\.\d+)?$/) // never 'Unrepresentable amount'
  })
})

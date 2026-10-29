/**
 * A panel chosen from the index, in motion, at every width of e2e/ux.config.ts: it is marked on
 * every frame of the smooth scroll that brings it into view, and once that scroll has stopped,
 * even where the page's end stops it short of the panel; the reader's own scroll then hands the
 * index back to the page. The chosen panel starts below the view and is not the one the page-end
 * rule would mark, so a lost choice shows; where no screen has one at the width's own height, a
 * 640 px tall window (a short laptop) is used. Same with reduced motion. Read-only. With UX_SHOTS
 * set, it keeps a picture of the page once the smooth jump has stopped, per width, there.
 */
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, ROUTES, settled, urlOf } from './routes'

type Target = { id: string, name: string, end: number }

/**
 * A panel below the view that the page end stops the scroll short of and that is not the first
 * of the bottom drawn row; null when this screen at this width has none.
 */
const clampedTarget = (page: Page): Promise<Target | null> => page.evaluate(() => {
  const ix = document.querySelector<HTMLElement>('.lw-panels')!
  const under = (parseFloat(getComputedStyle(ix).top) || 0) + ix.offsetHeight
  const end = document.documentElement.scrollHeight - innerHeight
  const order = [...document.querySelectorAll<HTMLElement>('main [data-panel]')].map((el) => {
    const box = el.getBoundingClientRect()
    return { id: el.id, name: el.dataset.panel!, top: Math.round(box.top + scrollY), left: box.left }
  }).sort((a, b) => a.top - b.top || a.left - b.left)
  const bottom = order.find((p) => p.top === order[order.length - 1].top)!
  const p = order.find((p) => p !== bottom && p.top >= innerHeight && p.top - under - 4 > end + 2)
  return p ? { id: p.id, name: p.name, end } : null
})

/** The marked link's text on every frame from the act (a click or a key) until the page has not moved for 300 ms. */
async function framesUntilStill (page: Page, act: () => Promise<void>): Promise<string[]> {
  await page.evaluate(() => {
    const w = window as unknown as { __marks: string[], __still: Promise<void> }
    w.__marks = []
    w.__still = new Promise((resolve) => {
      let y = 0
      let since = 0
      const look = (now: number) => {
        w.__marks.push(document.querySelector('[data-test="panel-index"] [aria-current="true"]')?.textContent ?? '')
        if (scrollY !== y) { y = scrollY; since = now }
        if (now - since > 300) resolve()
        else requestAnimationFrame(look)
      }
      const start = () => {
        removeEventListener('click', start, true)
        removeEventListener('keydown', start, true)
        y = scrollY
        since = performance.now()
        requestAnimationFrame(look)
      }
      addEventListener('click', start, true)
      addEventListener('keydown', start, true)
    })
  })
  await act()
  return page.evaluate(async () => {
    const w = window as unknown as { __marks: string[], __still: Promise<void> }
    await w.__still
    return w.__marks
  })
}

const current = (page: Page) => page.locator('[data-test="panel-index"] [aria-current="true"]')
const top = (page: Page) => page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))

test('a chosen panel stays marked through a smooth scroll the page end stops short of it', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const { width, height } = info.project.use.viewport!
  let target: Target | null = null
  search: for (const tall of [height, 640]) {
    await page.setViewportSize({ width, height: tall })
    for (const route of ROUTES) {
      await page.goto(urlOf(route, runId))
      await settled(page)
      await expect(page.locator('[data-test="panel-index"]')).toBeVisible()
      target = await clampedTarget(page)
      if (target) break search
    }
  }
  expect(target, 'no screen has a panel the page end stops a jump short of').not.toBeNull()
  const { id, name, end } = target!
  const link = page.locator(`[data-test="panel-link"][href="#${id}"]`)

  for (const motion of ['no-preference', 'reduce'] as const) {
    await page.emulateMedia({ reducedMotion: motion })
    await top(page)
    await expect(current(page)).not.toHaveText(name)
    const marks = await framesUntilStill(page, () => link.click())
    expect(await page.evaluate(() => scrollY), `${motion}: the scroll reached the page end`).toBeGreaterThanOrEqual(end - 2)
    expect(new Set(marks), `${motion}: every frame after the click`).toEqual(new Set([name]))
    await expect(current(page)).toHaveText(name)
    if (process.env.UX_SHOTS && motion === 'no-preference') {
      await page.screenshot({ path: join(process.env.UX_SHOTS, `${info.project.name}-panel-jump.png`) })
    }
  }

  // the reader's own scroll hands the index back to the page: back at the end, the bottom row
  await framesUntilStill(page, () => page.keyboard.press('PageUp'))
  await expect(current(page)).not.toHaveText(name)
  await framesUntilStill(page, () => page.keyboard.press('End'))
  await expect(current(page)).not.toHaveText(name)
  expect(writes).toEqual([])
})

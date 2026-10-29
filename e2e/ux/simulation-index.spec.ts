/**
 * Live simulation's panel index in motion, at every width of e2e/ux.config.ts: the panel being
 * read is the one marked, by where the grid draws it (controls; graph beside feed; cash below at
 * two columns, feed and cash under the graph once it is expanded; the markup's order on a phone),
 * never by its place in the markup. Read-only. With UX_SHOTS set, it keeps a picture of the page
 * end per width, graph expanded and not, there.
 */
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, settled } from './routes'

type Drawn = { name: string, top: number, reach: number }

/** The marked panels as drawn, top to bottom then left to right, with the scroll that reads each. */
const drawn = (page: Page): Promise<{ order: Drawn[], end: number }> => page.evaluate(() => {
  const ix = document.querySelector<HTMLElement>('.lw-panels')!
  const under = (parseFloat(getComputedStyle(ix).top) || 0) + ix.offsetHeight
  const order = [...document.querySelectorAll<HTMLElement>('main [data-panel]')].map((el) => {
    const box = el.getBoundingClientRect()
    return { name: el.dataset.panel!, top: Math.round(box.top + scrollY), left: box.left, reach: Math.round(box.top + scrollY - under - 4) }
  }).sort((a, b) => a.top - b.top || a.left - b.left)
  return { order, end: document.documentElement.scrollHeight - innerHeight }
})

const scrollTo = (page: Page, y: number) => page.evaluate((y) => window.scrollTo({ top: y, behavior: 'instant' }), y)

async function sweep (page: Page, shot: string): Promise<string[]> {
  const current = page.locator('[data-test="panel-index"] [aria-current="true"]')
  const { order, end } = await drawn(page)
  const rows = order.filter((p, n) => n === 0 || p.top !== order[n - 1].top) // a row reads as its left panel
  for (const p of rows.slice(1)) {
    if (p.reach > end - 2) continue // the page ends first: the end rule below marks it
    await scrollTo(page, p.reach)
    await expect(current, `reading ${p.name}`).toHaveText(p.name)
  }
  await scrollTo(page, end)
  await expect(current, 'at the page end').toHaveText(rows[rows.length - 1].name)
  if (process.env.UX_SHOTS) await page.screenshot({ path: join(process.env.UX_SHOTS, `${shot}.png`) })
  await scrollTo(page, 0)
  await expect(current).toHaveText(order[0].name)
  return order.map((p) => p.name)
}

test('panel index marks the panel in view by its drawn position, graph expanded or not', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const phone = info.project.use.viewport!.width <= 720
  await page.goto(`/simulation?run_id=${await demoRunId(request)}`)
  await settled(page)
  const links = page.locator('[data-test="panel-index"] [data-test="panel-link"]')
  // the index keeps the screen's own order, the phone reading order
  const listed = ['Round and controls', 'Cash paths', 'Event feed', 'World map and actors']
  await expect(links).toHaveText(listed)

  const order = await sweep(page, `${info.project.name}-simulation-end`)
  expect(order, 'drawn order').toEqual(phone ? listed : ['Round and controls', 'World map and actors', 'Event feed', 'Cash paths'])

  // the graph expanded spans the width: feed and cash each take a row under it
  await page.locator('[data-test="graph"] .tool-btn', { has: page.locator('.icon-maximize') }).click()
  await expect(page.locator('.lw-live')).toHaveClass(/is-graph-expanded/)
  const expanded = await sweep(page, `${info.project.name}-simulation-end-expanded`)
  expect(expanded, 'drawn order, graph expanded').toEqual(phone ? listed : ['Round and controls', 'World map and actors', 'Event feed', 'Cash paths'])
  expect(writes).toEqual([])
})

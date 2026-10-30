/**
 * Live simulation's evidence graph sits in a disclosure that starts closed, at every width of
 * e2e/ux.config.ts, on the prepared demonstration run. The graph is drawn while closed, at 0×0;
 * opening the disclosure the first time — after the cursor moved or not, with no resize — draws
 * the selected round at the size the open box has. Read-only. With UX_SHOTS set, it keeps a
 * picture of the opened graph per width there.
 */
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, settled, sideways } from './routes'

/** The drawing's viewBox size and the nodes it drew, as the browser laid them out. */
const drawing = (page: Page) => page.evaluate(() => {
  const svg = document.querySelector<SVGSVGElement>('[data-test="graph"] .graph-svg')!
  const [, , w, h] = (svg.getAttribute('viewBox') ?? '0 0 0 0').split(' ').map(Number)
  const box = svg.getBoundingClientRect()
  const nodes = [...svg.querySelectorAll('circle')].filter((c) => c.getBoundingClientRect().width > 0)
  return { w, h, boxW: Math.round(box.width), boxH: Math.round(box.height), nodes: nodes.length }
})

test('the evidence graph draws at its open size on first opening', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  await page.goto(`/simulation?run_id=${await demoRunId(request)}`)
  await settled(page)
  const slider = page.locator('[data-test="scrubber-slider"]')
  await expect(slider).toHaveAttribute('aria-valuenow', /^\d+$/)
  const last = Number(await slider.getAttribute('aria-valuenow'))

  // the cursor moves while the graph is closed; the opened graph is that round's
  await slider.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(slider).toHaveAttribute('aria-valuenow', String(last - 1))

  await page.locator('.lw-sim__source').click()
  const disclosure = page.locator('details.lw-sim__evidence')
  await expect(disclosure).not.toHaveAttribute('open', '')
  await disclosure.locator('summary').click()
  await expect(disclosure).toHaveAttribute('open', '')
  await expect.poll(async () => (await drawing(page)).w, 'viewBox width after opening').toBeGreaterThan(0)
  const shown = await drawing(page)
  expect(shown.h, 'viewBox height after opening').toBeGreaterThan(0)
  expect(Math.abs(shown.w - shown.boxW), 'drawn at the open box width').toBeLessThanOrEqual(1)
  expect(Math.abs(shown.h - shown.boxH), 'drawn at the open box height').toBeLessThanOrEqual(1)
  expect(shown.nodes, 'nodes drawn and visible').toBeGreaterThan(0)
  await expect(slider).toHaveAttribute('aria-valuenow', String(last - 1))
  await expect(page.locator('[data-test="graph"]')).toContainText(`Market relationships at round ${last - 1}`)

  // Keeping the inner graph open while closing its parent must not strand it at 0×0.
  await page.locator('#simulation-evidence > summary').click()
  await slider.focus()
  await page.keyboard.press('Home')
  await page.locator('.lw-sim__source').click()
  await expect(page.locator('#simulation-evidence > summary')).toBeFocused()
  await expect.poll(async () => (await drawing(page)).w).toBeGreaterThan(0)
  expect(await sideways(page), 'Live simulation scrolls sideways').toBeLessThanOrEqual(0)
  if (process.env.UX_SHOTS) {
    await disclosure.screenshot({ path: join(process.env.UX_SHOTS, `${info.project.name}-evidence-graph.png`) })
  }
  expect(writes).toEqual([])
})

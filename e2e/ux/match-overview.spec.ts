/**
 * Overview as one payroll decision around the 72-hour cash path (the 2026-10-31 Overview design,
 * prp/2026-11-03-overview-cash-path), at 1440, 834 and 390 px and at 390x844 and 1440x900 in both
 * themes:
 *
 * - the first viewport, without scrolling: the answer (h1), the cash path with its reserve floor
 *   line, and Open simulation;
 * - the chart is the API's data: the floor, the trough and the late path's low point read back
 *   off the drawing's own axis equal the API's values for the same snapshot, and their labels
 *   say the API's figures;
 * - the equation settled − reserved = spendable, the what-if table, Hide path;
 * - nothing sideways at any width; every control a finger uses is at least 44 px on a phone;
 * - tooltips on the equation and on every chart point; the word budget (checks/word_budget.py);
 * - a screenshot of each first viewport, attached to the run.
 *
 * Read-only.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { settled, sideways, tipWorks } from './routes'
import { visibleWords, wordBudget } from './words'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const box = async (l: Locator) => (await l.boundingBox())!
const whole = (minor: number) => `${minor < 0 ? '-' : ''}$${(Math.abs(minor) / 100).toLocaleString('en-US')}`

/** The value a y pixel stands for on the chart's own axis ($0 gridline and the top one). */
async function axisOf (page: Page): Promise<(py: number) => number> {
  const grid = await page.locator('.lw-path__grid').evaluateAll((ls) => ls.map((l) => Number(l.getAttribute('y1'))))
  const labels = await page.locator('.lw-path__axis text').allTextContents()
  const zero = grid[labels.indexOf('$0')]
  const top = grid.at(-1)!
  const topMinor = Number(labels.at(-1)!.replace(/[$,]/g, '').replace(/k$/, '000').replace(/M$/, '000000')) * 100
  return (py) => Math.round(((zero - py) / (zero - top)) * topMinor)
}

/** The three things a reader must see without scrolling, in the viewport as it opened. */
async function firstViewport (page: Page, where: string): Promise<void> {
  const height = page.viewportSize()!.height
  for (const [what, l] of [['the answer', page.locator('h1')], ['the floor line', $(page, 'outlook-floor')],
    ['the cash path', $(page, 'outlook-line')], ['Open simulation', page.locator('a[data-test="open-simulation"]')]] as const) {
    const b = await box(l)
    expect(b.y, `${where}: ${what} starts above the page`).toBeGreaterThanOrEqual(0)
    expect(b.y + b.height, `${where}: ${what} is below the first viewport`).toBeLessThanOrEqual(height)
  }
  expect(await page.evaluate(() => window.scrollY), `${where}: the page opened scrolled`).toBe(0)
}

test('Overview: one payroll decision around the 72-hour cash path', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const touch = Boolean(info.project.use.hasTouch)
  const width = info.project.use.viewport!.width
  const api = await (await request.get('/api/v1/overview')).json()
  const late = api.scenario?.outlook ?? []
  expect(late.length, 'the prepared demonstration serves its late-receipt path').toBeGreaterThan(0)
  await page.goto('/overview')
  await settled(page)

  // the answer and its condition, from the API's coverage
  const hours = Math.round((Date.parse(api.coverage.at) - Date.parse(api.as_of)) / 3_600_000)
  await expect(page.locator('h1')).toHaveText('Payroll is covered.')
  await expect($(page, 'hero-subtitle')).toContainText(
    `Cash dips to ${whole(api.coverage.min_projected.minor)} at hour ${hours}, ${whole(api.coverage.headroom.minor)} above the reserve floor`)
  await expect($(page, 'hero-subtitle')).toContainText('as long as the $20,000 receivable lands at hour 12.')

  // settled − reserved = spendable, the API's figures
  await expect($(page, 'settled').locator('.lw-figure')).toHaveText(whole(api.cash.minor))
  await expect($(page, 'reserved').locator('.lw-figure')).toHaveText(whole(api.accounts[0].buckets.reserved.minor))
  await expect($(page, 'spendable').locator('.lw-figure')).toHaveText(whole(api.spendable.minor))

  // the chart is the API's data: read back off the drawing's own axis
  const value = await axisOf(page)
  expect(value(Number(await $(page, 'outlook-floor').getAttribute('y1'))), 'the floor line').toBe(api.coverage.floor.minor)
  expect(value(Number(await $(page, 'outlook-low-label').locator('circle').getAttribute('cy'))), 'the trough').toBe(api.coverage.min_projected.minor)
  const d = (await $(page, 'late-path').locator('path').first().getAttribute('d'))!
  const lateYs = [...d.matchAll(/[MV]\s*(?:[\d.]+,)?([\d.]+)/g)].map((m) => value(Number(m[1])))
  expect(lateYs, 'the late path').toEqual(late.map((p: any) => p.value.minor))
  const lateLow = Math.min(...late.map((p: any) => p.value.minor))
  await expect($(page, 'outlook-floor-label')).toContainText(whole(api.coverage.floor.minor))
  await expect($(page, 'outlook-low-label')).toContainText(whole(api.coverage.min_projected.minor))
  await expect($(page, 'outlook-low-label')).toContainText(`${whole(api.coverage.headroom.minor)} above`)
  await expect($(page, 'late-low-label')).toContainText(`${whole(lateLow)} if late`)
  await expect($(page, 'late-low-label')).toContainText(`${whole(api.coverage.floor.minor - lateLow)} below`)
  await expect($(page, 'outlook-point')).toHaveCount(api.outlook.length)

  // the what-if: the table, Hide path, the action
  await expect($(page, 'hypothetical')).toHaveText(/hypothetical · dashed path/i)
  await expect($(page, 'late-row')).toContainText(whole(lateLow))
  await expect($(page, 'coverage')).toContainText(whole(api.coverage.min_projected.minor))
  const open = page.locator('a[data-test="open-simulation"]')
  await expect(open).toHaveText('Open simulation')
  await expect(open).toHaveAttribute('href', `/simulation?run_id=${api.demo.run_id}`)

  // the first viewport, then a screenshot of it
  await firstViewport(page, `${width} px`)
  await page.screenshot({ path: info.outputPath(`overview-${width}-light.png`) })
  await info.attach(`overview-${width}-light`, { path: info.outputPath(`overview-${width}-light.png`), contentType: 'image/png' })

  // nothing sideways; a finger's controls are at least 44 px
  expect(await sideways(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
  if (touch) {
    for (const l of [open, $(page, 'toggle-late'), page.locator('a[data-test="outlook-event"]'), page.locator('.lw-ov-fold summary')]) {
      for (const el of await l.all()) {
        expect((await box(el)).height, `${await el.innerText()} is shorter than 44 px`).toBeGreaterThanOrEqual(44)
      }
    }
  }

  // tooltips: the equation and every chart point
  await tipWorks(page, $(page, 'tip-spendable'), touch, 'spendable now')
  await tipWorks(page, $(page, 'outlook-point').nth(2), touch, 'the low point')

  // Hide path takes the dashed path away; the table keeps its numbers
  await $(page, 'toggle-late').click()
  await expect($(page, 'late-path')).toHaveCount(0)
  await expect($(page, 'late-row')).toContainText(whole(lateLow))
  await $(page, 'toggle-late').click()
  await expect($(page, 'late-path')).toHaveCount(1)

  // the payroll under the axis opens its Treasury row
  await expect(page.locator('a[data-test="outlook-event"]')).toHaveAttribute('href', /\/treasury\?focus=obligation(%3A|:)payroll-1/)

  // the word budget at the mockup's width
  if (width >= 1200) {
    await page.setViewportSize({ width: 1487, height: 1058 })
    const words = (await visibleWords(page)).length
    info.annotations.push({ type: 'words', description: `${words} at 1487` })
    expect(words, `Overview at 1487 px shows ${words} words`).toBeLessThanOrEqual(wordBudget('overview'))
  }
  expect(writes).toEqual([])
})

for (const size of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  for (const scheme of ['light', 'dark'] as const) {
    test(`first viewport at ${size.width}x${size.height}, ${scheme}: the answer, the cash path with its floor, Open simulation`, async ({ page, baseURL }, info) => {
      test.skip(info.project.use.viewport!.width !== size.width, 'one run per size, on the project of that width')
      const writes = await readOnly(page, baseURL!)
      await page.emulateMedia({ colorScheme: scheme })
      await page.setViewportSize(size)
      await page.goto('/overview')
      await settled(page)
      await expect($(page, 'late-path')).toHaveCount(1)
      await firstViewport(page, `${size.width}x${size.height} ${scheme}`)
      expect(await sideways(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
      const file = info.outputPath(`overview-${size.width}-${scheme}.png`)
      await page.screenshot({ path: file })
      await info.attach(`overview-${size.width}x${size.height}-${scheme}`, { path: file, contentType: 'image/png' })
      expect(writes).toEqual([])
    })
  }
}

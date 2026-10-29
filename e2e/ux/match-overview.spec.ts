/**
 * Design match 1: Overview as mockup 01 (prp/2026-10-29-ux-pass/MATCH.md, 01 Overview), at
 * 1487 px (the mockup's width, on the desktop project), 834 and 390 px:
 *
 * - layout order: hero, the four figures, the cash outlook beside (wide) or above (narrow) the
 *   next obligation and the world exposure, the hypothetical banner last;
 * - the hero: headline, the treasury's subtitle, Open simulation as its one action;
 * - the four figures, from the API: Settled cash, Spendable now, the next obligation due with
 *   its hours ("in 40h"), Reserve headroom, as "$70,000";
 * - the outlook: a $ axis, the start and each flow annotated when wide, the lowest point boxed,
 *   the reserve floor, a legend; every point a control with the shared tooltip;
 * - tooltips on every figure, chart point and world node: hover (or tap on a phone) and keyboard
 *   focus open them, Escape closes them;
 * - the word budget (checks/word_budget.py) at every width.
 *
 * Read-only.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { settled, sideways } from './routes'
import { visibleWords, wordBudget } from './words'

const box = async (l: Locator) => (await l.boundingBox())!

/** Open a tooltip the way this width's reader would, and close it with Escape after focus. */
async function tipWorks (page: Page, trigger: Locator, touch: boolean, what: string): Promise<void> {
  const tip = trigger.locator('xpath=ancestor-or-self::*[contains(concat(" ", @class, " "), " lw-tip ")][1]')
  const bubble = tip.locator(':scope > [role="tooltip"]')
  await expect(bubble, `${what}: shown before it is asked for`).toBeHidden()
  if (touch) {
    await trigger.tap()
  } else {
    await trigger.hover()
  }
  await expect(bubble, `${what}: does not open on ${touch ? 'tap' : 'hover'}`).toBeVisible()
  await page.mouse.move(0, 0)
  await page.keyboard.press('Escape')
  await page.locator('h1').click()
  await expect(bubble, `${what}: does not close`).toBeHidden()
  await trigger.focus()
  await expect(bubble, `${what}: does not open on focus`).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(bubble, `${what}: Escape does not close it`).toBeHidden()
}

test('Overview as mockup 01', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const touch = Boolean(info.project.use.hasTouch)
  let width = info.project.use.viewport!.width
  if (width >= 1200) {
    width = 1487
    await page.setViewportSize({ width, height: 1058 })
  }
  const api = await (await request.get('/api/v1/overview')).json()
  await page.goto('/overview')
  await settled(page)

  // the hero
  await expect(page.locator('h1')).toHaveText('Know your cash. Rehearse the risk.')
  await expect(page.locator('[data-test="hero-subtitle"]')).toHaveText('Northwind Parts treasury / Observed snapshot', { useInnerText: true })
  const open = page.locator('[data-test="hero-action"] a[data-test="open-simulation"]')
  await expect(open).toHaveText('Open simulation')
  await expect(open).toHaveAttribute('href', `/simulation?run_id=${api.demo.run_id}`)

  // the four figures, the API's, in the mockup's words and format
  const metrics = page.locator('[data-test="strip"] .lw-ov-metric')
  await expect(metrics.locator('.lw-ov-metric__label')).toHaveText(['Settled cash', 'Spendable now', 'Payroll due', 'Reserve headroom'])
  const whole = (minor: number) => `$${(minor / 100).toLocaleString('en-US')}`
  await expect(metrics.locator('.lw-figure')).toHaveText([
    whole(api.cash.minor), whole(api.spendable.minor), whole(api.upcoming_outflows[0].amount.minor), whole(api.coverage.headroom.minor)
  ])
  const hours = Math.round((Date.parse(api.upcoming_outflows[0].due_at) - Date.parse(api.as_of)) / 3_600_000)
  await expect(page.locator('[data-test="next-due-at"]')).toHaveText(`· in ${hours}h`)

  // the outlook: axis, annotations (wide), the lowest point, the floor, the legend
  const chart = page.locator('[data-test="outlook-chart"]')
  await expect(chart.locator('.lw-outlook__axis text').first()).toHaveText(/^\$\d/)
  await expect(page.locator('[data-test="outlook-low-label"]')).toContainText(`${whole(api.coverage.min_projected.minor)} · h40`)
  await expect(page.locator('[data-test="outlook-floor-label"]')).toContainText(whole(api.coverage.floor.minor))
  if (width >= 1200) {
    await expect(page.locator('[data-test="outlook-note"]')).toHaveCount(3) // h0, the receivable, the venue inflow
    await expect(page.locator('[data-test="outlook-note"]').first()).toContainText('Starting cash')
  }
  await expect(page.locator('.lw-outlook__legend li')).toHaveText([/Projected cash \(observed\)/, /Reserve floor \(\$30,000\)/, /Lowest point/])
  await expect(page.locator('[data-test="outlook-point"]')).toHaveCount(api.outlook.length)

  // the next obligation and the world
  const next = page.locator('[data-test="next-obligation"]')
  await expect(next.locator('h2')).toHaveText('Next obligation')
  await expect(next).toContainText(/Due in\s*in 40h/)
  await expect(next.locator('[data-test="open-treasury"]')).toBeVisible()
  const world = page.locator('[data-test="exposure"]')
  await expect(world.locator('h2')).toHaveText('World exposure')
  await expect(world.locator('[data-test="treasury-node"]')).toContainText(`Treasury${whole(api.cash.minor)} settled`)
  expect(await world.locator('[data-test="relation"]').count()).toBeGreaterThanOrEqual(2)
  await expect(world.locator('[data-test="explore-world"]')).toHaveText('Explore world')

  // the hypothetical, last
  const scenario = page.locator('[data-test="scenario"]')
  await expect(scenario.locator('[data-test="hypothetical"]')).toHaveText(/hypothetical/i)
  await expect(scenario.locator('h2')).toHaveText('What if your $20,000 receivable arrives late?')
  await expect(scenario.locator('[data-test="preview-scenario"]')).toHaveText('Preview scenario')

  // layout order
  const hero = await box(page.locator('[data-test="hero"]'))
  const strip = await box(page.locator('[data-test="strip"]'))
  const outlook = await box(page.locator('[data-test="outlook"]'))
  const nextBox = await box(next)
  const worldBox = await box(world)
  const banner = await box(scenario)
  expect(strip.y, 'the figures sit under the hero').toBeGreaterThan(hero.y + hero.height - 1)
  expect(outlook.y, 'the outlook sits under the figures').toBeGreaterThan(strip.y + strip.height - 1)
  if (width >= 1200) {
    expect(nextBox.x, 'the next obligation sits right of the outlook').toBeGreaterThan(outlook.x + outlook.width - 1)
    expect(nextBox.y).toBeLessThan(outlook.y + 40)
  } else {
    expect(nextBox.y, 'narrow: the next obligation follows the outlook').toBeGreaterThan(outlook.y + outlook.height - 1)
  }
  expect(worldBox.y, 'the world follows the next obligation').toBeGreaterThanOrEqual(width < 768 ? nextBox.y + nextBox.height - 1 : nextBox.y)
  expect(banner.y, 'the hypothetical is last').toBeGreaterThan(Math.max(outlook.y + outlook.height, worldBox.y + worldBox.height) - 1)

  // tooltips: every figure, every chart point, every world node carries one
  for (const m of await metrics.all()) await expect(m.locator('[role="tooltip"]')).toHaveCount(1)
  await expect(page.locator('[data-test="tip-coverage"] [role="tooltip"]')).toContainText(/lowest point ahead \$40,000 · safety minimum \$30,000/)
  await tipWorks(page, page.locator('[data-test="spendable"] .lw-tip'), touch, 'a figure')
  await tipWorks(page, page.locator('[data-test="outlook-point"]').nth(2), touch, 'a chart point')
  await tipWorks(page, world.locator('[data-test="relation"]').first(), touch, 'a world node')

  // the word budget, and nothing sideways
  const words = (await visibleWords(page)).length
  info.annotations.push({ type: 'words', description: `${words} at ${width}` })
  expect(words, `Overview at ${width} px shows ${words} words`).toBeLessThanOrEqual(wordBudget('overview'))
  expect(await sideways(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

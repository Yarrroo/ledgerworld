/**
 * Lending as one answer (board item 177, the accepted 2026-11-02 Lending design), at 1440, 834 and
 * 390 px, and at 390x900 and 1440x900 in both themes:
 *
 * - the first viewport, without scrolling: the answer (h1, the API's K_p), the whole main object
 *   (the column, You, the venue with both its links) and Compare funding plans;
 * - the main object is the API's data: the column's segments stand for settled known, the
 *   committed line and the floor at one scale, the venue's block at the same scale, each label the
 *   API's figure; the treasury's cash from the overview;
 * - Compare funding plans in the hero on a wide screen, under the main object on a phone, its
 *   helper in words; the disabled Rehearse venue freeze with its reason as visible text, and no
 *   capacity-under-freeze figure;
 * - compact facility terms with the repayment schedule in place; the breakdown, Source and authority and
 *   When the reading changes folded;
 * - on a phone the six screens behind Menu (Escape closes it and gives focus back), every control
 *   of the screen at least 44 px; nothing sideways; the word budget (checks/word_budget.py);
 * - a screenshot of each first viewport, attached to the run.
 *
 * Read-only.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { settled, sideways } from './routes'
import { visibleWords, wordBudget } from './words'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const box = async (l: Locator) => (await l.boundingBox())!
const whole = (m: { minor: number }) => `${m.minor < 0 ? '-' : ''}$${(Math.abs(m.minor) / 100).toLocaleString('en-US')}`
const node = (page: Page, id: string) => page.locator(`[data-test="map-node"][data-node="${id}"]`)
const height = async (l: Locator) => Number(await l.getAttribute('height'))
const fund = (page: Page) => page.locator('[data-test="fund"]:visible, [data-test="fund-phone"]:visible')

/** The answer, the main object and the one action, in the viewport as it opened. */
async function firstViewport (page: Page, where: string): Promise<void> {
  const h = page.viewportSize()!.height
  for (const [what, l] of [['the answer', page.locator('h1')], ['the main object', $(page, 'loop')],
    ['Compare funding plans', fund(page)]] as const) {
    const b = await box(l)
    expect(b.y, `${where}: ${what} starts above the page`).toBeGreaterThanOrEqual(0)
    expect(b.y + b.height, `${where}: ${what} is below the first viewport`).toBeLessThanOrEqual(h)
  }
  expect(await page.evaluate(() => window.scrollY), `${where}: the page opened scrolled`).toBe(0)
}

test('Lending: the capacity and what it rests on, as one answer', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const width = info.project.use.viewport!.width
  const api = await (await request.get('/api/v1/lending')).json()
  const overview = await (await request.get('/api/v1/overview')).json()
  const { K_p: kp, parts } = api.capacity
  expect(api.capacity.authority, 'the demonstration reading is whole').toBe('full')
  expect(api.capacity.unobserved).toEqual([])
  await page.goto('/lending')
  await settled(page)

  // the answer, and what it is not
  await expect(page.locator('h1')).toHaveText(`Your lender can still lend you up to ${whole(kp)}.`)
  await expect($(page, 'hero-subtitle')).toHaveText(new RegExp(`^Not ${whole(parts.settled_known).replace('$', '\\$')}: `), { useInnerText: true })
  await expect($(page, 'capacity-value')).toHaveText(whole(kp))
  await expect(page.locator('#capacity-heading')).toHaveText(new RegExp(`^What the ${whole(kp).replace('$', '\\$')} rests on`))

  // the column: settled known at one scale, each part the API takes away a cut of it
  const loop = $(page, 'loop')
  const kpH = await height(loop.locator('rect[data-part="K_p"]'))
  const scale = kpH / kp.minor
  let drawn = kpH
  for (const key of ['committed_undrawn', 'pledged', 'obligations_due', 'floor']) {
    const seg = loop.locator(`rect[data-part="${key}"]`)
    if (parts[key].minor === 0) {
      await expect(seg, `${key} at $0 is said in words, not drawn`).toHaveCount(0)
      continue
    }
    const h = await height(seg)
    expect(h / scale, `${key} is not to scale`).toBeCloseTo(parts[key].minor, -2)
    drawn += h
  }
  expect(drawn / scale, 'the column is not settled known').toBeCloseTo(parts.settled_known.minor, -2)
  await expect(node(page, api.pool)).toContainText(whole(parts.settled_known))
  for (const key of ['committed_undrawn', 'floor']) {
    if (parts[key].minor > 0) await expect(loop).toContainText(`−${whole(parts[key])}`)
  }

  // You, and the venue under both, from the overview's relations
  const me = overview.company?.entity_id ?? 'treasury'
  await expect(node(page, me)).toContainText('You')
  if (width >= 1200) await expect(node(page, me)).toContainText(`Settled cash ${whole(overview.cash)}`)
  const pooled = overview.relations.find((r: any) => r.kind === 'venue_exposure' && r.source.entity_id === api.pool)
  expect(pooled, 'the demonstration relates the pool to a venue').toBeTruthy()
  const venue = node(page, pooled.target.entity_id)
  await expect(venue).toContainText(`The pool: ${whole(pooled.amount)} balance, counted`)
  await expect(venue).toContainText('which claim it backs is not itemised')
  await expect(venue).toContainText('Your treasury:')
  expect((await height(venue.locator('rect'))) / scale, 'the venue is not at the column’s scale').toBeCloseTo(pooled.amount.minor, -2)
  // nothing links the treasury to a borrower
  for (const e of await $(page, 'relations').locator('li').allTextContents()) {
    expect(e).not.toMatch(/Treasury → Bellfield|Bellfield Kitchens → Treasury/)
  }

  // the one action, its helper in words
  const action = fund(page)
  await expect(action).toHaveCount(1)
  await expect(action).toHaveText('Compare funding plans')
  await expect(action).toHaveAttribute('href', `/decisions?run_id=${overview.demo.run_id}`)
  await expect(page.locator('.lw-len-act__why:visible')).toHaveText('Compare ways to cover a cash gap. Nothing is lent from this page.')
  if (width < 768) {
    expect((await box(action)).y, 'phone: the action sits under the main object').toBeGreaterThan((await box(loop)).y + (await box(loop)).height - 1)
  }

  // the venue freeze: a hypothetical, its reason in words, no figure under a freeze
  const freeze = $(page, 'freeze')
  await expect(freeze.locator('h2')).toContainText('If the venue froze')
  await expect($(page, 'hypothetical')).toHaveText(/hypothetical/i)
  const rehearse = $(page, 'rehearse-freeze')
  await expect(rehearse).toHaveText('Rehearse venue freeze')
  if (await rehearse.evaluate((el) => el.tagName === 'BUTTON')) {
    await expect(rehearse).toBeDisabled()
    await expect($(page, 'freeze-why')).toBeVisible()
    await expect(rehearse).toHaveAttribute('aria-describedby', (await $(page, 'freeze-why').getAttribute('id'))!)
  }
  expect(await freeze.innerText()).not.toMatch(/\$\d/)

  // the facility terms, compact; the schedule in place
  const terms = $(page, 'facility-terms')
  for (const f of api.facilities) {
    const dl = terms.locator(`dl[data-facility="${f.facility_id}"]`)
    await expect(dl).toContainText(f.facility_id)
    await expect(dl).toContainText(whole(f.principal))
    if (f.observed_revenue.status !== 'known') await expect(dl).toContainText('expected revenue is not a receipt')
  }
  const schedule = $(page, 'view-repayments')
  await schedule.click()
  await expect($(page, 'repayments')).toContainText('never from a forecast')
  await schedule.click()

  // the depth, folded
  for (const id of ['breakdown', 'how-lending']) expect(await $(page, id).evaluate((el) => (el as HTMLDetailsElement).open), id).toBe(false)
  await expect($(page, 'calculation')).toBeHidden()

  // a phone: every control of the screen at least 44 px; the six screens behind Menu
  if (width < 768) {
    const controls = page.locator('[data-test="capacity"], .lw-len__readings, .lw-len__depth, [data-test="hero-action"]')
      .locator('a, button, summary')
    for (const c of await controls.all()) {
      if (!(await c.isVisible())) continue
      expect((await box(c)).height, `"${(await c.innerText()).trim()}" is under 44 px`).toBeGreaterThanOrEqual(43.5)
    }
    const menu = $(page, 'menu')
    expect((await box(menu)).height).toBeGreaterThanOrEqual(43.5)
    await menu.click()
    await expect(page.locator('nav.lw-nav ul a')).toHaveText(['Overview', 'Treasury', 'Lending', 'Simulation', 'Decisions', 'Execution'])
    await page.keyboard.press('Escape')
    await expect(menu).toBeFocused()
    await expect(menu).toHaveAttribute('aria-expanded', 'false')
  }
  expect(await sideways(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)

  // the first viewport, at the handoff's sizes, in both themes
  const size = width >= 1200 ? { width: 1440, height: 900 } : width < 768 ? { width: 390, height: 900 } : null
  if (size) {
    await page.setViewportSize(size)
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme })
      await page.goto('/lending')
      await settled(page)
      await firstViewport(page, `${size.width}x${size.height} ${scheme}`)
      expect(await sideways(page)).toBeLessThanOrEqual(0)
      if (process.env.UX_OUT) await page.screenshot({ path: `${process.env.UX_OUT}/match-lending-${size.width}-${scheme}.png` })
    }
    await page.emulateMedia({ colorScheme: 'light' })
  }

  // the word budget, at the mockup's width
  if (width >= 1200) {
    await page.setViewportSize({ width: 1487, height: 1058 })
    await page.goto('/lending')
    await settled(page)
    const words = (await visibleWords(page)).length
    info.annotations.push({ type: 'words', description: `${words} at 1487` })
    expect(words, `Lending at 1487 px shows ${words} words`).toBeLessThanOrEqual(wordBudget('lending'))
  }
  expect(writes).toEqual([])
})

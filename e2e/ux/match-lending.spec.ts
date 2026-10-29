/**
 * Design match 3: Lending as mockup 03 (prp/2026-10-29-ux-pass/MATCH.md, 03 Lending), at 1487 px
 * (the mockup's width, on the desktop project), 834 and 390 px:
 *
 * - layout order: hero; the capacity figure, the bridge and the exposure map on the left beside
 *   (wide) or above (narrow) the capacity breakdown and the venue freeze; the facility terms last;
 * - the hero: headline, the pool's subtitle, Compare funding plans as its one action;
 * - figures from the API: the big available capacity, the bridge's terms (settled known, every
 *   part that takes something away, the total), the breakdown's every part, the facility terms;
 * - the exposure map: the pool, each borrower and the venue as nodes, each facility an edge;
 * - tooltips on a figure, a bridge term, a table amount, a map node, a status and an action:
 *   hover (or tap on a phone) and keyboard focus open them, Escape closes them;
 * - the word budget (checks/word_budget.py) at every width; nothing scrolls sideways.
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
  await trigger.scrollIntoViewIfNeeded()
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

const whole = (m: { minor: number }) => `$${(m.minor / 100).toLocaleString('en-US')}`

test('Lending as mockup 03', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const touch = Boolean(info.project.use.hasTouch)
  let width = info.project.use.viewport!.width
  if (width >= 1200) {
    width = 1487
    await page.setViewportSize({ width, height: 1058 })
  }
  const api = await (await request.get('/api/v1/lending')).json()
  const overview = await (await request.get('/api/v1/overview')).json()
  const kp = api.capacity.K_p
  const parts = api.capacity.parts
  await page.goto('/lending')
  await settled(page)

  // the hero
  await expect(page.locator('h1')).toHaveText('Capacity you can rely on.')
  await expect(page.locator('[data-test="hero-subtitle"]')).toHaveText('Harbourline Credit pool / Observed snapshot', { useInnerText: true })
  const fund = page.locator('[data-test="hero-action"] [data-test="fund"]')
  await expect(fund).toHaveText('Compare funding plans')
  await expect(fund).toHaveAttribute('href', `/decisions?run_id=${overview.demo.run_id}`)

  // the big figure and its basis
  const capacity = page.locator('[data-test="capacity"]')
  await expect(capacity.locator('h2')).toHaveText('Available pool capacity')
  await expect(page.locator('[data-test="capacity-value"] .lw-tip').first()).toHaveText(new RegExp(`^${whole(kp).replace('$', '\\$')}`))
  await expect(page.locator('[data-test="capacity-basis"]')).toHaveText(/^Full balance authority\s*·\s*Known funds$/, { useInnerText: true })

  // the bridge: settled known − each part that takes something away = available capacity
  const bridge = page.locator('[data-test="parts"]')
  await expect(page.locator('#bridge-heading')).toHaveText('Capacity bridge')
  const taken = ['committed_undrawn', 'pledged', 'obligations_due', 'floor'].filter((k) => parts[k].minor !== 0)
  await expect(bridge.locator('li')).toHaveCount(taken.length + 2)
  await expect(bridge.locator('[data-part="settled_known"] .lw-len__amount')).toHaveText(whole(parts.settled_known))
  for (const k of taken) await expect(bridge.locator(`[data-part="${k}"] .lw-len__amount`)).toHaveText(`minus ${whole(parts[k])}`)
  await expect(bridge.locator('[data-part="K_p"] .lw-len__amount')).toHaveText(`equals ${whole(kp)}`)
  await expect(bridge.locator('.lw-len__term-label')).toHaveText(['Settled known', 'Committed undrawn', 'Reserve floor', 'Available capacity'])
  await expect(page.locator('[data-test="calculation"]')).toContainText('60,000.00 - 10,000.00 - 0.00 - 0.00 - 8,000.00 = 42,000.00')

  // the breakdown: every part, zeros included, the minus parts signed, the total highlighted
  const rows = page.locator('[data-test="breakdown"] tbody tr')
  await expect(rows.locator('th')).toHaveText(['Settled known', 'Committed undrawn', 'Pledged', 'Pool obligations', 'Reserve floor', 'Available capacity'])
  await expect(rows.locator('td .lw-tip')).toHaveText([
    whole(parts.settled_known), `−${whole(parts.committed_undrawn)}`, whole(parts.pledged), whole(parts.obligations_due),
    `−${whole(parts.floor)}`, whole(kp)
  ].map((t) => new RegExp(`^${t.replace('$', '\\$')}`)))
  await expect(rows.locator('.is-minus')).toHaveCount(2)

  // the exposure map: the pool, each borrower, the treasury and the venue; each facility an edge
  const map = page.locator('[data-test="exposure"]')
  await expect(map.locator('h2')).toHaveText('Shared exposure map')
  await expect(map.locator(`[data-test="map-node"][data-node="${api.pool}"]`)).toContainText(`Harbourline Credit pool`)
  await expect(map.locator(`[data-test="map-node"][data-node="${api.pool}"]`)).toContainText(whole(kp))
  for (const f of api.facilities) {
    await expect(map.locator(`[data-test="map-node"][data-node="${f.borrower}"]`)).toBeVisible()
    await expect(map.locator(`[data-edge="facility:${f.facility_id}"]`).first()).toBeAttached()
  }
  await expect(map.locator('[data-test="map-node"][data-node="treasury"]')).toContainText(whole(overview.cash))
  await expect(map.locator('[data-test="map-node"][data-node="venue"]')).toContainText('Quayside Exchange')
  // nothing links the treasury to a borrower
  for (const e of await map.locator('[data-test="relations"] li').allTextContents()) {
    expect(e).not.toMatch(/Treasury → Bellfield|Bellfield Kitchens → Treasury/)
  }
  if (width >= 768) {
    await expect(map.locator('[data-test="map-edge"]').first()).toBeVisible()
    expect(await map.locator('svg.lw-len__lines line').count()).toBeGreaterThanOrEqual(api.facilities.length)
  } else {
    await expect(map.locator('[data-test="relations"] li').first()).toBeVisible()
  }

  // the venue freeze, a labelled hypothetical, and its action
  const freeze = page.locator('[data-test="freeze"]')
  await expect(freeze.locator('h2')).toHaveText('Venue freeze scenario')
  await expect(freeze.locator('[data-test="hypothetical"]')).toHaveText(/hypothetical/i)
  await expect(freeze).toContainText('Unknown')
  await expect(freeze.locator('[data-test="rehearse-freeze"]')).toHaveText('Rehearse venue freeze')

  // the facility terms, last
  const terms = page.locator('[data-test="facility-terms"]')
  await expect(terms.locator('h2')).toHaveText('Facility terms')
  await expect(terms.locator('thead th')).toHaveText(['Facility', 'From', 'To', 'Principal', 'Fee', 'Total owed'])
  for (const f of api.facilities) {
    const row = terms.locator(`tr[data-facility="${f.facility_id}"] td`)
    await expect(row.nth(0)).toHaveText(new RegExp(`^${f.facility_id}`))
    await expect(row.nth(3)).toHaveText(new RegExp(`^${whole(f.principal).replace('$', '\\$')}`))
    await expect(row.nth(4)).toHaveText(new RegExp(`^${whole(f.fee).replace('$', '\\$')}`))
    await expect(row.nth(5)).toHaveText(new RegExp(`^${whole(f.owed).replace('$', '\\$')}`))
  }
  const schedule = terms.locator('[data-test="view-repayments"]')
  await expect(schedule).toHaveText('View repayment schedule')

  // layout order
  const hero = await box(page.locator('[data-test="hero"]'))
  const cap = await box(capacity)
  const bridgeBox = await box(page.locator('[data-test="bridge"]'))
  const mapBox = await box(map)
  const breakdown = await box(page.locator('[data-test="breakdown"]'))
  const freezeBox = await box(freeze)
  const termsBox = await box(terms)
  expect(cap.y, 'the figure sits under the hero').toBeGreaterThan(hero.y + hero.height - 1)
  expect(bridgeBox.y, 'the bridge follows the figure').toBeGreaterThan(cap.y + cap.height - 1)
  expect(mapBox.y, 'the map follows the bridge').toBeGreaterThan(bridgeBox.y + bridgeBox.height - 1)
  if (width >= 1200) {
    expect(breakdown.x, 'the breakdown sits right of the figure').toBeGreaterThan(cap.x + cap.width - 1)
    expect(breakdown.y).toBeLessThan(cap.y + 40)
  } else {
    expect(breakdown.y, 'narrow: the breakdown follows the map').toBeGreaterThan(mapBox.y + mapBox.height - 1)
  }
  expect(freezeBox.y, 'the freeze follows the breakdown').toBeGreaterThan(breakdown.y + breakdown.height - 1)
  expect(termsBox.y, 'the facility terms are last').toBeGreaterThan(Math.max(mapBox.y + mapBox.height, freezeBox.y + freezeBox.height) - 1)

  // tooltips: a figure, a bridge term, a table amount, a node, a status, an action
  await tipWorks(page, page.locator('[data-test="capacity-value"] .lw-tip').first(), touch, 'the capacity figure')
  await tipWorks(page, bridge.locator('[data-part="committed_undrawn"] .lw-tip'), touch, 'a bridge term')
  await tipWorks(page, rows.nth(4).locator('td .lw-tip'), touch, 'a breakdown amount')
  await tipWorks(page, map.locator(`[data-test="map-node"][data-node="${api.pool}"]`), touch, 'a map node')
  await tipWorks(page, freeze.locator('.lw-tip', { has: page.locator('[data-test="hypothetical"]') }), touch, 'the hypothetical status')
  await tipWorks(page, terms.locator('tr[data-facility] td').nth(3).locator('.lw-tip'), touch, 'a facility amount')
  await expect(page.locator('[data-test="calculation"]')).toBeAttached()

  // the repayment schedule opens and says how repayment is computed
  await schedule.click()
  await expect(terms.locator('[data-test="repayments"]')).toContainText('never from a forecast')
  await schedule.click()

  // the word budget, and nothing sideways
  const words = (await visibleWords(page)).length
  info.annotations.push({ type: 'words', description: `${words} at ${width}` })
  expect(words, `Lending at ${width} px shows ${words} words`).toBeLessThanOrEqual(wordBudget('lending'))
  expect(await sideways(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
  if (process.env.UX_OUT) await page.screenshot({ path: `${process.env.UX_OUT}/match-lending-${width}.png`, fullPage: true })
  expect(writes).toEqual([])
})

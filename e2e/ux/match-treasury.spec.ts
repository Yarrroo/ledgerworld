/**
 * Design match 2: Treasury as mockup 02 (prp/2026-10-29-ux-pass/MATCH.md, 02 Treasury), at
 * 1487 px (the mockup's width, on the desktop project), 834 and 390 px:
 *
 * - layout order: hero, the three figures, the cash buckets, the obligations and arrivals with
 *   View calculation; beside them (wide) or after them (narrow) spendable is not settled, the
 *   reserve coverage and the 72-hour projected cash path;
 * - the hero: headline, subtitle, Rehearse a cash shock as its one action;
 * - the figures, from the API: Settled cash, Reserved for payroll, Spendable now, as "$70,000";
 * - the bucket table and the obligations table with a status dot and one word per row, timing as
 *   h12, amounts signed; no account selector when the API serves one account;
 * - spendable is not settled: settled, less reserved, to the API's spendable;
 * - reserve coverage: the minimum with its hour, the floor, the headroom, the floor status;
 * - tooltips on figures, table cells and chart points: hover (or tap on a phone) and keyboard
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
const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)

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

test('Treasury as mockup 02', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const touch = Boolean(info.project.use.hasTouch)
  let width = info.project.use.viewport!.width
  if (width >= 1200) {
    width = 1487
    await page.setViewportSize({ width, height: 1058 })
  }
  const api = await (await request.get('/api/v1/treasury')).json()
  const a = api.accounts.find((x: { id: string }) => x.id.endsWith('/operating')) ?? api.accounts[0]
  const whole = (minor: number) => `$${(minor / 100).toLocaleString('en-US')}`
  const h = (at: string) => `h${Math.round((Date.parse(at) - Date.parse(api.as_of)) / 3_600_000)}`
  await page.goto('/treasury')
  await settled(page)

  // the hero
  await expect(page.locator('h1')).toHaveText('Every dollar, accounted for.')
  await expect($(page, 'hero-subtitle')).toHaveText('Cash, commitments and deadlines / Observed snapshot', { useInnerText: true })
  const rehearse = $(page, 'hero-action').locator('a[data-test="rehearse"]')
  await expect(rehearse).toHaveText('Rehearse a cash shock')

  // one account: no selector
  if (api.accounts.length === 1) await expect($(page, 'account-selector')).toHaveCount(0)

  // the three figures, the API's, in the mockup's words and format
  const metrics = $(page, 'strip').locator('.lw-tre-metric')
  await expect(metrics.locator('.lw-tre-metric__label')).toHaveText(['Settled cash', 'Reserved for payroll', 'Spendable now'])
  await expect(metrics.locator('.lw-figure')).toHaveText([whole(a.buckets.settled.minor), whole(a.buckets.reserved.minor), whole(a.spendable.minor)])

  // the cash buckets
  const buckets = $(page, 'buckets')
  await expect(buckets.locator('h2')).toHaveText('Operating account')
  await expect(buckets.locator('th')).toHaveText(['Cash bucket', 'Amount', 'Status'])
  await expect(buckets.locator('tbody tr td:first-child')).toHaveText(['Settled', 'Reserved for payroll', 'Pledged', 'Pending out'])
  await expect($(page, 'bucket-settled').locator('.lw-dot')).toHaveText('Known')
  await expect($(page, 'bucket-reserved').locator('.lw-dot')).toHaveText('Held')

  // obligations and arrivals: plain name, h-timing, signed amount, a state dot
  const rows = $(page, 'obligations')
  await expect(page.locator('#rows-heading')).toHaveText('Obligations & arrivals')
  await expect(rows.locator('th')).toHaveText(['Event', 'Timing', 'Amount', 'State'])
  const owed = api.obligations.filter((o: { account: string }) => o.account === a.id)
  const flows = [...a.buckets.pending_in, ...a.buckets.pending_out]
  await expect(rows.locator('tbody tr[data-row]')).toHaveCount(owed.length + flows.length)
  const payroll = owed.find((o: { kind: string }) => o.kind === 'payroll')
  const prow = $(page, `obligation-${payroll.obligation_id}`)
  await expect(prow.locator('td').nth(0)).toContainText('Payroll (employee payments)')
  await expect(prow.locator('td').nth(1)).toContainText(h(payroll.due_at))
  await expect(prow.locator('td').nth(2)).toContainText(`−${whole(payroll.amount.minor)}`)
  await expect(prow.locator('td').nth(3).locator('.lw-dot')).toHaveText('Reserved')
  const receivable = a.buckets.pending_in.find((f: { kind: string }) => f.kind === 'receivable')
  const rrow = rows.locator(`tr[data-row="${receivable.flow_id}"]`)
  await expect(rrow.locator('td').nth(1)).toContainText(h(receivable.expected_at))
  await expect(rrow.locator('td').nth(2)).toContainText(`+${whole(receivable.amount.minor)}`)
  await expect(rrow.locator('td').nth(3).locator('.lw-dot')).toHaveText('Expected')
  const calc = $(page, 'spend-calc')
  await expect(calc.locator('summary')).toHaveText('View calculation')
  await expect($(page, 'calculation')).toBeHidden()

  // spendable is not settled: settled less what is held, to the API's S
  const bridge = $(page, 'spend-bridge')
  await expect(bridge.locator('h2')).toHaveText('Spendable is not settled')
  await expect(bridge.locator('dt')).toHaveText(['Settled cash', 'Less: reserved for payroll'])
  await expect(bridge.locator('dd')).toHaveText([whole(a.buckets.settled.minor), `−${whole(a.buckets.reserved.minor)}`])
  await expect($(page, 'bridge-spendable')).toHaveText(whole(a.spendable.minor))
  await expect(bridge).toContainText('Reservations protect payroll.')

  // reserve coverage
  const low = a.projected.reduce((m: any, p: any) => (p.value.minor < m.value.minor ? p : m))
  const coverage = $(page, 'coverage')
  await expect(coverage.locator('h2')).toHaveText('Reserve coverage')
  await expect(coverage.locator('dt')).toHaveText([`Minimum projected (at ${h(low.t)})`, 'Reserve floor', 'Headroom', 'Status'])
  await expect($(page, 'minimum')).toHaveText(whole(low.value.minor))
  await expect($(page, 'floor-line')).toHaveText(whole(a.floor.minor))
  await expect($(page, 'headroom')).toHaveText(whole(low.value.minor - a.floor.minor))
  await expect($(page, 'floor-status')).toHaveText(/Above your safety minimum/)

  // the 72-hour path: a $ axis, the floor, the lowest point boxed, one control per API point
  const outlook = $(page, 'outlook')
  await expect(outlook.locator('h2')).toHaveText('72-hour projected cash path')
  await expect(outlook.locator('.lw-outlook__axis text').first()).toHaveText(/^\$\d/)
  await expect($(page, 'outlook-floor-label')).toContainText(whole(a.floor.minor))
  await expect($(page, 'outlook-low-label')).toContainText(`${whole(low.value.minor)} · ${h(low.t)}`)
  await expect($(page, 'outlook-point')).toHaveCount(a.projected.length)
  await expect(outlook.locator('.lw-outlook__axis text').filter({ hasText: /^72$/ })).toHaveCount(1)

  // layout order
  const hero = await box($(page, 'hero'))
  const strip = await box($(page, 'strip'))
  const bucketsBox = await box(buckets)
  const rowsBox = await box($(page, 'rows'))
  const bridgeBox = await box(bridge)
  const coverBox = await box(coverage)
  const pathBox = await box(outlook)
  expect(strip.y, 'the figures sit under the hero').toBeGreaterThan(hero.y + hero.height - 1)
  expect(bucketsBox.y, 'the buckets follow the figures').toBeGreaterThan(strip.y + strip.height - 1)
  expect(rowsBox.y, 'the obligations follow the buckets').toBeGreaterThan(bucketsBox.y + bucketsBox.height - 1)
  if (width >= 1200) {
    expect(bridgeBox.x, 'spendable is not settled sits right of the figures').toBeGreaterThan(strip.x + strip.width - 1)
    expect(bridgeBox.y).toBeLessThan(strip.y + 40)
  } else {
    expect(bridgeBox.y, 'narrow: spendable is not settled follows the obligations').toBeGreaterThan(rowsBox.y + rowsBox.height - 1)
  }
  expect(coverBox.y, 'the coverage follows spendable').toBeGreaterThan(bridgeBox.y + bridgeBox.height - 1)
  expect(pathBox.y, 'the path is last').toBeGreaterThan(coverBox.y + coverBox.height - 1)

  // tooltips: every figure, every table amount and state, every chart point
  for (const m of await metrics.all()) await expect(m.locator('[role="tooltip"]')).toHaveCount(1)
  for (const cell of await rows.locator('tbody tr[data-row] td').all()) await expect(cell.locator('[role="tooltip"]')).toHaveCount(1)
  await expect($(page, 'tip-spendable').locator('[role="tooltip"]')).toContainText(a.id)
  await tipWorks(page, $(page, 'tip-spendable'), touch, 'a figure')
  await tipWorks(page, prow.locator('td').nth(3).locator('.lw-tip'), touch, 'a state dot')
  await tipWorks(page, $(page, 'outlook-point').nth(2), touch, 'a chart point')

  // the fold shows the calculation on demand
  await calc.locator('summary').click()
  await expect($(page, 'spend-calculation')).toContainText(`S(now) in ${a.currency}`)
  await expect($(page, 'calculation')).toContainText(`in ${a.currency}`)
  await calc.locator('summary').click()

  // the word budget, and nothing sideways
  const words = (await visibleWords(page)).length
  info.annotations.push({ type: 'words', description: `${words} at ${width}` })
  expect(words, `Treasury at ${width} px shows ${words} words`).toBeLessThanOrEqual(wordBudget('treasury'))
  expect(await sideways(page), 'the page scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

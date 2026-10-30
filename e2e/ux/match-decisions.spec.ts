import { expect, test } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, settled, sideways, tipWorks } from './routes'
import { visibleWords, wordBudget } from './words'

// Mockup 05: the browser's layout order and data-backed comparison at each supplied width.
test('Decisions as mockup 05', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const touch = Boolean(info.project.use.hasTouch)
  let width = info.project.use.viewport!.width
  if (width >= 1200) { width = 1487; await page.setViewportSize({ width, height: 1058 }) }
  const runId = await demoRunId(request)
  const api = await (await request.get(`/api/v1/decisions/${runId}`)).json()
  const treasury = await (await request.get('/api/v1/treasury')).json()
  const account = treasury.accounts.find((a: any) => a.id.endsWith('/operating'))
  const none = api.results.filter((r: any) => r.policy === 'no-action')
  const minimum = Math.min(...none.map((r: any) => r.min_cash.minor))
  await page.goto(`/decisions?run_id=${runId}`)
  await settled(page)
  const $ = (id: string) => page.locator(`[data-test="${id}"]`)
  await expect(page.locator('h1')).toHaveText('Protect payroll. Preserve your reserve.')
  await expect($('hero-action')).toHaveCount(0)
  await expect($('decision-steps').locator('li')).toHaveText(['1 Rehearse', '2 Compare', '3 Review'])
  await expect($('decision-steps').locator('[aria-current="step"]')).toContainText('Compare')
  await expect(page.locator('#gap-heading')).toHaveText('The gap we need to close')
  const fmt = (minor: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: account.currency, maximumFractionDigits: 0 }).format(minor / 100)
  await expect($('gap-amount')).toHaveText(fmt(Math.max(0, account.floor.minor - minimum)))
  await expect($('waterfall')).toContainText('Cash waterfall (before plan)')
  await expect($('waterfall-point')).toHaveCount(3)
  await expect($('waterfall-bar-0')).toContainText(fmt(account.buckets.settled.minor))
  await expect($('waterfall-bar-1')).toContainText(fmt(minimum - account.buckets.settled.minor))
  await expect($('waterfall-bar-2')).toContainText(fmt(minimum))
  await expect($('waterfall-floor')).toHaveAttribute('y1', /\d/)
  await expect($('timing')).toContainText('Key timing in this scenario')
  await expect($('timing').locator('tr[data-at="0"]')).toContainText('Now')
  await expect($('timing').locator('tr[data-at="40"]')).toContainText('payroll')
  await expect($('timing').locator('tr[data-at="252"]')).toContainText('arrives late')
  await expect(page.locator('#policies-heading')).toHaveText('Three ways forward')
  await expect(page.locator('.lw-dec__name')).toHaveText(['No action', 'Fixed reserve', 'Integrated plan'])
  await expect(page.getByRole('radio')).toHaveCount(3)
  for (const policy of ['no-action', 'fixed-reserve', 'integrated']) {
    const row = $(`policy-${policy}`)
    await expect(row.locator('dt')).toHaveText(['Reserve outcome', 'Funding cost', 'Obligations unmet'])
  }
  await expect($('explanation')).toContainText('Minimum projected cash')
  await expect($('review-plan')).toHaveText('Review current plan')
  await expect($('review-plan')).toHaveAttribute('href', `/execution?run_id=${runId}&review=1`)
  await expect($('compare-details')).toHaveText('Compare scenario details')
  await expect($('open-simulation')).toHaveAttribute('href', `/simulation?run_id=${runId}`)
  const hero = (await $('hero').boundingBox())!, steps = (await $('decision-steps').boundingBox())!
  const gap = (await $('gap').boundingBox())!, plans = (await $('policies').boundingBox())!
  expect(steps.y).toBeGreaterThanOrEqual(hero.y + hero.height)
  expect(gap.y).toBeGreaterThanOrEqual(steps.y + steps.height)
  if (width >= 1200) expect(plans.x).toBeGreaterThanOrEqual(gap.x + gap.width)
  else expect(plans.y).toBeGreaterThanOrEqual(gap.y + gap.height)
  const panels = ['gap-summary', 'waterfall', 'timing']
  const boxes = await Promise.all(panels.map(async (id) => (await $(id).boundingBox())!))
  for (let i = 1; i < boxes.length; i++) expect(boxes[i].y).toBeGreaterThanOrEqual(boxes[i - 1].y + boxes[i - 1].height)
  for (const [trigger, name] of [
    [$('gap-tip'), 'gap'], [$('waterfall-point').nth(1), 'cash change'],
    [$('waterfall-floor-tip'), 'reserve floor'],
    [$('policy-integrated').locator('dd .lw-tip').first(), 'reserve outcome'],
    [$('minimum-tip'), 'minimum cash']
  ] as const) {
    await page.mouse.move(0, 0)
    await page.keyboard.press('Escape')
    await page.evaluate(() => (document.activeElement as HTMLElement)?.blur())
    await tipWorks(page, trigger, touch, name)
  }
  await $('policy-no-action').getByRole('radio').check()
  await expect($('explanation')).toContainText(fmt(minimum))
  await $('policy-integrated').getByRole('radio').check()
  await $('compare-details').click()
  await expect($('details-sheet')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect($('details-sheet')).toBeHidden()
  await page.locator('h1').click()
  const words = (await visibleWords(page)).length
  info.annotations.push({ type: 'words', description: `${words} at ${width}` })
  expect(words, `${words} words at ${width}`).toBeLessThanOrEqual(wordBudget('decisions'))
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    expect(await sideways(page)).toBeLessThanOrEqual(0)
    if (process.env.DECISIONS_SHOTS) await page.screenshot({ path: `${process.env.DECISIONS_SHOTS}/${width}-${scheme}.png`, fullPage: true })
  }
  await $('review-plan').click()
  await expect(page).toHaveURL(new RegExp(`/execution\\?run_id=${runId}&review=1$`))
  expect(writes).toEqual([])
})

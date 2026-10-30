/**
 * Decisions in motion (prp/2026-10-29-ux-pass/HANDOFF.md D1–D6), at every width of
 * e2e/ux.config.ts, on the prepared demonstration run: the cohort context with no probability;
 * the gap explanation and its always-visible timing table (the cash observed, the payroll deadline, the
 * venue arrival, the delayed receipt, in hours from the world's h0); the three policies as a
 * radio group whose choice highlights its row and updates the explanation without approving
 * anything; the scenario details drawer; the review
 * handoff to Execution; on a phone, grouped rows stacked, never a carousel. Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { crumb, demoRunId, settled, sideways } from './routes'
import { fmt } from './copy'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const NAMES: Record<string, string> = { 'no-action': 'No action', 'fixed-reserve': 'Fixed reserve', integrated: 'Integrated plan' }

async function open (page: Page, runId: string): Promise<void> {
  await page.goto(`/decisions?run_id=${runId}`)
  await settled(page)
  await expect(crumb(page)).toHaveText('Decisions')
  await expect($(page, 'error')).toHaveCount(0)
}

test('D1–D2: cohort context, the gap and its timing', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await (await request.get(`/api/v1/decisions/${runId}`)).json()
  await open(page, runId)

  const evidence = page.locator('details[data-test="how-decisions"]')
  await expect(evidence).toHaveCount(1)
  await expect($(page, 'cohort')).toBeHidden()
  await evidence.locator('summary').click()
  await expect($(page, 'cohort')).toBeVisible()
  await expect($(page, 'cohort')).toContainText(`Run ${runId}`)
  await expect($(page, 'cohort')).toContainText('not a probability')
  await evidence.locator('summary').click()
  expect(await page.locator('main').innerText(), 'a probability was inferred').not.toMatch(/\d\s*%|probability of/i)
  await expect(page.locator('a[data-test="open-simulation"]')).toHaveAttribute('href', `/simulation?run_id=${runId}`)

  const treasury = await (await request.get('/api/v1/treasury')).json()
  const account = treasury.accounts.find((a: any) => a.id.endsWith('/operating')) ?? treasury.accounts[0]
  const none = api.results.filter((r: { policy: string }) => r.policy === 'no-action')
  const lowest = none.reduce((a: any, b: any) => b.min_cash.minor < a.min_cash.minor ? b : a).min_cash
  const summary = $(page, 'gap-summary')
  await expect(page.locator('#gap-heading')).toHaveText('The gap we need to close')
  await expect(summary).toBeVisible()
  await expect(summary).toContainText(fmt({ minor: Math.max(0, account.floor.minor - lowest.minor), currency: lowest.currency }))
  if (lowest.minor < account.floor.minor) await expect(summary).toContainText(/short|below|under/i)
  if (none.every((r: any) => r.obligations_unmet === 0)) await expect(summary).toContainText(/every obligation met|all obligations met/i)

  await expect($(page, 'timing')).toBeVisible()
  await expect($(page, 'timing').locator('summary, li')).toHaveCount(0)
  const steps = $(page, 'timing').locator('tr[data-at]')
  await expect(steps.first()).toBeVisible()
  await expect(steps.first()).toContainText('settled cash observed')
  const hours = (await steps.evaluateAll((els) => els.map((e) => Number(e.getAttribute('data-at')))))
  expect([...hours].sort((a, b) => a - b), 'timing is not in time order').toEqual(hours)
  if (/delayed-receipt/.test(api.cohort)) {
    // h40 payroll, h48 venue arrival, h12 + 240 h = h252 delayed receipt (the integrity appendix)
    for (const h of ['40', '48', '252']) await expect($(page, 'timing').locator(`tr[data-at="${h}"]`)).toHaveCount(1)
    await expect($(page, 'timing').locator('tr[data-at="252"]')).toContainText('arrives late')
  }
  expect(await sideways(page), 'Decisions scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('D3: a radio group whose choice explains, highlights and approves nothing', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await (await request.get(`/api/v1/decisions/${runId}`)).json()
  await open(page, runId)

  await expect($(page, 'decision-steps').locator('li')).toHaveText(['1 Rehearse', '2 Compare', '3 Review'])
  await expect(page.locator('[data-test="hero-action"] :is(a, button)')).toHaveCount(0)
  await expect(page.locator('#policies-heading')).toHaveText('Three ways forward')
  const group = page.getByRole('radiogroup')
  const radios = group.getByRole('radio')
  await expect(radios).toHaveCount(3)
  await expect($(page, 'policies').locator('[data-test="selected"]')).toHaveCount(1)
  await expect($(page, `policy-${api.selected}`).locator('[data-test="selected"]')).toBeVisible()
  await expect($(page, `policy-${api.selected}`).getByRole('radio')).toBeChecked()
  await expect($(page, 'explanation')).toContainText(`With ${NAMES[api.selected]}`)
  const review = $(page, 'policies').locator('a[data-test="review-plan"]')
  const href = await review.getAttribute('href')

  for (const policy of ['no-action', 'fixed-reserve', 'integrated']) {
    const row = $(page, `policy-${policy}`)
    await row.getByRole('radio').check()
    await expect(row).toHaveClass(/is-chosen/)
    const minimum = api.results.filter((r: any) => r.policy === policy)
      .reduce((a: any, b: any) => b.min_cash.minor < a.min_cash.minor ? b : a).min_cash
    await expect($(page, 'explanation')).toContainText('Minimum projected cash')
    await expect($(page, 'minimum-tip')).toContainText(fmt(minimum))
    await expect($(page, 'minimum-tip').locator('[role="tooltip"]')).toContainText(`With ${NAMES[policy]}`)
    await expect(page.locator('.lw-dec__row.is-chosen')).toHaveCount(1)
    // the backend's selection and the review do not move
    await expect($(page, `policy-${api.selected}`).locator('[data-test="selected"]')).toBeVisible()
    await expect(review).toHaveAttribute('href', href!)
  }
  // keyboard: arrows move within the group
  await $(page, 'policy-no-action').getByRole('radio').focus()
  await page.keyboard.press('ArrowDown')
  await expect($(page, 'policy-fixed-reserve').getByRole('radio')).toBeChecked()
  await expect($(page, 'explanation')).toContainText('With Fixed reserve')
  for (const head of await page.locator('.lw-dec__head').all()) {
    expect((await head.boundingBox())!.height).toBeGreaterThanOrEqual(43.5)
  }
  expect(writes).toEqual([])
})

test('D4–D5: scenario details drawer; review hands off to Execution', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await (await request.get(`/api/v1/decisions/${runId}`)).json()
  await open(page, runId)

  const opener = $(page, 'compare-details')
  await opener.click()
  const sheet = $(page, 'details-sheet')
  await expect(sheet).toBeVisible()
  await expect(sheet.locator('tbody tr')).toHaveCount(api.results.length)
  await expect(sheet).toContainText("not the current plan's fee")
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  await expect(opener).toBeFocused()

  const evidence = page.locator('details[data-test="how-decisions"]')
  const execution = evidence.locator('a[data-test="view-execution"]')
  await expect(execution).toBeHidden()
  await evidence.locator('summary').click()
  await expect(execution).toBeVisible()
  await expect(execution).toHaveAttribute('href', `/execution?run_id=${runId}`)
  await evidence.locator('summary').click()
  if (api.status === 'selected') {
    const review = page.locator('a[data-test="review-plan"]')
    await expect(review).toHaveAttribute('href', `/execution?run_id=${runId}&review=1`)
    await review.click()
    await expect(page).toHaveURL(/\/execution\?/)
    await settled(page)
    await expect(crumb(page)).toHaveText('Execution')
  } else {
    await expect(page.locator('[data-test="review-plan"]')).toHaveCount(0)
  }
  expect(writes, 'opening the review sent a write').toEqual([])
})

test('phone: gap, timing, grouped rows stacked, review; no carousel', async ({ page, request }, info) => {
  test.skip(info.project.use.viewport!.width >= 768, 'the phone layout')
  const runId = await demoRunId(request)
  await open(page, runId)
  const y = async (selector: string) => (await page.locator(selector).first().boundingBox())!.y
  const order = [await y('[data-test="gap-summary"]'), await y('[data-test="timing"]'),
    await y('[data-test="policy-no-action"]'), await y('[data-test="explanation"]')]
  expect([...order].sort((a, b) => a - b)).toEqual(order)
  const review = $(page, 'policies').locator('a[data-test="review-plan"]')
  if (await review.count()) {
    await expect(review).toBeVisible()
    expect((await review.boundingBox())!.y).toBeGreaterThan(await y('[data-test="explanation"]'))
  }
  const boxes = await page.locator('.lw-dec__row').evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect()
    return { x: Math.round(r.x), y: r.y, right: r.right }
  }))
  for (let i = 1; i < boxes.length; i++) {
    expect(boxes[i].x, 'policy rows sit side by side').toBe(boxes[0].x)
    expect(boxes[i].y).toBeGreaterThan(boxes[i - 1].y)
  }
  for (const b of boxes) expect(b.right).toBeLessThanOrEqual(info.project.use.viewport!.width)
  expect(await sideways(page)).toBeLessThanOrEqual(0)
})

test('a comparison with a replayed result says Replay in the header, outside every tooltip', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await (await request.get(`/api/v1/decisions/${runId}`)).json()
  // one replayed branch among fresh ones; the comparison's body itself carries no replay
  const results = api.results.map((r: { replay: boolean }, i: number) => ({ ...r, replay: i === 0 }))
  await page.route(`**/api/v1/decisions/${runId}`, (route) => route.fulfill({ json: { ...api, results } }))
  await open(page, runId)
  await expect($(page, 'context-line')).toBeVisible()
  await expect($(page, 'context-line')).toHaveText(/ · Replay$/)
  await expect($(page, 'mode')).toBeVisible()
  await expect($(page, 'mode')).toContainText('Replay')
  expect(await sideways(page), 'Decisions scrolls sideways').toBeLessThanOrEqual(0)
  await page.locator('[data-test="banner"]').screenshot({ path: info.outputPath('replay-header.png') })
  expect(writes).toEqual([])
})

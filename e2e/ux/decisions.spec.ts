/**
 * Decisions in motion (prp/2026-10-29-ux-pass/HANDOFF.md D1–D6), at every width of
 * e2e/ux.config.ts, on the prepared demonstration run: the cohort context with no probability;
 * the gap explanation and its timing disclosure (the cash observed, the payroll deadline, the
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
const NAMES: Record<string, string> = { 'no-action': 'Do nothing', 'fixed-reserve': 'Keep a fixed buffer', integrated: 'Borrow just enough' }

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

  await expect($(page, 'cohort')).toContainText(`Run ${runId}`)
  await expect($(page, 'cohort')).toContainText('not a probability')
  expect(await page.locator('main').innerText(), 'a probability was inferred').not.toMatch(/\d\s*%|probability of/i)
  await expect(page.locator('a[data-test="open-simulation"]')).toHaveAttribute('href', `/simulation?run_id=${runId}`)

  const none = api.results.find((r: { policy: string }) => r.policy === 'no-action')
  const summary = $(page, 'gap-summary')
  await expect(summary).toContainText('Lowest point')
  await expect(summary).toContainText(fmt(none.min_cash))
  if (!none.floor_kept) await expect(summary).toContainText('short')
  if (none.obligations_unmet === 0) await expect(summary).toContainText('Every obligation met')

  await $(page, 'timing').locator('summary').click()
  const steps = $(page, 'timing').locator('li')
  await expect(steps.first()).toContainText('settled cash observed')
  const hours = (await steps.evaluateAll((els) => els.map((e) => Number(e.getAttribute('data-at')))))
  expect([...hours].sort((a, b) => a - b), 'timing is not in time order').toEqual(hours)
  if (/delayed-receipt/.test(api.cohort)) {
    // h40 payroll, h48 venue arrival, h12 + 240 h = h252 delayed receipt (the integrity appendix)
    for (const h of ['40', '48', '252']) await expect($(page, 'timing').locator(`li[data-at="${h}"]`)).toHaveCount(1)
    await expect($(page, 'timing').locator('li[data-at="252"]')).toContainText('arrives late')
  }
  expect(await sideways(page), 'Decisions scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('D3: a radio group whose choice explains, highlights and approves nothing', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await (await request.get(`/api/v1/decisions/${runId}`)).json()
  await open(page, runId)

  const group = page.getByRole('radiogroup')
  const radios = group.getByRole('radio')
  await expect(radios).toHaveCount(3)
  await expect($(page, 'policies').locator('[data-test="selected"]')).toHaveCount(1)
  await expect($(page, `policy-${api.selected}`).locator('[data-test="selected"]')).toBeVisible()
  await expect($(page, `policy-${api.selected}`).getByRole('radio')).toBeChecked()
  await expect($(page, 'explanation')).toContainText(`With ${NAMES[api.selected]}`)
  const review = page.locator('a[data-test="review-plan"]')
  const href = await review.getAttribute('href')

  for (const policy of ['no-action', 'fixed-reserve', 'integrated']) {
    const row = $(page, `policy-${policy}`)
    await row.getByRole('radio').check()
    await expect(row).toHaveClass(/is-chosen/)
    await expect($(page, 'explanation')).toContainText(`With ${NAMES[policy]}`)
    await expect(page.locator('.lw-dec__row.is-chosen')).toHaveCount(1)
    // the backend's selection and the review do not move
    await expect($(page, `policy-${api.selected}`).locator('[data-test="selected"]')).toBeVisible()
    await expect(review).toHaveAttribute('href', href!)
  }
  // keyboard: arrows move within the group
  await $(page, 'policy-no-action').getByRole('radio').focus()
  await page.keyboard.press('ArrowDown')
  await expect($(page, 'policy-fixed-reserve').getByRole('radio')).toBeChecked()
  await expect($(page, 'explanation')).toContainText('With Keep a fixed buffer')
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

  await expect(page.locator('a[data-test="view-execution"]')).toHaveAttribute('href', `/execution?run_id=${runId}`)
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
    await y('[data-test="policy-no-action"]'), await y('[data-test="view-execution"]')]
  expect([...order].sort((a, b) => a - b)).toEqual(order)
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

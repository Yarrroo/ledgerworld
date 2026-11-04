/**
 * Lending in motion (board item 177, the accepted 2026-11-02 Lending design), at every width of
 * e2e/ux.config.ts: the breakdown listing every part, zeros included, with the calculation and the
 * account evidence, folded under the readings; Source and authority folded beside it; the main object's
 * parties (the pool, the treasury, the venue, the committed line's borrower) and its text
 * alternative with the appendix's canonical edges (the pool to Borrower B via line-b, never a
 * Treasury–Borrower B credit); the freeze scenario as a labelled hypothetical, its disabled reason
 * in words; the facility terms and the repayment schedule; Compare funding plans opening
 * Decisions for the prepared run. Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { crumb, demoRunId, settled, sideways } from './routes'
import { fmt } from './copy'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)

async function open (page: Page): Promise<void> {
  await page.goto('/lending')
  await settled(page)
  await expect(crumb(page)).toHaveText('Lending')
  await expect($(page, 'error')).toHaveCount(0)
}

const figure = (minor: number) => {
  const digits = String(Math.abs(minor)).padStart(3, '0')
  const whole = digits.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${minor < 0 ? '-' : ''}${whole}.${digits.slice(-2)}`
}

test('L1–L2: every part, zeros included, and the source, folded', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  const how = $(page, 'how-lending')
  await expect($(page, 'authority')).toBeHidden()
  await how.locator('summary').click()
  await expect(how).toContainText(api.snapshot_id)
  await expect(how).toContainText(api.capacity.K_p.currency)
  await expect($(page, 'authority')).toContainText(api.capacity.authority)

  // the breakdown lists every part, in the API's order, and the calculation from them
  const breakdown = $(page, 'breakdown')
  await breakdown.locator('summary').click()
  const rows = breakdown.locator('tbody tr')
  await expect(rows).toHaveCount(6)
  for (const key of ['settled_known', 'committed_undrawn', 'pledged', 'obligations_due', 'floor']) {
    const metric = api.capacity.parts[key]
    const row = breakdown.locator(`[data-row="${key}"]`)
    await expect(row, `part ${key}`).toBeVisible()
    if (metric.minor !== null) await expect(row).toContainText(fmt(metric))
  }
  const p = api.capacity.parts
  const line = [p.settled_known, p.committed_undrawn, p.pledged, p.obligations_due, p.floor]
    .map((m: { minor: number }) => figure(m.minor)).join(' - ')
  await expect($(page, 'calculation')).toBeVisible()
  await expect($(page, 'calculation')).toContainText(`${line} = ${figure(api.capacity.K_p.minor)}`)
  await expect($(page, 'evidence')).toBeVisible()
  await expect($(page, 'evidence')).toContainText('Not counted')
  await expect($(page, 'evidence')).toContainText('not itemised')
  expect(await sideways(page), 'Lending scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('L3: the main object’s parties and canonical edges', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  for (const f of api.facilities) {
    await expect($(page, 'relations').locator(`[data-edge="facility:${f.facility_id}"]`), `facility ${f.facility_id} is not stated`).toHaveCount(1)
  }
  // line-b runs from the pool to Borrower B; nothing links the treasury to Borrower B
  const lineB = api.facilities.find((f: { facility_id: string }) => f.facility_id === 'line-b')
  if (lineB) {
    expect(lineB.borrower).toBe('borrower-b')
    await expect($(page, 'relations').locator('[data-edge="facility:line-b"]')).toContainText(/Pool → (Bellfield Kitchens|borrower-b)/)
  }
  for (const text of await $(page, 'relations').locator('li').allTextContents()) {
    expect(text, 'a Treasury–Borrower B relationship is drawn').not.toMatch(/Treasury → Bellfield|Bellfield Kitchens → Treasury/)
  }

  // the drawing's parties, when the reading is whole
  if (api.capacity.authority === 'full' && !api.capacity.unobserved.length) {
    await expect(page.locator(`[data-test="map-node"][data-node="${api.pool}"]`)).toContainText(fmt(api.capacity.parts.settled_known))
    await expect(page.locator('[data-test="map-node"][data-node="treasury"]')).toContainText('You')
    if (lineB) await expect(page.locator('[data-test="map-node"][data-node="borrower-b"]')).toContainText(fmt(lineB.principal))
  }
  expect(await sideways(page), 'Lending scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('L4–L5: freeze is Unknown not zero; facility terms and repayments', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  const freeze = $(page, 'freeze')
  await expect(freeze).toContainText(api.capacity.authority === 'full' ? 'What-if' : 'Happening now')
  await expect(freeze).toContainText('Unknown')
  await expect(freeze).not.toContainText(/(^|[^\d.,])\$0(?![\d,])/)
  const rehearse = $(page, 'rehearse-freeze')
  if (await rehearse.evaluate((el) => el.tagName === 'BUTTON')) {
    await expect(rehearse).toBeDisabled()
    await expect($(page, 'freeze-why')).toBeVisible()
    await expect($(page, 'freeze-why')).toHaveText(/\w/)
  }

  for (const f of api.facilities) {
    const row = $(page, 'facilities').locator(`dl[data-facility="${f.facility_id}"]`)
    await expect(row).toContainText(fmt(f.principal))
    await expect(row).toContainText(fmt(f.fee))
    await expect(row).toContainText(fmt(f.owed))
  }
  const schedule = $(page, 'view-repayments')
  expect((await schedule.boundingBox())!.height).toBeGreaterThanOrEqual(43.5)
  await schedule.click()
  await expect($(page, 'repayments')).toContainText('never from a forecast')
  for (const f of api.facilities) await expect($(page, 'repayments')).toContainText(f.facility_id)
  await expect($(page, 'facility-terms')).toContainText('not proof of disbursement')
  await schedule.click()
  await expect($(page, 'repayments')).toHaveCount(0)
  expect(writes).toEqual([])
})

test('L6: Compare funding plans opens Decisions for the prepared run', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)
  const fund = page.locator('[data-test="fund"]:visible, [data-test="fund-phone"]:visible')
  if (api.capacity.authority !== 'full' || api.capacity.K_p.status !== 'known') {
    await expect(fund).toBeDisabled()
    await expect($(page, 'fund-why')).toHaveText(/\w/)
    return
  }
  await expect(fund).toHaveText('Compare funding plans')
  await fund.click()
  await expect(page).toHaveURL(/\/decisions\?/)
  expect(new URL(page.url()).searchParams.get('run_id')).toBe(runId)
  await settled(page)
  await expect(crumb(page)).toHaveText('Decisions')
  expect(writes).toEqual([])
})

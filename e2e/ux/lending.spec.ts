/**
 * Lending in motion (prp/2026-10-29-ux-pass/HANDOFF.md L1–L6, laid out as mockup 03), at every
 * width of e2e/ux.config.ts: the pool and its authority one (i) down; the bridge and the breakdown
 * listing every part, zeros included, with the calculation and the account evidence in tooltips;
 * the exposure map with the appendix's canonical edges (the pool to Borrower B via line-b, never a
 * Treasury–Borrower B credit), each node and edge explained by its tooltip; the freeze scenario as
 * a labelled hypothetical; the facility terms and the repayment schedule; Compare funding plans
 * opening Decisions for the prepared run. Read-only.
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

test('L1–L2: pool context and every part, zeros included', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  await expect($(page, 'pool')).toBeVisible()
  const how = $(page, 'how-lending')
  await how.locator('.lw-how__icon').focus()
  const facts = how.locator('[role="tooltip"]')
  await expect(facts).toBeVisible()
  await expect(facts).toContainText(api.snapshot_id)
  await expect(facts).toContainText(api.capacity.K_p.currency)
  await expect($(page, 'authority')).toContainText(api.capacity.authority)
  await page.keyboard.press('Escape')

  // the breakdown lists every part; the bridge every part that takes something away
  const rows = $(page, 'breakdown').locator('tbody tr')
  await expect(rows).toHaveCount(6)
  for (const key of ['settled_known', 'committed_undrawn', 'pledged', 'obligations_due', 'floor']) {
    const metric = api.capacity.parts[key]
    const row = $(page, 'breakdown').locator(`[data-row="${key}"]`)
    await expect(row, `part ${key}`).toBeVisible()
    if (metric.minor !== null) await expect(row).toContainText(fmt(metric))
    if (metric.minor !== 0) await expect($(page, 'parts').locator(`[data-part="${key}"]`)).toBeVisible()
  }
  const total = $(page, 'expand-calculation')
  await total.focus()
  const p = api.capacity.parts
  const line = [p.settled_known, p.committed_undrawn, p.pledged, p.obligations_due, p.floor]
    .map((m: { minor: number }) => figure(m.minor)).join(' - ')
  await expect($(page, 'calculation')).toBeVisible()
  await expect($(page, 'calculation')).toContainText(`${line} = ${figure(api.capacity.K_p.minor)}`)
  await page.keyboard.press('Escape')
  const settledTerm = $(page, 'parts').locator('[data-part="settled_known"] .lw-tip')
  await settledTerm.focus()
  await expect($(page, 'evidence')).toBeVisible()
  await expect($(page, 'evidence')).toContainText('Not counted')
  await expect($(page, 'evidence')).toContainText('not itemised')
  await page.keyboard.press('Escape')
  expect(await sideways(page), 'Lending scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('L3: canonical edges; a node and an edge explain themselves', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  for (const f of api.facilities) {
    await expect($(page, 'relations').locator(`[data-edge="facility:${f.facility_id}"]`), `facility ${f.facility_id} is not drawn`).toHaveCount(1)
    await expect(page.locator(`[data-test="map-edge"][data-edge="facility:${f.facility_id}"]`)).toHaveCount(1)
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

  // a node, by keyboard: its tooltip names what it is
  const pool = page.locator(`[data-test="map-node"][data-node="${api.pool}"]`)
  await pool.focus()
  await expect(pool.locator(':scope > [role="tooltip"]')).toBeVisible()
  await expect(pool.locator(':scope > [role="tooltip"]')).toContainText('lender pool')
  await page.keyboard.press('Escape')
  await expect(pool.locator(':scope > [role="tooltip"]')).toBeHidden()

  // an edge, by keyboard: the facility it stands for
  const first = api.facilities[0]
  if (first) {
    const wide = await page.locator(`[data-test="map-edge"][data-edge="facility:${first.facility_id}"]`).isVisible()
    const edge = wide
      ? page.locator(`[data-test="map-edge"][data-edge="facility:${first.facility_id}"]`)
      : $(page, 'relations').locator(`[data-edge="facility:${first.facility_id}"] .lw-tip`)
    await edge.focus()
    await expect(edge.locator(':scope > [role="tooltip"]')).toContainText(first.facility_id)
    await page.keyboard.press('Escape')
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
    await expect($(page, 'freeze-why')).toHaveText(/\w/)
  }

  for (const f of api.facilities) {
    const row = $(page, 'facilities').locator(`tr[data-facility="${f.facility_id}"]`)
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
  const fund = $(page, 'fund')
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

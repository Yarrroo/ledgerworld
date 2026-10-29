/**
 * Lending in motion (prp/2026-10-29-ux-pass/HANDOFF.md L1–L6), at every width of
 * e2e/ux.config.ts: the pool's context; the capacity bridge listing every part, zeros included,
 * with its calculation and account evidence; the exposure map with the appendix's canonical edges
 * (the pool to Borrower B via line-b, never a Treasury–Borrower B credit) where a node or an edge
 * opens its details; the freeze scenario as a labelled hypothetical; facility detail and
 * repayments; Compare funding plans opening Decisions for the prepared run. Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, settled, sideways } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const sheet = (page: Page) => $(page, 'lending-detail')

async function open (page: Page): Promise<void> {
  await page.goto('/lending')
  await settled(page)
  await expect(page.locator('h1')).toHaveText('Lending')
  await expect($(page, 'error')).toHaveCount(0)
}

const figure = (minor: number) => {
  const digits = String(Math.abs(minor)).padStart(3, '0')
  const whole = digits.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${minor < 0 ? '-' : ''}${whole}.${digits.slice(-2)}`
}

test('L1–L2: pool context and a bridge of every part, zeros included', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  const context = $(page, 'pool-context')
  await expect(context).toContainText(api.pool)
  await expect(context).toContainText(api.snapshot_id)
  await expect(context).toContainText(api.capacity.K_p.currency)
  await expect($(page, 'authority')).toContainText(api.capacity.authority)

  const parts = $(page, 'parts').locator('li')
  await expect(parts).toHaveCount(6)
  for (const key of ['settled_known', 'committed_undrawn', 'pledged', 'obligations_due', 'floor']) {
    const metric = api.capacity.parts[key]
    const row = $(page, 'parts').locator(`[data-part="${key}"]`)
    await expect(row, `part ${key}`).toBeVisible()
    if (metric.minor !== null) await expect(row).toContainText(`${metric.currency} ${figure(metric.minor)}`)
  }
  await $(page, 'expand-calculation').locator('summary').click()
  const p = api.capacity.parts
  const line = [p.settled_known, p.committed_undrawn, p.pledged, p.obligations_due, p.floor]
    .map((m: { minor: number }) => figure(m.minor)).join(' - ')
  await expect($(page, 'calculation')).toContainText(`${line} = ${figure(api.capacity.K_p.minor)}`)
  await $(page, 'evidence').locator('summary').click()
  await expect($(page, 'evidence')).toContainText('Not counted')
  await expect($(page, 'evidence')).toContainText('not itemised')
  expect(await sideways(page), 'Lending scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('L3: canonical edges; a node and an edge open their details', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  for (const f of api.facilities) {
    const edge = page.locator(`[data-test="map-edge"][data-edge="facility:${f.facility_id}"]`)
    await expect(edge, `facility ${f.facility_id} is not drawn`).toHaveCount(1)
    await expect(edge).toHaveAttribute('aria-label', /^financial edge/)
  }
  // line-b runs from the pool to Borrower B; nothing links the treasury to Borrower B
  const lineB = api.facilities.find((f: { facility_id: string }) => f.facility_id === 'line-b')
  if (lineB) {
    expect(lineB.borrower).toBe('borrower-b')
    await expect($(page, 'relations').locator('[data-edge="facility:line-b"]')).toContainText(/→ Bellfield Kitchens|→ borrower-b/)
  }
  for (const text of await $(page, 'relations').locator('li').allInnerTexts()) {
    expect(text, 'a Treasury–Borrower B relationship is drawn').not.toMatch(/Northwind Parts treasury → Bellfield|Bellfield Kitchens → Northwind Parts treasury/)
  }

  // a node, by keyboard
  const pool = page.locator(`[data-test="map-node"][data-node="${api.pool}"]`)
  await pool.focus()
  await page.keyboard.press('Enter')
  await expect(sheet(page)).toBeVisible()
  await expect(sheet(page).locator('[data-test="node-detail"]')).toContainText('Relationships')
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toBeHidden()
  await expect(pool).toBeFocused()

  // an edge, by pointer: a facility edge opens the facility
  const first = api.facilities[0]
  if (first) {
    await page.locator(`[data-test="map-edge"][data-edge="facility:${first.facility_id}"] line`).last().click({ force: true })
    await expect(sheet(page).locator('[data-test="facility-detail"]')).toContainText(first.facility_id)
    await $(page, 'sheet-close').click()
    await expect(sheet(page)).toBeHidden()
  }
  // the text list reaches every edge too
  const relation = $(page, 'relations').locator('button').last()
  await relation.click()
  await expect(sheet(page)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(relation).toBeFocused()
  expect(await sideways(page), 'Lending scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('L4–L5: freeze is Unknown not zero; facility detail and repayments', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/lending')).json()
  await open(page)

  const freeze = $(page, 'freeze')
  await expect(freeze).toContainText(api.capacity.authority === 'full' ? 'What-if' : 'Happening now')
  await expect(freeze).toContainText('Unknown')
  await expect(freeze).not.toContainText(/USD 0\.00/)
  const rehearse = $(page, 'rehearse-freeze')
  if (await rehearse.evaluate((el) => el.tagName === 'BUTTON')) {
    await expect(rehearse).toBeDisabled()
    await expect($(page, 'freeze-why')).toHaveText(/\w/)
  }

  for (const f of api.facilities) {
    const opener = $(page, `facility-${f.facility_id}`)
    expect((await opener.boundingBox())!.height).toBeGreaterThanOrEqual(43.5)
    await opener.click()
    const detail = sheet(page).locator('[data-test="facility-detail"]')
    for (const term of ['Parties', 'Status', 'Principal', 'Fee', 'Owed', 'Outstanding', 'Observed revenue']) {
      await expect(detail.locator(`dt:text-is("${term}")`)).toBeVisible()
    }
    await expect(detail).toContainText(`${f.principal.currency} ${figure(f.principal.minor)}`)
    await sheet(page).locator('[data-test="repayments"] summary').click()
    await expect(sheet(page).locator('[data-test="repayments"]')).toContainText('never from a forecast')
    await expect(sheet(page)).toContainText('not proof of disbursement')
    await page.keyboard.press('Escape')
    await expect(opener).toBeFocused()
  }
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
  await expect(page.locator('h1')).toHaveText('Decisions')
  expect(writes).toEqual([])
})

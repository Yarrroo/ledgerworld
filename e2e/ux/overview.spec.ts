/**
 * Overview, panels O1–O6 of prp/2026-10-29-ux-pass/HANDOFF.md, in motion at every width of
 * e2e/ux.config.ts: the context, the cash strip (a metric opens the inputs the API served, and
 * cash and spendable open their account row on Treasury), the cash outlook (focusable points,
 * View data), the next obligation (deep link to its Treasury row), the exposure preview and the
 * hypothetical scenario entry. Read-only.
 *
 * Two answers drive it: the app's own (whatever state its prepared demonstration left), and the
 * recorded baseline contracts/examples/c6_api/valid-overview-demo-baseline.json — the API's
 * answer on the demo world before any run, kept equal to it by tests/api — for the handoff's
 * exact numbers, with the app's own prepared run and scenario.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { settled, sideways } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const BASELINE = JSON.parse(readFileSync(join(__dirname, '../../contracts/examples/c6_api/valid-overview-demo-baseline.json'), 'utf-8')).instance

/** "USD 70,000.00", as the screen formats integer minor units. */
const usd = (minor: number) => `USD ${(minor / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}`
const metric = (m: { minor: number | null, status: string }) =>
  m.status === 'known' ? usd(m.minor!) : m.status === 'stale' ? `${usd(m.minor!)} · stale` : null

async function live (page: Page): Promise<any> {
  const reply = await page.request.get('/api/v1/overview')
  expect(reply.status(), 'GET /api/v1/overview').toBe(200)
  return reply.json()
}

/** Serve the recorded baseline for /api/v1/overview, with the app's own run and scenario. */
async function baseline (page: Page): Promise<any> {
  const own = await live(page)
  const body = { ...BASELINE, demo: own.demo, scenario: own.scenario }
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: body }))
  return body
}

async function open (page: Page): Promise<void> {
  await page.goto('/overview')
  await settled(page)
}

/** Every control a finger uses is at least 44 px tall. */
async function tall (page: Page, selector: string): Promise<void> {
  for (const el of await page.locator(selector).all()) {
    if (!(await el.isVisible())) continue
    expect((await el.boundingBox())!.height, `${selector} is shorter than 44 px`).toBeGreaterThanOrEqual(44)
  }
}

test('O1 context: the complete snapshot identity, currency, company and as of; read again', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  await open(page)
  const panel = $(page, 'context-panel')
  await expect($(page, 'context-snapshot')).toHaveText(body.snapshot_id)
  await expect($(page, 'context-currency')).toHaveText(body.cash.currency)
  await expect(panel).toContainText(body.company.name)
  await expect(panel).toContainText('Simulated provider')
  await expect($(page, 'context-time')).toHaveText(/^\d{4}-\d\d-\d\d \d\d:\d\d UTC · local /)
  const again = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/v1/overview')
  await $(page, 'context-refresh').click()
  await again
  await settled(page)
  await expect($(page, 'context-snapshot')).toHaveText(body.snapshot_id)
  await tall(page, '[data-test="context-refresh"]')
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('O2 cash strip: a metric opens its API inputs; cash and spendable open their Treasury row', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  const [account] = body.accounts
  await open(page)
  await expect($(page, 'settled').locator('.lw-figure')).toHaveText(metric(body.cash)!)
  await expect($(page, 'spendable').locator('.lw-figure')).toHaveText(metric(body.spendable)!)
  await expect($(page, 'coverage').locator('.lw-figure')).toHaveText(metric(body.coverage.headroom)!)
  await expect($(page, 'settled')).toContainText(/Known|Stale/)
  // the strip's figures are set in the heading serif, as the handoff draws them
  expect(await $(page, 'settled').locator('.lw-figure').evaluate((e) => getComputedStyle(e).fontFamily)).toMatch(/Source Serif 4/)
  await tall(page, '.lw-ov-metric__pick')

  for (const key of ['settled', 'spendable', 'next-due', 'coverage']) {
    const pick = $(page, `pick-${key}`)
    await pick.click()
    await expect(pick).toHaveAttribute('aria-expanded', 'true')
    await expect($(page, 'metric-inputs')).toBeVisible()
    await expect(page.locator('[aria-expanded="true"][data-test^="pick-"]')).toHaveCount(1)
  }
  await $(page, 'pick-coverage').click() // the selected one again closes it
  await expect($(page, 'metric-inputs')).toHaveCount(0)

  await $(page, 'pick-settled').click()
  await expect($(page, 'metric-inputs')).toContainText(`${account.id}: ${usd(account.buckets.settled.minor)} settled`)
  await expect($(page, 'metric-inputs')).toContainText(`API result: ${metric(body.cash)}`)
  await $(page, 'pick-spendable').click()
  const inputs = $(page, 'metric-inputs')
  await expect(inputs).toContainText('S = settled − reserved − pledged − pending out + pending in arrived by now')
  await expect(inputs).toContainText(`${(account.buckets.reserved.minor / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })} reserved`)
  await expect(inputs).toContainText(`= ${metric(account.spendable)}`)

  for (const key of ['settled', 'spendable']) {
    await open(page)
    await $(page, `pick-${key}`).click()
    await $(page, 'metric-link').first().click()
    await expect(page).toHaveURL(/\/treasury\?/)
    const url = new URL(page.url())
    expect(url.searchParams.get('focus')).toBe(`account:${account.id}`)
    expect(url.searchParams.get('snapshot')).toBe(body.snapshot_id)
    await settled(page)
    const row = page.locator(`[data-focus="account:${account.id}"]`)
    await expect(row).toBeFocused()
    await expect(row).toHaveClass(/lw-row--focus/)
    await expect(row).toBeInViewport()
    await expect($(page, 'snapshot-moved')).toHaveCount(0)
  }
  expect(writes).toEqual([])
})

test('O3 cash outlook: the API points, each focusable with its time, amount and event; View data', async ({ page, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  await open(page)
  const points = $(page, 'outlook-point')
  await expect(points).toHaveCount(body.outlook.length)
  for (const [n, p] of body.outlook.entries()) {
    await points.nth(n).focus()
    const tip = $(page, 'outlook-tip')
    await expect(tip).toContainText(metric(p.value)!)
    await expect(tip).toContainText(/t=\d+ h simulated · \d{4}-\d\d-\d\d \d\d:\d\d UTC/)
    for (const e of p.events) await expect(tip).toContainText(e.ref)
  }
  await page.keyboard.press('Tab') // focus leaves the last point: its tip goes
  await expect($(page, 'outlook-tip')).toHaveCount(0)
  // hover on a pointer, a tap on touch: the same tip
  if (info.project.use.hasTouch) await points.nth(1).tap()
  else await points.nth(1).hover()
  await expect($(page, 'outlook-tip')).toContainText(metric(body.outlook[1].value)!)

  const view = $(page, 'outlook-view-data')
  await expect(view).toHaveAttribute('aria-expanded', 'false')
  await view.click()
  await expect(view).toHaveAttribute('aria-expanded', 'true')
  const rows = $(page, 'outlook-table').locator('tbody tr')
  await expect(rows).toHaveCount(body.outlook.length)
  for (const [n, p] of body.outlook.entries()) await expect(rows.nth(n)).toContainText(metric(p.value)!)
  await tall(page, '[data-test="outlook-view-data"]')
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('baseline: the handoff numbers, a green minimum, and the next payroll opens its Treasury row', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await baseline(page)
  await open(page)
  // O2: settled 70k, spendable 20k, payroll 50k due t=40 h, headroom 10k
  await expect($(page, 'settled').locator('.lw-figure')).toHaveText('USD 70,000.00')
  await expect($(page, 'spendable').locator('.lw-figure')).toHaveText('USD 20,000.00')
  await expect($(page, 'next-due').locator('.lw-figure')).toHaveText('USD 50,000.00')
  await expect($(page, 'next-due-at')).toHaveText('due t=40 h')
  await expect($(page, 'coverage').locator('.lw-figure')).toHaveText('USD 10,000.00')
  await expect($(page, 'floor-status')).toHaveText(/Above your safety minimum/)
  await $(page, 'pick-spendable').click()
  await expect($(page, 'metric-inputs')).toContainText(
    'treasury/operating (USD): 70,000.00 settled − 50,000.00 reserved − 0.00 pledged = USD 20,000.00')

  // O3: P 70k, 90k, 40k, 55k, 55k at t = 0, 12, 40, 48, 72; the lowest, kept, is green
  await $(page, 'outlook-view-data').click()
  const rows = $(page, 'outlook-table').locator('tbody tr')
  const want = [[0, 70_000], [12, 90_000], [40, 40_000], [48, 55_000], [72, 55_000]]
  await expect(rows).toHaveCount(want.length)
  for (const [n, [h, dollars]] of want.entries()) {
    await expect(rows.nth(n).locator('td').first()).toHaveText(`t=${h} h`)
    await expect(rows.nth(n)).toContainText(usd(dollars * 100))
  }
  await expect(rows.nth(1)).toContainText('receivable-1 +USD 20,000.00')
  await expect(rows.nth(2)).toContainText('payroll-1 −USD 50,000.00')
  const low = page.locator('[data-test="outlook-point"].is-low')
  await expect(low).toHaveCount(1)
  await expect(low).toHaveClass(/is-ok/)
  await expect(low).toHaveAttribute('data-t', body.outlook[2].t)

  // O4: amount, exact deadline, reservation, state, funding account; Open Treasury → its row
  const next = $(page, 'next-obligation')
  await expect(next).toContainText('USD 50,000.00')
  await expect($(page, 'due')).toHaveText(/^due 2026-01-02 16:00 UTC · local .* · t=40 h from as of$/)
  await expect(next).toContainText('reserved · payroll-hold')
  await expect(next).toContainText('Open')
  await expect(next).toContainText('treasury/operating')
  await tall(page, '[data-test="open-treasury"]')
  // O6: the receivable the scenario delays, by its amount; nothing observed changes
  await expect($(page, 'scenario')).toContainText('What if the USD 20,000.00 receivable arrives late?')

  await $(page, 'open-treasury').click()
  await expect(page).toHaveURL(/\/treasury\?/)
  expect(new URL(page.url()).searchParams.get('focus')).toBe('obligation:payroll-1')
  await settled(page)
  const row = page.locator('[data-focus="obligation:payroll-1"]')
  await expect(row).toBeFocused()
  await expect(row).toHaveClass(/lw-row--focus/)
  await expect(row).toBeInViewport()
  expect(writes).toEqual([])
})

test('O5 exposure and O6 scenario: text relationships, the prepared run, a read-only preview', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  await open(page)
  const relations = $(page, 'relation')
  await expect(relations).toHaveCount(body.relations.length)
  for (const [n, r] of body.relations.entries()) {
    await expect(relations.nth(n)).toContainText(r.source.name)
    if (r.target) await expect(relations.nth(n)).toContainText(r.target.name)
    await expect(relations.nth(n)).toContainText(r.ref)
  }
  await expect($(page, 'exposure')).toContainText('not a payment')
  await expect($(page, 'lender-capacity')).toContainText(metric(body.lender_capacity)!)
  await expect($(page, 'explore-world')).toHaveAttribute('href', `/simulation?run_id=${body.demo.run_id}`)
  await tall(page, '[data-test="explore-world"], [data-test="lender-capacity"] a')

  await expect($(page, 'hypothetical')).toHaveText(/what-if/i)
  const before = await $(page, 'settled').textContent()
  const preview = $(page, 'preview-scenario')
  await preview.click()
  await expect(preview).toHaveAttribute('aria-expanded', 'true')
  const shown = $(page, 'scenario-preview')
  await expect(shown).toContainText(body.scenario.family)
  await expect(shown).toContainText(body.scenario.about)
  await expect(shown).toContainText(body.demo.run_id)
  if (body.scenario.params.delay_h) {
    await expect($(page, 'scenario-timing')).toContainText(`delayed ${body.scenario.params.delay_h} h`)
  }
  expect(await $(page, 'settled').textContent()).toBe(before) // the preview changes no observed figure
  await tall(page, '[data-test="preview-scenario"], a[data-test="open-simulation"]')
  expect(await sideways(page)).toBeLessThanOrEqual(0)

  await $(page, 'explore-world').click()
  await expect(page).toHaveURL(new RegExp(`/simulation\\?run_id=${body.demo.run_id}$`))
  await open(page)
  await page.locator('a[data-test="open-simulation"]').click()
  await expect(page).toHaveURL(new RegExp(`/simulation\\?run_id=${body.demo.run_id}$`))
  expect(writes).toEqual([])
})

test('no prepared run: the world and the scenario say why, nothing pretends to open', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = { ...BASELINE, upcoming_outflows: [], demo: { run_id: null, execution_id: null }, scenario: null }
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: body }))
  await open(page)
  await expect($(page, 'explore-why')).toHaveText('No demonstration run is prepared')
  await expect(page.locator('a[data-test="explore-world"]')).toHaveCount(0)
  await expect($(page, 'open-simulation')).toBeDisabled()
  await expect($(page, 'open-simulation-why')).toHaveText('No demonstration run is prepared')
  await expect($(page, 'preview-scenario')).toBeDisabled()
  await expect($(page, 'preview-why')).toBeVisible()
  // no obligation: a neutral empty state, not a zero
  await expect($(page, 'no-obligation')).toHaveText('No open obligation')
  await expect($(page, 'next-obligation')).not.toContainText('USD 0.00')
  await expect($(page, 'next-due').locator('.lw-figure')).toHaveText('None open')
  expect(writes).toEqual([])
})

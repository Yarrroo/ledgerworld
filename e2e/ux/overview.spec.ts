/**
 * Overview, panels O1–O6 of prp/2026-10-29-ux-pass/HANDOFF.md as rebuilt to mockup 01
 * (prp/2026-10-29-ux-pass/MATCH.md), in motion at every width of e2e/ux.config.ts: the context
 * line and its tooltip (read again when the tab comes back), the four figures with the inputs the
 * API served in their tooltips, the cash outlook (focusable points, each with its tooltip), the
 * next obligation (deep link to its Treasury row), the world exposure and the hypothetical
 * scenario entry. Read-only.
 *
 * Two answers drive it: the app's own (whatever state its prepared demonstration left), and the
 * recorded baseline contracts/examples/c6_api/valid-overview-demo-baseline.json — the API's
 * answer on the demo world before any run, kept equal to it by tests/api — for the handoff's
 * exact numbers, with the app's own prepared run and scenario.
 *
 * Removed with the redesign (MATCH.md items 2, 4): the context panel's Refresh (a screen reads
 * again on visibilitychange), the strip's click-to-open metric inputs and their Treasury links
 * (the inputs are each figure's tooltip now), and the outlook's View data table (each point's
 * tooltip carries its time, amount and event).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { fmt } from './copy'
import { settled, sideways } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const bubble = (tip: Locator) => tip.locator(':scope > [role="tooltip"]')
const BASELINE = JSON.parse(readFileSync(join(__dirname, '../../contracts/examples/c6_api/valid-overview-demo-baseline.json'), 'utf-8')).instance

/** "10 days", "1 day", "36 hours": a whole-hour span as the screen says it. */
const words = (h: number) => (h && h % 24 === 0 ? `${h / 24} day${h === 24 ? '' : 's'}` : `${h} hour${h === 1 ? '' : 's'}`)
const metric = (m: { minor: number | null, currency: string, status: string }) =>
  m.status === 'known' ? fmt(m) : m.status === 'stale' ? `${fmt(m)} · stale` : null
const plain = (name: string) => name.replace(/\s*\(synthetic\)\s*$/i, '')

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

/** A tooltip opens on keyboard focus, holds `facts`, and Escape closes it. */
async function focusTip (page: Page, tip: Locator, facts: (string | RegExp)[]): Promise<void> {
  const body = bubble(tip)
  await expect(body).toBeHidden()
  await tip.focus()
  await expect(body).toBeVisible()
  for (const fact of facts) await expect(body).toContainText(fact)
  await page.keyboard.press('Escape')
  await expect(body).toBeHidden()
}

test('O1 context: snapshot, currency, company and as of; read again when the tab comes back', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  await open(page)
  await expect($(page, 'context-line')).toHaveText(new RegExp(`^Snapshot ${body.snapshot_id} · ${body.cash.currency} · `))
  await expect($(page, 'company')).toContainText(plain(body.company.name).replace(/\s+treasury$/i, ''))
  await expect($(page, 'mode')).toHaveText(/^Simulated provider/)
  // the provider, the full time and the snapshot are in the context tooltip
  const facts = bubble($(page, 'how-context-bar'))
  await expect($(page, 'context-bar-snapshot')).toHaveText(body.snapshot_id)
  await expect(facts).toContainText('Simulated provider')
  await expect(facts).toContainText(/\d{4}-\d\d-\d\d \d\d:\d\d UTC · local /)
  // no Refresh button: the screen reads again, quietly, when its tab is visible again
  const again = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/v1/overview')
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await again
  await settled(page)
  await expect($(page, 'context-bar-snapshot')).toHaveText(body.snapshot_id)
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('O2 cash strip: the API figures, each with its inputs in a focusable tooltip', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  const [account] = body.accounts
  await open(page)
  await expect($(page, 'settled').locator('.lw-figure')).toHaveText(metric(body.cash)!)
  await expect($(page, 'spendable').locator('.lw-figure')).toHaveText(metric(body.spendable)!)
  await expect($(page, 'coverage').locator('.lw-figure')).toHaveText(metric(body.coverage.headroom)!)
  // the strip's figures are set in the heading serif, as the handoff draws them
  expect(await $(page, 'settled').locator('.lw-figure').evaluate((e) => getComputedStyle(e).fontFamily)).toMatch(/Source Serif 4/)

  await focusTip(page, $(page, 'tip-settled'), [`${fmt(account.buckets.settled)} settled`, /Known|Stale/])
  await focusTip(page, $(page, 'tip-spendable'), [
    'Settled − reserved − pledged − pending out + pending in arrived by now',
    `${(account.buckets.reserved.minor / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })} reserved`,
    `= ${metric(account.spendable)}`
  ])
  await focusTip(page, $(page, 'tip-next-due'), [/earliest open obligation|Nothing you owe/])
  await focusTip(page, $(page, 'tip-coverage'), ['reserve floor'])
  expect(writes).toEqual([])
})

test('O3 cash outlook: the API points, each focusable with its time, amount and event', async ({ page, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  await open(page)
  const points = $(page, 'outlook-point')
  const tips = page.locator('.lw-outlook__pt')
  await expect(points).toHaveCount(body.outlook.length)
  for (const [n, p] of body.outlook.entries()) {
    await points.nth(n).focus()
    const tip = bubble(tips.nth(n))
    await expect(tip).toBeVisible()
    await expect(tip).toContainText(metric(p.value)!)
    await expect(tip).toContainText(/ · h\d+ \((now|in \d+ (hours?|days?))\)/)
    await expect(tip).toContainText(/\d{4}-\d\d-\d\d \d\d:\d\d UTC/)
    for (const e of p.events) await expect(tip).toContainText(e.ref)
    await expect(points.nth(n)).toHaveAttribute('aria-describedby', (await tip.getAttribute('id'))!)
  }
  await page.keyboard.press('Tab') // focus leaves the last point: its tip goes
  await expect(page.locator('.lw-outlook__pt [role="tooltip"]:visible')).toHaveCount(0)
  // hover on a pointer, a tap on touch: the same tip
  if (info.project.use.hasTouch) await points.nth(1).tap()
  else await points.nth(1).hover()
  await expect(bubble(tips.nth(1))).toBeVisible()
  await expect(bubble(tips.nth(1))).toContainText(metric(body.outlook[1].value)!)
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('baseline: the handoff numbers, a green minimum, and the next payroll opens its Treasury row', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await baseline(page)
  await open(page)
  // O2: settled 70k, spendable 20k, payroll 50k due in 40 hours, headroom 10k
  await expect($(page, 'settled').locator('.lw-figure')).toHaveText('$70,000')
  await expect($(page, 'spendable').locator('.lw-figure')).toHaveText('$20,000')
  await expect($(page, 'next-due').locator('.lw-figure')).toHaveText('$50,000')
  await expect($(page, 'next-due-at')).toHaveText('· in 40h')
  await expect($(page, 'coverage').locator('.lw-figure')).toHaveText('$10,000')
  await expect($(page, 'floor-status')).toHaveText(/Above your safety minimum/)
  await expect(bubble($(page, 'tip-spendable'))).toContainText('70,000.00 settled − 50,000.00 reserved − 0.00 pledged = $20,000')

  // O3: P 70k, 90k, 40k, 55k, 55k at t = 0, 12, 40, 48, 72; the lowest, kept, is green
  const tips = page.locator('[data-test="outlook-tip"]')
  const want = ['$70,000 · h0 (now)', '$90,000 · h12 (in 12 hours)', '$40,000 · h40 (in 40 hours)', '$55,000 · h48 (in 2 days)', '$55,000 · h72 (in 3 days)']
  await expect(tips).toHaveCount(want.length)
  for (const [n, text] of want.entries()) await expect(tips.nth(n)).toContainText(text)
  await expect(tips.nth(1)).toContainText('receivable-1 +$20,000')
  await expect(tips.nth(2)).toContainText('payroll-1 -$50,000')
  const low = $(page, 'outlook-point').nth(2)
  await expect(low).toHaveAttribute('aria-label', /Lowest point\.$/)
  await expect(low).toHaveAttribute('data-t', body.outlook[2].t)
  await expect(page.locator('.lw-outlook__dot.is-ok')).toHaveCount(1)
  await expect($(page, 'outlook-low-label')).toHaveClass(/is-ok/)
  await expect($(page, 'outlook-low-label')).toContainText('$40,000 · h40')

  // O4: amount, exact deadline, reservation, funding account; Open Treasury → its row
  const next = $(page, 'next-obligation')
  await expect($(page, 'next-amount')).toHaveText('$50,000')
  await expect($(page, 'due')).toHaveText(/^due 2026-01-02 16:00 UTC · local /)
  await expect(next).toContainText(/Due in\s*in 40h/)
  await expect(next).toContainText(/Reserved\s*Yes/)
  await expect(next).toContainText('Held by reservation payroll-hold')
  await expect($(page, 'paid-from')).toHaveText('Operating account · USD')
  await expect(next).toContainText('Paid from Operating account · USD')
  await tall(page, '[data-test="open-treasury"]')
  // O6: the receivable the scenario delays, by its amount; nothing observed changes
  await expect($(page, 'scenario').locator('h2')).toHaveText('What if your $20,000 receivable arrives late?')

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

test('O5 exposure and O6 scenario: the parties the API relates, the prepared run, a read-only preview', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page)
  await open(page)
  const me = body.company?.entity_id ?? 'treasury'
  const world = $(page, 'relations')
  const parties = new Set<string>()
  for (const r of body.relations) {
    if (r.source.entity_id === me) {
      if (r.target) parties.add(r.target.entity_id)
      await expect(world).toContainText(r.ref.replace(/_/g, ' '))
    } else {
      parties.add(r.source.entity_id)
      await expect(world).toContainText(plain(r.source.name))
    }
    if (r.target && r.target.entity_id !== me) await expect(world).toContainText(plain(r.target.name))
  }
  await expect($(page, 'relation')).toHaveCount(Math.min(4, parties.size))
  await expect($(page, 'treasury-node')).toContainText(`${metric(body.cash)} settled`)
  await expect($(page, 'exposure')).toContainText('not a payment')
  if (metric(body.lender_capacity)) await expect(world).toContainText(`Can lend ${metric(body.lender_capacity)}`)
  await expect($(page, 'explore-world')).toHaveAttribute('href', `/simulation?run_id=${body.demo.run_id}`)
  await tall(page, '[data-test="explore-world"]')

  await expect($(page, 'hypothetical')).toHaveText(/hypothetical/i)
  const before = await $(page, 'settled').textContent()
  const preview = $(page, 'preview-scenario')
  await preview.click()
  await expect(preview).toHaveAttribute('aria-expanded', 'true')
  const shown = $(page, 'scenario-preview')
  await expect(shown).toContainText(body.scenario.family)
  await expect(shown).toContainText(body.scenario.about)
  if (body.scenario.params.delay_h) {
    await expect($(page, 'scenario-timing')).toContainText(`delayed ${words(body.scenario.params.delay_h)}`)
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

test('no prepared run: the world and the scenario say why, nothing pretends to open', async ({ page, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const body = { ...BASELINE, upcoming_outflows: [], demo: { run_id: null, execution_id: null }, scenario: null }
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: body }))
  await open(page)
  await expect(bubble($(page, 'explore-why'))).toHaveText('No demonstration run is prepared')
  await expect(page.locator('a[data-test="explore-world"]')).toHaveCount(0)
  await expect($(page, 'open-simulation')).toBeDisabled()
  await expect(bubble($(page, 'open-simulation-why'))).toHaveText('No demonstration run is prepared')
  await expect($(page, 'preview-scenario')).toBeDisabled()
  await expect(bubble($(page, 'preview-why'))).toHaveText(/No prepared run/)
  // the why is shown where the reader looks: on hover over (or a tap on) the disabled action
  if (info.project.use.hasTouch) await $(page, 'explore-why').tap()
  else await $(page, 'explore-why').hover()
  await expect(bubble($(page, 'explore-why'))).toBeVisible()
  // no obligation: a neutral empty state, not a zero
  await expect($(page, 'no-obligation')).toHaveText('No open obligation')
  await expect($(page, 'next-obligation')).not.toContainText('$0')
  await expect($(page, 'next-due').locator('.lw-figure')).toHaveText('None open')
  expect(writes).toEqual([])
})

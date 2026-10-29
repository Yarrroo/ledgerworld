/**
 * Loading, empty and failure states on all six screens (prp/2026-10-29-ux-pass/HANDOFF.md,
 * "Loading, empty & failure states"), at every width of e2e/ux.config.ts. Each state is forced
 * through a mocked API (page.route over the app's own answers) and checked by its text, its icon
 * and the reason a dependent action is disabled: skeletons and a polite Loading in place of
 * amounts; no prepared run explained inline, with no chart; a known zero distinct from Unknown
 * and Not assessed; a stale band with as of; a read error with Retry, keeping the last loaded
 * figures labelled not current; Operator access inline near the writes, with Forget access and
 * nothing kept on reload. Read-only: every write is aborted and the check fails on one.
 */
import { expect, test, type Page, type Route as Fulfil } from '@playwright/test'
import { readOnly } from '../guard'
import { ROUTES, demoRunId, settled, sideways, urlOf } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const API = '**/api/v1/**'
const UTC = /\d{4}-\d\d-\d\d \d\d:\d\d UTC/

/** The drawer is open on a phone, so the six links are on screen. */
async function showNav (page: Page): Promise<void> {
  if (await $(page, 'menu').isVisible()) await $(page, 'menu').click()
}

/** The app's own answer for an /api/v1 path. */
async function live (page: Page, path: string): Promise<any> {
  const reply = await page.request.get(`/api/v1${path}`)
  expect(reply.status(), `GET /api/v1${path}`).toBe(200)
  return reply.json()
}

/** Serve ``body`` for one /api/v1 path. */
const serve = (page: Page, path: string, body: unknown) =>
  page.route(`**/api/v1${path}`, (route) => route.fulfill({ json: body }))

const down = (route: Fulfil) => route.fulfill({
  status: 503, json: { error: { code: 'unavailable', detail: 'the API is down for this check' } }
})

const metric = (minor: number | null, currency: string, status: string, asOf: string | null = null) =>
  ({ minor, currency, status, as_of: asOf })

test('loading: skeletons and a polite Loading in place of amounts; navigation still works', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  await page.route(API, () => {}) // no answer arrives
  for (const route of ROUTES) {
    await page.goto(urlOf(route, runId))
    await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'true')
    await expect(page.locator('h1')).toHaveText(route.title)
    const loading = $(page, 'loading')
    await expect(loading).toHaveText(`Loading ${route.title}…`)
    await expect(loading).toHaveAttribute('role', 'status')
    await expect($(page, 'skeleton').locator('.lw-skeleton')).toHaveCount(8)
    await expect(page.locator('main .lw-figure')).toHaveCount(0)
    await expect(page.locator('main')).not.toContainText(/USD|\d+[.,]\d\d/)
    await expect($(page, 'refresh')).toBeDisabled()
    await expect($(page, 'mode')).toHaveText('Bank connection not loaded')
    expect(await sideways(page), `${route.path} scrolls sideways while loading`).toBeLessThanOrEqual(0)
  }
  // navigation is not held by a read in flight
  await showNav(page)
  await page.locator('nav.lw-nav').getByRole('link', { name: 'Overview', exact: true }).click()
  await expect(page).toHaveURL(/\/overview$/)
  await expect(page.locator('h1')).toHaveText('Overview')
  expect(writes).toEqual([])
})

test('no prepared run: every screen explains the absence, nothing pretends to open', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const overview = { ...(await live(page, '/overview')), demo: { run_id: null, execution_id: null }, scenario: null }
  await serve(page, '/overview', overview)

  await page.goto('/overview')
  await settled(page)
  await expect($(page, 'explore-why')).toHaveText('No demonstration run is prepared')
  await expect($(page, 'open-simulation')).toBeDisabled()
  await expect($(page, 'preview-scenario')).toBeDisabled()

  await page.goto('/treasury')
  await settled(page)
  await expect($(page, 'rehearse')).toBeDisabled()
  await expect($(page, 'rehearse-why')).toContainText('No demonstration run is prepared')

  await page.goto('/lending')
  await settled(page)
  await expect($(page, 'rehearse-freeze')).toBeDisabled()
  await expect($(page, 'freeze-why')).toHaveText(/\w/)

  for (const route of ROUTES.filter((r) => r.run)) {
    await page.goto(route.path)
    await settled(page)
    await expect(page.locator('h1')).toHaveText(route.title)
    const empty = $(page, 'empty')
    await expect(empty.locator('h2')).toHaveText('No prepared run')
    await expect(empty).toContainText('No demonstration run is prepared')
    await expect(empty).toContainText(`${route.title} reads a prepared run`)
    await expect($(page, 'error')).toHaveCount(0) // an absence, not a failure
    await expect(page.locator('main [data-panel], main svg, main canvas')).toHaveCount(0) // no fabricated chart
    await expect(page.locator('main')).not.toContainText(/USD|\d+[.,]\d\d/)
    await expect($(page, 'refresh')).toHaveText('Refresh')
    expect(await sideways(page), `${route.path} scrolls sideways`).toBeLessThanOrEqual(0)
  }
  await $(page, 'empty-overview').click()
  await expect(page).toHaveURL(/\/overview$/)
  expect(writes).toEqual([])
})

test('Overview: known zero, Unknown, Not assessed and Stale stay distinct, with a stale band', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page, '/overview')
  const c = body.cash.currency
  const stale = 'treasury/reserve-check'
  await serve(page, '/overview', {
    ...body,
    cash: metric(0, c, 'known', body.as_of),
    spendable: metric(null, c, 'unknown'),
    coverage: { ...body.coverage, headroom: metric(null, c, 'unassessed') },
    lender_capacity: metric(12345600, c, 'stale', body.as_of),
    completeness: { status: 'partial', missing: [stale], accounts: [{ account_id: stale, status: 'stale', as_of: body.as_of }] }
  })
  await page.goto('/overview')
  await settled(page)

  const line = (key: string) => $(page, key).locator('.lw-ov-metric__pick > .lw-time')
  await expect($(page, 'settled').locator('.lw-figure')).toHaveText(`${c} 0.00`) // a known zero
  await expect(line('settled')).toHaveText(new RegExp(`^● Known as of ${UTC.source}$`))
  await expect($(page, 'spendable').locator('.lw-figure')).toHaveText('Unknown')
  await expect(line('spendable')).toHaveText('? Unknown')
  await expect($(page, 'coverage').locator('.lw-figure')).toHaveText('Not assessed')
  await expect($(page, 'floor-status')).toHaveText(/–\s*Not assessed/)
  await expect($(page, 'coverage')).not.toContainText(/Floor kept|Floor breached|Above your safety minimum|Below your safety minimum/)
  await expect($(page, 'lender-capacity')).toContainText(`${c} 123,456.00 · stale`)

  const band = $(page, 'stale-band')
  await expect(band).toContainText('◷ Stale')
  await expect(band).toContainText('Treasury reserve check account') // the account by name; its id is in How we know
  await expect(band).toContainText(UTC)
  await expect($(page, 'partial')).toContainText('Treasury reserve check account')
  expect(await sideways(page), 'Overview scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('Treasury: S known at zero, stale with its as of, Unknown; the floor Not assessed', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page, '/treasury')
  const asOf = body.as_of
  const cases = [
    { status: 'known', minor: 0, figure: (c: string) => `${c} 0.00`, line: /^● Known as of / },
    { status: 'stale', minor: 500000, figure: (c: string) => `${c} 5,000.00 · stale`, line: /^◷ Stale as of / },
    { status: 'unknown', minor: null, figure: () => 'Unknown', line: /^\? Unknown$/ }
  ]
  for (const k of cases) {
    await page.unroute('**/api/v1/treasury')
    await serve(page, '/treasury', {
      ...body,
      accounts: body.accounts.map((a: any) => ({
        ...a, floor: null, spendable: metric(k.minor, a.currency, k.status, k.status === 'unknown' ? null : asOf)
      }))
    })
    await page.goto('/treasury')
    await settled(page)
    const id = await page.locator('.lw-tre').getAttribute('data-account')
    const currency = body.accounts.find((a: any) => a.id === id).currency
    await expect($(page, 'spendable').locator('.lw-figure')).toHaveText(k.figure(currency))
    await expect($(page, 'spendable-status')).toHaveText(k.line)
    await expect($(page, 'floor-status')).toHaveText(/–\s*Not assessed/)
    await expect($(page, 'coverage')).not.toContainText(/Floor kept|Floor breached|Above your safety minimum|Below your safety minimum/)
    if (k.status === 'stale') {
      await expect($(page, 'stale-band')).toContainText('◷ Stale')
      await expect($(page, 'stale-band')).toContainText(`${id!.split('/')[0].replace(/^./, (c) => c.toUpperCase())} ${id!.split('/')[1]} account`)
      await expect($(page, 'stale-band')).toContainText(UTC)
    } else {
      await expect($(page, 'stale-band')).toHaveCount(0)
    }
  }
  expect(writes).toEqual([])
})

test('Lending: K_p known at zero; a stale account is banded and not counted', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await live(page, '/lending')
  const c = body.capacity.K_p.currency
  const venue = 'lender/stale-venue'
  await serve(page, '/lending', {
    ...body,
    capacity: {
      ...body.capacity,
      K_p: metric(0, c, 'known', body.as_of),
      unobserved: [{ account_id: venue, status: 'stale', as_of: body.as_of }]
    }
  })
  await page.goto('/lending')
  await settled(page)
  await expect($(page, 'capacity-value')).toHaveText(new RegExp(`^${c} 0\\.00`))
  await expect($(page, 'capacity-status')).toHaveText(/^● Known as of /)
  await expect($(page, 'not-current')).toContainText('Lender stale venue account')
  await expect($(page, 'not-current')).toContainText('◷')
  await expect($(page, 'evidence')).toContainText(venue)
  await expect($(page, 'stale-band')).toContainText('◷ Stale')
  await expect($(page, 'stale-band')).toContainText('Lender stale venue account')
  expect(writes).toEqual([])
})

test('read error: Could not load with Retry; a failed refresh keeps the last values, not current', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  for (const route of ROUTES) {
    // the first read fails: no figure, the reason and Retry
    await page.route(API, down)
    await page.goto(urlOf(route, runId))
    await settled(page)
    const error = $(page, 'error')
    await expect(error).toHaveAttribute('role', 'alert')
    await expect(error).toContainText('! Could not load.')
    await expect(error).toContainText('the API is down for this check')
    await expect($(page, 'retry')).toBeEnabled()
    await expect($(page, 'refresh')).toHaveText('Retry')
    await expect(page.locator('main [data-panel]')).toHaveCount(0)
    await page.unroute(API, down)
    await $(page, 'retry').click()
    await settled(page)
    await expect(error).toHaveCount(0)
    await expect(page.locator('main [data-panel]').first()).toBeVisible()
    const panels = await page.locator('main [data-panel]').count()

    // a refresh fails: the last loaded body stays, labelled not current
    await page.route(API, down)
    await $(page, 'refresh').click()
    await expect(error).toContainText('! Could not refresh. Last loaded, not current.')
    await expect(page.locator('main [data-panel]')).toHaveCount(panels)
    await expect($(page, 'retry')).toBeEnabled()
    await page.unroute(API, down)
    await $(page, 'retry').click()
    await settled(page)
    await expect(error).toHaveCount(0)
  }
  expect(writes).toEqual([])
})

test('permission: Operator access inline near the writes, password-style, Forget access, gone on reload', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)

  // Live simulation: fork and interview take operator access; reading needs none
  await page.goto(`/simulation?run_id=${runId}`)
  await settled(page)
  const token = $(page, 'token')
  await expect(token).toHaveAttribute('type', 'password')
  await expect(page.locator('label', { has: token })).toContainText('Operator access')
  await expect($(page, 'fork')).toBeDisabled()
  await expect($(page, 'fork-why')).toHaveText(/\w/)
  await expect($(page, 'forget')).toHaveCount(0)
  await token.fill('not-a-real-token')
  await expect($(page, 'forget')).toHaveText('Forget access')
  await $(page, 'forget').click()
  await expect(token).toHaveValue('')
  await expect($(page, 'forget')).toHaveCount(0)
  await token.fill('not-a-real-token')
  await page.reload()
  await settled(page)
  await expect($(page, 'token')).toHaveValue('') // never retained

  // Execution: the approval asks for operator access in its review, not a login wall
  await page.goto(`/execution?run_id=${runId}`)
  await settled(page)
  await expect($(page, 'authority')).toContainText('Reading needs no operator access')
  const review = $(page, 'review-plan')
  test.skip(await review.isDisabled(), `the prepared run offers no review: ${await $(page, 'review-why').textContent()}`)
  await expect($(page, 'review-why')).toHaveText('Operator access required')
  await review.click()
  const field = page.locator('#operator-token')
  await expect(field).toHaveAttribute('type', 'password')
  await expect(page.locator('label[for="operator-token"]')).toContainText('Operator access')
  await expect($(page, 'confirm')).toBeDisabled()
  await expect($(page, 'confirm-why')).toHaveText('Operator access required')
  await field.fill('not-a-real-token')
  await expect($(page, 'confirm-why')).not.toHaveText('Operator access required')
  await page.keyboard.press('Escape')
  await expect($(page, 'forget-token')).toHaveText('Forget access')
  await $(page, 'forget-token').click()
  await expect($(page, 'forget-token')).toHaveCount(0)
  await expect($(page, 'review-why')).toHaveText('Operator access required')
  expect(writes).toEqual([])
})

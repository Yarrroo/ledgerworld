/**
 * Copy pass 3 (prp/2026-10-29-ux-pass/COPY.md) on the shared shell and the times and accounts every
 * screen shows, at every width of e2e/ux.config.ts: the context bar reads in plain words
 * ("Simulated bank connection · Scripted agents · As of 1 Jan, 00:00 UTC") with the provider mode,
 * model, full time, snapshot and run one click down in its How we know; a time ahead reads
 * "in 40 hours", never "t=40 h"; an account reads by name ("Operating account · USD"), its id in
 * How we know. Every data-test hook stays. Read-only.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { $, folded, open, read } from './copy'
import { ROUTES, demoRunId, settled, urlOf } from './routes'

const BASELINE = JSON.parse(readFileSync(join(__dirname, '../../contracts/examples/c6_api/valid-overview-demo-baseline.json'), 'utf-8')).instance

/** What the bar must not show on its face: ids, raw mode and model names, the old hour notation. */
const MECHANICS = /snapshot|Synthetic|Simulated provider|Model |\blocal\b|t=\d/

/** The rendered text of an element: a closed disclosure's body is not part of it. */
const shown = (page: Page, selector: string) => page.locator(selector).first().evaluate((el) => (el as HTMLElement).innerText)

test('the context bar: plain words on every screen, the mechanics in its How we know', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  for (const route of ROUTES) {
    const snapshot = route.run ? null : (await read(page, route.path)).snapshot_id as string
    await page.goto(urlOf(route, runId))
    await settled(page)
    await expect($(page, 'mode')).toHaveText('Simulated bank connection')
    await expect($(page, 'model')).toHaveText('Scripted agents')
    await expect($(page, 'context-as-of')).toHaveText(/^As of \d{1,2} [A-Z][a-z]{2}, \d\d:\d\d UTC$/)
    await expect($(page, 'refresh')).toBeVisible()
    const face = await shown(page, '.lw-context__bar')
    expect(face, `${route.path}: the bar shows mechanics: ${face}`).not.toMatch(MECHANICS)
    if (snapshot) expect(face).not.toContain(snapshot)
    expect(face).not.toContain(runId)
    const facts = ['Simulated provider', 'scripted', 'UTC · local']
    if (snapshot) facts.push(snapshot)
    if (route.run) facts.push(runId)
    await folded(page, 'how-context-bar', facts)
    await expect($(page, 'source')).not.toBeEmpty()
  }
  expect(writes).toEqual([])
})

test('Overview: due in 40 hours, paid from the operating account, a day-and-time as of', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const own = await read(page, '/overview')
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: { ...BASELINE, demo: own.demo, scenario: own.scenario } }))
  await open(page, '/overview')
  await expect($(page, 'context-as-of')).toHaveText('As of 1 Jan, 00:00 UTC')
  await expect($(page, 'next-due-at')).toHaveText('due in 40 hours')
  await expect($(page, 'due')).toHaveText(/ · in 40 hours$/)
  await expect($(page, 'paid-from')).toHaveText('Operating account · USD')
  await folded(page, 'how-next', ['treasury/operating'])
  await folded(page, 'how-context-bar', [BASELINE.snapshot_id, '2026-01-01 00:00 UTC'])
  const main = await shown(page, 'main.lw-main')
  expect(main).not.toMatch(/t=\d/)
  expect(main).not.toContain('treasury/operating')
  expect(writes).toEqual([])
})

test('Treasury: accounts by name, times in words, the id one click down', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await read(page, '/treasury')
  const account = body.accounts.find((a: any) => a.id.endsWith('/operating')) ?? body.accounts[0]
  await open(page, '/treasury')
  const choice = $(page, `account-${account.id}`)
  await expect(choice.locator('.lw-tre__choice-id')).toHaveText('Operating account')
  await expect(choice).toContainText(account.currency)
  await expect($(page, 'spendable').locator('.lw-tile__label')).toHaveText(`Operating account · ${account.currency}`)
  for (const point of await $(page, 'timeline-point').all()) {
    await expect(point).toHaveText(/^(now|in \d+ (hours?|days?)|\d+ (hours?|days?) ago)$/)
  }
  await folded(page, 'how-spendable', [account.id])
  const main = await shown(page, 'main.lw-main')
  expect(main).not.toMatch(/t=\d/)
  expect(main).not.toContain(account.id)
  expect(writes).toEqual([])
})

test('a stale account is named in the band, never by its id', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await read(page, '/lending')
  const venue = 'lender/stale-venue'
  await page.route('**/api/v1/lending', (route) => route.fulfill({
    json: { ...body, capacity: { ...body.capacity, unobserved: [{ account_id: venue, status: 'stale', as_of: body.as_of }] } }
  }))
  await page.goto('/lending')
  await settled(page)
  await expect($(page, 'stale-band')).toContainText('Lender stale venue account')
  await expect($(page, 'not-current')).toContainText('Lender stale venue account')
  expect(await shown(page, 'main.lw-main')).not.toContain(venue)
  await expect($(page, 'evidence')).toContainText(venue)
  expect(writes).toEqual([])
})

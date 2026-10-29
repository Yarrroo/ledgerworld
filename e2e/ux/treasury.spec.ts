/**
 * Treasury in motion (prp/2026-10-29-ux-pass/HANDOFF.md T1–T6, laid out as mockup 02), at every
 * width of e2e/ux.config.ts: the account (a selector only when there are several) drives the
 * figures, the buckets, the spendable calculation and the cash path together; a bucket names its
 * inputs and source time in its tooltip; an obligation or arrival row opens its details (a
 * full-width sheet on a phone) and gives focus back; the chart draws the API points and each
 * point's tooltip names P at that instant; Rehearse a cash shock carries the account and snapshot
 * to the prepared run. Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { crumb, demoRunId, settled, sideways } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)

async function open (page: Page): Promise<void> {
  await page.goto('/treasury')
  await settled(page)
  await expect(crumb(page)).toHaveText('Treasury')
  await expect($(page, 'error')).toHaveCount(0)
}

async function atLeast44 (page: Page, selector: string): Promise<void> {
  for (const el of await page.locator(selector).all()) {
    if (!(await el.isVisible())) continue
    const box = (await el.boundingBox())!
    expect(box.height, `${selector} is under 44 px tall`).toBeGreaterThanOrEqual(43.5)
  }
}

test('T1–T3: the selected account drives figures, buckets, S and its calculation together', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/treasury')).json()
  await open(page)

  // one account needs no choice; several show a selector, one checked
  const several = api.accounts.length > 1
  await expect($(page, 'account-selector')).toHaveCount(several ? 1 : 0)
  if (several) {
    await expect($(page, 'account-selector').getByRole('radio')).toHaveCount(api.accounts.length)
    await expect($(page, 'account-selector').getByRole('radio', { checked: true })).toHaveCount(1)
    await atLeast44(page, '.lw-tre__choice')
  }

  for (const account of api.accounts) {
    if (several) {
      await $(page, `account-${account.id}`).click()
      await expect($(page, `account-${account.id}`).getByRole('radio')).toBeChecked()
    }
    await expect(page.locator('.lw-tre')).toHaveAttribute('data-account', account.id)
    // S is the API's, in the account's own currency ("$70,000"); the account id is in its tooltip
    await expect($(page, 'spendable')).toContainText(account.id)
    const sign = ({ USD: '\\$', EUR: '€', GBP: '£' } as Record<string, string>)[account.currency] ?? `${account.currency} `
    await expect($(page, 'spendable').locator('.lw-figure')).toHaveText(new RegExp(`^-?${sign}\\d|^Unknown$`))
    await $(page, 'spend-calc').locator('summary').click()
    await expect($(page, 'spend-calculation')).toContainText(`S(now) in ${account.currency}`)
    await expect($(page, 'spend-calculation')).toContainText('(API)')
    await $(page, 'spend-calc').locator('summary').click()
    // four buckets; settled names its inputs, account and source time in its tooltip
    await expect($(page, 'buckets').locator('tbody tr')).toHaveCount(4)
    const inputs = $(page, 'bucket-settled').locator('[data-test="bucket-inputs"]')
    await expect(inputs).toContainText(account.id)
    await expect(inputs).toContainText(/\d{4}-\d\d-\d\d \d\d:\d\d UTC/)
    if (account.buckets.settled === null) await expect($(page, 'bucket-settled')).toContainText('Unknown')
    // pending inflows are expected, not settled
    for (const f of account.buckets.pending_in) {
      await expect($(page, 'obligations').locator(`tr[data-row="${f.flow_id}"] .lw-dot`)).toHaveText('Expected')
    }
    // the cash path follows: one chart point per API point of this account
    await expect($(page, 'outlook-point')).toHaveCount(account.projected.length)
  }
  expect(await sideways(page), 'Treasury scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('T4: a row opens its details, a sheet on the phone, and gives focus back', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/treasury')).json()
  await open(page)
  const account = await page.locator('.lw-tre').getAttribute('data-account')
  const owed = api.obligations.filter((o: { account: string }) => o.account === account)
  const a = api.accounts.find((x: { id: string }) => x.id === account)
  const flows = a.buckets.pending_in.length + a.buckets.pending_out.length
  const rows = $(page, 'obligations').locator('tbody tr[data-row]')
  await expect(rows).toHaveCount(owed.length + flows)
  test.skip(owed.length + flows === 0, 'this snapshot has no obligation or pending flow')
  await atLeast44(page, '.lw-tre__open')

  const opener = rows.first().locator('button')
  const id = await rows.first().getAttribute('data-row')
  await opener.click()
  const sheet = $(page, 'row-detail')
  await expect(sheet).toBeVisible()
  await expect(sheet.locator('h2')).toContainText(id!)
  for (const term of ['Amount', 'Reservation', 'Source', 'Current state']) {
    await expect(sheet.locator(`dt:text-is("${term}")`)).toBeVisible()
  }
  await expect(sheet.locator('dt').filter({ hasText: /^(Deadline|Expected)$/ })).toBeVisible()
  await expect(sheet).toContainText('makes no payment')
  if (info.project.use.viewport!.width < 768) {
    const box = (await sheet.boundingBox())!
    expect(box.width, 'the phone sheet is not full width').toBeGreaterThanOrEqual(info.project.use.viewport!.width - 1)
    expect(box.height, 'the phone sheet is not full height').toBeGreaterThanOrEqual(info.project.use.viewport!.height - 1)
  }
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  await expect(opener).toBeFocused()
  // and Close does the same
  await opener.click()
  await $(page, 'sheet-close').click()
  await expect(sheet).toBeHidden()
  expect(writes).toEqual([])
})

test('T5: the chart draws the API points; a point names P at that instant', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/treasury')).json()
  await open(page)
  const account = await page.locator('.lw-tre').getAttribute('data-account')
  const a = api.accounts.find((x: { id: string }) => x.id === account)

  const points = $(page, 'outlook-point')
  await expect(points).toHaveCount(a.projected.length)
  // the first point is "now", read again by each request; the event times are the API's own
  for (let i = 1; i < a.projected.length; i++) {
    await expect(points.nth(i)).toHaveAttribute('data-t', a.projected[i].t)
  }
  await expect($(page, 'floor-status')).toHaveText(/[A-Za-z]/)
  // the minimum is projected cash P, not spendable S
  await expect($(page, 'coverage')).toContainText('Minimum projected')
  await expect($(page, 'minimum').locator('xpath=..').locator('[role="tooltip"]')).toContainText('Lowest projected cash P')

  // keyboard: focus a chart point, its instant's P and what moves it are in its tooltip
  const last = points.last()
  await last.focus()
  const tip = last.locator('xpath=..').locator('[role="tooltip"]')
  await expect(tip).toBeVisible()
  await expect(tip).toContainText(`h${Math.round((Date.parse(a.projected.at(-1).t) - Date.parse(api.as_of)) / 3_600_000)}`)
  await page.keyboard.press('Escape')
  // the minimum's calculation discloses in the fold
  await $(page, 'spend-calc').locator('summary').click()
  await expect($(page, 'calculation')).toContainText(`in ${a.currency}`)
  expect(await sideways(page), 'Treasury scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('T6: Rehearse a cash shock carries the account and snapshot to the prepared run', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await (await request.get('/api/v1/treasury')).json()
  await open(page)
  const account = await page.locator('.lw-tre').getAttribute('data-account')
  const link = page.locator('a[data-test="rehearse"]')
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/simulation\?/)
  const query = new URL(page.url()).searchParams
  expect(query.get('run_id')).toBe(runId)
  expect(query.get('account')).toBe(account)
  expect(query.get('snapshot')).toBe(api.snapshot_id)
  await settled(page)
  await expect(crumb(page)).toHaveText('Simulation')
  expect(writes).toEqual([])
})

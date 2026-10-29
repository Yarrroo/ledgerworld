/**
 * Treasury in motion (prp/2026-10-29-ux-pass/HANDOFF.md T1–T6), at every width of
 * e2e/ux.config.ts: the account selector drives the buckets, the spendable calculation and the
 * cash path together; a bucket discloses its inputs and source time; an obligation or arrival row
 * opens its details (a full-width sheet on a phone) and gives focus back; the chart and the table
 * draw the same API points and a chosen point shows P's terms at that instant; Rehearse a cash
 * shock carries the account and snapshot to the prepared run. Read-only.
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

test('T1–T3: the selected account drives buckets, S and its calculation together', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/treasury')).json()
  await open(page)

  const options = $(page, 'account-selector').getByRole('radio')
  await expect(options).toHaveCount(api.accounts.length)
  await expect($(page, 'account-selector').getByRole('radio', { checked: true })).toHaveCount(1)
  await atLeast44(page, '.lw-tre__choice')

  for (const account of api.accounts) {
    await $(page, `account-${account.id}`).click()
    await expect($(page, `account-${account.id}`).getByRole('radio')).toBeChecked()
    await expect(page.locator('.lw-tre')).toHaveAttribute('data-account', account.id)
    // S is the API's, in the account's own currency ("$70,000"); the account id is in its (i)
    await expect($(page, 'spendable')).toContainText(account.id)
    const sign = ({ USD: '\\$', EUR: '€', GBP: '£' } as Record<string, string>)[account.currency] ?? `${account.currency} `
    await expect($(page, 'spendable').locator('.lw-figure')).toHaveText(new RegExp(`^-?${sign}\\d|^Unknown$`))
    await $(page, 'spend-calc').locator('summary').click()
    await expect($(page, 'spend-calculation')).toContainText(`S(now) in ${account.currency}`)
    await expect($(page, 'spend-calculation')).toContainText('(API)')
    // five buckets; settled discloses its inputs, account and source time
    await expect($(page, 'buckets').locator('li')).toHaveCount(5)
    const settledRow = $(page, 'bucket-settled')
    await settledRow.locator('summary').click()
    await expect(settledRow.locator('[data-test="bucket-inputs"]')).toContainText(account.id)
    await expect(settledRow.locator('[data-test="bucket-inputs"]')).toContainText(/\d{4}-\d\d-\d\d \d\d:\d\d UTC/)
    if (account.buckets.settled === null) await expect(settledRow.locator('summary')).toContainText('Unknown')
    // pending inflows are expected, not settled
    await expect($(page, 'bucket-pending-in').locator('summary')).toContainText('expected')
    // the cash path follows: one chart point per API point of this account
    await expect($(page, 'chart-point')).toHaveCount(api.accounts.find((a: { id: string }) => a.id === account.id)
      .projected.filter((p: { value: { minor: number | null } }) => p.value.minor !== null).length)
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

test('T5: the chart and the table share the API points; a point shows P at that instant', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const api = await (await request.get('/api/v1/treasury')).json()
  await open(page)
  const account = await page.locator('.lw-tre').getAttribute('data-account')
  const a = api.accounts.find((x: { id: string }) => x.id === account)

  await expect($(page, 'timeline').locator('tbody tr')).toHaveCount(a.projected.length)
  const points = $(page, 'chart-point')
  const known = a.projected.filter((p: { value: { minor: number | null } }) => p.value.minor !== null)
  await expect(points).toHaveCount(known.length)
  // the first point is "now", read again by each request; the event times are the API's own
  for (let i = 1; i < known.length; i++) {
    await expect(points.nth(i)).toHaveAttribute('data-t', known[i].t)
  }
  await expect($(page, 'floor-status')).toHaveText(/[A-Za-z]/)
  // the lowest point is projected cash P, not spendable S (the label's old "not spendable now" is in its tooltip)
  await expect($(page, 'coverage')).toContainText('Lowest point ahead')
  await expect($(page, 'coverage').locator('[role="tooltip"]').first()).toContainText('Lowest projected cash P')

  // keyboard: focus a chart point, its instant's terms are announced
  const last = points.last()
  await last.focus()
  await expect(last).toHaveAttribute('aria-pressed', 'true')
  const hours = (await last.getAttribute('aria-label'))!.split(',')[0]
  await expect($(page, 'point-calculation')).toContainText(hours)
  await expect($(page, 'point-calculation')).toContainText(/= /)
  // the table's own control selects the same instant
  const first = $(page, 'timeline-point').first()
  await first.click()
  await expect(first).toHaveAttribute('aria-pressed', 'true')
  await expect($(page, 'point-calculation')).toContainText((await first.innerText()).trim())
  await expect(points.first()).toHaveAttribute('aria-pressed', 'true')
  // the minimum's calculation discloses inline
  await $(page, 'coverage').locator('details.lw-calc summary').click()
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

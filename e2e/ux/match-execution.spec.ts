import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { settled, sideways, tipWorks } from './routes'
import { visibleWords, wordBudget } from './words'

const evidence = join(__dirname, '../../prp/2026-10-30-match-execution/ux')
const fixture = (path: string) => JSON.parse(readFileSync(join(__dirname, '../../contracts/examples', path), 'utf8')).instance
const overview = fixture('c6_api/valid-overview-lf1.json')
const approval = fixture('c3_bound_approval/valid-lf1-integrated.json')
const execution = fixture('c6_api/valid-execution.json')
const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)

async function shot (page: Page, name: string) {
  mkdirSync(evidence, { recursive: true })
  await page.screenshot({ path: join(evidence, `${page.viewportSize()!.width}-${name}.png`), fullPage: name.startsWith('execution-') })
}

async function controls (page: Page) {
  for (const control of await $(page, 'review').locator('button, input, summary').all()) {
    if (!await control.isVisible()) continue
    expect((await control.boundingBox())!.height, await control.innerText()).toBeGreaterThanOrEqual(44)
  }
  const footer = (await page.locator('.lw-dialog__footer').boundingBox())!
  expect(footer.y).toBeGreaterThanOrEqual(0)
  expect(footer.y + footer.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1)
  expect(await sideways(page)).toBeLessThanOrEqual(0)
}

// Real read path: values must match the offline app, not the illustrative amounts in the picture.
test('Execution matches mockup 06', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  if (info.project.use.viewport!.width >= 1200) await page.setViewportSize({ width: 1487, height: 1058 })
  const head = await (await request.get('/api/v1/overview')).json()
  const body = await (await request.get(`/api/v1/executions/${head.demo.execution_id}`)).json()
  await page.goto('/execution')
  await settled(page)
  await expect(page.locator('h1')).toHaveText('From approved plan to proof.')
  await expect(page.locator('#receipts-heading')).toHaveText('Execution legs')
  await expect(page.locator('#summary-heading')).toHaveText('Bound approval')
  await expect($(page, 'execution-progress').locator('li > span:nth-child(2)')).toHaveText([
    'Approved, reached', 'Submitted, reached', 'Provider confirmed, reached', 'Reconciled, reached'
  ])
  await expect($(page, 'execution-banner')).toContainText('Reconciled as of')
  await expect($(page, 'execution-banner')).toContainText('Illustrative receipt')
  await expect($(page, 'no-incidents')).toContainText('No open incidents for this reading.')
  // C6 has journal ids but no journal amounts: no invented reconciliation totals.
  await expect(page.getByRole('heading', { name: 'Ledger reconciliation' })).toHaveCount(0)
  const rows = page.locator('.lw-leg')
  await expect(rows).toHaveCount(body.legs.length)
  for (let i = 0; i < body.legs.length; i++) {
    const leg = body.legs[i]
    await expect(rows.nth(i)).not.toHaveAttribute('open', '')
    await expect(rows.nth(i).locator('[data-test="receipt-pill"]')).toContainText('Reconciled')
    if (leg.receipt) {
      const amount = new Intl.NumberFormat('en-US', { style: 'currency', currency: leg.receipt.currency, maximumFractionDigits: 0 }).format(Number(leg.receipt.amount))
      await expect(rows.nth(i).locator('[data-test="receipt-amount"]')).toHaveText(amount)
    }
  }
  const left = (await $(page, 'receipts').boundingBox())!, right = (await $(page, 'summary').boundingBox())!
  if (page.viewportSize()!.width >= 1200) expect(right.x).toBeGreaterThanOrEqual(left.x + left.width)
  else expect(right.y).toBeGreaterThanOrEqual(left.y + left.height)
  const counts: Record<string, number> = {}
  for (const theme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: theme })
    await page.locator('h1').click()
    const words = (await visibleWords(page)).length
    counts[theme] = words
    info.annotations.push({ type: 'words', description: `${words} at ${page.viewportSize()!.width} ${theme}` })
    expect(words).toBeLessThanOrEqual(wordBudget('execution'))
    expect(await sideways(page)).toBeLessThanOrEqual(0)
    await shot(page, `execution-${theme}`)
  }
  writeFileSync(join(evidence, `${page.viewportSize()!.width}-words.json`), JSON.stringify(counts, null, 2) + '\n')
  await tipWorks(page, rows.first().locator('.lw-leg__status'), Boolean(info.project.use.hasTouch), 'receipt status')
  await expect(rows.first()).not.toHaveAttribute('open', '')
  await rows.first().locator('.lw-leg__chevron').click()
  await expect(rows.first().locator('.lw-leg__detail')).toBeVisible()
  for (const term of ['Request id', 'Provider id', 'Journal']) {
    await expect(rows.first().getByRole('button', { name: `Copy ${term}`, exact: true })).toBeVisible()
  }
  await rows.first().getByText('Open receipt →', { exact: true }).click()
  await expect(rows.first().getByText('Fields', { exact: true })).toBeVisible()
  await $(page, 'summary-plain').locator('summary').click()
  await expect($(page, 'summary-approval')).toHaveText(body.approval_id)
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

// Browser-isolated writes: the real app never receives an approval or execution POST.
test('Approval matches mockup 07 and keeps two explicit actions', async ({ page }, info) => {
  if (info.project.use.viewport!.width >= 1200) await page.setViewportSize({ width: 1487, height: 1058 })
  const posts: string[] = []
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const method = route.request().method()
    if (method === 'GET' && path === '/overview') return route.fulfill({ json: { ...overview, demo: { run_id: 'run-1', execution_id: null } } })
    if (method === 'GET' && path === '/decisions/run-1') return route.fulfill({ json: {
      as_of: '2026-11-05T10:00:00Z', mode: 'fake', run_id: 'run-1', snapshot_id: 'lf1',
      cohort: 'delayed-receipt', weight_kind: 'equal', status: 'selected', selected: 'integrated',
      results: [{ policy: 'integrated', scenario_id: 's1', branch_id: 'branch-1', funding_cost: { minor: 80000, currency: 'USD' } }]
    } })
    if (method === 'POST' && path === '/approvals') {
      posts.push(path)
      return route.fulfill({ status: 201, json: { as_of: '2026-11-05T10:00:00Z', mode: 'fake', approval } })
    }
    if (method === 'POST' && path === '/executions') {
      posts.push(path)
      return route.fulfill({ status: 202, json: { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: approval.approval_id } })
    }
    if (method === 'GET' && path === `/executions/${approval.approval_id}`) return route.fulfill({ json: execution })
    if (method !== 'GET') { posts.push(`UNEXPECTED ${method} ${path}`); return route.abort('blockedbyclient') }
    return route.fulfill({ status: 404, json: {} })
  })
  await page.goto('/execution')
  await settled(page)
  await $(page, 'review-plan').click()
  await expect(page.locator('#review-heading')).toHaveText('Review before you execute.')
  await expect(page.locator('#review-heading')).toBeFocused()
  await expect($(page, 'confirm')).toHaveText('Create approval')
  await expect($(page, 'confirm')).toBeDisabled()
  await expect($(page, 'execute')).toHaveCount(0)
  await $(page, 'token').fill('operator-ux-token-not-a-secret')
  await expect($(page, 'token')).toHaveAttribute('type', 'password')
  await $(page, 'show-token').click()
  await expect($(page, 'token')).toHaveAttribute('type', 'text')
  await expect($(page, 'show-token')).toHaveAttribute('aria-pressed', 'true')
  await page.keyboard.press('Escape')
  await expect($(page, 'review-plan')).toBeFocused()
  await $(page, 'review-plan').click()
  await expect($(page, 'token')).toHaveAttribute('type', 'password')
  for (const theme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: theme })
    await controls(page)
    await shot(page, `create-${theme}`)
  }
  await $(page, 'confirm').click()
  await expect($(page, 'review')).toHaveAttribute('data-stage', 'approved')
  expect(posts).toEqual(['/approvals'])
  await expect($(page, 'execute')).toHaveText('Execute approved plan')
  await expect($(page, 'plan-hash')).toHaveText(approval.plan_hash)
  await expect($(page, 'legs')).toContainText('$10,000')
  await expect($(page, 'legs')).toContainText('$50,000')
  await expect($(page, 'legs').locator('tbody tr')).toHaveCount(2) // fee is not a third payment
  if (page.viewportSize()!.width < 768) await expect($(page, 'create-stage')).toBeHidden()
  else {
    const create = (await $(page, 'create-stage').boundingBox())!, bound = (await $(page, 'bound-stage').boundingBox())!
    expect(bound.x).toBeGreaterThanOrEqual(create.x + create.width)
  }
  for (const theme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: theme })
    await controls(page)
    await shot(page, `approval-${theme}`)
  }
  await $(page, 'execute').click()
  await expect($(page, 'review')).toHaveAttribute('data-stage', 'reconciled')
  await expect($(page, 'execute')).toHaveCount(0)
  expect(posts).toEqual(['/approvals', '/executions'])
  await page.keyboard.press('Escape')
  await expect($(page, 'review')).toHaveCount(0)
  await expect($(page, 'review-plan')).toBeFocused()
})

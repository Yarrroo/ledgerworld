/**
 * Execution, panels E1–E6 and the approval dialog of prp/2026-10-29-ux-pass/HANDOFF.md (design:
 * prp/2026-10-29-execution-dialog/design.md), in motion at every width of e2e/ux.config.ts. The
 * finance API is mocked in the browser from the recorded contract examples, so the dialog walks
 * every stage — review, submitting, unknown, approved, expired, executing, reconciled, incident —
 * and no write reaches the app: approval and execution POSTs are answered here, each counted.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { settled, sideways } from './routes'

const read = (path: string) => JSON.parse(readFileSync(join(__dirname, '../../', path), 'utf-8')).instance
const OVERVIEW = read('contracts/examples/c6_api/valid-overview-lf1.json')
const EXECUTION = read('contracts/examples/c6_api/valid-execution.json')
const APPROVAL = read('contracts/examples/c3_bound_approval/valid-lf1-integrated.json')
const TOKEN = 'operator-ux-token-not-a-secret'
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x))

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const dialog = (page: Page) => $(page, 'review')

const decisions = {
  as_of: '2026-11-05T10:00:00Z', mode: 'fake', run_id: 'run-1', snapshot_id: 'lf1', checkpoint_round: 3,
  cohort: 's1-s3', weight_kind: 'equal', status: 'selected', selected: 'integrated', escalation: null,
  results: ['s1', 's2', 's3'].map((s) => ({
    policy: 'integrated', scenario_id: s, branch_id: `run-1-${s}-integrated`, replay: false,
    obligations_unmet: 0, floor_kept: true, feasible: true,
    min_cash: { minor: 3000000, currency: 'USD', status: 'known' },
    funding_cost: { minor: 80000, currency: 'USD' }
  }))
}

/** The execution as the provider moves it: submitted (not reconciled), then reconciled. */
function executionAt (step: 'submitted' | 'reconciled' | 'incident'): any {
  const body = clone(EXECUTION)
  if (step === 'submitted') {
    for (const leg of body.legs) Object.assign(leg, { state: 'submitted', reconciled: false, journal_id: null })
  }
  if (step === 'incident') {
    body.incidents = [{
      incident_id: 'inc-1', leg_id: body.legs[0].leg_id, kind: 'amount_mismatch', state: 'open',
      opened_at: '2026-11-05T10:01:50Z'
    }]
  }
  return body
}

interface Mock { approval?: any, executions?: any[], approvalAborts?: boolean }

/** Serve the finance API for run-1; returns the POSTs it answered, in order. */
async function mock (page: Page, { approval, executions = [], approvalAborts = false }: Mock): Promise<string[]> {
  const posts: string[] = []
  const json = (route: Route, body: any, status = 200) => route.fulfill({ status, json: body })
  await page.route('**/api/v1/overview', (r) => json(r, { ...clone(OVERVIEW), mode: 'fake', demo: { run_id: 'run-1', execution_id: null } }))
  await page.route('**/api/v1/decisions/run-1', (r) => json(r, decisions))
  await page.route('**/api/v1/approvals', async (r) => {
    posts.push('POST /approvals')
    expect(r.request().headers().authorization).toBe(`Bearer ${TOKEN}`)
    await new Promise((resolve) => setTimeout(resolve, 400)) // long enough to see "submitting"
    if (approvalAborts) return r.abort('timedout')
    return json(r, approval ?? { as_of: '2026-11-05T10:00:00Z', mode: 'fake', approval: clone(APPROVAL) }, 201)
  })
  await page.route('**/api/v1/executions', (r) => {
    posts.push('POST /executions')
    return json(r, { as_of: '2026-11-05T10:00:05Z', mode: 'fake', execution_id: APPROVAL.approval_id }, 202)
  })
  let reads = 0
  await page.route(`**/api/v1/executions/${APPROVAL.approval_id}`, (r) =>
    json(r, executions[Math.min(reads++, executions.length - 1)] ?? executionAt('reconciled')))
  return posts
}

/** Open the screen and the review, with operator access entered. */
async function review (page: Page): Promise<void> {
  await page.goto('/execution')
  await settled(page)
  await $(page, 'review-plan').click()
  await expect(dialog(page)).toHaveAttribute('data-stage', 'review')
  await expect(page.locator('#review-heading')).toBeFocused()
  await $(page, 'token').fill(TOKEN)
}

/** Every control a finger uses inside the dialog is at least 44 px tall. */
async function tall (page: Page): Promise<void> {
  for (const el of await dialog(page).locator('button').all()) {
    if (!(await el.isVisible())) continue
    expect((await el.boundingBox())!.height, `${await el.innerText()} is shorter than 44 px`).toBeGreaterThanOrEqual(44)
  }
}

/** The action footer is in view; on a phone the dialog fills the screen and the footer sits at its foot. */
async function footed (page: Page): Promise<void> {
  const view = page.viewportSize()!
  const box = (await dialog(page).boundingBox())!
  const foot = (await dialog(page).locator('.lw-dialog__footer').boundingBox())!
  expect(foot.y + foot.height).toBeLessThanOrEqual(view.height + 1)
  expect(foot.y).toBeGreaterThanOrEqual(0)
  if (view.width < 768) {
    expect(Math.round(box.height)).toBe(view.height)
    expect(Math.round(foot.y + foot.height)).toBe(view.height)
  }
  await tall(page)
  expect(await sideways(page)).toBeLessThanOrEqual(0)
}

test('approve, then execute: one POST each, the dialog follows the execution to reconciled', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const posts = await mock(page, { executions: [executionAt('submitted'), executionAt('reconciled')] })
  await review(page)
  await footed(page)

  const confirm = $(page, 'confirm')
  await confirm.click()
  await expect(dialog(page)).toHaveAttribute('data-stage', 'submitting')
  await expect(confirm).toBeDisabled() // single flight: a second press sends nothing
  await confirm.click({ force: true })
  await expect(dialog(page)).toHaveAttribute('data-stage', 'approved')
  expect(posts).toEqual(['POST /approvals'])
  await expect($(page, 'plan-hash')).toHaveText(APPROVAL.plan_hash)
  await expect($(page, 'expires')).toContainText('2026-11-05 10:15 UTC · local')
  await footed(page)

  await $(page, 'copy-hash').click()
  await expect($(page, 'copied')).toHaveText('Plan hash copied')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(APPROVAL.plan_hash)
  await $(page, 'copy-approval').click()
  await expect($(page, 'copied')).toHaveText('Approval id copied')

  await $(page, 'execute').click()
  await expect(dialog(page)).toHaveAttribute('data-stage', 'executing')
  await expect($(page, 'execute')).toHaveCount(0) // no execute-again action
  await expect($(page, 'stage-status')).toContainText(`Execution ${APPROVAL.approval_id}: reading status`)
  await $(page, 'read-status').click() // a GET, never a resend
  await expect(dialog(page)).toHaveAttribute('data-stage', 'reconciled')
  await expect($(page, 'stage-status')).toContainText('not final')
  expect(posts).toEqual(['POST /approvals', 'POST /executions'])
  await footed(page)

  await dialog(page).getByRole('button', { name: 'Close' }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect($(page, 'review-plan')).toBeFocused()
  await expect($(page, 'context')).toContainText(`execution ${APPROVAL.approval_id}`)

  // E4 → E5: a leg expands to its receipt
  const leg = page.locator('[data-test="leg-advance"]')
  await expect(leg.locator('[data-test="leg-status"]')).toHaveText(/reconciled as of .* UTC/)
  await expect(leg.locator('[aria-current="step"]')).toContainText('Reconciled')
  await leg.locator('[data-test="receipt"] summary').click()
  await expect(leg.locator('[data-test="receipt"]')).toContainText(EXECUTION.legs[0].journal_id)
  await expect($(page, 'no-incidents')).toBeVisible()
  expect(await sideways(page)).toBeLessThanOrEqual(0)
})

test('a ledger-only repayment (mode B) is reconciled locally, never submitted or provider-confirmed', async ({ page }, info) => {
  const body = clone(EXECUTION)
  body.legs.push({ // as GET /executions serialises the outbox's ledger-only leg: no provider id, no receipt
    leg_id: `${APPROVAL.approval_id}:repayment`, request_id: 'req-repayment-1', kind: 'repayment', provider_id: null,
    state: 'settled', receipt: null, reconciled: true, journal_id: 'j-repayment-1', label: 'repayment (simulated)'
  })
  await mock(page, { executions: [body] })
  await page.route('**/api/v1/overview', (r) => r.fulfill({
    json: { ...clone(OVERVIEW), mode: 'fake', demo: { run_id: 'run-1', execution_id: APPROVAL.approval_id } }
  }))
  await page.goto('/execution')
  await settled(page)
  const leg = $(page, 'leg-repayment')
  await expect(leg.locator('[data-test="leg-status"]')).toHaveText(/Ledger only, no provider operation · reconciled as of .* UTC/)
  await expect(leg.locator('.lw-steps__done')).toHaveText([/Ready/, /Reconciled · ledger only/])
  await expect(leg.locator('.lw-steps__skipped')).toHaveText([/Submitted · not applicable/, /Provider-confirmed · not applicable/])
  await expect(leg.locator('[data-test="receipt-mode"]')).toHaveText('Ledger only (simulated)')
  await expect(leg.locator('[data-test="receipt"]')).toHaveCount(0)
  await expect($(page, 'leg-advance').locator('.lw-steps__done')).toHaveCount(4)
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  await leg.screenshot({ path: info.outputPath('ledger-only-repayment.png') })
})

test('an expired approval disables Execute and says why', async ({ page }) => {
  const posts = await mock(page, { approval: { as_of: APPROVAL.expires_at, mode: 'fake', approval: clone(APPROVAL) } })
  await review(page)
  await $(page, 'confirm').click()
  await expect(dialog(page)).toHaveAttribute('data-stage', 'expired')
  await expect($(page, 'execute')).toBeDisabled()
  await expect($(page, 'execute-why')).toHaveText('Approval expired')
  await footed(page)
  expect(posts).toEqual(['POST /approvals'])
})

test('an approval with no answer is unknown: blocked, never sent again', async ({ page }) => {
  const posts = await mock(page, { approvalAborts: true })
  await review(page)
  await $(page, 'confirm').click()
  await expect(dialog(page)).toHaveAttribute('data-stage', 'unknown')
  await expect($(page, 'stage-blocked')).toContainText('operator resolution required')
  await expect($(page, 'confirm')).toBeDisabled()
  await footed(page)
  expect(posts).toEqual(['POST /approvals'])
})

test('an incident keeps its evidence; nothing is resent or reversed', async ({ page }) => {
  const posts = await mock(page, { executions: [executionAt('incident')] })
  await review(page)
  await $(page, 'confirm').click()
  await $(page, 'execute').click()
  await expect(dialog(page)).toHaveAttribute('data-stage', 'incident')
  await expect($(page, 'stage-incident')).toContainText('amount mismatch')
  await expect(dialog(page).getByRole('button', { name: /resend|revers|retry/i })).toHaveCount(0)
  await footed(page)
  await page.keyboard.press('Escape')
  await expect(dialog(page)).toHaveCount(0)
  const evidence = $(page, 'incident')
  await expect(evidence).toContainText(EXECUTION.legs[0].receipt.provider_id)
  await expect(evidence).toContainText('Last read')
  expect(posts).toEqual(['POST /approvals', 'POST /executions'])
})

for (const step of ['reconciled', 'incident'] as const) {
  test(`a failed Read status after ${step} is said in the dialog, the stage kept`, async ({ page }) => {
    const posts = await mock(page, { executions: [executionAt(step)] })
    await review(page)
    await $(page, 'confirm').click()
    await $(page, 'execute').click()
    await expect(dialog(page)).toHaveAttribute('data-stage', step)
    const kept = await $(page, 'stage-status').innerText()
    // the newest route answers first: every later read is refused
    await page.route(`**/api/v1/executions/${APPROVAL.approval_id}`, (r) =>
      r.fulfill({ status: 403, json: { error: { code: 'forbidden', detail: 'not allowed' } } }))
    await $(page, 'read-status').click()
    await expect($(page, 'stage-status')).toContainText(
      `Could not read the status of execution ${APPROVAL.approval_id}: not allowed. Read status to try again.`)
    await expect($(page, 'stage-status')).toContainText(kept)
    await expect(dialog(page)).toHaveAttribute('data-stage', step)
    await footed(page)
    await page.screenshot({ path: test.info().outputPath(`read-failed-${step}.png`) })
    expect(posts).toEqual(['POST /approvals', 'POST /executions'])
  })
}

test('focus is trapped in the dialog and returned to Review plan', async ({ page }) => {
  await mock(page, {})
  await review(page)
  await $(page, 'confirm').click()
  await expect(dialog(page)).toHaveAttribute('data-stage', 'approved')
  for (let n = 0; n < 12; n++) {
    await page.keyboard.press(n % 3 === 2 ? 'Shift+Tab' : 'Tab')
    expect(await dialog(page).evaluate((box) => box.contains(document.activeElement))).toBe(true)
  }
  await page.keyboard.press('Escape')
  await expect(dialog(page)).toHaveCount(0)
  await expect($(page, 'review-plan')).toBeFocused()
})

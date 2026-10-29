/**
 * Copy pass 2 (prp/2026-10-29-ux-pass/COPY.md) on Simulation, Decisions and Execution, at every
 * width of e2e/ux.config.ts: each screen leads with one plain sentence built from the API's own
 * figures (the what-if, the plan that keeps you covered and its fee, what moved and was checked
 * against your books), the plans carry their plain names, the buttons are plain verbs, the run,
 * round, evidence and approval ids sit in a How we know disclosure that is closed by default and
 * opens from the keyboard, and the What-if and simulated-bank labels stay visible. Read-only.
 *
 * The judge path's controls keep their names (Compare policies, View execution, Open receipt:
 * prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/judge-path.json).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, settled } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const FAMILY = (id: string) => JSON.parse(readFileSync(join(__dirname, `../../scenarios/families/${id}.json`), 'utf-8'))
const PLANS: Record<string, string> = { 'no-action': 'Do nothing', 'fixed-reserve': 'Keep a fixed buffer', integrated: 'Borrow just enough' }
const DOING: Record<string, string> = { 'fixed-reserve': 'Keeping a fixed buffer', integrated: 'Borrowing just enough' }
const RIPPLE = 'Watch how it ripples through your partners, round by round.'

interface Money { minor: number, currency: string }
/** "USD 70,000.00", as the screens format integer minor units. */
const fmt = (m: Money) => `${m.currency} ${(m.minor / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}`
/** "2 Jan", the UTC day of an instant. */
const day = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })

/** The words a finance lead should not meet in a heading or a lead sentence (COPY.md rule 2). */
const JARGON = /\b(snapshot|branch|cohort|checkpoint|intent|provenance|policy|policies)\b/i
const SYMBOL = /K_p|\((S|P)\)|(^|\s)(P|S)(?=[\s,.;:]|$)/
const technical = (text: string) => JARGON.test(text) || SYMBOL.test(text)
/** Words in a sentence, an amount ("USD 20,000.00") counting as one and a dash as none. */
const words = (text: string) => text.replace(/\b[A-Z]{3} (?=[\d-])/g, '').split(/\s+/).filter((w) => /\w/.test(w)).length

async function read (page: Page, path: string): Promise<any> {
  const reply = await page.request.get(`/api/v1${path}`)
  expect(reply.status(), `GET /api/v1${path}`).toBe(200)
  return reply.json()
}

async function open (page: Page, path: string): Promise<void> {
  await page.goto(path)
  await settled(page)
}

/** The lead: short, plain, visible, before the screen's figures and panels. */
async function leads (page: Page): Promise<string> {
  const lead = $(page, 'lead')
  await expect(lead).toBeVisible()
  await expect(lead).not.toBeEmpty()
  const text = (await lead.textContent())!.trim()
  expect(words(text), `the lead is longer than 25 words: ${text}`).toBeLessThanOrEqual(25)
  expect(technical(text), `the lead uses a technical term: ${text}`).toBe(false)
  const first = await page.evaluate(() => {
    const lead = document.querySelector('main.lw-main [data-test="lead"]')
    const sections = [...document.querySelectorAll('main.lw-main section')].filter((s) => !s.contains(lead))
    return sections.every((s) => lead!.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING)
  })
  expect(first, 'the lead comes before every other panel').toBe(true)
  return text
}

/** Every visible section heading is in plain words. */
async function plainHeadings (page: Page): Promise<void> {
  for (const h of await page.locator('main.lw-main section h2').all()) {
    if (!(await h.isVisible())) continue
    const text = (await h.textContent())!.trim()
    expect(technical(text), `a heading uses a technical term: ${text}`).toBe(false)
  }
}

/** The honesty labels, visible in plain words. */
async function honest (page: Page, whatIf: boolean): Promise<void> {
  await expect($(page, 'plain-mode')).toHaveText(/^(Simulated bank connection|Sandbox bank)$/)
  await expect($(page, 'plain-mode')).toBeVisible()
  if (whatIf) {
    await expect($(page, 'hypothetical')).toHaveText('What-if')
    await expect($(page, 'hypothetical')).toBeVisible()
  }
}

/** A How we know disclosure: closed, keyboard-reachable, holding `facts`. */
async function folded (page: Page, test: string, facts: string[]): Promise<void> {
  const how = $(page, test)
  await expect(how).toHaveCount(1)
  await expect(how).not.toHaveAttribute('open', '')
  await expect(how.locator('.lw-calc__body')).not.toBeVisible()
  const summary = how.locator('summary')
  await expect(summary).toHaveText('How we know')
  await summary.focus()
  await expect(summary).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(how).toHaveAttribute('open', '')
  for (const fact of facts) await expect(how.locator('.lw-calc__body')).toContainText(fact)
  expect((await summary.boundingBox())!.height, 'How we know is shorter than 44 px').toBeGreaterThanOrEqual(44)
  await page.keyboard.press('Enter')
  await expect(how).not.toHaveAttribute('open', '')
}

test('Simulation: the what-if from the treasury and the family, ids one click down', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const run = await read(page, `/runs/${runId}`)
  const treasury = await read(page, '/treasury')
  await open(page, `/simulation?run_id=${runId}`)
  const text = await leads(page)
  const base = run.branches.find((b: any) => b.parent_branch_id === null)
  const id = ['delayed-receipt', 'fx-gap', 'stablecoin-depeg', 'redemption-spike', 'borrower-silence', 'confidence-rumour']
    .find((f) => run.branches.some((b: any) => b.branch_id.includes(f)))
  if (id === 'delayed-receipt') {
    const { params } = FAMILY(id)
    const flow = treasury.accounts.flatMap((a: any) => a.buckets.pending_in).find((f: any) => f.flow_id === params.flow_id)
    expect(text).toBe(`What if your ${fmt(flow.amount)} ${flow.kind.replace(/_/g, ' ')} arrives ${params.delay_h / 24} days late? ${RIPPLE}`)
  } else {
    expect(text).toMatch(/^What (if|happens)/)
    expect(text).toContain(RIPPLE)
  }
  await honest(page, true)
  await plainHeadings(page)
  await expect($(page, 'run-id')).not.toBeVisible()
  await folded(page, 'how-run', [runId, base.branch_id, 'Simulated provider'])
  await expect($(page, 'fork')).toHaveText('Try the plans on this shock')
  await expect($(page, 'fork-what')).toContainText('in its own what-if; approves nothing')
  await expect($(page, 'compare')).toHaveText('Compare policies') // the judge path's name
  await expect($(page, 'graph').locator('.lw-live-tag')).toHaveText('What-if')
  for (const hook of ['run-context', 'controls', 'phase', 'play', 'scrubber-slider', 'cursor', 'inspector', 'graph', 'settings']) {
    await expect($(page, hook)).toHaveCount(1)
  }
  expect(writes).toEqual([])
})

test('Decisions: what doing nothing costs, the plan that keeps you covered and its fee', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await read(page, `/decisions/${runId}`)
  const treasury = await read(page, '/treasury')
  await open(page, `/decisions?run_id=${runId}`)
  const text = await leads(page)
  const account = treasury.accounts.find((a: any) => a.id.endsWith('/operating')) ?? treasury.accounts[0]
  const none = api.results.filter((r: any) => r.policy === 'no-action')
  const lowest = none.reduce((a: any, b: any) => (b.min_cash.minor < a.min_cash.minor ? b : a)).min_cash
  if (api.status === 'selected' && lowest.minor < account.floor.minor) {
    const due = treasury.obligations.filter((o: any) => o.account === account.id && ['open', 'missed'].includes(o.state))
      .map((o: any) => o.due_at).sort()[0]
    expect(text).toContain(`Doing nothing leaves you ${fmt({ minor: account.floor.minor - lowest.minor, currency: lowest.currency })} ` +
      `under your safety minimum${due ? ` on ${day(due)}` : ''}.`)
  }
  if (api.status === 'selected' && api.selected !== 'no-action') {
    const fees = api.results.filter((r: any) => r.policy === api.selected).map((r: any) => r.funding_cost)
    const top = fees.reduce((a: any, b: any) => (b.minor > a.minor ? b : a))
    const fee = top.minor === 0 ? 'no fee' : fees.length > 1 ? `a fee of up to ${fmt(top)}` : `a ${fmt(top)} fee`
    expect(text).toMatch(new RegExp(`${DOING[api.selected]} keeps you covered for ${fee.replace(/[.]/g, '\\.')}\\.$`))
  }
  for (const [policy, name] of Object.entries(PLANS)) {
    await expect($(page, `policy-${policy}`).locator('.lw-dec__name')).toHaveText(name)
  }
  await expect(page.locator('#policies-heading')).toHaveText('Three plans side by side')
  await expect($(page, 'gap-summary')).toContainText('safety minimum')
  await honest(page, true)
  await plainHeadings(page)
  await expect($(page, 'cohort')).not.toBeVisible()
  await folded(page, 'how-decisions', [runId, api.cohort, 'not a probability'])
  const chosen = api.results.find((r: any) => r.policy === (api.selected ?? 'no-action'))
  await folded(page, `how-${chosen.policy}`, [chosen.branch_id, `Policy ${chosen.policy}`])
  await expect($(page, 'timing').locator('summary')).toHaveText('When the money moves')
  await expect($(page, 'compare-details')).toHaveText('Compare the what-ifs in detail')
  if (api.status === 'selected') await expect(page.locator('a[data-test="review-plan"]')).toHaveText('Review the plan')
  await expect(page.locator('a[data-test="view-execution"]')).toHaveText('View execution') // the judge path's name
  for (const hook of ['gap', 'gap-summary', 'policies', 'timing', 'compare-details', 'open-simulation', 'scenario', 'weight', 'cost']) {
    expect(await $(page, hook).count(), hook).toBeGreaterThan(0)
  }
  expect(writes).toEqual([])
})

test('Decisions: a comparison still running, or with no plan that holds, says so plainly', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await read(page, `/decisions/${runId}`)
  await page.route(`**/api/v1/decisions/${runId}`, (route) => route.fulfill({ json: { ...api, status: 'pending', selected: null } }))
  await open(page, `/decisions?run_id=${runId}`)
  expect(await leads(page)).toBe('The plans are still being tried on this shock; nothing is chosen yet.')
  await page.unroute(`**/api/v1/decisions/${runId}`)
  const escalation = { earliest_unmet: 'payroll-1', binding: 'reserve floor', contact: 'the treasurer' }
  await page.route(`**/api/v1/decisions/${runId}`, (route) => route.fulfill({ json: { ...api, status: 'all_infeasible', selected: null, escalation } }))
  await open(page, `/decisions?run_id=${runId}`)
  expect(await leads(page)).toBe('No plan keeps you above your safety minimum here; this needs a person to decide.')
  expect(writes).toEqual([])
})

/** "USD 10,000.00" from a provider receipt's decimal amount. */
const receiptMoney = (r: any) => fmt({ minor: Math.round(Number(r.amount) * 100), currency: r.currency })

test('Execution: what moved in and out, checked against your books; ids one click down', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const overview = await read(page, '/overview')
  const execution = await read(page, `/executions/${overview.demo.execution_id}`)
  await open(page, '/execution')
  // a read the offline app answers 500 (two reads at once on its SQLite file) is read again in 5 s
  await expect($(page, 'lead')).toHaveText(/^The plan you approved /, { timeout: 15_000 })
  const text = await leads(page)
  const sum = (kinds: string[]) => execution.legs.filter((l: any) => kinds.includes(l.kind)).map((l: any) => receiptMoney(l.receipt))
  const [inn, out] = [sum(['advance']), sum(['payout', 'repayment'])]
  if (execution.legs.every((l: any) => l.reconciled) && inn.length === 1 && out.length === 1 && execution.legs.length === 2) {
    expect(text).toBe(`The plan you approved moved ${inn[0]} in and paid ${out[0]} out — both checked against your books.`)
  } else {
    expect(text).toMatch(/^The plan you approved /)
  }
  await honest(page, false)
  await plainHeadings(page)
  await expect(page.locator('#authority-heading')).toHaveText('Approve, then send')
  await expect(page.locator('#summary-heading')).toHaveText('What you approved')
  await expect(page.locator('#receipts-heading')).toHaveText('Money moved, with receipts')
  await expect($(page, 'context')).not.toBeVisible()
  await folded(page, 'how-execution', [`execution ${overview.demo.execution_id}`, `Run ${overview.demo.run_id}`])
  await folded(page, 'how-summary', [execution.approval_id, execution.snapshot_id])
  await expect($(page, 'review-plan')).toHaveText('Review the plan')
  await expect($(page, 'receipt').first().locator('summary')).toHaveText('Open receipt') // the judge path's name
  for (const hook of ['authority', 'summary', 'receipts', 'review-why', 'summary-read', 'summary-approval']) {
    await expect($(page, hook)).toHaveCount(1)
  }

  // the review speaks plan names and plain verbs, and opening it sends nothing; a decision read
  // the offline app answered 500 (two reads at once on its SQLite file) is read again by Refresh
  await expect(async () => {
    if (await $(page, 'review-plan').isDisabled()) {
      await $(page, 'refresh').click()
      await settled(page)
    }
    await expect($(page, 'review-plan')).toBeEnabled({ timeout: 1_000 })
  }).toPass({ timeout: 20_000 })
  await $(page, 'review-plan').click()
  await expect($(page, 'review')).toHaveAttribute('data-stage', 'review')
  await expect(page.locator('#review-heading')).toHaveText(/^Review the plan · (Do nothing|Keep a fixed buffer|Borrow just enough)$/)
  await expect($(page, 'confirm')).toHaveText('Approve')
  expect(writes).toEqual([])
})

test('Execution: before anything is sent, and when something needs a look', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const overview = await read(page, '/overview')
  const execution = await read(page, `/executions/${overview.demo.execution_id}`)
  await page.route('**/api/v1/executions/**', (route) => route.fulfill({ status: 404, json: { code: 'not_found', message: 'No such execution' } }))
  await open(page, '/execution')
  expect(await leads(page)).toBe('Nothing moves until you approve and then send.')
  await page.unroute('**/api/v1/executions/**')

  const incident = { leg_id: execution.legs[0].leg_id, kind: 'amount_mismatch', state: 'open', opened_at: execution.as_of }
  await page.route('**/api/v1/executions/**', (route) => route.fulfill({ json: { ...execution, incidents: [incident] } }))
  await open(page, '/execution')
  expect(await leads(page)).toBe('Something needs a look: 1 problem on the plan you sent; nothing is resent.')
  expect(writes).toEqual([])
})

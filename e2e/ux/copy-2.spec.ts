/**
 * Copy pass 2 (prp/2026-10-29-ux-pass/COPY.md) on Simulation, Decisions and Execution, at every
 * width of e2e/ux.config.ts: each screen leads with one plain sentence built from the API's own
 * figures (the what-if, the plan that keeps you covered and its fee, what moved and was checked
 * against your books; now the hero subtitle's tooltip, prp/2026-10-29-ux-pass/MATCH.md item 1),
 * the plans carry their plain names, the buttons are plain verbs, the run, round, evidence and
 * approval ids sit in a How we know (i) that is closed by default and opens from the keyboard
 * (MATCH.md items 2, 4), and the header's simulated-provider and what-if labels stay visible. Read-only.
 *
 * The judge path's controls keep their names (Compare policies, View execution, Open receipt:
 * prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/judge-path.json).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { $, PLANS, fmt, folded, lead, open, plainHeadings, read, technical, words } from './copy'
import { demoRunId, settled } from './routes'

const FAMILY = (id: string) => JSON.parse(readFileSync(join(__dirname, `../../scenarios/families/${id}.json`), 'utf-8'))
const DOING: Record<string, string> = { 'fixed-reserve': 'Keeping a fixed buffer', integrated: 'Borrowing just enough' }
const RIPPLE = 'Watch how it ripples through your partners, round by round.'

/** "2 Jan", the UTC day of an instant. */
/** "10 days", "1 day", "36 hours": a delay as the lead says it. */
const delayWords = (h: number) => (h && h % 24 === 0 ? `${h / 24} day${h === 24 ? '' : 's'}` : `${h} hour${h === 1 ? '' : 's'}`)
/** The first payment still owed from `asOf` on (a missing state is open), for the lead's day. */
const firstDue = (obligations: any[], account: string, asOf: string) => obligations
  .filter((o) => o.account === account && ['open', 'missed'].includes(o.state ?? 'open') && Date.parse(o.due_at) >= Date.parse(asOf))
  .map((o) => o.due_at).sort((a, b) => Date.parse(a) - Date.parse(b))[0]
const day = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })

/** The lead: short, plain, in the hero, before the screen's figures and panels. */
async function leads (page: Page): Promise<string> {
  await expect(lead(page)).not.toBeEmpty()
  const text = (await lead(page).textContent())!.trim()
  expect(words(text), `the lead is longer than 25 words: ${text}`).toBeLessThanOrEqual(25)
  expect(technical(text), `the lead uses a technical term: ${text}`).toBe(false)
  const first = await page.evaluate(() => {
    const lead = document.querySelector('main.lw-main [data-test="hero-lead"]')
    const sections = [...document.querySelectorAll('main.lw-main section')].filter((s) => !s.contains(lead))
    return sections.every((s) => lead!.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING)
  })
  expect(first, 'the lead comes before every other panel').toBe(true)
  return text
}

/** The honesty labels, visible in the header (MATCH.md item 3). */
async function honest (page: Page, whatIf: boolean): Promise<void> {
  await expect($(page, 'mode')).toHaveText(/^(Simulated provider|Sandbox)\b.* · Scripted agents/)
  await expect($(page, 'mode')).toBeVisible()
  // a what-if says so in words on the page (the header on Simulation, the plans' rows on Decisions)
  if (whatIf) expect(await page.locator('main.lw-main').innerText()).toMatch(/what-if/i)
}

/** Read the screen again the way the shell does now: the tab becomes visible again. */
const reread = (page: Page) => page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))

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
    expect(text).toBe(`What if your ${fmt(flow.amount)} ${flow.kind.replace(/_/g, ' ')} arrives ${delayWords(params.delay_h)} late? ${RIPPLE}`)
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
    const due = firstDue(treasury.obligations, account.id, treasury.as_of)
    expect(text).toContain(`Doing nothing leaves you ${fmt({ minor: account.floor.minor - lowest.minor, currency: lowest.currency })} ` +
      `under your safety minimum${due ? ` on ${day(due)}` : ''}.`)
  }
  if (api.status === 'selected' && api.selected !== 'no-action') {
    const fees = api.results.filter((r: any) => r.policy === api.selected).map((r: any) => r.funding_cost)
    const top = fees.reduce((a: any, b: any) => (b.minor > a.minor ? b : a))
    const fee = top.minor === 0 ? 'no fee' : fees.length > 1 ? `a fee of up to ${fmt(top)}` : `a ${fmt(top)} fee`
    expect(text).toMatch(new RegExp(`${DOING[api.selected]} keeps you covered for ${fee.replace(/[$.]/g, '\\$&')}\\.$`))
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
  if (api.status === 'selected') await expect(page.locator('a[data-test="review-plan"]')).toHaveText('Review current plan')
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

/** "$10,000" from a provider receipt's decimal amount. */
const receiptMoney = (r: any) => fmt({ minor: Math.round(Number(r.amount) * 100), currency: r.currency })

test('Execution: what moved in and out, checked against your books; ids one click down', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const overview = await read(page, '/overview')
  const execution = await read(page, `/executions/${overview.demo.execution_id}`)
  await open(page, '/execution')
  // a read the offline app answers 500 (two reads at once on its SQLite file) is read again in 5 s
  await expect(lead(page)).toHaveText(/^The plan you approved /, { timeout: 15_000 })
  const text = await leads(page)
  const sum = (kinds: string[]) => execution.legs.filter((l: any) => kinds.includes(l.kind) && l.receipt).map((l: any) => receiptMoney(l.receipt))
  const [inn, out] = [sum(['advance']), sum(['payout', 'repayment'])]
  if (execution.legs.every((l: any) => l.reconciled && l.receipt) && inn.length === 1 && out.length === 1 && execution.legs.length === 2) {
    expect(text).toBe(`The plan you approved moved ${inn[0]} in and paid ${out[0]} out — both checked against your books.`)
  } else {
    expect(text).toMatch(/^The plan you approved /)
  }
  await honest(page, false)
  await plainHeadings(page)
  await expect(page.locator('#summary-heading')).toHaveText('What you approved')
  await expect(page.locator('#receipts-heading')).toHaveText('Money moved, with receipts')
  await expect($(page, 'context')).not.toBeVisible()
  await folded(page, 'how-execution', [`execution ${overview.demo.execution_id}`, `Run ${overview.demo.run_id}`])
  await folded(page, 'how-summary', [execution.approval_id, execution.snapshot_id])
  await expect($(page, 'review-plan')).toHaveText('Review plan')
  await expect($(page, 'receipt').first().locator('summary')).toHaveText('Open receipt') // the judge path's name
  for (const hook of ['authority', 'summary', 'receipts', 'review-why', 'summary-read', 'summary-approval']) {
    await expect($(page, hook)).toHaveCount(1)
  }

  // the review speaks plan names and plain verbs, and opening it sends nothing; a decision read
  // the offline app answered 500 (two reads at once on its SQLite file) is read again, as the
  // shell does when the tab is shown again
  await expect(async () => {
    if (await $(page, 'review-plan').isDisabled()) {
      await reread(page)
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

test('Simulation: a treasury read that failed is read again, and the amount comes back', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  let reads = 0
  await page.route('**/api/v1/treasury', (route) => (reads++ === 0
    ? route.fulfill({ status: 500, json: { code: 'internal', message: 'busy' } })
    : route.continue()))
  await open(page, `/simulation?run_id=${runId}`)
  await expect(lead(page)).toContainText('What if your expected payment arrives')
  await reread(page)
  await settled(page)
  await expect(lead(page)).toHaveText(/^What if your \$[\d,]+(\.\d\d)? \w/)
  expect(writes).toEqual([])
})

test('Decisions: the chosen plan that still falls short says so; the day is the first payment still ahead', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const api = await read(page, `/decisions/${runId}`)
  const treasury = await read(page, '/treasury')
  const account = treasury.accounts.find((a: any) => a.id.endsWith('/operating'))
  const due = firstDue(treasury.obligations, account.id, treasury.as_of)

  // a missed payment before today and obligations with no state: the day is still the next one due
  const before = new Date(Date.parse(treasury.as_of) - 86_400_000).toISOString()
  const changed = structuredClone(treasury)
  changed.obligations = [
    ...changed.obligations.map(({ state, ...o }: any) => o),
    { ...treasury.obligations[0], account: account.id, obligation_id: 'late-x', due_at: before, state: 'missed' }
  ]
  await page.route('**/api/v1/treasury', (route) => route.fulfill({ json: changed }))

  // the backend's pick still breaks the floor in one what-if
  const short = structuredClone(api)
  short.selected = 'fixed-reserve'
  for (const r of short.results) if (r.policy === 'fixed-reserve') r.floor_kept = false
  const n = short.results.filter((r: any) => r.policy === 'fixed-reserve').length
  await page.route(`**/api/v1/decisions/${runId}`, (route) => route.fulfill({ json: short }))
  await open(page, `/decisions?run_id=${runId}`)
  const text = await leads(page)
  if (due) expect(text).toContain(`under your safety minimum on ${day(due)}.`)
  expect(text).toMatch(new RegExp(`Keep a fixed buffer is best, yet short in ${n} of ${n} what-ifs?\\.$`))
  expect(text).not.toContain('keeps you covered')
  await page.unroute(`**/api/v1/decisions/${runId}`)

  // doing nothing chosen while it breaks the floor: no "needs no money" beside the shortfall
  const none = structuredClone(api)
  none.selected = 'no-action'
  await page.route(`**/api/v1/decisions/${runId}`, (route) => route.fulfill({ json: none }))
  await open(page, `/decisions?run_id=${runId}`)
  const lead = await leads(page)
  if (/under your safety minimum/.test(lead)) expect(lead).toMatch(/No plan does better\.$/)
  expect(writes).toEqual([])
})

test('Execution: a ledger-only leg is named as a ledger entry, never an unknown amount', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const overview = await read(page, '/overview')
  const execution = await read(page, `/executions/${overview.demo.execution_id}`)
  const legs = execution.legs.filter((l: any) => l.receipt)
  const ledger = { leg_id: `${legs[0].leg_id}-repayment`, kind: 'repayment', label: 'repayment (ledger only)', state: 'settled',
    reconciled: true, journal_id: 'j-ledger-only', provider_id: null, request_id: null, receipt: null }
  await page.route('**/api/v1/executions/**', (route) => route.fulfill({ json: { ...execution, legs: [...legs, ledger] } }))
  await open(page, '/execution')
  const text = await leads(page)
  expect(text).not.toContain('unknown amount')
  const inn = legs.filter((l: any) => l.kind === 'advance').map((l: any) => receiptMoney(l.receipt))
  const out = legs.filter((l: any) => ['payout', 'repayment'].includes(l.kind)).map((l: any) => receiptMoney(l.receipt))
  if (inn.length === 1 && out.length === 1) {
    expect(text).toBe(`The plan you approved moved ${inn[0]} in and paid ${out[0]} out, plus 1 ledger-only entry — all checked against your books.`)
  }
  expect(writes).toEqual([])
})

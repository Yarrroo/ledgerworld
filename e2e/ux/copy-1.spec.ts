/**
 * Copy pass 1 (prp/2026-10-29-ux-pass/COPY.md) on Overview, Treasury and Lending, at every width
 * of e2e/ux.config.ts: each screen leads with one plain sentence built from the API's own
 * figures, its visible headings use the cash owner's words, the mechanics (ids, formulas, raw
 * statuses) sit in a How we know disclosure that is closed by default and opens from the keyboard,
 * and the honesty labels stay visible. Read-only.
 *
 * The exact sentences come from the recorded baseline contracts/examples/c6_api/
 * valid-overview-demo-baseline.json (the handoff's numbers), served in place of the app's answer;
 * the app's own answers check that every amount in a sentence is the API's.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { settled } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const BASELINE = JSON.parse(readFileSync(join(__dirname, '../../contracts/examples/c6_api/valid-overview-demo-baseline.json'), 'utf-8')).instance

interface Money { minor: number | null, currency: string }
/** "USD 70,000.00", as the screens format integer minor units. */
const fmt = (m: Money) => `${m.currency} ${(m.minor! / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}`

/** The words a finance lead should not meet in a heading or a lead sentence (COPY.md rule 2). */
const JARGON = /\b(snapshot|branch|cohort|checkpoint|intent|provenance|policy)\b/i
const SYMBOL = /K_p|\((S|P)\)|(^|\s)(P|S)(?=[\s,.;:]|$)/

const technical = (text: string) => JARGON.test(text) || SYMBOL.test(text)

async function read (page: Page, path: string): Promise<any> {
  const reply = await page.request.get(`/api/v1${path}`)
  expect(reply.status(), `GET /api/v1${path}`).toBe(200)
  return reply.json()
}

async function open (page: Page, path: string): Promise<void> {
  await page.goto(path)
  await settled(page)
}

/** Words in a sentence, an amount ("USD 20,000.00") counting as one and a dash as none. */
const words = (text: string) => text.replace(/\b[A-Z]{3} (?=[\d-])/g, '').split(/\s+/).filter((w) => /\w/.test(w)).length

/** The lead: one short sentence, the first text of the screen, no jargon. */
async function leads (page: Page): Promise<string> {
  const lead = $(page, 'lead')
  await expect(lead).toBeVisible()
  const text = (await lead.textContent())!.trim()
  expect(words(text), `the lead is longer than 25 words: ${text}`).toBeLessThanOrEqual(25)
  expect(technical(text), `the lead uses a technical term: ${text}`).toBe(false)
  // nothing but the title and the shell's context comes before it
  const first = await page.evaluate(() => {
    const main = document.querySelector('main.lw-main [data-test="lead"]')
    const strip = document.querySelector('main.lw-main .lw-figure')
    return Boolean(main && (!strip || main.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING))
  })
  expect(first, 'the lead comes before every figure').toBe(true)
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

/** The screen's How we know disclosures: closed, keyboard-reachable, holding `facts`. */
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

test('Overview: the covered-until sentence from the baseline, plain strip, mechanics folded', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const own = await read(page, '/overview')
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: { ...BASELINE, demo: own.demo, scenario: own.scenario } }))
  await open(page, '/overview')
  expect(await leads(page)).toBe("You're covered until payroll on 2 Jan: USD 20,000.00 free now, and your lowest point " +
    'ahead is USD 40,000.00 — USD 10,000.00 above your USD 30,000.00 safety minimum.')
  for (const [key, label] of [['settled', 'Cash in the bank'], ['spendable', 'Free to spend now'], ['coverage', 'Room above your minimum']]) {
    await expect($(page, key).locator('.lw-tile__label')).toHaveText(label)
  }
  await expect($(page, 'coverage')).toContainText('lowest point ahead USD 40,000.00 · safety minimum USD 30,000.00')
  await expect($(page, 'floor-status')).toHaveText(/Above your safety minimum/)
  await expect($(page, 'lender-capacity')).toContainText('What the lender can still lend')
  await plainHeadings(page)

  // the ids are one click down, not on the page
  await expect($(page, 'context-snapshot')).not.toBeVisible()
  await folded(page, 'how-context', [BASELINE.snapshot_id, 'reserve floor', 'spendable S'])
  await folded(page, 'how-next', ['payroll-1', 'reserved · payroll-hold'])
  await folded(page, 'how-outlook', [BASELINE.snapshot_id, 'projected cash P'])
  await folded(page, 'how-exposure', ['K_p'])

  // honesty in plain words, visible
  await expect($(page, 'plain-mode')).toHaveText('Simulated bank connection')
  await expect($(page, 'plain-mode')).toBeVisible()
  await expect($(page, 'labels')).toContainText('Scripted agents')
  await expect($(page, 'hypothetical')).toHaveText('What-if')
  await expect($(page, 'hypothetical')).toBeVisible()
  // the judge path's button keeps its name
  await expect(page.locator('a[data-test="open-simulation"]')).toHaveText('Open simulation')
  expect(writes).toEqual([])
})

test('Overview: a broken floor leads with the day and the shortfall', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const coverage = {
    ...BASELINE.coverage,
    min_projected: { ...BASELINE.coverage.min_projected, minor: 2_500_000 },
    headroom: { ...BASELINE.coverage.headroom, minor: -500_000 }
  }
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: { ...BASELINE, coverage } }))
  await open(page, '/overview')
  expect(await leads(page)).toBe('Heads up: on 2 Jan you dip USD 5,000.00 below your USD 30,000.00 safety minimum.')
  await expect($(page, 'floor-status')).toHaveText(/Below your safety minimum/)
  expect(writes).toEqual([])
})

test("Overview: the app's own answer, every amount in the lead is the API's", async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await read(page, '/overview')
  await open(page, '/overview')
  const text = await leads(page)
  const headroom = body.coverage.headroom
  if (headroom.minor !== null && headroom.status !== 'unassessed' && headroom.minor < 0) {
    expect(text).toContain(`${fmt({ ...headroom, minor: -headroom.minor })} below your ${fmt(body.coverage.floor)} safety minimum`)
  } else if (headroom.status === 'known' && headroom.minor !== null) {
    expect(text).toContain(`${fmt(headroom)} above your ${fmt(body.coverage.floor)} safety minimum`)
    expect(text).toContain(`lowest point ahead is ${fmt(body.coverage.min_projected)}`)
    if (body.spendable.status === 'known') expect(text).toContain(`${fmt(body.spendable)} free now`)
  }
  expect(writes).toEqual([])
})

test('Treasury: in the bank, set aside, free to spend, from the selected account', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await read(page, '/treasury')
  await open(page, '/treasury')
  const account = body.accounts.find((a: any) => a.id.endsWith('/operating')) ?? body.accounts[0]
  const text = await leads(page)
  const b = account.buckets
  if (b.settled) expect(text).toContain(`${fmt(b.settled)} in the bank`)
  if (b.reserved.minor) {
    const kinds = body.obligations.filter((o: any) => o.account === account.id && o.reservation_id &&
      ['open', 'missed'].includes(o.state ?? 'open')).map((o: any) => o.kind.replace(/_/g, ' '))
    expect(text).toContain(`${fmt(b.reserved)} is set aside for ${kinds.length ? [...new Set(kinds)].join(' and ') : 'upcoming bills'}`)
  } else {
    expect(text).toContain('nothing is set aside')
  }
  if (account.spendable.minor !== null) expect(text).toContain(`so ${fmt(account.spendable)}`)
  expect(text).toMatch(/is free to spend\.$/)
  await expect(page.locator('#spend-heading')).toHaveText('Free to spend now')
  await expect($(page, 'bucket-settled').locator('summary')).toContainText('Cash in the bank')
  await expect($(page, 'bucket-reserved').locator('summary')).toContainText('Set aside')
  await expect($(page, 'floor').locator('.lw-tile__label')).toHaveText('Lowest point ahead · not spendable now')
  await plainHeadings(page)
  await folded(page, 'how-treasury', [body.snapshot_id, 'spendable S', 'reserve floor'])
  await folded(page, 'how-spendable', [account.id, `authority ${account.authority}`])
  await folded(page, 'how-handoff', [body.snapshot_id])
  // the hooks the older checks and the judge path read are all still there
  for (const hook of ['spendable', 'spend-calc', 'buckets', 'obligations', 'coverage', 'floor-status', 'timeline', 'rehearse']) {
    await expect($(page, hook)).toHaveCount(1)
  }
  expect(writes).toEqual([])
})

test('Lending: what the lender can still lend, then how; K_p one click down', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await read(page, '/lending')
  await open(page, '/lending')
  const text = await leads(page)
  const kp = body.capacity.K_p
  if (kp.minor === null) expect(text).toMatch(/unknown/)
  else expect(text).toMatch(new RegExp(`^Your lender can still lend you up to ${fmt(kp).replace(/[.]/g, '\\.')}`))
  await expect(page.locator('#capacity-heading')).toHaveText('What the lender can still lend')
  await expect($(page, 'parts').locator('[data-part="K_p"]')).toContainText('Left to lend')
  await expect($(page, 'parts').locator('[data-part="settled_known"]')).toContainText('Cash the lender holds')
  await plainHeadings(page)
  await expect($(page, 'authority')).not.toBeVisible()
  await folded(page, 'how-lending', [body.snapshot_id, 'K_p', `Balance authority ${body.capacity.authority}`])
  await expect($(page, 'freeze')).toContainText(body.capacity.authority === 'full' ? 'What-if' : 'Happening now')
  for (const hook of ['pool', 'capacity-value', 'capacity-status', 'parts', 'expand-calculation', 'evidence', 'relations', 'fund']) {
    await expect($(page, hook)).toHaveCount(1)
  }
  expect(writes).toEqual([])
})

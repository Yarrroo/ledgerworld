/**
 * Copy pass 1 (prp/2026-10-29-ux-pass/COPY.md) on Overview, Treasury and Lending, at every width
 * of e2e/ux.config.ts: each screen leads with one plain sentence built from the API's own
 * figures (now the hero subtitle's tooltip, prp/2026-10-29-ux-pass/MATCH.md item 1), its visible
 * headings use the cash owner's words, the mechanics (ids, formulas, raw statuses) sit in tooltips
 * or a How we know (i) that is closed by default and opens from the keyboard (MATCH.md items 2, 4),
 * and the honesty labels stay visible. Read-only.
 *
 * The exact sentences come from the recorded baseline contracts/examples/c6_api/
 * valid-overview-demo-baseline.json (the handoff's numbers), served in place of the app's answer;
 * the app's own answers check that every amount in a sentence is the API's.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { $, fmt, folded, lead, open, plainHeadings, read, technical, words } from './copy'

const BASELINE = JSON.parse(readFileSync(join(__dirname, '../../contracts/examples/c6_api/valid-overview-demo-baseline.json'), 'utf-8')).instance

/** The lead: one short sentence in the hero, before the screen's figures, no jargon. */
async function leads (page: Page, max = 25): Promise<string> {
  await expect(lead(page)).not.toBeEmpty()
  const text = (await lead(page).textContent())!.trim()
  // a stale reading's "last seen" sentence rides after the lead, as its own sentence
  const core = text.replace(/ ?Some figures were last seen [^.]*\.$/, '')
  expect(words(core), `the lead is longer than ${max} words: ${text}`).toBeLessThanOrEqual(max)
  expect(technical(text), `the lead uses a technical term: ${text}`).toBe(false)
  // nothing but the title and the shell's context comes before it
  const first = await page.evaluate(() => {
    const main = document.querySelector('main.lw-main [data-test="hero-lead"]')
    const strip = document.querySelector('main.lw-main .lw-figure')
    return Boolean(main && (!strip || main.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING))
  })
  expect(first, 'the lead comes before every figure').toBe(true)
  return text
}

/** Detail on demand: a tooltip, hidden until asked for, holding `facts`. */
async function tipped (tip: Locator, facts: string[]): Promise<void> {
  const body = tip.locator('[role="tooltip"]').first()
  await expect(body).toBeHidden()
  for (const fact of facts) await expect(body).toContainText(fact)
}

test('Overview: the covered-until sentence from the baseline, plain strip, mechanics folded', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const own = await read(page, '/overview')
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: { ...BASELINE, demo: own.demo, scenario: own.scenario } }))
  await open(page, '/overview')
  expect(await leads(page)).toBe("You're covered until payroll on 2 Jan: $20,000 free now, and your lowest point " +
    'ahead is $40,000 — $10,000 above your $30,000 safety minimum.')
  // the mockup's strip labels (MATCH.md 01)
  for (const [key, label] of [['settled', 'Settled cash'], ['spendable', 'Spendable now'], ['coverage', 'Reserve headroom']]) {
    await expect($(page, key).locator('.lw-ov-metric__label')).toHaveText(label)
  }
  await expect($(page, 'coverage')).toContainText('lowest point ahead $40,000 · safety minimum $30,000')
  await expect($(page, 'floor-status')).toHaveText(/Above your safety minimum/)
  await expect($(page, 'relations')).toContainText('Can lend $42,000')
  await plainHeadings(page)

  // the ids and formulas are in tooltips, not on the page
  await tipped($(page, 'how-context-bar'), [BASELINE.snapshot_id])
  await tipped($(page, 'tip-coverage'), ['reserve floor'])
  await tipped($(page, 'tip-spendable'), ['Settled − reserved − pledged'])
  await tipped($(page, 'next-obligation').locator('.lw-tip', { hasText: 'Yes' }), ['Held by reservation payroll-hold'])
  await expect($(page, 'open-treasury')).toHaveAttribute('href', /focus=obligation(%3A|:)payroll-1/)
  await expect($(page, 'outlook-point').first()).toHaveAttribute('aria-label', /projected cash/)
  await tipped($(page, 'relations').locator('.lw-tip', { hasText: 'Can lend' }), ['What it can still lend you'])
  const face = await page.locator('main.lw-main').innerText()
  expect(face).not.toContain('payroll-hold')
  expect(face).not.toContain('K_p')

  // honesty in plain words, visible
  await expect($(page, 'mode')).toHaveText(/^Simulated provider · Scripted agents/)
  await expect($(page, 'mode')).toBeVisible()
  await expect($(page, 'hypothetical')).toHaveText('Hypothetical')
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
  expect(await leads(page)).toBe('Heads up: on 2 Jan you dip $5,000 below your $30,000 safety minimum.')
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
    expect(text).toContain(`${fmt(b.reserved)} is set aside for `)
  } else {
    expect(text).toContain('nothing is set aside')
  }
  if (account.spendable.minor !== null && account.spendable.minor >= 0) {
    expect(text).toContain(`so ${fmt(account.spendable)}`)
    expect(text).toMatch(/is free to spend\.$/)
  }
  await expect(page.locator('#spend-heading')).toHaveText('Free to spend now')
  await expect($(page, 'bucket-settled').locator('summary')).toContainText('Cash in the bank')
  await expect($(page, 'bucket-reserved').locator('summary')).toContainText('Set aside')
  await expect($(page, 'floor').locator('.lw-tile__label')).toHaveText('Lowest point ahead')
  await plainHeadings(page)
  await folded(page, 'how-treasury', [body.snapshot_id, 'spendable S', 'reserve floor'])
  await folded(page, 'how-spendable', [account.id, `authority ${account.authority}`])
  await tipped($(page, 'rehearse-tip'), [body.snapshot_id]) // the hand-off to Simulation names its snapshot
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
  else expect(text).toMatch(new RegExp(`^Your lender can still lend you up to ${fmt(kp).replace(/[$.]/g, '\\$&')}`))
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

/** The baseline overview with some of its figures replaced. */
async function serveOverview (page: Page, change: (body: any) => any): Promise<void> {
  const body = change(structuredClone(BASELINE))
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: body }))
}

test('Overview: a shortfall is never free money, stale figures say when they were seen, unknown reads as words', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  // spendable below zero while the floor holds
  await serveOverview(page, (b) => ({ ...b, spendable: { ...b.spendable, minor: -1_000_000 } }))
  await open(page, '/overview')
  let text = await leads(page)
  expect(text).toContain('nothing free now ($10,000 short)')
  expect(text).not.toMatch(/-\$|-\d|−/)
  await page.unroute('**/api/v1/overview')

  // every figure stale: no tag inside the sentence, one last-seen sentence after it
  const at = '2026-01-01T00:00:00Z'
  await serveOverview(page, (b) => {
    const stale = (m: any) => ({ ...m, status: 'stale', as_of: at })
    return { ...b, spendable: stale(b.spendable), coverage: { ...b.coverage, floor: stale(b.coverage.floor),
      min_projected: stale(b.coverage.min_projected), headroom: stale(b.coverage.headroom) } }
  })
  await open(page, '/overview')
  text = await leads(page)
  expect(text).not.toContain('stale')
  expect(text).toMatch(/\. Some figures were last seen 2026-01-01 00:00 UTC\.$/)
  await page.unroute('**/api/v1/overview')

  // a stale breach: the shortfall in words, the last-seen line beside it
  await serveOverview(page, (b) => ({ ...b, coverage: { ...b.coverage,
    headroom: { ...b.coverage.headroom, minor: -500_000, status: 'stale', as_of: at } } }))
  await open(page, '/overview')
  expect(await leads(page)).toBe('Heads up: on 2 Jan you dip $5,000 below your $30,000 safety minimum. ' +
    'Some figures were last seen 2026-01-01 00:00 UTC.')
  await page.unroute('**/api/v1/overview')

  // nothing known: a sentence that starts like one
  await serveOverview(page, (b) => {
    const unknown = (m: any) => ({ ...m, minor: null, status: 'unknown', as_of: null })
    return { ...b, spendable: unknown(b.spendable), coverage: { ...b.coverage, headroom: unknown(b.coverage.headroom) } }
  })
  await open(page, '/overview')
  text = await leads(page)
  expect(text).toMatch(/^[A-Z]/)
  expect(text).toContain('an unknown amount free now')
  expect(text).not.toContain('last seen')
  expect(writes).toEqual([])
})

test('Treasury: a shortfall is not free to spend; every reservation names what it is for', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await read(page, '/treasury')
  const account = body.accounts.find((a: any) => a.id.endsWith('/operating')) ?? body.accounts[0]
  const changed = structuredClone(body)
  const mine = changed.accounts.find((a: any) => a.id === account.id)
  const currency = account.currency
  mine.spendable = { ...mine.spendable, minor: -1_000_000, status: 'known', currency }
  mine.buckets.reserved = { currency, minor: 7_000_000 }
  // two obligations and one pending outflow, each held by its own reservation
  changed.obligations = [
    ...changed.obligations.filter((o: any) => o.account !== account.id),
    { account: account.id, amount: { currency, minor: 5_000_000 }, due_at: body.as_of, entity: 'x', kind: 'payroll',
      mandatory: true, obligation_id: 'payroll-x', reservation_id: 'hold-payroll', state: 'open' },
    { account: account.id, amount: { currency, minor: 1_000_000 }, due_at: body.as_of, entity: 'x', kind: 'rent',
      mandatory: true, obligation_id: 'rent-x', reservation_id: 'hold-rent', state: 'open' }
  ]
  mine.buckets.pending_out = [{ amount: { currency, minor: 1_000_000 }, expected_at: body.as_of, flow_id: 'supplier-x',
    kind: 'supplier_payment', reservation_id: 'hold-supplier' }]
  await page.route('**/api/v1/treasury', (route) => route.fulfill({ json: changed }))
  await open(page, '/treasury')
  const text = await leads(page)
  expect(text).toContain(`${fmt({ currency, minor: 7_000_000 })} is set aside for payroll, rent and supplier payment`)
  expect(text).toMatch(new RegExp(`so nothing is free to spend: you are ${fmt({ currency, minor: 1_000_000 }).replace(/[$.]/g, '\\$&')} short\\.$`))
  expect(text).not.toMatch(/-\$|-\d/)
  expect(writes).toEqual([])
})

test('Lending: a capacity at or below zero says the lender cannot lend', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const body = await read(page, '/lending')
  const changed = structuredClone(body)
  changed.capacity.K_p = { ...changed.capacity.K_p, minor: -500_000, status: 'known' }
  await page.route('**/api/v1/lending', (route) => route.fulfill({ json: changed }))
  await open(page, '/lending')
  expect(await leads(page)).toBe('Your lender cannot lend you anything right now; here is how that number is worked out.')
  expect(writes).toEqual([])
})

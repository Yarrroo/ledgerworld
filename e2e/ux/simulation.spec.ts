/**
 * Live simulation in motion (prp/2026-10-29-ux-pass/HANDOFF.md S1–S6), at every width of
 * e2e/ux.config.ts, on the prepared demonstration run: the run and scenario context with the
 * read-only scenario settings; the world map where selecting an actor — on the map, in the
 * keyboard actor list or from the feed — syncs the inspector and the feed highlight (a
 * full-height sheet on a phone); an edge opening its evidence; one committed-round cursor shared
 * by scrubber, feed, inspector, map and cash (arrows, Home, End; round n = 4n h); fork asking
 * first and naming its checkpoint and policies; Compare policies opening Decisions. Read-only:
 * the fork is never confirmed here.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { crumb, demoRunId, settled, sideways } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const isPhone = (width: number) => width < 768

async function open (page: Page, runId: string): Promise<void> {
  await page.goto(`/simulation?run_id=${runId}`)
  await settled(page)
  await expect(crumb(page)).toHaveText('Simulation')
  await expect($(page, 'error')).toHaveCount(0)
  await expect($(page, 'scrubber-slider')).toHaveAttribute('aria-valuenow', /^\d+$/)
}

test('S1: run context and the read-only scenario settings', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const run = await (await request.get(`/api/v1/runs/${runId}`)).json()
  await open(page, runId)

  const context = $(page, 'run-context')
  await expect($(page, 'run-id')).toHaveText(runId)
  const base = run.branches.find((b: { parent_branch_id: string | null }) => b.parent_branch_id === null)
  await expect(context).toContainText(base.branch_id)
  await expect(context).toContainText(/Fresh run|Replay/)
  await expect(context).toContainText('Simulated provider')
  const forks = run.branches.filter((b: { checkpoint_round: number | null }) => b.checkpoint_round !== null)
  if (forks.length) await expect(context).toContainText(`round ${forks[0].checkpoint_round}`)

  const opener = $(page, 'settings')
  await opener.click()
  const sheet = $(page, 'settings-sheet')
  await expect(sheet).toBeVisible()
  await expect(sheet.locator('[data-family]')).toHaveCount(6)
  for (const id of ['delayed-receipt', 'fx-gap', 'stablecoin-depeg', 'redemption-spike', 'borrower-silence', 'confidence-rumour']) {
    await expect(sheet.locator(`[data-family="${id}"]`)).toBeVisible()
  }
  const family = (await $(page, 'family').textContent())!.trim() // folded in How we know
  if (family !== 'not named by this run') await expect(sheet.locator(`[data-family="${family}"]`)).toContainText('this run')
  await expect(sheet).toContainText('Read-only')
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  await expect(opener).toBeFocused()
  expect(await sideways(page), 'Live simulation scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('S2–S4: one selected actor drives map, inspector and feed; an edge opens its evidence', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  await open(page, runId)

  // The keyboard actor list lives in Source evidence.
  await page.locator('.lw-sim__source').click()
  const lender = page.locator('[data-actor="lender"]')
  await lender.focus()
  await page.keyboard.press('Enter')
  await expect(lender).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[data-test="map-node"][data-node="lender"]')).toHaveAttribute('aria-pressed', 'true')
  const detail = $(page, 'actor-detail')
  await expect(detail).toBeVisible()
  await expect(detail).toContainText('What changed')
  // Actor metadata is on demand; the timeline remains inline at every width.
  await expect(page.locator('[data-test="how-actor"]')).toContainText('lender pool')
  const highlighted = page.locator('[data-test="feed"] .is-highlight')
  for (const item of await highlighted.all()) await expect(item).toContainText('lender')

  // the map: a node selects its actor, and the list follows
  const treasury = page.locator('[data-test="map-node"][data-node="treasury"]')
  await treasury.click()
  await expect(treasury).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[data-actor="treasury"]')).toHaveAttribute('aria-pressed', 'true')
  await expect(detail).toContainText('Northwind')
  await expect($(page, 'inspector')).toBeVisible()

  // canonical edges: pool → Borrower B via line-b; no Treasury–Borrower B credit
  const edges = await page.locator('[data-test="map-edge"]').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''))
  expect(edges.some((e) => /^financial edge, Harbourline Credit pool to Bellfield Kitchens: line-b/.test(e))).toBe(true)
  expect(edges.filter((e) => /^financial edge, (Northwind Parts treasury to Bellfield|Bellfield Kitchens to Northwind)/.test(e))).toEqual([])
  expect(edges.filter((e) => /^financial edge, Ledger Street Wire/.test(e)), 'a feed edge is drawn as cash').toEqual([])

  // an edge opens its evidence, and gives focus back
  const edge = page.locator('[data-test="map-edge"][data-edge="contract:line-b"]')
  await edge.focus()
  await page.keyboard.press('Enter')
  const evidence = $(page, 'evidence-sheet')
  await expect(evidence).toBeVisible()
  await expect(evidence.locator('[data-test="evidence-detail"]')).toContainText('line-b')
  await page.keyboard.press('Escape')
  await expect(evidence).toBeHidden()
  await expect(edge).toBeFocused()

  // a feed item selects its actor and opens its evidence
  const pick = page.locator('[data-test="feed"] [data-test="feed-open"]').first()
  if (await pick.count()) {
    const who = (await pick.innerText()).trim()
    await pick.click()
    await expect(evidence).toBeVisible()
    await expect(evidence.locator('[data-test="evidence-detail"]')).toContainText('Journal')
    await page.keyboard.press('Escape')
    await expect(page.locator(`[data-actor="${who}"]`)).toHaveAttribute('aria-pressed', 'true')
    for (const item of await highlighted.all()) await expect(item).toContainText(who)
  }
  expect(await sideways(page), 'Live simulation scrolls sideways').toBeLessThanOrEqual(0)
  expect(writes).toEqual([])
})

test('S5: one committed-round cursor; arrows, Home and End; round n is 4n h', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const run = await (await request.get(`/api/v1/runs/${runId}`)).json()
  await open(page, runId)
  const last = run.committed_round
  const slider = $(page, 'scrubber-slider')

  const atRound = async (n: number) => {
    await expect(slider).toHaveAttribute('aria-valuenow', String(n))
    await expect($(page, 'cursor')).toHaveText(new RegExp(`^Round ${n} of 18 · ${4 * n}h simulated$`))
    await expect(page.locator('#feed-title')).toContainText(`Action feed · round ${n}`)
    await expect($(page, 'selected-round')).toHaveText(`Selected actor · Round ${n}`)
    await expect(page.locator('.lw-cash-values > summary')).toContainText(`Round ${n}`)
    await expect($(page, 'graph')).toContainText(`Market relationships at round ${n}`)
  }
  await atRound(last)
  await slider.focus()
  await page.keyboard.press('Home')
  await atRound(1)
  await page.keyboard.press('ArrowRight')
  await atRound(2)
  await page.keyboard.press('End')
  await atRound(last)
  await page.keyboard.press('ArrowLeft')
  await atRound(last - 1)
  expect(writes).toEqual([])
})

test('S6: fork asks first and names its checkpoint and policies; Compare opens Decisions', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  await open(page, runId)
  const round = await $(page, 'scrubber-slider').getAttribute('aria-valuenow')

  const fork = $(page, 'fork')
  if (await fork.isDisabled()) {
    await expect($(page, 'fork-why')).toHaveText(/\w/)
  }
  await $(page, 'token').fill('not-a-real-token')
  await expect($(page, 'forget')).toBeVisible()
  if (!(await fork.isDisabled())) {
    await fork.click()
    const panel = $(page, 'fork-confirm-panel')
    await expect(panel).toContainText(`at committed round ${round} into no-action, fixed-reserve, integrated`)
    await expect(panel).toContainText('creates no approval')
    await $(page, 'fork-cancel').click()
    await expect(panel).toBeHidden()
  }
  // Forget access clears it from the tab
  await $(page, 'forget').click()
  await expect($(page, 'token')).toHaveValue('')
  await expect(fork).toBeDisabled()
  await expect($(page, 'fork-why')).toHaveText(/^Enter operator access to fork\.?$/)

  await page.locator('a[data-test="compare"]').click()
  await expect(page).toHaveURL(/\/decisions\?/)
  expect(new URL(page.url()).searchParams.get('run_id')).toBe(runId)
  await settled(page)
  expect(writes, 'the fork was sent').toEqual([])
})

test('phone reading order: map and actor, round control, cash, folded source evidence', async ({ page, request }, info) => {
  test.skip(!isPhone(info.project.use.viewport!.width), 'the phone order')
  await open(page, await demoRunId(request))
  const top = async (selector: string) => (await page.locator(selector).first().boundingBox())!.y
  const order = [await top('[data-test="map"]'), await top('[data-test="inspector"]'),
    await top('[data-test="controls"]'), await top('[data-test="cash"]'), await top('#simulation-evidence')]
  expect([...order].sort((a, b) => a - b)).toEqual(order)
})

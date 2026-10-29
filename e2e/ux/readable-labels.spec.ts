/**
 * Labels a reader can read, at every width of e2e/ux.config.ts, on the prepared demonstration
 * run: the Simulation map's edge captions overlap no node box, no other caption and no edge of
 * the map, and a node shows its actor's name (never its id) inside its box; the actor list and
 * the cash-path rows lead with names and policies, ids second, a name never broken mid-word;
 * Treasury prints flow and obligation kinds as words, never a raw `snake_case` kind. Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { PLANS } from './copy'
import { demoRunId, settled } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)

type Box = { x: number, y: number, width: number, height: number }
const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
const inside = (a: Box, b: Box) =>
  a.x >= b.x - 0.5 && a.y >= b.y - 0.5 && a.x + a.width <= b.x + b.width + 0.5 && a.y + a.height <= b.y + b.height + 0.5

async function simulation (page: Page, runId: string): Promise<void> {
  await page.goto(`/simulation?run_id=${runId}`)
  await settled(page)
  await expect($(page, 'error')).toHaveCount(0)
  await expect($(page, 'map-node').first()).toBeVisible()
}

test('the map: captions clear the nodes, each other and the frame; nodes show names', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  await simulation(page, await demoRunId(request))
  const frame = (await page.locator('[data-test="map"] svg').boundingBox())!
  const nodes = await $(page, 'map-node').all()
  const boxes: Box[] = []
  for (const node of nodes) {
    const id = (await node.getAttribute('data-node'))!
    const box = (await node.locator('rect').boundingBox())!
    const name = node.locator('text').first()
    const text = (await name.textContent())!.trim()
    const aria = (await node.getAttribute('aria-label'))!
    // the node's own name from its accessible name ("Harbourline Credit, lender"), never the id
    if (!aria.startsWith(`${id},`) && aria !== id) expect(text, `node ${id} shows its id`).not.toBe(id)
    expect(inside((await name.boundingBox())!, box), `node ${id}'s name "${text}" draws past its box`).toBe(true)
    boxes.push(box)
  }

  const captions = await page.locator('[data-test="map"] .lw-map__edge-label').all()
  if (frame.width >= 600) expect(captions.length, 'no edge caption drawn on a wide map').toBeGreaterThan(0)
  const placed: Array<Box & { text: string }> = []
  for (const caption of captions) {
    const text = (await caption.textContent())!.trim()
    const box = (await caption.boundingBox())!
    expect(text, 'a caption ends cut at a separator').not.toMatch(/[·:,-]$/)
    expect(inside(box, frame), `caption "${text}" is clipped by the map's edge`).toBe(true)
    boxes.forEach((b, i) => expect(overlaps(box, b), `caption "${text}" is drawn over node ${i}`).toBe(false))
    for (const other of placed) expect(overlaps(box, other), `caption "${text}" overlaps "${other.text}"`).toBe(false)
    placed.push({ ...box, text })
  }
  expect(writes).toEqual([])
})

test('the actor list and the cash paths lead with names, ids second', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const run = await (await request.get(`/api/v1/runs/${runId}`)).json()
  await simulation(page, runId)

  const actors = await page.locator('[data-actor]').all()
  expect(actors.length).toBeGreaterThan(0)
  for (const button of actors) {
    const id = (await button.getAttribute('data-actor'))!
    const [first, ...rest] = (await button.innerText()).split('\n').map((l) => l.trim()).filter(Boolean)
    const named = (await page.locator(`[data-test="map-node"][data-node="${id}"]`).getAttribute('aria-label')) ?? id
    expect(first, `actor ${id} does not lead with its name`).toBe(named.split(',')[0])
    expect(rest.join(' '), `actor ${id}'s id is not shown second`).toContain(id)
  }

  for (const branch of run.branches) {
    const row = page.locator(`.lw-cash__row[data-branch="${branch.branch_id}"]`)
    const name = row.locator('.lw-cash__branch')
    const lead = (await name.textContent())!.trim()
    expect(lead, `cash row ${branch.branch_id} leads with the raw id`).not.toContain(branch.branch_id)
    if (branch.policy) expect(lead).toBe(PLANS[branch.policy] ?? branch.policy) // the plan's plain name
    // a name on one line: never broken mid-word
    expect(await name.evaluate((el) => el.getClientRects().length), `"${lead}" wraps`).toBe(1)
    await expect(row.locator('.lw-cash__account')).toContainText(branch.branch_id)
  }
  expect(writes).toEqual([])
})

test('Treasury prints kinds as words', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  await page.goto('/treasury')
  await settled(page)
  await expect($(page, 'error')).toHaveCount(0)
  await expect($(page, 'obligations')).toBeVisible()
  const raw = /\b[a-z]+_[a-z_]+\b/
  for (const id of ['obligations', 'calculation', 'coverage']) {
    const where = $(page, id)
    if (!(await where.count())) continue
    expect((await where.first().textContent()) ?? '', `a raw kind on Treasury's ${id}`).not.toMatch(raw)
  }
  for (const bucket of await page.locator('[data-test^="bucket-"]').all()) {
    expect((await bucket.textContent()) ?? '', 'a raw kind in a cash bucket').not.toMatch(raw)
  }
  expect(writes).toEqual([])
})

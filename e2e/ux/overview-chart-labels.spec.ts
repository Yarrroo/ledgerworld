/**
 * The cash outlook's labels at every width of e2e/ux.config.ts: the low-point label never crosses
 * the dashed reserve-floor line, the floor label, the step line P or any point marker. Three
 * answers: the app's own, the recorded baseline (P lowest at 40,000 against a 30,000 floor, the
 * h48 point just above and to the right), and the baseline with its lowest point moved just above
 * the floor and near the right edge, under the floor label. Read-only.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { settled } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const BASELINE = JSON.parse(readFileSync(join(__dirname, '../../contracts/examples/c6_api/valid-overview-demo-baseline.json'), 'utf-8')).instance

type Box = { x: number, y: number, width: number, height: number }
const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

async function live (page: Page): Promise<any> {
  const reply = await page.request.get('/api/v1/overview')
  expect(reply.status(), 'GET /api/v1/overview').toBe(200)
  return reply.json()
}

/** The baseline, with the app's own run and scenario, its outlook changed by `edit`. */
async function serve (page: Page, edit: (body: any) => void = () => {}): Promise<void> {
  const own = await live(page)
  const body = structuredClone({ ...BASELINE, demo: own.demo, scenario: own.scenario })
  edit(body)
  await page.route('**/api/v1/overview', (route) => route.fulfill({ json: body }))
}

async function clear (page: Page): Promise<void> {
  await page.goto('/overview')
  await settled(page)
  const label = (await $(page, 'outlook-low-label').boundingBox())!
  const floor = (await $(page, 'outlook-floor').boundingBox())!
  const floorLabel = (await $(page, 'outlook-floor-label').boundingBox())!
  const lineY = floor.y + floor.height / 2
  expect(lineY > label.y && lineY < label.y + label.height,
    `the low-point label (y ${label.y}–${label.y + label.height}) crosses the floor line at y ${lineY}`).toBe(false)
  expect(overlaps(label, floorLabel), 'the low-point label overlaps the floor label').toBe(false)
  const markers = page.locator('[data-test="outlook-chart"] .lw-outlook__dot')
  expect(await markers.count(), 'no point markers drawn').toBeGreaterThan(0)
  for (let n = 0; n < await markers.count(); n++) {
    const marker = (await markers.nth(n).boundingBox())!
    expect(overlaps(label, marker), `the low-point label overlaps point marker ${n} at x ${marker.x}`).toBe(false)
  }
  // the step line, sampled along its length in viewport coordinates (boundingBox's): no sample
  // inside the label
  const crossing = await $(page, 'outlook-line').evaluate((path: SVGPathElement, box: Box) => {
    const m = path.getScreenCTM()!
    const total = path.getTotalLength()
    for (let at = 0; at <= total; at += 1) {
      const { x, y } = path.getPointAtLength(at).matrixTransform(m)
      if (x > box.x && x < box.x + box.width && y > box.y && y < box.y + box.height) return { x, y }
    }
    return null
  }, label)
  expect(crossing, `the low-point label sits on the step line at ${JSON.stringify(crossing)}`).toBeNull()
}

test('the app\'s own answer: the low-point label clears the floor line and its label', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  await clear(page)
  expect(writes).toEqual([])
})

test('the baseline: lowest 40,000 over a 30,000 floor, the label clears both', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  await serve(page)
  await clear(page)
  expect(writes).toEqual([])
})

test('lowest just above the floor, near the right edge: the label clears both', async ({ page, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  await serve(page, (body) => {
    // the lowest point moves to the last time, 1,000 above the floor
    const last = body.outlook[body.outlook.length - 1]
    last.value = { ...last.value, minor: body.coverage.floor.minor + 100_000 }
    body.coverage.at = last.t
    body.coverage.min_projected = { ...body.coverage.min_projected, minor: last.value.minor }
  })
  await clear(page)
  expect(writes).toEqual([])
})

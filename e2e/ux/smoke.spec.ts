/**
 * Smoke: each of the six finance routes opens on the prepared demonstration run, at every width
 * of e2e/ux.config.ts, reads its context from the API, and does not scroll sideways. Read-only.
 */
import { expect, test } from '@playwright/test'
import { readOnly } from '../guard'

const ROUTES = [
  { path: '/overview', title: 'Overview' },
  { path: '/treasury', title: 'Treasury' },
  { path: '/lending', title: 'Lending' },
  { path: '/simulation', title: 'Live simulation', run: true },
  { path: '/decisions', title: 'Decisions', run: true },
  { path: '/execution', title: 'Execution', run: true }
]

test('the six routes open on the prepared run', async ({ page, request, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const overview = await request.get('/api/v1/overview')
  expect(overview.status()).toBe(200)
  const runId: string | null = (await overview.json()).demo?.run_id ?? null
  expect(runId, 'the app names no prepared demonstration run').toBeTruthy()

  for (const route of ROUTES) {
    const response = await page.goto(route.run ? `${route.path}?run_id=${runId}` : route.path)
    expect(response?.status(), route.path).toBe(200)
    await expect(page.locator('h1'), route.path).toHaveText(route.title)
    await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
    await expect(page.locator('[data-test="mode"]').first()).toHaveText(/Simulated provider/)
    await expect(page.locator('[data-test="error"]'), `${route.path} shows a load error`).toHaveCount(0)
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `${route.path} scrolls sideways`).toBeLessThanOrEqual(0)
  }
  expect(writes, 'the smoke walk sent a write').toEqual([])
})

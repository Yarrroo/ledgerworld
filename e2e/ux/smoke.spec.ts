/**
 * Smoke: each of the six finance routes opens on the prepared demonstration run, at every width
 * of e2e/ux.config.ts, reads its context from the API, and does not scroll sideways. Read-only.
 */
import { expect, test } from '@playwright/test'
import { readOnly } from '../guard'
import { ROUTES, crumb, demoRunId, settled, sideways, urlOf } from './routes'

test('the six routes open on the prepared run', async ({ page, request, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)

  for (const route of ROUTES) {
    const response = await page.goto(urlOf(route, runId))
    expect(response?.status(), route.path).toBe(200)
    await expect(crumb(page), route.path).toHaveText(route.title)
    await expect(page.locator('h1'), route.path).toHaveText(route.headline)
    await settled(page)
    await expect(page.locator('[data-test="mode"]').first(), route.path).toHaveText(/^Simulated provider · Scripted agents/)
    await expect(page.locator('[data-test="error"]'), `${route.path} shows a load error`).toHaveCount(0)
    expect(await sideways(page), `${route.path} scrolls sideways`).toBeLessThanOrEqual(0)
  }
  expect(writes, 'the smoke walk sent a write').toEqual([])
})

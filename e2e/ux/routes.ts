/** The six finance routes and the steps every interaction check shares. */
import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const ROUTES = [
  { path: '/overview', title: 'Overview', run: false },
  { path: '/treasury', title: 'Treasury', run: false },
  { path: '/lending', title: 'Lending', run: false },
  { path: '/simulation', title: 'Live simulation', run: true },
  { path: '/decisions', title: 'Decisions', run: true },
  { path: '/execution', title: 'Execution', run: true }
] as const

export type Route = typeof ROUTES[number]

/** The prepared demonstration run the app names on Overview; the check fails when there is none. */
export async function demoRunId (request: APIRequestContext): Promise<string> {
  const reply = await request.get('/api/v1/overview')
  expect(reply.status(), 'GET /api/v1/overview').toBe(200)
  const runId: string | null = (await reply.json()).demo?.run_id ?? null
  expect(runId, 'the app names no prepared demonstration run').toBeTruthy()
  return runId!
}

/** A route's URL, on the demonstration run where the screen reads one. */
export const urlOf = (route: Route, runId: string): string =>
  route.run ? `${route.path}?run_id=${runId}` : route.path

/** The screen has its answer: the main region is no longer busy. */
export async function settled (page: Page): Promise<void> {
  await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
}

/** How far the page scrolls sideways; 0 or less when it does not. */
export const sideways = (page: Page): Promise<number> =>
  page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)

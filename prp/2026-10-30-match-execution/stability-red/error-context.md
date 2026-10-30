# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: match-execution.spec.ts >> Execution matches mockup 06
- Location: ux/match-execution.spec.ts:32:5

# Error details

```
Error: expect(locator).toHaveAttribute(expected) failed

Locator:  locator('main.lw-main')
Expected: "false"
Received: "true"
Timeout:  30000ms

Call log:
  - Expect "toHaveAttribute" locator('main.lw-main') with timeout 30000ms
  - waiting for locator('main.lw-main')
    63 × locator resolved to <main class="lw-main" aria-busy="true">…</main>
       - unexpected value "true"

```

```yaml
- main:
  - navigation "Breadcrumb"
  - text: Provider not loaded
  - heading "From approved plan to proof." [level=1]
  - status: Loading Execution…
```

# Test source

```ts
  1  | /**
  2  |  * The six finance routes and the steps every interaction check shares. `title` is the breadcrumb's
  3  |  * and the sidebar's name; `headline` is the page hero's (prp/2026-10-29-ux-pass/MATCH.md, item 1).
  4  |  */
  5  | import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'
  6  | 
  7  | export const ROUTES = [
  8  |   { path: '/overview', title: 'Overview', headline: 'Know your cash. Rehearse the risk.', run: false },
  9  |   { path: '/treasury', title: 'Treasury', headline: 'Every dollar, accounted for.', run: false },
  10 |   { path: '/lending', title: 'Lending', headline: 'Capacity you can rely on.', run: false },
  11 |   { path: '/simulation', title: 'Simulation', headline: 'See the crisis before it spreads.', run: true },
  12 |   { path: '/decisions', title: 'Decisions', headline: 'Protect payroll. Preserve your reserve.', run: true },
  13 |   { path: '/execution', title: 'Execution', headline: 'From approved plan to proof.', run: true }
  14 | ] as const
  15 | 
  16 | export type Route = typeof ROUTES[number]
  17 | 
  18 | /** The prepared demonstration run the app names on Overview; the check fails when there is none. */
  19 | export async function demoRunId (request: APIRequestContext): Promise<string> {
  20 |   const reply = await request.get('/api/v1/overview')
  21 |   expect(reply.status(), 'GET /api/v1/overview').toBe(200)
  22 |   const runId: string | null = (await reply.json()).demo?.run_id ?? null
  23 |   expect(runId, 'the app names no prepared demonstration run').toBeTruthy()
  24 |   return runId!
  25 | }
  26 | 
  27 | /** A route's URL, on the demonstration run where the screen reads one. */
  28 | export const urlOf = (route: Route, runId: string): string =>
  29 |   route.run ? `${route.path}?run_id=${runId}` : route.path
  30 | 
  31 | /** The screen has its answer: the main region is no longer busy. */
  32 | export async function settled (page: Page): Promise<void> {
> 33 |   await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
     |                                              ^ Error: expect(locator).toHaveAttribute(expected) failed
  34 | }
  35 | 
  36 | /** How far the page scrolls sideways; 0 or less when it does not. */
  37 | export const sideways = (page: Page): Promise<number> =>
  38 |   page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  39 | 
  40 | /** The screen the page is on: the breadcrumb's current item. */
  41 | export const crumb = (page: Page) => page.locator('[data-test="breadcrumb"] [aria-current="page"]')
  42 | 
  43 | /**
  44 |  * Open a tooltip the way this width's reader would (hover, or tap on a touch screen), close it,
  45 |  * open it again by keyboard focus and close it with Escape (prp/2026-10-29-ux-pass/MATCH.md, item 4).
  46 |  */
  47 | export async function tipWorks (page: Page, trigger: Locator, touch: boolean, what: string): Promise<void> {
  48 |   const tip = trigger.locator('xpath=ancestor-or-self::*[contains(concat(" ", @class, " "), " lw-tip ")][1]')
  49 |   const bubble = tip.locator(':scope > [role="tooltip"]')
  50 |   await trigger.scrollIntoViewIfNeeded()
  51 |   await expect(bubble, `${what}: shown before it is asked for`).toBeHidden()
  52 |   if (touch) {
  53 |     await trigger.tap()
  54 |   } else {
  55 |     await trigger.hover()
  56 |   }
  57 |   await expect(bubble, `${what}: does not open on ${touch ? 'tap' : 'hover'}`).toBeVisible()
  58 |   await page.mouse.move(0, 0)
  59 |   await page.keyboard.press('Escape')
  60 |   await page.locator('h1').click()
  61 |   await expect(bubble, `${what}: does not close`).toBeHidden()
  62 |   await trigger.focus()
  63 |   await expect(bubble, `${what}: does not open on focus`).toBeVisible()
  64 |   await page.keyboard.press('Escape')
  65 |   await expect(bubble, `${what}: Escape does not close it`).toBeHidden()
  66 | }
  67 | 
```
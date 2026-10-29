/**
 * Design match 0 (prp/2026-10-29-ux-pass/MATCH.md, shared items 1–8) on all six finance screens,
 * at every width of e2e/ux.config.ts:
 *
 * - the page hero: the mockup's serif headline as the page's one h1, a one-line subtitle, and at
 *   most one primary button, the journey's next step (item 1, 7);
 * - gone from the visible page: the panel-index tab row, chip rows, "How we know" links, "Check
 *   again", Refresh, and the prepared run's ids (item 2);
 * - the header and sidebar as the mockups: "LedgerWorld / Page", "Simulated provider · Scripted
 *   agents", the date, "Snapshot … · USD · Synthetic data", "Simulation" in the sidebar and the
 *   company block (item 3);
 * - tooltips on every screen, and the one tooltip's behaviour: hover, keyboard focus and tap open
 *   it, Escape and a second tap close it, and it never covers the value it explains (item 4);
 * - the word budget: each screen's visible words at 1487 px are measured and written to
 *   UX_OUT/word-counts.json for checks/word_budget.py; Overview, rebuilt to its mockup, is held to
 *   its budget here (item 8; the other screens' rebuilds are their own items and hold theirs).
 *
 * Read-only.
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { ROUTES, crumb, demoRunId, settled, sideways, urlOf } from './routes'
import { visibleWords, wordBudget } from './words'

/** The hero's one action per screen (MATCH.md item 7); null where the mockup's hero has none. */
const ACTION: Record<string, RegExp | null> = {
  '/overview': /^Open simulation$/,
  '/treasury': /^Rehearse a cash shock$/,
  '/lending': /^Compare funding plans$/,
  '/simulation': /^Compare policies$/,
  '/decisions': /^Review current plan$/,
  '/execution': /^Review plan$/
}
const SIDEBAR = ['Overview', 'Treasury', 'Lending', 'Simulation', 'Decisions', 'Execution']
const NOISE = /How we know|Check again|^Refresh$/

const bubble = (tip: Locator): Locator => tip.locator('[role="tooltip"]')

/** The visible texts of every element matching `selector`. */
async function shown (page: Page, selector: string): Promise<string[]> {
  return page.locator(selector).evaluateAll((els) => els
    .filter((el) => (el as HTMLElement).checkVisibility() && el.getBoundingClientRect().width > 1)
    .map((el) => (el as HTMLElement).innerText.trim()))
}

test('the shared page: hero, header, sidebar, no noise, tooltips', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const width = info.project.use.viewport!.width

  for (const route of ROUTES) {
    await page.goto(urlOf(route, runId))
    await settled(page)
    const where = `${route.path} at ${width}`

    // item 1, 7: the hero
    await expect(page.locator('h1'), where).toHaveCount(1)
    await expect(page.locator('h1'), where).toHaveText(route.headline)
    await expect(page.locator('[data-test="hero-subtitle"]'), where).not.toBeEmpty()
    const actions = page.locator('[data-test="hero-action"] :is(a, button)')
    const action = ACTION[route.path]
    if (action) {
      await expect(actions, where).toHaveCount(1)
      await expect(actions.first(), where).toBeVisible()
      expect((await actions.first().innerText()).trim(), where).toMatch(action)
    } else {
      await expect(actions, where).toHaveCount(0)
    }

    // item 2: the noise is gone
    await expect(page.locator('[data-test="panel-index"]'), where).toHaveCount(0)
    expect(await shown(page, '.lw-tag, .lw-labels, .lw-live-tag'), `${where}: chip rows`).toEqual([])
    const controls = await shown(page, 'main a, main button, main summary')
    expect(controls.filter((t) => NOISE.test(t)), `${where}: How we know, Check again or Refresh`).toEqual([])
    const text = await page.locator('main').innerText()
    expect(text, `${where}: the run id is on the page`).not.toContain(runId)
    expect(text, `${where}: "Known as of" lines`).not.toMatch(/Known as of/)

    // item 3: header and sidebar
    await expect(crumb(page), where).toHaveText(route.title)
    await expect(page.locator('[data-test="breadcrumb"] li').first(), where).toHaveText('LedgerWorld')
    await expect(page.locator('[data-test="mode"]'), where).toHaveText(/^Simulated provider · Scripted agents/)
    await expect(page.locator('[data-test="context-as-of"]'), where).toHaveText(/^[A-Z][a-z]+ \d{1,2}, \d{4}$/)
    await expect(page.locator('[data-test="context-line"]'), where).toHaveText(/^Snapshot \S+ · USD · (Synthetic data|What-if branch|Replay)$/)
    const nav = page.locator('nav.lw-nav ul a')
    await expect(nav, where).toHaveText(SIDEBAR)
    await expect(nav.filter({ hasText: route.title }), where).toHaveAttribute('aria-current', 'page')
    await expect(page.locator('[data-test="company"]'), where).toHaveText(/Northwind Parts\s*Synthetic company/)

    // item 4: tooltips on the screen's figures and actions
    expect(await page.locator('[role="tooltip"]').count(), `${where}: tooltips`).toBeGreaterThanOrEqual(3)

    expect(await sideways(page), `${where} scrolls sideways`).toBeLessThanOrEqual(0)
  }
  expect(writes, 'the walk sent a write').toEqual([])
})

test('one tooltip: hover, focus and tap open it; Escape, blur and a second tap close it', async ({ page, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  await page.goto('/overview')
  await settled(page)
  const tip = page.locator('[data-test="hero-lead"]')
  const trigger = tip
  const body = bubble(tip)
  await expect(body).toBeHidden()
  await expect(body).toHaveText(/\$|USD/) // the lead sentence, in the DOM until asked for

  if (info.project.use.hasTouch) {
    await trigger.tap()
    await expect(body).toBeVisible()
    await trigger.tap()
    await expect(body).toBeHidden()
  } else {
    await trigger.hover()
    await expect(body).toBeVisible()
    await page.mouse.move(1, 1)
    await expect(body).toBeHidden()
  }

  // keyboard: focus opens it, the describedby names it, Escape closes it, blur keeps it closed
  await trigger.focus()
  await expect(body).toBeVisible()
  await expect(trigger).toHaveAttribute('aria-describedby', await body.getAttribute('id') ?? 'none')
  const a = (await trigger.boundingBox())!
  const b = (await body.boundingBox())!
  const overlaps = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
  expect(overlaps, 'the tooltip covers the value it explains').toBe(false)
  expect(b.x, 'the tooltip leaves the viewport').toBeGreaterThanOrEqual(0)
  expect(b.x + b.width).toBeLessThanOrEqual(info.project.use.viewport!.width)
  await page.keyboard.press('Escape')
  await expect(body).toBeHidden()
  await trigger.focus()
  await expect(body).toBeVisible()
  await page.locator('h1').click()
  await expect(body).toBeHidden()

  // an (i) on a figure: the detail that was subtext
  const how = page.locator('.lw-how').first()
  await how.locator('button').focus()
  await expect(bubble(how)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(bubble(how)).toBeHidden()
  expect(writes).toEqual([])
})

test('the word budget at 1487 px', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.use.viewport!.width < 1200, 'the budget is measured at 1487 px, on the desktop project')
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  await page.setViewportSize({ width: 1487, height: 1058 })
  const counts: Record<string, number> = {}
  for (const route of ROUTES) {
    await page.goto(urlOf(route, runId))
    await settled(page)
    counts[route.path.slice(1)] = (await visibleWords(page)).length
  }
  const out = process.env.UX_OUT
  if (out) {
    mkdirSync(out, { recursive: true })
    writeFileSync(join(out, 'word-counts.json'), JSON.stringify(counts, null, 1))
  }
  info.annotations.push({ type: 'words', description: JSON.stringify(counts) })
  expect(counts.overview, 'Overview words over its budget').toBeLessThanOrEqual(wordBudget('overview'))
  expect(writes).toEqual([])
})

/**
 * The shared shell in motion (prp/2026-10-29-ux-shell/design.md), at every width of
 * e2e/ux.config.ts: the logo and six labelled links with an active state that follows the route
 * (208 px sidebar, 72 px icon rail with names, 48 px header with a menu drawer), the breadcrumb
 * and context bar, the ivory palette with self-hosted Source Serif 4 and Inter, and the panel
 * index that marks the panel in view while the page scrolls. Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'

const SIX = ['Overview', 'Treasury', 'Lending', 'Live simulation', 'Decisions', 'Execution']
const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const navLink = (page: Page, name: string) =>
  page.locator('nav.lw-nav').getByRole('link', { name, exact: true })

type Layout = 'sidebar' | 'rail' | 'drawer'
const layoutOf = (width: number): Layout => width >= 1200 ? 'sidebar' : width >= 768 ? 'rail' : 'drawer'

/** Open the drawer when the layout has one; the six links are then on screen. */
async function showNav (page: Page, layout: Layout): Promise<void> {
  if (layout !== 'drawer') return
  await $(page, 'menu').click()
  await expect($(page, 'menu')).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('nav.lw-nav')).toBeVisible()
}

async function goTo (page: Page, layout: Layout, name: string, path: string): Promise<void> {
  await showNav(page, layout)
  await navLink(page, name).click()
  await expect(page).toHaveURL(new RegExp(`${path}(\\?|$)`))
  await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
  if (layout === 'drawer') await expect(page.locator('nav.lw-nav')).toBeHidden()
}

test('navigation: six labelled links, the active one follows the route', async ({ page, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const width = info.project.use.viewport!.width
  const layout = layoutOf(width)
  await page.goto('/overview')
  await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')

  const nav = page.locator('nav.lw-nav')
  if (layout === 'drawer') {
    const bar = page.locator('header.lw-topbar')
    await expect(bar).toBeVisible()
    expect(Math.round((await bar.boundingBox())!.height)).toBe(48)
    await expect(nav).toBeHidden()
    await expect($(page, 'menu')).toHaveAttribute('aria-expanded', 'false')
    // the drawer lists all six; Escape closes it and gives focus back to Menu
    await showNav(page, layout)
    await expect($(page, 'brand-nav')).toBeVisible()
    await expect(navLink(page, 'Overview')).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(nav).toBeHidden()
    await expect($(page, 'menu')).toBeFocused()
    await showNav(page, layout)
  } else {
    await expect(page.locator('header.lw-topbar')).toBeHidden()
    await expect(nav).toBeVisible()
    expect(Math.round((await nav.boundingBox())!.width)).toBe(layout === 'sidebar' ? 208 : 72)
    await expect($(page, 'brand-nav')).toBeVisible()
  }
  for (const name of SIX) {
    const link = navLink(page, name)
    await expect(link, `${name} is not offered`).toBeVisible()
    // a name on screen beside the icon at every width, never an icon alone
    await expect(link.locator('span')).toBeVisible()
    expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  await expect(navLink(page, 'Overview')).toHaveAttribute('aria-current', 'page')
  if (layout === 'drawer') {
    await page.keyboard.press('Escape')
    await expect(nav).toBeHidden()
  }

  for (const [name, path] of [['Treasury', '/treasury'], ['Lending', '/lending'], ['Overview', '/overview']]) {
    await goTo(page, layout, name, path)
    await expect(page.locator('h1')).toHaveText(name)
    await showNav(page, layout)
    await expect(navLink(page, name)).toHaveAttribute('aria-current', 'page')
    await expect(page.locator('nav.lw-nav [aria-current="page"]')).toHaveCount(1)
    if (layout === 'drawer') await page.keyboard.press('Escape')
  }
  expect(writes).toEqual([])
})

test('context: breadcrumb, mode, model, as of and snapshot on every screen', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId: string = (await (await request.get('/api/v1/overview')).json()).demo.run_id
  for (const [path, title, run] of [
    ['/overview', 'Overview', false], ['/treasury', 'Treasury', false], ['/lending', 'Lending', false],
    ['/simulation', 'Live simulation', true], ['/decisions', 'Decisions', true], ['/execution', 'Execution', true]
  ] as const) {
    await page.goto(run ? `${path}?run_id=${runId}` : path)
    await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
    const crumbs = $(page, 'breadcrumb')
    await expect(crumbs).toBeVisible()
    await expect(crumbs.getByRole('link', { name: 'LedgerWorld' })).toBeVisible()
    await expect(crumbs).toContainText(title)
    if (run) await expect(crumbs.locator('[aria-current="page"]')).toHaveText(`Run ${runId}`)
    else await expect(crumbs.locator('[aria-current="page"]')).toHaveText(title)
    await expect($(page, 'mode')).toHaveText('Simulated provider')
    await expect($(page, 'model')).toContainText('scripted')
    await expect($(page, 'context-as-of')).toHaveText(/^As of \d{4}-\d\d-\d\d \d\d:\d\d UTC · /)
    await expect($(page, 'source')).not.toBeEmpty()
    await expect($(page, 'refresh')).toBeVisible()
    // the page does not scroll sideways at any width
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
      .toBeLessThanOrEqual(0)
  }
  expect(writes).toEqual([])
})

test('visual system: ivory surface, Source Serif 4 headings, Inter text, no font CDN', async ({ page, baseURL }) => {
  const origin = new URL(baseURL!).origin
  const elsewhere: string[] = []
  page.on('request', (r) => { if (new URL(r.url()).origin !== origin) elsewhere.push(r.url()) })
  await page.goto('/treasury')
  await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
  await page.evaluate(() => document.fonts.ready)
  const look = await page.evaluate(() => {
    const css = (sel: string) => getComputedStyle(document.querySelector(sel)!)
    return {
      surface: css('.lw-page').backgroundColor,
      ink: css('.lw-page').color,
      h1: css('h1').fontFamily,
      text: css('.lw-page').fontFamily,
      serif: document.fonts.check('600 36px "Source Serif 4 Variable"'),
      inter: document.fonts.check('16px "Inter Variable"'),
      loaded: [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family)
    }
  })
  expect(look.surface).toBe('rgb(250, 248, 243)')
  expect(look.ink).toBe('rgb(23, 37, 30)')
  expect(look.h1).toMatch(/^"?Source Serif 4/)
  expect(look.text).toMatch(/^"?Inter/)
  expect(look.serif && look.inter).toBe(true)
  expect(look.loaded.some((f) => f.includes('Source Serif 4'))).toBe(true)
  expect(look.loaded.some((f) => f.includes('Inter'))).toBe(true)
  expect(elsewhere, 'a request left the app origin (font CDN?)').toEqual([])
})

test('panel index: the panel in view is marked while scrolling, and a link jumps to its panel', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  await page.goto('/treasury')
  await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
  const index = $(page, 'panel-index')
  await expect(index).toBeVisible()
  const links = index.locator('[data-test="panel-link"]')
  const count = await links.count()
  expect(count, 'Treasury lists its panels').toBeGreaterThanOrEqual(2)
  const current = index.locator('[aria-current="true"]')
  await expect(current).toHaveCount(1)
  await expect(current).toHaveText(await links.first().innerText())

  // scrolling to the end marks the last panel; back to the top marks the first again
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect(current).toHaveText(await links.last().innerText())
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect(current).toHaveText(await links.first().innerText())

  // choosing a panel scrolls it to just under the sticky header and marks it
  const second = links.nth(1)
  const id = (await second.getAttribute('href'))!.slice(1)
  await second.click()
  await expect(second).toHaveAttribute('aria-current', 'true')
  await expect.poll(async () => page.evaluate((id) => {
    const top = document.getElementById(id)!.getBoundingClientRect().top
    const under = document.querySelector('.lw-panels')!.getBoundingClientRect().bottom
    return Math.abs(top - under) <= 24 || window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
  }, id)).toBe(true)
  await expect(index).toBeInViewport()
  await expect(page).toHaveURL(/\/treasury$/)

  // every screen marks at least two panels
  const runId: string = (await (await request.get('/api/v1/overview')).json()).demo.run_id
  for (const path of ['/overview', '/lending', `/simulation?run_id=${runId}`, `/decisions?run_id=${runId}`,
    `/execution?run_id=${runId}`]) {
    await page.goto(path)
    await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
    await expect(links.first(), `${path} has no panel index`).toBeVisible()
    expect(await links.count(), `${path} panels`).toBeGreaterThanOrEqual(2)
  }
  expect(writes).toEqual([])
})

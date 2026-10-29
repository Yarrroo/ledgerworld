/**
 * The shared shell in motion (prp/2026-10-29-ux-shell/design.md), at every width of
 * e2e/ux.config.ts: the logo and six labelled links with an active state that follows the route
 * (208 px sidebar, 72 px icon rail with names, 48 px header with a modal menu drawer), the
 * breadcrumb and context bar, and the ivory palette with self-hosted Source Serif 4 and Inter.
 * The screen's name is the breadcrumb's current item; the h1 is the page hero's headline
 * (prp/2026-10-29-ux-pass/MATCH.md, items 1 and 3). The panel index this spec once covered was
 * removed by design (MATCH.md item 2). Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { ROUTES, crumb, demoRunId, settled, urlOf } from './routes'

const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)
const nav = (page: Page) => page.locator('nav.lw-nav')
const navLink = (page: Page, name: string) => nav(page).getByRole('link', { name, exact: true })

type Layout = 'sidebar' | 'rail' | 'drawer'
const layoutOf = (width: number): Layout => width >= 1200 ? 'sidebar' : width >= 768 ? 'rail' : 'drawer'

/** Open the drawer when the layout has one; the six links are then on screen. */
async function showNav (page: Page, layout: Layout): Promise<void> {
  if (layout !== 'drawer') return
  await $(page, 'menu').click()
  await expect($(page, 'menu')).toHaveAttribute('aria-expanded', 'true')
  await expect(nav(page)).toBeVisible()
}

async function hideNav (page: Page, layout: Layout): Promise<void> {
  if (layout !== 'drawer') return
  await page.keyboard.press('Escape')
  await expect(nav(page)).toBeHidden()
}

test('navigation: six labelled links, the active one follows the route', async ({ page, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const layout = layoutOf(info.project.use.viewport!.width)
  await page.goto('/overview')
  await settled(page)

  if (layout === 'drawer') {
    const bar = page.locator('header.lw-topbar')
    await expect(bar).toBeVisible()
    expect(Math.round((await bar.boundingBox())!.height)).toBe(48)
    await expect(nav(page)).toBeHidden()
    await expect($(page, 'menu')).toHaveAttribute('aria-expanded', 'false')
    // the drawer lists all six; Escape closes it and gives focus back to Menu
    await showNav(page, layout)
    await expect(navLink(page, 'Overview')).toBeFocused()
    await hideNav(page, layout)
    await expect($(page, 'menu')).toBeFocused()
    await showNav(page, layout)
  } else {
    await expect(page.locator('header.lw-topbar')).toBeHidden()
    await expect(nav(page)).toBeVisible()
    expect(Math.round((await nav(page).boundingBox())!.width)).toBe(layout === 'sidebar' ? 208 : 72)
  }
  await expect($(page, 'brand-nav')).toBeVisible()
  for (const { title } of ROUTES) {
    const link = navLink(page, title)
    await expect(link, `${title} is not offered`).toBeVisible()
    // a name on screen beside the icon at every width, never an icon alone
    await expect(link.locator('span')).toBeVisible()
    expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  await expect(navLink(page, 'Overview')).toHaveAttribute('aria-current', 'page')
  await hideNav(page, layout)

  for (const name of ['Treasury', 'Lending', 'Overview']) {
    await showNav(page, layout)
    await navLink(page, name).click()
    await expect(page).toHaveURL(new RegExp(`/${name.toLowerCase()}$`))
    await settled(page)
    await expect(crumb(page)).toHaveText(name)
    await expect(page.locator('h1')).toHaveText(ROUTES.find((r) => r.title === name)!.headline)
    if (layout === 'drawer') await expect(nav(page)).toBeHidden()
    await showNav(page, layout)
    await expect(navLink(page, name)).toHaveAttribute('aria-current', 'page')
    await expect(page.locator('nav.lw-nav [aria-current="page"]')).toHaveCount(1)
    await hideNav(page, layout)
  }
  expect(writes).toEqual([])
})

test('drawer: modal while open, closed by any link, and by leaving the phone width', async ({ page, baseURL }, info) => {
  test.skip(layoutOf(info.project.use.viewport!.width) !== 'drawer', 'the drawer is the phone layout')
  const writes = await readOnly(page, baseURL!)
  await page.goto('/overview')
  await settled(page)
  const menu = $(page, 'menu')

  // the screen already showing, and the logo, close the drawer as any other link does
  await menu.click()
  await navLink(page, 'Overview').click()
  await expect(nav(page)).toBeHidden()
  await expect(menu).toHaveAttribute('aria-expanded', 'false')
  await menu.click()
  await $(page, 'brand-nav').click()
  await expect(nav(page)).toBeHidden()

  // focus stays in the drawer: the page under the scrim is inert
  await menu.click()
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab')
    const behind = await page.evaluate(() => !!document.activeElement?.closest('main, header.lw-topbar'))
    expect(behind, `Tab ${i + 1} reached the page behind the open drawer`).toBe(false)
  }
  await page.keyboard.press('Escape')
  await expect(menu).toBeFocused()

  // a drawer left open does not survive a wider layout, nor come back on narrowing again
  await menu.click()
  await page.setViewportSize({ width: 834, height: 1112 })
  await expect(nav(page)).toBeVisible() // the rail
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(nav(page)).toBeHidden()
  await expect(menu).toHaveAttribute('aria-expanded', 'false')
  await expect(page.locator('main.lw-main')).not.toHaveAttribute('inert', /.*/)
  expect(writes).toEqual([])
})

test('context: breadcrumb, provider and agents, date, snapshot line; the mechanics in a tooltip', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  for (const route of ROUTES) {
    await page.goto(urlOf(route, runId))
    await settled(page)
    const crumbs = $(page, 'breadcrumb')
    await expect(crumbs).toBeVisible()
    await expect(crumbs.getByRole('link', { name: 'LedgerWorld' })).toBeVisible()
    await expect(crumb(page)).toHaveText(route.title)
    await expect($(page, 'mode'), route.path).toHaveText(/^Simulated provider · Scripted agents/)
    await expect($(page, 'context-as-of')).toHaveText(/^[A-Z][a-z]+ \d{1,2}, \d{4}$/)
    await expect($(page, 'context-line')).toHaveText(/^Snapshot \S+ · /)
    // the bar's tooltip holds what the chips once said: provider, as of, figures, snapshot, run
    const tip = $(page, 'how-context-bar')
    const facts = tip.locator('[role="tooltip"]')
    await expect(facts).toBeHidden()
    await expect($(page, 'source')).not.toBeEmpty()
    await expect($(page, 'context-provider')).not.toBeEmpty()
    if (route.run) await expect($(page, 'context-run')).toHaveText(runId)
    await tip.focus()
    await expect(facts).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(facts).toBeHidden()
    // no Refresh in the header: a screen reads again when the tab comes back into view
    await expect($(page, 'refresh')).toHaveCount(0)
  }
  // back on the tab, the screen reads its endpoint again, quietly
  const route = ROUTES[1]
  await page.goto(urlOf(route, runId))
  await settled(page)
  const again = page.waitForRequest((r) => r.method() === 'GET' && new URL(r.url()).pathname === `/api/v1${route.path}`)
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await again
  await settled(page)
  expect(writes).toEqual([])
})

test('visual system: ivory surface, Source Serif 4 headings, Inter text, no font CDN', async ({ page, baseURL }) => {
  const origin = new URL(baseURL!).origin
  const elsewhere: string[] = []
  page.on('request', (r) => { if (new URL(r.url()).origin !== origin) elsewhere.push(r.url()) })
  await page.goto('/treasury')
  await settled(page)
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

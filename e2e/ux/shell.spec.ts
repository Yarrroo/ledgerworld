/**
 * The shared shell in motion (prp/2026-10-29-ux-shell/design.md), at every width of
 * e2e/ux.config.ts: the logo and six labelled links with an active state that follows the route
 * (208 px sidebar, 72 px icon rail with names, 48 px header with a modal menu drawer), the
 * breadcrumb and context bar, the ivory palette with self-hosted Source Serif 4 and Inter, and the
 * panel index that marks the panel in view while the page scrolls. Read-only.
 */
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { ROUTES, demoRunId, settled, urlOf } from './routes'

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
    await expect(page.locator('h1')).toHaveText(name)
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

test('context: breadcrumb, mode, model, as of and snapshot on every screen', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  for (const route of ROUTES) {
    await page.goto(urlOf(route, runId))
    await settled(page)
    const crumbs = $(page, 'breadcrumb')
    await expect(crumbs).toBeVisible()
    await expect(crumbs.getByRole('link', { name: 'LedgerWorld' })).toBeVisible()
    await expect(crumbs).toContainText(route.title)
    await expect(crumbs.locator('[aria-current="page"]')).toHaveText(route.run ? `Run ${runId}` : route.title)
    await expect($(page, 'mode')).toHaveText('Simulated bank connection')
    await expect($(page, 'model')).toHaveText('Scripted agents')
    await expect($(page, 'context-as-of')).toHaveText(/^As of \d{1,2} [A-Z][a-z]{2}, \d\d:\d\d UTC$/)
    await expect($(page, 'source')).not.toBeEmpty() // in the bar's How we know
    await expect($(page, 'refresh')).toBeVisible()
  }
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

test('panel index: the panel in view is marked while scrolling, and a chosen one stays marked', async ({ page, baseURL, request }) => {
  const writes = await readOnly(page, baseURL!)
  await page.goto('/treasury')
  await settled(page)
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

  // a chosen panel scrolls to just under the sticky header, or as far as the page goes, and
  // stays marked once the scroll has stopped, even where the page's end comes first
  for (const n of [count - 2, 0]) {
    const link = links.nth(n)
    const id = (await link.getAttribute('href'))!.slice(1)
    await link.click()
    await expect.poll(() => page.evaluate(() => new Promise<number>((resolve) => {
      const y = window.scrollY
      setTimeout(() => resolve(Math.abs(window.scrollY - y)), 250)
    }))).toBe(0)
    await expect(link).toHaveAttribute('aria-current', 'true')
    expect(await page.evaluate((id) => {
      const top = document.getElementById(id)!.getBoundingClientRect().top
      const under = document.querySelector('.lw-panels')!.getBoundingClientRect().bottom
      return Math.abs(top - under) <= 24 || window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
    }, id)).toBe(true)
    await expect(index).toBeInViewport()
  }
  await expect(page).toHaveURL(/\/treasury$/)

  // every screen marks at least two panels
  const runId = await demoRunId(request)
  for (const route of ROUTES) {
    await page.goto(urlOf(route, runId))
    await settled(page)
    await expect(links.first(), `${route.path} has no panel index`).toBeVisible()
    expect(await links.count(), `${route.path} panels`).toBeGreaterThanOrEqual(2)
  }
  expect(writes).toEqual([])
})

/**
 * The LedgerWorld mark in motion, at every width of e2e/ux.config.ts: the vector mark beside the
 * wordmark in the shell's brand (sidebar, icon rail, phone header), named for assistive
 * technology, in the theme's logo blue in light and dark, and the favicon served as the same
 * SVG. Read-only. With UX_SHOTS set, it keeps a picture of the brand per width and theme there.
 */
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { readOnly } from '../guard'
import { settled } from './routes'

const THEMES = { light: 'rgb(36, 105, 232)', dark: 'rgb(111, 155, 242)' } as const

test('the mark in the shell and as the favicon', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const phone = info.project.use.viewport!.width < 768

  for (const [scheme, blue] of Object.entries(THEMES)) {
    await page.emulateMedia({ colorScheme: scheme as 'light' | 'dark' })
    await page.goto('/overview')
    await settled(page)

    const brand = page.locator(phone ? 'header.lw-topbar .lw-brand' : 'nav.lw-nav .lw-brand')
    await expect(brand).toBeVisible()
    const mark = brand.getByRole('img', { name: 'LedgerWorld', exact: true })
    await expect(mark).toBeVisible()
    const box = (await mark.boundingBox())!
    // 28 px beside the wordmark, 24 px in the 48 px phone header
    const side = phone ? 24 : 28
    expect([Math.round(box.width), Math.round(box.height)]).toEqual([side, side])
    await expect(mark).toHaveCSS('color', blue)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (process.env.UX_SHOTS) {
      await page.screenshot({ path: join(process.env.UX_SHOTS, `${info.project.name}-${scheme}.png`) })
    }
  }

  const icon = page.locator('link[rel="icon"]')
  await expect(icon).toHaveAttribute('href', '/logo.svg')
  const reply = await request.get('/logo.svg')
  expect(reply.status()).toBe(200)
  expect(reply.headers()['content-type']).toContain('image/svg+xml')
  expect(await reply.text()).toContain('<title>LedgerWorld</title>')
  expect(writes).toEqual([])
})

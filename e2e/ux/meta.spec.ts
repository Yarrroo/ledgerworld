/**
 * The link preview and the tab: what Slack, a judging site or a browser tab reads off the app,
 * at every width of e2e/ux.config.ts. The served page, read raw as a crawler reads it (no
 * script runs), names LedgerWorld in English with an Open Graph and a Twitter card whose URLs are
 * absolute on the app's public origin (LEDGERWORLD_URL; the request's own origin when it is
 * unset, as here), and the card image is a 1200x630 PNG the app serves. Each finance route then
 * titles its tab "<screen> · LedgerWorld". Read-only.
 */
import { expect, test } from '@playwright/test'
import { readOnly } from '../guard'
import { ROUTES, demoRunId, settled, urlOf } from './routes'

const DESCRIPTION = /^An agentic treasury that rehearses a crisis before it spends a dollar/
const CJK = /[　-鿿＀-￯]/

/** The content of the first `<meta>` whose property or name is `key`, from raw HTML. */
function meta (html: string, key: string): string | null {
  for (const tag of html.match(/<meta\b[^>]*>/g) ?? []) {
    if (new RegExp(`(?:property|name)="${key}"`).test(tag)) {
      return tag.match(/content="([^"]*)"/)?.[1] ?? null
    }
  }
  return null
}

test('the served page previews as LedgerWorld', async ({ request, baseURL }) => {
  const origin = new URL(baseURL!).origin
  for (const path of ['/', '/treasury']) {
    const reply = await request.get(path)
    expect(reply.status(), path).toBe(200)
    const html = await reply.text()
    expect(html, `${path} still names MiroFish`).not.toContain('MiroFish')
    expect(html.match(CJK), `${path} carries Chinese text`).toBeNull()
    expect(html).toMatch(/<html lang="en">/)
    expect(html.match(/<title>([^<]*)<\/title>/)?.[1]).toBe('LedgerWorld')

    expect(meta(html, 'description')).toMatch(DESCRIPTION)
    expect(meta(html, 'og:title')).toBe('LedgerWorld')
    expect(meta(html, 'og:description')).toMatch(DESCRIPTION)
    expect(meta(html, 'og:type')).toBe('website')
    expect(meta(html, 'og:site_name')).toBe('LedgerWorld')
    expect(meta(html, 'og:url')).toBe(`${origin}/`)
    expect(meta(html, 'og:image')).toBe(`${origin}/og-card.png`)
    expect(meta(html, 'og:image:width')).toBe('1200')
    expect(meta(html, 'og:image:height')).toBe('630')
    expect(meta(html, 'og:image:alt')).toBeTruthy()
    expect(meta(html, 'twitter:card')).toBe('summary_large_image')
    expect(meta(html, 'twitter:image')).toBe(`${origin}/og-card.png`)
    expect(html, `${path} leaves the origin placeholder unfilled`).not.toContain('__LEDGERWORLD_URL__')
  }

  const card = await request.get('/og-card.png')
  expect(card.status()).toBe(200)
  expect(card.headers()['content-type']).toContain('image/png')
  const png = await card.body()
  expect(png.subarray(1, 4).toString('latin1')).toBe('PNG')
  // IHDR: width and height, big-endian, at bytes 16 and 20
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([1200, 630])
})

test('each finance route titles its tab', async ({ page, request, baseURL }) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  for (const route of ROUTES) {
    await page.goto(urlOf(route, runId))
    await settled(page)
    await expect(page, route.path).toHaveTitle(`${route.title} · LedgerWorld`)
  }
  expect(writes).toEqual([])
})

// Where an /api/v1 request goes under each deployment setting of VITE_API_BASE_URL. The image
// builds with "/" (the page's own origin); a development build names an absolute origin, with or
// without a trailing slash, or a path prefix. "//api/v1/…" would be a protocol-relative URL to a
// host called "api", so every case is resolved against the page the way a browser would.
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../src/api/v1.js'

const PAGE = 'https://ledgerworld.example/treasury'
const resolved = (url) => new URL(url, PAGE).href

describe('apiUrl', () => {
  it.each([
    ['/', 'https://ledgerworld.example/api/v1/overview'],
    ['', 'https://ledgerworld.example/api/v1/overview'],
    ['//', 'https://ledgerworld.example/api/v1/overview'],
    ['http://localhost:5001', 'http://localhost:5001/api/v1/overview'],
    ['http://localhost:5001/', 'http://localhost:5001/api/v1/overview'],
    ['https://api.example:8443//', 'https://api.example:8443/api/v1/overview'],
    ['/ledgerworld', 'https://ledgerworld.example/ledgerworld/api/v1/overview'],
    ['/ledgerworld/', 'https://ledgerworld.example/ledgerworld/api/v1/overview'],
    ['https://host.example/prefix/', 'https://host.example/prefix/api/v1/overview']
  ])('base %j reaches %s', (base, expected) => {
    expect(resolved(apiUrl('/overview', base))).toBe(expected)
  })

  it('never yields a protocol-relative URL for a same-origin base', () => {
    for (const base of ['/', '//', '']) {
      for (const path of ['/overview', 'treasury', '//lending']) {
        expect(apiUrl(path, base).startsWith('//')).toBe(false)
      }
    }
  })
})

describe('request under the deployment setting', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it.each([
    ['/', '/api/v1/overview'],
    ['http://localhost:5001/', 'http://localhost:5001/api/v1/overview'],
    ['http://localhost:5001', 'http://localhost:5001/api/v1/overview']
  ])('VITE_API_BASE_URL=%j fetches %s', async (base, expected) => {
    vi.stubEnv('VITE_API_BASE_URL', base)
    vi.resetModules()
    const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetch)
    const { getOverview, getTreasury, getLending } = await import('../../src/api/v1.js')
    await Promise.all([getOverview(), getTreasury(), getLending()])
    const urls = fetch.mock.calls.map(([url]) => url)
    expect(urls[0]).toBe(expected)
    for (const url of urls) expect(new URL(url, PAGE).origin).toBe(new URL(expected, PAGE).origin)
  })
})

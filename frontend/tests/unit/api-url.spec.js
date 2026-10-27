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
    ['/', '/overview', 'https://ledgerworld.example/api/v1/overview'],
    ['/', 'treasury', 'https://ledgerworld.example/api/v1/treasury'],
    ['/', '//lending', 'https://ledgerworld.example/api/v1/lending'],
    ['', '/overview', 'https://ledgerworld.example/api/v1/overview'],
    ['//', '/overview', 'https://ledgerworld.example/api/v1/overview'],
    ['http://localhost:5001', '/overview', 'http://localhost:5001/api/v1/overview'],
    ['http://localhost:5001/', '/overview', 'http://localhost:5001/api/v1/overview'],
    ['https://api.example:8443//', '/overview', 'https://api.example:8443/api/v1/overview'],
    ['/ledgerworld', '/overview', 'https://ledgerworld.example/ledgerworld/api/v1/overview'],
    ['/ledgerworld/', '/overview', 'https://ledgerworld.example/ledgerworld/api/v1/overview'],
    ['https://host.example/prefix/', '/overview', 'https://host.example/prefix/api/v1/overview']
  ])('base %j, path %j reaches %s', (base, path, expected) => {
    expect(resolved(apiUrl(path, base))).toBe(expected)
  })

  it('names the API root itself without a trailing slash', () => {
    expect(apiUrl('', '/')).toBe('/api/v1')
    expect(apiUrl('/', 'http://localhost:5001/')).toBe('http://localhost:5001/api/v1')
  })
})

describe('request under the deployment setting', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it.each([
    ['/', ''],
    ['http://localhost:5001/', 'http://localhost:5001']
  ])('VITE_API_BASE_URL=%j fetches each screen under %j/api/v1', async (base, root) => {
    vi.stubEnv('VITE_API_BASE_URL', base)
    vi.resetModules()
    const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetch)
    const { getOverview, getTreasury, getLending } = await import('../../src/api/v1.js')
    await Promise.all([getOverview(), getTreasury(), getLending()])
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(
      ['overview', 'treasury', 'lending'].map((screen) => `${root}/api/v1/${screen}`))
  })
})

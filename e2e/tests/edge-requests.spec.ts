/**
 * The read-only guard (guard.ts) against a local server, no network: the Cloudflare edge's own
 * same-origin /cdn-cgi/ POSTs pass and are not counted; any other write, a /cdn-cgi/ path on
 * another origin included, is aborted before it leaves the browser and counted.
 *
 *   npm --prefix e2e run test:guard
 */
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { expect, test } from '@playwright/test'
import { isEdgeRequest, readOnly } from '../guard'

let server: Server
let port = 0
const received: string[] = []

test.beforeAll(async () => {
  server = createServer((req, res) => {
    received.push(`${req.method} ${req.url}`)
    res.setHeader('access-control-allow-origin', '*')
    res.end(req.method === 'GET' ? '<!doctype html><title>app</title><h1>app</h1>' : 'ok')
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  port = (server.address() as AddressInfo).port
})

test.afterAll(async () => {
  await new Promise((resolve) => server.close(resolve))
})

test('isEdgeRequest: only the deployment origin\'s /cdn-cgi/ paths', () => {
  const origin = 'https://ledgerworld.moonward.net'
  expect(isEdgeRequest(`${origin}/cdn-cgi/rum?`, origin)).toBe(true)
  expect(isEdgeRequest(`${origin}/cdn-cgi/challenge-platform/h/g/jsd/oneshot/x`, `${origin}/`)).toBe(true)
  expect(isEdgeRequest(`${origin}/api/v1/approvals`, origin)).toBe(false)
  expect(isEdgeRequest(`${origin}/api/cdn-cgi/rum`, origin)).toBe(false)
  expect(isEdgeRequest(`${origin}/cdn-cgirum`, origin)).toBe(false)
  expect(isEdgeRequest('https://evil.example/cdn-cgi/rum', origin)).toBe(false)
  expect(isEdgeRequest('http://ledgerworld.moonward.net/cdn-cgi/rum', origin)).toBe(false)
  expect(isEdgeRequest('not a url', origin)).toBe(false)
})

test('edge beacons pass uncounted; app writes and foreign /cdn-cgi/ are aborted and counted', async ({ page }) => {
  received.length = 0
  const origin = `http://127.0.0.1:${port}`
  const foreign = `http://localhost:${port}` // same server, another origin
  const writes = await readOnly(page, origin)
  await page.goto(`${origin}/overview`)

  const post = (url: string): Promise<string> => page.evaluate(async (u) => {
    try {
      return String((await fetch(u, { method: 'POST', body: '{}' })).status)
    } catch {
      return 'blocked'
    }
  }, url)

  expect(await post(`${origin}/cdn-cgi/rum?`)).toBe('200')
  expect(await post(`${origin}/cdn-cgi/challenge-platform/h/g/jsd/oneshot/x`)).toBe('200')
  expect(await post(`${origin}/api/v1/approvals`)).toBe('blocked')
  expect(await post(`${foreign}/cdn-cgi/rum?`)).toBe('blocked')

  expect(writes).toEqual([
    `POST ${origin}/api/v1/approvals`,
    `POST ${foreign}/cdn-cgi/rum?`
  ])
  expect(received.filter((r) => !r.startsWith('GET'))).toEqual([
    'POST /cdn-cgi/rum?',
    'POST /cdn-cgi/challenge-platform/h/g/jsd/oneshot/x'
  ])
})

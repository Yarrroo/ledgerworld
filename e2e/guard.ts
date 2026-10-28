/**
 * The read-only guard shared by judge-path.spec.ts and walkthrough.spec.ts: every request other
 * than GET/HEAD is aborted before it leaves the browser and remembered, and the spec fails on it.
 *
 * One exception: behind Cloudflare the edge injects its own scripts into the page, and they POST
 * to the edge's same-origin /cdn-cgi/ paths (rum beacons, the challenge platform). Those requests
 * are answered by the edge and never reach the app, so they pass through and are not counted.
 * A /cdn-cgi/ path on another origin, or any other write, still fails.
 */
import type { Page } from '@playwright/test'

/** True for a request to the deployment's own Cloudflare edge path, which never reaches the app. */
export function isEdgeRequest (url: string, origin: string): boolean {
  let u: URL
  try {
    u = new URL(url)
  } catch {
    return false
  }
  return u.origin === new URL(origin).origin && u.pathname.startsWith('/cdn-cgi/')
}

/** Abort and remember every write to the app; the path is read-only by construction, not by luck. */
export async function readOnly (page: Page, origin: string): Promise<string[]> {
  const writes: string[] = []
  await page.route('**/*', async (route) => {
    const request = route.request()
    const method = request.method()
    if (method === 'GET' || method === 'HEAD' || isEdgeRequest(request.url(), origin)) {
      return route.continue()
    }
    writes.push(`${method} ${request.url()}`)
    return route.abort('blockedbyclient')
  })
  return writes
}

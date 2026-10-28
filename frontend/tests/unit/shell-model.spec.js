// The shell's model label comes from /health, read once per page load. A read that failed is
// not remembered: the next screen reads again, so a brief outage at the first mount does not
// hide the model for the rest of the session.
import { afterEach, describe, expect, it, vi } from 'vitest'

const answer = (body) => ({ ok: true, status: 200, json: async () => body })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('modelSource', () => {
  it('reads /health again after a failed read, then keeps the answer', async () => {
    const { modelSource } = await import('../../src/api/v1.js')
    const fetch = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection refused'))
      .mockResolvedValueOnce(answer({ ok: true, model: 'scripted' }))
    vi.stubGlobal('fetch', fetch)

    expect(await modelSource()).toBeNull()
    expect(await modelSource()).toBe('scripted')
    expect(await modelSource()).toBe('scripted')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch.mock.calls.every(([url]) => String(url).endsWith('/api/v1/health'))).toBe(true)
  })
})

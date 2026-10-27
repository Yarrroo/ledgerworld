// A judge opening the deployed URL at / lands on the treasury app, not the upstream engine's
// home page; that page stays reachable at its own path.
import { describe, expect, it } from 'vitest'

import router from '../../src/router/index.js'

describe('root route', () => {
  it('resolves / to the Overview route', async () => {
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('Overview')
    expect(router.currentRoute.value.path).toBe('/overview')
  })

  it('keeps the upstream home page reachable at /home', () => {
    expect(router.resolve('/home').name).toBe('Home')
  })
})

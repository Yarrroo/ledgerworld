// Every page footer links the source (AGPL-3.0 §13, system brief §3). The shell reads the link
// from VITE_SOURCE_URL at build time and the image refuses to build without it
// (deploy/Dockerfile), so each reading screen, built the way the image builds it, carries the link.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import overview from '../../../contracts/examples/c6_api/valid-overview-lf1.json'
import treasury from '../../../contracts/examples/c6_api/valid-treasury-lf1-delayed.json'
import lending from '../../../contracts/examples/c6_api/valid-lending-lf2.json'

const SOURCE = 'https://source.example/ledgerworld'
const ANSWERS = {
  '/overview': overview.instance,
  '/treasury': treasury.instance,
  '/lending': lending.instance
}
// Lending reads the overview of its own context beside it
const LENDING_OVERVIEW = { ...overview.instance, snapshot_id: lending.instance.snapshot_id, mode: lending.instance.mode }
const SCREENS = [['Overview', '/overview'], ['Treasury', '/treasury'], ['Lending', '/lending']]

/** Mount ``name`` from a fresh module graph built with ``env``, every request answered offline. */
async function open (name, path, env) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', '/')
  for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value)
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const screen = new URL(url, 'https://ledgerworld.example').pathname.replace('/api/v1', '')
    const body = path === '/lending' && screen === '/overview' ? LENDING_OVERVIEW : ANSWERS[screen]
    if (!body) throw new Error(`no recorded answer for ${url}`)
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(body)) }
  }))
  const views = {
    Overview: (await import('../../src/views/Overview.vue')).default,
    Treasury: (await import('../../src/views/Treasury.vue')).default,
    Lending: (await import('../../src/views/Lending.vue')).default
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: SCREENS.map(([screen, route]) => ({ path: route, component: views[screen] }))
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(views[name], { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('the source link', () => {
  it.each(SCREENS)('%s links the source from its footer under the image setting', async (name, path) => {
    const wrapper = await open(name, path, { VITE_SOURCE_URL: SOURCE })
    expect(wrapper.find('[data-test="error"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="mode"]').text()).toBe('Simulated provider')
    const link = wrapper.get(`main a[href="${SOURCE}"]`)
    expect(link.text()).toBe('Source code (AGPL-3.0)')
  })

  it.each(SCREENS)('%s shows no dead link when built without one', async (name, path) => {
    const wrapper = await open(name, path, { VITE_SOURCE_URL: '' })
    expect(wrapper.get('[data-test="mode"]').text()).toBe('Simulated provider')
    expect(wrapper.findAll('a').filter((a) => a.text().startsWith('Source code'))).toEqual([])
  })
})

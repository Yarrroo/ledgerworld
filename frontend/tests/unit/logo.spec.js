// The LedgerWorld mark is one vector drawing: the shell renders it inline (sidebar and phone
// header), named for assistive technology, and the favicon is the same paths as a file.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { h } from 'vue'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ScreenShell } from '../../src/api/v1.js'
import { LOGO_BLUE, LOGO_BLUE_DARK, MARK } from '../../src/components/logo.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const favicon = new DOMParser().parseFromString(read('../../public/logo.svg'), 'image/svg+xml')
const page = new DOMParser().parseFromString(read('../../index.html'), 'text/html')

async function shell () {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
  await router.push('/')
  await router.isReady()
  return mount({ render: () => h(ScreenShell, { title: 'T', reading: { body: null, status: 'idle', error: null, contextChanged: false }, refresh: () => {} }) },
    { global: { plugins: [router] } })
}

describe('the LedgerWorld logo', () => {
  it('the sidebar and the phone header render the mark inline with an accessible name', async () => {
    const wrapper = await shell()
    for (const where of ['.lw-nav .lw-brand', '.lw-topbar .lw-brand']) {
      const svg = wrapper.get(`${where} svg`)
      expect(svg.attributes('role')).toBe('img')
      expect(svg.attributes('aria-label')).toBe('LedgerWorld')
      expect(svg.attributes('viewBox')).toBe(MARK.viewBox)
      const paths = svg.findAll('path')
      expect(paths.map((p) => p.attributes('d'))).toEqual([MARK.base, ...MARK.facets.map((f) => f.d)])
      expect(paths[0].attributes('fill')).toBe('currentColor')
      expect(wrapper.get(where).text()).toBe('LedgerWorld')
    }
  })

  it('the favicon link points at the vector mark', () => {
    const links = page.querySelectorAll('link[rel="icon"]')
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('/logo.svg')
    expect(links[0].getAttribute('type')).toBe('image/svg+xml')
  })

  it('the favicon is the same drawing as the inline mark, in the logo blue', () => {
    const svg = favicon.documentElement
    expect(svg.getAttribute('viewBox')).toBe(MARK.viewBox)
    expect(svg.querySelector('title').textContent).toBe('LedgerWorld')
    const paths = [...svg.querySelectorAll('path')]
    expect(paths.map((p) => p.getAttribute('d'))).toEqual([MARK.base, ...MARK.facets.map((f) => f.d)])
    expect(paths[0].getAttribute('fill')).toBe(LOGO_BLUE)
    // a dark tab strip gets the dark theme's logo blue, as the inline mark does
    expect(paths[0].getAttribute('class')).toBe('base')
    expect(svg.querySelector('style').textContent.replace(/\s+/g, ''))
      .toBe(`@media(prefers-color-scheme:dark){.base{fill:${LOGO_BLUE_DARK}}}`)
    const tokens = read('../../src/styles/tokens.css')
    expect(tokens).toContain(`--lw-logo: ${LOGO_BLUE};`)
    expect(tokens).toContain(`--lw-logo: ${LOGO_BLUE_DARK};`)
    expect(paths.slice(1).map((p) => [p.getAttribute('fill'), p.getAttribute('fill-opacity')]))
      .toEqual(MARK.facets.map((f) => [f.fill, f.opacity]))
  })
})

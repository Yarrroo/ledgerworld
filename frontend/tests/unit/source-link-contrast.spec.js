// The footer's source link, and every plain link in a reading screen, takes its colour from the
// theme's link token in both themes. Left to the browser it stays the default link blue, 1.95:1
// on the dark surface, and fails the accessibility pass (WCAG AA needs 4.5:1 for normal text).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { h } from 'vue'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../src/styles/tokens.css'), 'utf8')

const SOURCE = 'https://source.example/ledgerworld'

/** Custom properties declared in the first ``:root`` block of ``text``. */
function tokens (text) {
  const block = text.match(/:root\s*{([^}]*)}/)
  expect(block).not.toBeNull()
  return Object.fromEntries([...block[1].matchAll(/(--lw-[\w-]+)\s*:\s*([^;]+);/g)]
    .map(([, name, value]) => [name, value.trim()]))
}

function luminance (hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast (a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const light = tokens(css)
const dark = tokens(css.slice(css.indexOf('prefers-color-scheme: dark')))
const THEMES = [['light', light], ['dark', dark]]

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('the source link contrast', () => {
  it.each(THEMES)('the %s theme declares a link token readable on every surface', (_, theme) => {
    expect(theme['--lw-link']).toMatch(/^#[0-9A-Fa-f]{6}$/)
    for (const surface of ['--lw-surface', '--lw-surface-raised']) {
      expect(contrast(theme['--lw-link'], theme[surface])).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('plain links in a reading screen use the link token', () => {
    const rule = css.match(/\.lw-main a:not\(\.lw-button\)\s*{([^}]*)}/)
    expect(rule).not.toBeNull()
    expect(rule[1]).toMatch(/(^|;|\s)color:\s*var\(--lw-link\)/)
  })

  it('the footer link is a plain link inside the reading screen', async () => {
    vi.stubEnv('VITE_SOURCE_URL', SOURCE)
    const { ScreenShell } = await import('../../src/api/v1.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
    await router.push('/')
    await router.isReady()
    const wrapper = mount({ render: () => h(ScreenShell, { title: 'T', reading: { body: null, status: 'idle', error: null, contextChanged: false }, refresh: () => {} }) },
      { global: { plugins: [router] } })
    const link = wrapper.get(`main.lw-main a[href="${SOURCE}"]`)
    expect(link.classes()).not.toContain('lw-button')
    expect(link.text()).toBe('Source code (AGPL-3.0)')
  })
})

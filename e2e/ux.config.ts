/**
 * The interaction checks (e2e/ux/*.spec.ts): one anonymous chromium per width the design names
 * (prp/2026-10-29-ux-pass/HANDOFF.md, "Quality checks before release": 1440, 834 and 390 px),
 * video on. Run through scripts/ux-check.sh, which starts the app and passes it as UX_URL and the
 * output directory as UX_OUT.
 */
import { join } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const url = process.env.UX_URL
if (!url) throw new Error('UX_URL is not set: run scripts/ux-check.sh SPEC')

const WIDTHS = [
  { name: 'desktop-1440', viewport: { width: 1440, height: 900 } },
  { name: 'tablet-834', viewport: { width: 834, height: 1112 } },
  { name: 'phone-390', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }
]

export default defineConfig({
  testDir: 'ux',
  outputDir: join(process.env.UX_OUT ?? '/tmp', 'artifacts'),
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: url.replace(/\/+$/, ''),
    storageState: undefined,
    colorScheme: 'light',
    trace: 'off',
    screenshot: 'only-on-failure'
  },
  projects: WIDTHS.map(({ name, viewport, ...rest }) => ({
    name,
    use: { viewport, video: { mode: 'on', size: viewport }, ...rest }
  }))
})

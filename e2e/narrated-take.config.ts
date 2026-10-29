/**
 * The narrated machine take: one anonymous chromium at 1280 × 720 with video on, run through
 * scripts/narrated_take.sh, which passes the deployment as NARRATED_URL, the beat plan as
 * NARRATED_PLAN, the opening card as NARRATED_LABEL and the output directory as NARRATED_OUT.
 * The demo token, when set, reaches only the spec's own request context: never `use` here, whose
 * headers the browser would send and the video could show.
 */
import { join } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const url = process.env.NARRATED_URL
if (!url) throw new Error('NARRATED_URL is not set: run scripts/narrated_take.sh URL')
const size = { width: 1280, height: 720 }

export default defineConfig({
  testDir: '.',
  testMatch: 'narrated-take.spec.ts',
  outputDir: join(process.env.NARRATED_OUT ?? '/tmp', 'artifacts'),
  workers: 1,
  retries: 0,
  // the card and the plan's 4:35 in real time, plus room for a slow fork and first load
  timeout: 600_000,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: url.replace(/\/+$/, ''),
    storageState: undefined,
    viewport: size,
    colorScheme: 'light',
    video: { mode: 'on', size },
    trace: 'off'
  }
})

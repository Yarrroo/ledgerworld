/**
 * The walkthrough rehearsal: one anonymous chromium at 1280 × 720 with video on, run through
 * scripts/walkthrough.sh, which passes the deployment as WALKTHROUGH_URL, the beat plan as
 * WALKTHROUGH_PLAN and the output directory as WALKTHROUGH_OUT.
 */
import { join } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const url = process.env.WALKTHROUGH_URL
if (!url) throw new Error('WALKTHROUGH_URL is not set: run scripts/walkthrough.sh URL')
const size = { width: 1280, height: 720 }

export default defineConfig({
  testDir: '.',
  testMatch: 'walkthrough.spec.ts',
  outputDir: join(process.env.WALKTHROUGH_OUT ?? '/tmp', 'artifacts'),
  workers: 1,
  retries: 0,
  // the plan's 4:35 in real time, plus room for a slow first load
  timeout: 420_000,
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

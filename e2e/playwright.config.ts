/**
 * The judge path (T26): one cold, anonymous chromium per viewport × theme, from the fixture
 * prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/judge-path.json. Run through
 * scripts/judge-path.sh, which passes the deployment as JUDGE_PATH_URL and collects each run's
 * elapsed seconds from JUDGE_PATH_OUT.
 *
 * One worker: the runs share this machine's CPU, and a timing taken beside five other browsers
 * would measure the machine, not the path.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const FIXTURE = join(__dirname, '..', 'prp', '2026-10-20-ledgerworld', 'design', 'modules', 'ui',
  'fixtures', 'judge-path.json')
const judge = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as {
  viewports: { width: number, height: number }[]
  themes: ('light' | 'dark')[]
}

const url = process.env.JUDGE_PATH_URL
if (!url) throw new Error('JUDGE_PATH_URL is not set: run scripts/judge-path.sh URL')

export default defineConfig({
  testDir: '.',
  testMatch: 'judge-path.spec.ts',
  outputDir: join(process.env.JUDGE_PATH_OUT ?? '/tmp', 'artifacts'),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // the 60 s limit is the wrapper's (--max-seconds); this only stops a hung page holding the run
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: url.replace(/\/+$/, ''),
    // anonymous and cold: no stored state, no token, a fresh context per test
    storageState: undefined,
    trace: 'off',
    screenshot: 'only-on-failure'
  },
  projects: judge.viewports.flatMap((viewport) => judge.themes.map((theme) => ({
    name: `${viewport.width}-${theme}`,
    use: {
      viewport,
      colorScheme: theme,
      isMobile: viewport.width < 600,
      hasTouch: viewport.width < 600
    }
  })))
})

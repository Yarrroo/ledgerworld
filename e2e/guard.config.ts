/**
 * The read-only guard's own tests (tests/edge-requests.spec.ts): one chromium against a local
 * server, no deployment and no network. Run with `npm --prefix e2e run test:guard`.
 */
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: 'tests',
  testMatch: 'edge-requests.spec.ts',
  // nothing is left in the tree: failure output goes to the system temp directory
  outputDir: join(tmpdir(), 'ledgerworld-guard'),
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: { ...devices['Desktop Chrome'], trace: 'off' }
})

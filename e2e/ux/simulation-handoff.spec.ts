/**
 * A handoff that disagrees with the run it lands on is said on the page, at every width of
 * e2e/ux.config.ts, on the prepared demonstration run: a Treasury link made on another snapshot,
 * or a link asking for a scenario this run does not play, puts a visible note beside the run's
 * context, inside the page's width; a link that agrees with the run puts none, and its account
 * echo stays behind the (i). Read-only. With UX_SHOTS set, it keeps a picture of the note per width.
 */
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, settled, sideways } from './routes'

const note = (page: Page) => page.locator('[data-test="handoff-mismatch"]')

async function open (page: Page, query: string): Promise<void> {
  await page.goto(`/simulation?${query}`)
  await settled(page)
  await expect(page.locator('[data-test="scrubber-slider"]')).toHaveAttribute('aria-valuenow', /^\d+$/)
}

test('another snapshot or scenario is a visible note; an agreeing handoff adds none', async ({ page, baseURL, request }, info) => {
  const writes = await readOnly(page, baseURL!)
  const runId = await demoRunId(request)
  const run = await (await request.get(`/api/v1/runs/${runId}`)).json()
  const other = ['delayed-receipt', 'fx-gap'].find((id) => !run.branches.some((b: { branch_id: string }) => b.branch_id.includes(id)))!

  await open(page, `run_id=${runId}&account=treasury/operating&snapshot=elsewhere-1&scenario=${other}`)
  await expect(note(page)).toBeVisible()
  await expect(note(page)).toContainText('snapshot elsewhere-1')
  await expect(note(page)).toContainText(run.snapshot_id)
  await expect(note(page)).toContainText(`Scenario asked for: ${other}`)
  await expect(note(page)).not.toContainText('treasury/operating')
  const box = (await note(page).boundingBox())!
  expect(box.x + box.width, 'the note fits the page').toBeLessThanOrEqual(page.viewportSize()!.width)
  expect(await sideways(page), 'Live simulation scrolls sideways').toBeLessThanOrEqual(0)
  if (process.env.UX_SHOTS) {
    await page.locator('[data-test="run-context"]').screenshot({ path: join(process.env.UX_SHOTS, `${info.project.name}-handoff-mismatch.png`) })
  }

  await open(page, `run_id=${runId}&account=treasury/operating&snapshot=${run.snapshot_id}`)
  await expect(note(page)).toHaveCount(0)
  await expect(page.locator('[data-test="handoff"]')).toBeHidden()
  await expect(page.locator('[data-test="handoff"]')).toContainText('treasury/operating')
  expect(writes).toEqual([])
})

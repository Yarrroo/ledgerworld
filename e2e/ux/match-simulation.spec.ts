import { expect, test } from '@playwright/test'
import { readOnly } from '../guard'
import { demoRunId, settled, sideways, tipWorks } from './routes'
import { visibleWords, wordBudget } from './words'

// Mockup 04: the visible reading order, run-owned facts and interactions at all three widths.
test('Simulation as mockup 04', async ({ page, request, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const touch = Boolean(info.project.use.hasTouch)
  let width = info.project.use.viewport!.width
  if (width >= 1200) { width = 1487; await page.setViewportSize({ width, height: 1058 }) }
  const runId = await demoRunId(request)
  const run = await (await request.get(`/api/v1/runs/${runId}`)).json()
  await page.goto(`/simulation?run_id=${runId}`)
  await settled(page)
  const $ = (id: string) => page.locator(`[data-test="${id}"]`)
  await expect(page.locator('h1')).toHaveText('See the crisis before it spreads.')
  await expect($('hero-action').locator('a')).toHaveText('Compare policies')
  await expect($('hero-action').locator('a')).toHaveAttribute('href', `/decisions?run_id=${runId}`)
  await expect($('run-context')).toContainText('Scenario')
  await expect($('run-context')).toContainText('Branch')
  await expect($('run-context')).toContainText('Cohort')
  await expect($('relationships-title')).toHaveText(`Market relationships at round ${run.committed_round}`)
  await expect($('map-node')).toHaveCount(8)
  await expect(page.locator('.lw-map__icon')).toHaveCount(8)
  expect(await page.locator('.lw-map__edge.is-causal').count()).toBeGreaterThan(0)
  await expect($('selected-round')).toHaveText(`Selected actor · Round ${run.committed_round}`)
  await expect($('actor-detail')).toContainText('What changed')
  await expect($('actor-actions')).toContainText('h')
  await expect($('interview').locator('label')).toContainText('Ask this actor')
  await expect($('ask')).toBeDisabled()
  await expect($('token')).toHaveAttribute('type', 'password')
  await expect($('cursor')).toHaveText(`Round ${run.committed_round} of 18 · ${run.rounds.find((r: any) => r.round === run.committed_round).t_hours}h simulated`)
  await expect($('tick-mark')).toHaveText('Shock event')
  await expect($('fork')).toHaveText('Fork checkpoint')
  await expect($('controls')).toContainText('Playback only · No funds move')
  await expect(page.locator('#cash-title')).toHaveText('Treasury cash path (72-hour outlook)')
  await expect(page.locator('[data-policy="no-action"]')).toBeVisible()
  await expect(page.locator('[data-policy="fixed-reserve"]')).toBeVisible()
  await expect(page.locator('[data-policy="integrated"]')).toBeVisible()
  await expect($('cash-floor')).toHaveAttribute('y1', /\d/)
  await expect($('policy-chart')).toBeVisible()
  await expect($('cash-shortfall')).toContainText('$10,000 at h40')
  await expect($('feed')).toBeHidden()
  const ids = ['hero', 'run-context', 'relationships', 'controls', 'cash']
  const boxes = await Promise.all(ids.map(async (id) => (await $(id).boundingBox())!))
  for (let i = 1; i < boxes.length; i++) expect(boxes[i].y).toBeGreaterThanOrEqual(boxes[i - 1].y + boxes[i - 1].height - 1)
  const map = (await $('map').boundingBox())!, actor = (await $('inspector').boundingBox())!
  if (width >= 1200) expect(actor.x).toBeGreaterThanOrEqual(map.x + map.width)
  else expect(actor.y).toBeGreaterThanOrEqual(map.y + map.height)
  for (const [trigger, name] of [
    [page.locator('.lw-sim__selector .lw-tip').first(), 'scenario'],
    [$('phase-tip'), 'run status'],
    [$('actor-actions').locator('.lw-tip').last(), 'timeline event'],
    [$('cash-shortfall').locator('..'), 'shortfall'],
    [$('cash-point').last(), 'cash point']
  ] as const) {
    await page.mouse.move(0, 0)
    await page.keyboard.press('Escape')
    await page.evaluate(() => (document.activeElement as HTMLElement)?.blur())
    await tipWorks(page, trigger, touch, name)
  }
  await $('scrubber-slider').focus()
  await page.keyboard.press('Home')
  await expect($('selected-round')).toHaveText('Selected actor · Round 1')
  await expect($('cursor')).toContainText('Round 1 of 18')
  await page.keyboard.press('End')
  await expect($('cursor')).toContainText(`Round ${run.committed_round} of 18`)
  await page.locator('.lw-sim__source').click()
  await expect($('feed')).toBeVisible()
  await page.locator('.lw-sim__source').click()
  await page.locator('h1').click()
  const words = (await visibleWords(page)).length
  info.annotations.push({ type: 'words', description: `${words} at ${width}` })
  expect(words, `${words} words at ${width}`).toBeLessThanOrEqual(wordBudget('simulation'))
  expect(await sideways(page)).toBeLessThanOrEqual(0)
  if (process.env.UX_OUT) await page.screenshot({ path: `${process.env.UX_OUT}/match-simulation-${width}.png`, fullPage: true })
  if (process.env.SIMULATION_SHOTS) {
    await page.screenshot({ path: `${process.env.SIMULATION_SHOTS}/${width}-light.png`, fullPage: true })
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.screenshot({ path: `${process.env.SIMULATION_SHOTS}/${width}-dark.png`, fullPage: true })
  }
  expect(writes).toEqual([])
})

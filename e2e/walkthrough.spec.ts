/**
 * The walkthrough rehearsal (goal g5): drive the deployed app through the seven timed beats of
 * docs/video-script.md in real time, with each beat's shot overlaid as a caption, and record it.
 *
 * The plan comes from scripts/walkthrough_plan.py through scripts/walkthrough.sh (WALKTHROUGH_PLAN).
 * Each beat opens its route (a beat on the route already shown stays there), overlays its caption
 * and holds until the beat's planned end, scrolling through the screen as it holds. When a beat
 * is late, the next starts at once: the lateness is the measurement, never hidden by a shorter hold.
 * Per-beat planned and actual seconds go to $WALKTHROUGH_OUT/beats.json after every beat.
 *
 * Anonymous and read-only like judge-path.spec.ts: every request other than GET/HEAD is aborted
 * and fails the run. The fresh fork and the interview are operator POSTs, so they are not driven.
 * A beat whose screen does not load is recorded as unreached and the run continues to the next.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

interface Beat { beat: string, start: number, end: number, route: string, caption: string, note: string }
interface Result {
  beat: string, route: string, planned_start: number, planned_end: number,
  ready: number | null, left: number, reached: boolean, error: string
}

const PLAN = process.env.WALKTHROUGH_PLAN
const OUT = process.env.WALKTHROUGH_OUT
if (!PLAN || !OUT) throw new Error('WALKTHROUGH_PLAN and WALKTHROUGH_OUT are not set: run scripts/walkthrough.sh URL')
const BEATS: Beat[] = JSON.parse(readFileSync(PLAN, 'utf-8')).beats

const mmss = (s: number): string => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

/** The caption box: fixed over the bottom of the screen, never in the way of a click. */
async function caption (page: Page, beat: Beat): Promise<void> {
  await page.evaluate(({ title, text, note }) => {
    let box = document.getElementById('lw-walkthrough-caption')
    if (!box) {
      box = document.createElement('div')
      box.id = 'lw-walkthrough-caption'
      box.setAttribute('aria-hidden', 'true')
      box.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;' +
        'pointer-events:none;padding:10px 16px;background:rgba(10,12,16,.86);color:#fff;' +
        'font:13px/1.4 system-ui,sans-serif;max-height:32vh;overflow:hidden'
      document.body.appendChild(box)
    }
    box.innerHTML = ''
    const head = document.createElement('strong')
    head.textContent = title
    const body = document.createElement('div')
    body.textContent = text
    box.append(head, body)
    if (note) {
      const aside = document.createElement('em')
      aside.textContent = `Not shown: ${note}.`
      box.append(aside)
    }
  }, {
    title: `Rehearsal · silent · read-only — ${beat.beat} ${mmss(beat.start)}–${mmss(beat.end)}`,
    text: beat.caption,
    note: beat.note
  })
}

/** Scroll from one fraction of the page to another, evenly over the time left in the beat. */
async function hold (page: Page, until: number, now: () => number, from: number, to: number): Promise<void> {
  const steps = Math.max(1, Math.ceil(until - now()))
  for (let i = 1; i <= steps && now() < until; i++) {
    const at = from + (to - from) * i / steps
    await page.evaluate((f) => window.scrollTo({ top: f * (document.documentElement.scrollHeight - innerHeight) }), at)
      .catch(() => {})
    await page.waitForTimeout(Math.max(0, Math.min(1000, (until - now()) * 1000)))
  }
}

/** Each beat's place in the run of consecutive beats on its route: [index, length]. */
function runs (beats: Beat[]): [number, number][] {
  const out: [number, number][] = []
  for (let i = 0; i < beats.length;) {
    let j = i
    while (j < beats.length && beats[j].route === beats[i].route) j++
    for (let k = i; k < j; k++) out.push([k - i, j - i])
    i = j
  }
  return out
}

test('walkthrough rehearsal: seven timed beats, captioned and recorded', async ({ page }) => {
  mkdirSync(OUT, { recursive: true })
  const writes: string[] = []
  await page.route('**/*', async (route) => {
    const method = route.request().method()
    if (method === 'GET' || method === 'HEAD') return route.continue()
    writes.push(`${method} ${route.request().url()}`)
    return route.abort('blockedbyclient')
  })

  // the prepared demonstration run, as Overview names it: the other screens open on it, as the
  // judge path's clicks do; without one they open bare and the screen's own error marks them unreached
  let run: string | null = null
  page.on('response', async (r) => {
    if (new URL(r.url()).pathname !== '/api/v1/overview' || !r.ok()) return
    run = (await r.json().catch(() => null))?.demo?.run_id ?? run
  })

  const results: Result[] = []
  const started = performance.now()
  const now = (): number => (performance.now() - started) / 1000
  const places = runs(BEATS)
  let shown = ''
  for (const [i, beat] of BEATS.entries()) {
    const [k, n] = places[i]
    const result: Result = {
      beat: beat.beat, route: beat.route, planned_start: beat.start, planned_end: beat.end,
      ready: null, left: 0, reached: false, error: ''
    }
    try {
      if (beat.route !== shown) {
        shown = ''
        const query = run && beat.route !== '/overview' ? `?run_id=${encodeURIComponent(run)}` : ''
        await page.goto(beat.route + query, { timeout: 30_000 })
        shown = beat.route
      }
      await expect(page.locator('h1')).toBeVisible({ timeout: 30_000 })
      await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 })
      // loaded means the screen's reading arrived: a source label and no load error
      await expect(page.locator('[data-test="error"]'), 'the screen shows a load error').toHaveCount(0)
      await expect(page.locator('[data-test="source"]').first()).not.toBeEmpty({ timeout: 5_000 })
      result.reached = true
    } catch (error) {
      result.error = String((error as Error).message ?? error).split('\n')[0]
    }
    result.ready = result.reached ? now() : null
    await caption(page, beat).catch(() => {})
    await hold(page, beat.end, now, k / n, (k + 1) / n)
    result.left = now()
    results.push(result)
    writeFileSync(join(OUT, 'beats.json'), JSON.stringify({ writes, beats: results }, null, 2))
  }

  expect(writes, 'the rehearsal sent a write').toEqual([])
  expect(results.filter((r) => !r.reached).map((r) => `${r.beat} ${r.route}: ${r.error}`),
    'beats whose screen did not load').toEqual([])
})

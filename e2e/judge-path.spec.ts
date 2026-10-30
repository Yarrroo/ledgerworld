/**
 * The judge path (T26, goal g4): a cold anonymous browser walks Overview → Live simulation →
 * Decisions → Execution in four clicks and reads a reconciled receipt, under 60 s.
 *
 * Fixtures, loaded unchanged: prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/
 * judge-path.json (the clicks, the timing window, the viewport × theme matrix) and
 * accessibility.json (focus, contrast, 44 px controls, overflow, reduced motion, status text).
 *
 * - "timed path": from just before the first navigation until the fourth click's receipt
 *   assertions pass. Its seconds go to $JUDGE_PATH_OUT/<project>.json; a failed run writes
 *   nothing, which the wrapper reads as 999.
 * - "accessibility": the same four clicks untimed, with the checks at each screen, then
 *   Treasury and Lending; reduced motion is on for this one.
 *
 * Both are anonymous and read-only (guard.ts). Every request other than GET/HEAD, bar the
 * Cloudflare edge's own same-origin /cdn-cgi/, is aborted before it leaves the browser and fails
 * the test: no approval, no execution, no fork, no interview. The prepared demonstration run and
 * its execution come from the deployment (Overview's `demo`); when either is missing the path fails and says so, it never falls back to another run or receipt.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { readOnly } from './guard'

const UI = join(__dirname, '..', 'prp', '2026-10-20-ledgerworld', 'design', 'modules', 'ui', 'fixtures')
const JUDGE = JSON.parse(readFileSync(join(UI, 'judge-path.json'), 'utf-8'))
const A11Y = JSON.parse(readFileSync(join(UI, 'accessibility.json'), 'utf-8'))
const CASE = Object.fromEntries(A11Y.cases.map((c: { id: string }) => [c.id, c]))
const CLICKS: { n: number, name: string, route: string }[] = JUDGE.clicks
/** The provider mode as a receipt names it, and as the context bar says it in plain words. */
const MODES = ['Simulated provider', 'Airwallex sandbox']
const OUT = process.env.JUDGE_PATH_OUT

interface Demo { run_id: string | null, execution_id: string | null }

const test$ = (page: Page, id: string): Locator => page.locator(`[data-test="${id}"]`)

/** The click the fixture names, on the control carrying that name. */
async function click (page: Page, n: number, control: Locator): Promise<void> {
  const step = CLICKS.find((c) => c.n === n)!
  await expect(control, `click ${n} "${step.name}" is not offered`).toBeVisible()
  await expect(control).toHaveText(new RegExp(step.name))
  await control.click()
  await expect(page).toHaveURL(new RegExp(`${step.route}(\\?|$)`))
}

/** Overview: cash, the payroll deadline, minimum projected cash against the floor, the run. */
async function overview (page: Page): Promise<Demo> {
  const answer = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/overview',
    { timeout: JUDGE.timing.limit_seconds * 1000 })
  await page.goto('/overview')
  const reply = await answer
  expect(reply.status(), 'GET /api/v1/overview').toBe(200)
  const demo: Demo = (await reply.json()).demo ?? { run_id: null, execution_id: null }
  await expect(test$(page, 'mode')).toHaveText(new RegExp(MODES.join('|')))
  await expect(test$(page, 'source')).not.toBeEmpty()
  await expect(test$(page, 'settled').locator('.lw-figure')).toHaveText(/\d/)
  // the payroll deadline in UTC and local time; once the demonstration's own execution has paid
  // it, the observed state has no open obligation left and the tile says so in words
  const next = test$(page, 'next-obligation')
  await expect(next).toContainText(/due \d{4}-\d\d-\d\d \d\d:\d\d UTC · local |No open obligation/)
  if (await test$(page, 'due').count()) {
    await expect(test$(page, 'due')).toHaveText(/due \d{4}-\d\d-\d\d \d\d:\d\d UTC · local /)
  }
  await expect(test$(page, 'coverage')).toContainText(/lowest point ahead .*\d.* · safety minimum .*\d/)
  await expect(test$(page, 'coverage').locator('.lw-figure')).toHaveText(/\d|Unknown|Not assessed/)
  await expect(test$(page, 'floor-status')).toHaveText(/\w/)
  expect(demo.run_id, 'the deployment names no prepared demonstration run').toBeTruthy()
  expect(demo.execution_id, `run ${demo.run_id} has no linked execution`).toBeTruthy()
  return demo
}

/** Click 1, Open simulation: the same run, a committed round on the one cursor. */
async function simulation (page: Page, demo: Demo): Promise<void> {
  await click(page, 1, page.locator('a[data-test="open-simulation"]'))
  expect(new URL(page.url()).searchParams.get('run_id')).toBe(demo.run_id)
  const slider = test$(page, 'scrubber-slider')
  await expect(slider).toHaveAttribute('aria-valuenow', /^[1-9]\d*$/)
  const round = await slider.getAttribute('aria-valuenow')
  await expect(test$(page, 'cursor')).toHaveText(new RegExp(`^Round ${round} of \\d+ · \\d+h simulated$`))
  await expect(test$(page, 'phase')).not.toHaveText(/invalid/i)
  // feed, graph inspector and cursor read the same committed round
  await expect(page.locator('#feed-title')).toContainText(`Action feed · round ${round}`)
  await expect(test$(page, 'selected-round')).toHaveText(`Selected actor · Round ${round}`)
  await expect(test$(page, 'feed-unloaded')).toHaveCount(0)
  // a replayed run says so on the page, in the header, not only in its tooltip (COPY.md rule 4)
  if (await test$(page, 'replay-note').count()) {
    await expect(test$(page, 'mode')).toBeVisible()
    await expect(test$(page, 'mode')).toContainText('Replay', { useInnerText: true })
  }
}

/** Click 2, Compare policies: three policies, the surviving one beside no-action, no odds. */
async function decisions (page: Page, demo: Demo): Promise<void> {
  await click(page, 2, page.locator('a[data-test="compare"]'))
  expect(new URL(page.url()).searchParams.get('run_id')).toBe(demo.run_id)
  const policies = test$(page, 'policies')
  for (const p of ['no-action', 'fixed-reserve', 'integrated']) {
    await expect(test$(page, `policy-${p}`), `policy ${p}`).toBeVisible()
  }
  await test$(page, 'how-decisions').locator('summary').click()
  await expect(test$(page, 'cohort')).toContainText(`Run ${demo.run_id}`)
  await expect(test$(page, 'cohort')).toContainText('not a probability')
  await expect(policies.locator('[data-test="selected"]')).toHaveCount(1)
  expect(await policies.innerText(), 'a probability was inferred from scenario counts').not.toMatch(/\d\s*%/)
}

/** Click 3, View execution: the execution linked to this run, every leg reconciled. */
async function execution (page: Page, demo: Demo): Promise<void> {
  await click(page, 3, page.locator('a[data-test="view-execution"]'))
  expect(new URL(page.url()).searchParams.get('run_id')).toBe(demo.run_id)
  await expect(test$(page, 'context')).toContainText(`execution ${demo.execution_id}`)
  for (const absent of ['no-execution', 'not-found', 'poll-error', 'no-legs', 'incident']) {
    await expect(test$(page, absent), `execution screen shows ${absent}`).toHaveCount(0)
  }
  const legs = page.locator('[data-test^="leg-"]:not([data-test="leg-status"])')
  await expect(legs.first()).toBeVisible()
  for (const leg of await legs.all()) {
    await expect(leg).toHaveAttribute('data-test', /^leg-(advance|payout|fx|repayment)$/)
    await expect(leg.locator('[data-test="leg-status"]')).toHaveText(/reconciled as of .* UTC/)
    await expect(leg.locator('[data-test="leg-status"]')).not.toHaveText(/not reconciled/)
    await expect(leg.locator('[data-test="receipt-mode"]')).toHaveText(new RegExp(MODES.join('|')))
    // a reconciled leg has a receipt; setup funding is never one of these legs (the kinds above)
    await expect(leg.locator('[data-test="receipt"]')).toHaveCount(1)
  }
}

/** Click 4, Open receipt: provider id, journal, observed time; read-only. */
async function receipt (page: Page): Promise<void> {
  const details = test$(page, 'receipt').first()
  await click(page, 4, details.locator('.lw-leg__chevron'))
  await expect(details).toHaveAttribute('open', '')
  // the opened one is read on screen; every other leg's receipt carries the same fields
  for (const each of await test$(page, 'receipt').all()) {
    const field = (name: string) => each.locator(`dt:text-is("${name}") + dd`)
    await expect(field('Provider id')).toHaveText(/\S/)
    await expect(field('Journal')).toHaveText(/\S/)
    await expect(field('Journal')).not.toHaveText('not posted')
    await expect(field('Observed')).toHaveText(/\d{4}-\d\d-\d\d \d\d:\d\d UTC/)
    await expect(field('Provider')).toHaveText(new RegExp(MODES.join('|')))
  }
  await expect(test$(page, 'review')).toHaveCount(0) // nothing was opened for approval
}

// ---------------------------------------------------------------------------- accessibility

interface Contrast { text: string, ratio: number, need: number, fg: string, bg: string }

/** Rendered text below its WCAG AA ratio; colours composited over the nearest opaque ancestors. */
function lowContrast (page: Page, root: string): Promise<Contrast[]> {
  return page.evaluate(({ root, normal, large }) => {
    const rgba = (s: string): number[] | null => {
      const m = s.match(/^rgba?\(([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:[ ,/]+([\d.]+))?\)$/)
      return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null
    }
    const over = (top: number[], under: number[]) =>
      [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat(1)
    const lum = (c: number[]) => {
      const [r, g, b] = c.slice(0, 3).map((v) => {
        const x = v / 255
        return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
    /** The background under ``el``; null when an image or an unreadable colour is in the way. */
    const background = (el: Element | null): number[] | null => {
      const layers: number[][] = []
      for (let e = el; e; e = e.parentElement) {
        const style = getComputedStyle(e)
        if (style.backgroundImage !== 'none') return null
        const c = rgba(style.backgroundColor)
        if (!c) return null
        if (c[3] > 0) layers.push(c)
        if (c[3] === 1) break
      }
      return layers.reduceRight((under, top) => over(top, under), [255, 255, 255, 1])
    }
    const failed: { text: string, ratio: number, need: number, fg: string, bg: string }[] = []
    for (const el of document.querySelectorAll(`${root} *`)) {
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim())
      if (!own || !(el as HTMLElement).checkVisibility?.({ visibilityProperty: true, opacityProperty: true })) continue
      if (el.closest('[disabled], [aria-disabled="true"], [aria-hidden="true"], svg')) continue
      const style = getComputedStyle(el)
      const bg = background(el)
      const fg = rgba(style.color)
      if (!bg || !fg) continue
      const text = over(fg, bg)
      const [hi, lo] = [lum(text), lum(bg)].sort((a, b) => b - a)
      const ratio = (hi + 0.05) / (lo + 0.05)
      const size = parseFloat(style.fontSize)
      const isLarge = size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700)
      const need = isLarge ? large : normal
      if (ratio + 1e-6 < need) {
        failed.push({ text: el.textContent!.trim().slice(0, 60), ratio: Math.round(ratio * 100) / 100, need,
          fg: style.color, bg: `rgb(${bg.slice(0, 3).map(Math.round).join(', ')})` })
      }
    }
    return failed
  }, { root, normal: CASE.contrast.expect.normal_text_min_ratio, large: CASE.contrast.expect.large_text_and_controls_min_ratio })
}

/** The focus indicator ``el`` draws now: its outline and box shadow. */
const ringOf = (el: Element): string => {
  const s = getComputedStyle(el)
  const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0
    ? `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}` : 'none'
  return `${outline} | ${s.boxShadow}`
}

/** Tab (keyboard only) until ``control`` has focus; focused, it must look different from at rest. */
async function focusByKeyboard (page: Page, control: Locator, name: string): Promise<void> {
  await control.scrollIntoViewIfNeeded()
  const rest = await control.evaluate(ringOf)
  for (let i = 0; i < 120; i++) {
    if (await control.evaluate((el) => el === document.activeElement)) {
      const focused = await control.evaluate(ringOf)
      expect(focused, `${name}: keyboard focus is not visible`).not.toBe(rest)
      expect(focused, `${name}: keyboard focus is not visible`).not.toBe('none | none')
      return
    }
    await page.keyboard.press('Tab')
  }
  throw new Error(`${name}: not reachable by keyboard`)
}

/** The accessibility fixture's checks on the screen in view. */
async function accessible (page: Page, screen: string, phone: boolean): Promise<void> {
  await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, `${screen}: the page scrolls sideways`).toBeLessThanOrEqual(0)
  for (const status of await page.locator('.lw-status').all()) {
    if (await status.isVisible()) await expect(status, `${screen}: a status is colour only`).toHaveText(/[A-Za-z]/)
  }
  if (phone) {
    const min = CASE.phone.expect.primary_controls_min_css_px
    for (const control of await page.locator('.lw-button').all()) {
      if (!(await control.isVisible())) continue
      const box = (await control.boundingBox())!
      expect(Math.min(box.width, box.height), `${screen}: "${(await control.innerText()).trim()}" is under ${min} px`)
        .toBeGreaterThanOrEqual(min - 0.5)
    }
  }
  expect(await lowContrast(page, '.lw-page'), `${screen}: text under its contrast ratio`).toEqual([])
}

// -------------------------------------------------------------------------------- the tests

test('timed path: Overview → Live simulation → Decisions → Execution → receipt', async ({ page, baseURL }, info) => {
  const writes = await readOnly(page, baseURL!)
  const started = performance.now() // just before the initial navigation
  const demo = await overview(page)
  await simulation(page, demo)
  await decisions(page, demo)
  await execution(page, demo)
  await receipt(page)
  const seconds = (performance.now() - started) / 1000
  expect(writes, 'the path sent a write').toEqual([])
  info.annotations.push({ type: 'elapsed', description: `${seconds.toFixed(1)} s` })
  // the limit is the wrapper's (--max-seconds, the fixture's 60 by default): it compares the slowest run
  if (OUT) {
    mkdirSync(OUT, { recursive: true })
    writeFileSync(join(OUT, `${info.project.name}.json`), JSON.stringify({ project: info.project.name, seconds }))
  }
})

test.describe('accessibility', () => {
  test.use({ reducedMotion: 'reduce' })

  test('the four screens of the path, then Treasury and Lending, read-only', async ({ page, baseURL }, info) => {
    const phone = (info.project.use.viewport?.width ?? 1280) < 600
    const writes = await readOnly(page, baseURL!)
    const demo = await overview(page)
    await accessible(page, 'Overview', phone)
    await focusByKeyboard(page, page.locator('a[data-test="open-simulation"]'), 'Open simulation')

    await simulation(page, demo)
    await accessible(page, 'Live simulation', phone)
    const moving = await page.evaluate(() => document.getAnimations().filter((a) => {
      const target = (a.effect as KeyframeEffect | null)?.target as Element | null
      return a.playState === 'running' &&
        (a.effect?.getTiming().iterations === Infinity || !!target?.closest('.lw-scrubber, .lw-figure'))
    }).length)
    expect(moving, 'animation runs under prefers-reduced-motion').toBe(0)
    await focusByKeyboard(page, page.locator('a[data-test="compare"]'), 'Compare policies')

    await decisions(page, demo)
    await accessible(page, 'Decisions', phone)
    await focusByKeyboard(page, page.locator('a[data-test="view-execution"]'), 'View execution')

    await execution(page, demo)
    await accessible(page, 'Execution', phone)
    await focusByKeyboard(page, test$(page, 'receipt').first().locator(':scope > summary'), 'Open receipt')
    await receipt(page)
    await accessible(page, 'Execution receipt', phone)

    for (const screen of JUDGE.outside_timed_path.read_only_visits as string[]) {
      // on a phone the six screens sit in the menu drawer
      if (await test$(page, 'menu').isVisible()) await test$(page, 'menu').click()
      await page.locator('nav.lw-nav').getByRole('link', { name: screen, exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`/${screen.toLowerCase()}$`))
      await expect(page.locator('[data-test="breadcrumb"] [aria-current="page"]')).toHaveText(screen)
      await expect(test$(page, 'mode')).toHaveText(new RegExp(MODES.join('|')))
      await expect(test$(page, 'source')).not.toBeEmpty()
      await accessible(page, screen, phone)
      const drill = page.locator('details.lw-calc summary').first()
      if (await drill.count()) {
        await focusByKeyboard(page, drill, `${screen} drill-down`)
        await page.keyboard.press('Enter')
        await expect(page.locator('details.lw-calc').first()).toHaveAttribute('open', '')
      }
    }
    expect(writes, 'the accessibility walk sent a write').toEqual([])
  })
})

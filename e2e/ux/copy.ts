/**
 * What the copy passes' specs (copy-1, copy-2; prp/2026-10-29-ux-pass/COPY.md) share: the
 * screens' money format, the jargon a lead or heading must not use, the lead sentence (now the
 * hero subtitle's tooltip, MATCH.md item 1) and the How we know check (now an (i) tooltip,
 * MATCH.md item 2 and 4).
 */
import { expect, type Page } from '@playwright/test'
import { settled } from './routes'

export const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)

/** The three plans' plain names (COPY.md glossary), by policy id. */
export const PLANS: Record<string, string> = { 'no-action': 'Do nothing', 'fixed-reserve': 'Keep a fixed buffer', integrated: 'Borrow just enough' }

export interface Money { minor: number | null, currency: string }
const SIGN: Record<string, string> = { USD: '$', EUR: '€', GBP: '£' }
/** "$70,000", "$1,234.50", "-$50,000", as the screens format integer minor units (MATCH.md item 5). */
export const fmt = (m: Money) => {
  const plain = (Math.abs(m.minor!) / 100).toLocaleString('en-US', { minimumFractionDigits: 2 }).replace(/\.00$/, '')
  const sign = m.minor! < 0 ? '-' : ''
  return SIGN[m.currency] ? `${sign}${SIGN[m.currency]}${plain}` : `${sign}${m.currency} ${plain}`
}

/** The words a finance lead should not meet in a heading or a lead sentence (COPY.md rule 2). */
const JARGON = /\b(snapshot|branch|cohort|checkpoint|intent|provenance|policy|policies)\b/i
const SYMBOL = /K_p|\((S|P)\)|(^|\s)(P|S)(?=[\s,.;:]|$)/
export const technical = (text: string) => JARGON.test(text) || SYMBOL.test(text)

/** Words in a sentence, an amount ("USD 20,000.00") counting as one and a dash as none. */
export const words = (text: string) => text.replace(/\b[A-Z]{3} (?=[\d-])/g, '').split(/\s+/).filter((w) => /\w/.test(w)).length

export async function read (page: Page, path: string): Promise<any> {
  const reply = await page.request.get(`/api/v1${path}`)
  expect(reply.status(), `GET /api/v1${path}`).toBe(200)
  return reply.json()
}

export async function open (page: Page, path: string): Promise<void> {
  await page.goto(path)
  await settled(page)
}

/** Every visible section heading is in plain words. */
export async function plainHeadings (page: Page): Promise<void> {
  for (const h of await page.locator('main.lw-main section h2').all()) {
    if (!(await h.isVisible())) continue
    const text = (await h.textContent())!.trim()
    expect(technical(text), `a heading uses a technical term: ${text}`).toBe(false)
  }
}

/** The screen's lead sentence: the hero subtitle's tooltip, in the DOM until asked for. */
export const lead = (page: Page) => page.locator('[data-test="hero-lead"] [role="tooltip"]')

/** A How we know (i): closed, keyboard-reachable, named "How we know", its tooltip holding `facts`. */
export async function folded (page: Page, test: string, facts: string[]): Promise<void> {
  const how = $(page, test)
  await expect(how).toHaveCount(1)
  const body = how.locator('[role="tooltip"]')
  await expect(body).toBeHidden()
  const button = how.locator('.lw-how__icon')
  await expect(button).toHaveAccessibleName('How we know')
  await button.focus()
  await expect(button).toBeFocused()
  await expect(body).toBeVisible()
  await expect(button).toHaveAttribute('aria-describedby', new RegExp(await body.getAttribute('id') ?? 'none'))
  for (const fact of facts) await expect(body).toContainText(fact)
  expect((await button.boundingBox())!.height, 'the (i) is shorter than 24 px').toBeGreaterThanOrEqual(24)
  await page.keyboard.press('Escape')
  await expect(body).toBeHidden()
}

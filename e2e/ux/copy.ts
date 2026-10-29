/**
 * What the copy passes' specs (copy-1, copy-2; prp/2026-10-29-ux-pass/COPY.md) share: the
 * screens' money format, the jargon a lead or heading must not use, and the How we know check.
 */
import { expect, type Page } from '@playwright/test'
import { settled } from './routes'

export const $ = (page: Page, id: string) => page.locator(`[data-test="${id}"]`)

/** The three plans' plain names (COPY.md glossary), by policy id. */
export const PLANS: Record<string, string> = { 'no-action': 'Do nothing', 'fixed-reserve': 'Keep a fixed buffer', integrated: 'Borrow just enough' }

export interface Money { minor: number | null, currency: string }
/** "USD 70,000.00", as the screens format integer minor units. */
export const fmt = (m: Money) => `${m.currency} ${(m.minor! / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}`

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

/** A How we know disclosure: closed, keyboard-reachable, holding `facts`. */
export async function folded (page: Page, test: string, facts: string[]): Promise<void> {
  const how = $(page, test)
  await expect(how).toHaveCount(1)
  await expect(how).not.toHaveAttribute('open', '')
  await expect(how.locator('.lw-calc__body')).not.toBeVisible()
  const summary = how.locator('summary')
  await expect(summary).toHaveText('How we know')
  await summary.focus()
  await expect(summary).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(how).toHaveAttribute('open', '')
  for (const fact of facts) await expect(how.locator('.lw-calc__body')).toContainText(fact)
  expect((await summary.boundingBox())!.height, 'How we know is shorter than 44 px').toBeGreaterThanOrEqual(44)
  await page.keyboard.press('Enter')
  await expect(how).not.toHaveAttribute('open', '')
}

/**
 * The word budget (prp/2026-10-29-ux-pass/MATCH.md, shared item 8): the words a reader sees on a
 * screen, counted the way checks/word_budget.py counted the mockups — every rendered text node on
 * the whole page (not only the first viewport), SVG labels included, split on white space, a token
 * counting only when it carries a letter or a digit ("·", "/", "→" are not words). Text a reader
 * cannot see is not counted: a closed tooltip, a hidden element, a visually hidden label (a box of
 * 1 px or less).
 */
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import type { Page } from '@playwright/test'

export async function visibleWords (page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const words: string[] = []
    const seen = new Map<Element, boolean>()
    const visible = (el: Element): boolean => {
      if (!seen.has(el)) {
        const box = el.getBoundingClientRect()
        seen.set(el, el.checkVisibility({ opacityProperty: true, visibilityProperty: true }) &&
          box.width > 1 && box.height > 1)
      }
      return seen.get(el)!
    }
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement
      if (!parent || parent.closest('script, style, title') || !visible(parent)) continue
      for (const token of (node.textContent ?? '').split(/\s+/)) {
        if (/[\p{L}\p{N}]/u.test(token)) words.push(token)
      }
    }
    return words
  })
}

/** The screen's budget, from checks/word_budget.py: the mockup's words plus 15 %. */
export function wordBudget (screen: string): number {
  const root = join(__dirname, '..', '..')
  const out = execFileSync('uv', ['run', '--project', root, 'python', join(root, 'checks', 'word_budget.py'),
    '--budget', screen], { encoding: 'utf-8' })
  return Number(out.trim())
}

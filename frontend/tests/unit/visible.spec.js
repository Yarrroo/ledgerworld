// The checks' reader of what is on the page: a closed tooltip, a closed dialog, a closed details'
// body and a hidden element are not, so a label moved into one of them fails the check that wants it.
import { afterEach, describe, expect, it } from 'vitest'
import { isShown, visibleText } from './visible.js'

const page = (html) => {
  document.body.innerHTML = `<main>${html}</main>`
  return document.body.querySelector('main')
}

afterEach(() => { document.body.innerHTML = '' })

describe('visibleText', () => {
  it('leaves out a closed tooltip and keeps an open one', () => {
    expect(visibleText(page('Cash <span role="tooltip" hidden>from the ledger</span>'))).toBe('Cash')
    expect(visibleText(page('Cash <span role="tooltip">from the ledger</span>'))).toBe('Cash from the ledger')
  })

  it('leaves out a closed dialog and keeps an open one', () => {
    expect(visibleText(page('Plan <dialog><p>Replay</p></dialog>'))).toBe('Plan')
    expect(visibleText(page('Plan <dialog open><p>Replay</p></dialog>'))).toBe('Plan Replay')
  })

  it('keeps a closed details\' summary and leaves out its body', () => {
    expect(visibleText(page('<details><summary>Timing</summary><p>h12</p></details>'))).toBe('Timing')
    expect(visibleText(page('<details><summary>Timing</summary>Replay</details>'))).toBe('Timing')
    expect(visibleText(page('<details open><summary>Timing</summary> <p>h12</p></details>'))).toBe('Timing h12')
  })

  it('leaves out an element hidden by attribute or by display none', () => {
    expect(visibleText(page('A <b hidden>B</b> <i style="display: none">C</i> D'))).toBe('A D')
    expect(visibleText(page('Cash <span class="lw-visually-hidden">Replay</span>'))).toBe('Cash')
  })

  it('reads nothing of an element inside a folded one', () => {
    const root = page('<span role="tooltip" hidden><p data-test="replay">Replay</p></span><dialog><b>x</b></dialog>')
    expect(visibleText(root.querySelector('[data-test="replay"]'))).toBe('')
    expect(isShown(root.querySelector('b'))).toBe(false)
    expect(isShown(root)).toBe(true)
  })
})

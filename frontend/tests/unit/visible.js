// What a reader sees without opening anything (prp/2026-10-29-ux-pass/COPY.md rule 4: honesty stays
// visible). A wrapper's .text() reads every text node, so a label moved into a closed tooltip or a
// closed dialog still "passes"; these helpers leave out what the page does not show.

/** Not on the page until asked for: a hidden element, a closed dialog, a closed details' body. */
function folded (el) {
  // jsdom loads no stylesheet: the one hiding class the app uses is named here
  if (el.hidden || el.style?.display === 'none' || el.classList?.contains('lw-visually-hidden')) return true
  if (el.tagName === 'DIALOG' && !el.hasAttribute('open')) return true
  const details = el.parentElement
  return details?.tagName === 'DETAILS' && !details.hasAttribute('open') && el.tagName !== 'SUMMARY'
}

/** Whether ``el`` is shown: neither it nor anything around it is folded away. */
export function isShown (el) {
  for (let at = el; at && at.nodeType === 1; at = at.parentElement) if (folded(at)) return false
  return true
}

/** What the page shows of the element marked ``data-test="test"`` inside a mounted wrapper. */
export const onPage = (wrapper, test) => visibleText(wrapper.get(`[data-test="${test}"]`))

/** An element's (or a test wrapper's) words as the page shows them, white space collapsed. */
export function visibleText (target) {
  const el = target.element ?? target
  if (!isShown(el)) return ''
  const copy = el.cloneNode(true)
  ;[...copy.querySelectorAll('*')].filter(folded).forEach((c) => c.remove())
  // a closed details' bare text is folded too, not only its elements
  for (const d of copy.querySelectorAll('details:not([open])')) {
    for (const n of [...d.childNodes]) if (n.nodeType === 3) n.remove()
  }
  return copy.textContent.replace(/\s+/g, ' ').trim()
}

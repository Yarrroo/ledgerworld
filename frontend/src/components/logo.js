/**
 * The LedgerWorld mark: a faceted hexagonal "C" in the logo blue, redrawn as vector geometry
 * from the handoff's concept (prp/2026-10-29-ux-pass, Brand). The outer hexagon is pointy-top on
 * a 32-unit grid; the counter is the same hexagon at half size, open to the right. The shell
 * draws it in `currentColor` (the theme's `--lw-logo`), and `frontend/public/logo.svg`, the
 * favicon, is the same paths in the two theme blues — a unit test keeps them in step.
 */
import { h } from 'vue'

export const LOGO_BLUE = '#2469E8'
export const LOGO_BLUE_DARK = '#6F9BF2'

export const MARK = {
  viewBox: '0 0 32 32',
  /** the whole C, under the facets, so their shared edges never show a seam */
  base: 'M16 2L28 9L22 12.5L16 9L10 12.5L10 19.5L16 23L22 19.5L28 23L16 30L4 23L4 9Z',
  /** light falls from the upper right: the top arm is lit, the left wall and lower arm are in shade */
  facets: [
    { d: 'M16 2L28 9L22 12.5L16 9Z', fill: '#FFFFFF', opacity: '0.3' },
    { d: 'M4 9L16 2L16 9L10 12.5Z', fill: '#FFFFFF', opacity: '0.1' },
    { d: 'M4 9L10 12.5L10 19.5L4 23Z', fill: '#000000', opacity: '0.2' },
    { d: 'M4 23L10 19.5L16 23L16 30Z', fill: '#000000', opacity: '0.1' }
  ]
}

/** The mark as an inline SVG named for assistive technology; colour from `currentColor`. */
export function logoMark (attrs = {}) {
  return h('svg', { viewBox: MARK.viewBox, role: 'img', 'aria-label': 'LedgerWorld', focusable: 'false', ...attrs }, [
    h('path', { fill: 'currentColor', d: MARK.base }),
    ...MARK.facets.map((f) => h('path', { fill: f.fill, 'fill-opacity': f.opacity, d: f.d }))
  ])
}

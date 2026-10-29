/**
 * The /api/v1 client and the shared screen shell (system brief §11–12, contract C6).
 *
 * - Reads are public; a write takes the operator's token as an argument, kept in memory by the
 *   caller and never written to storage, a URL or a log. No request is retried: a financial POST
 *   that times out is resolved by a GET, never by sending it again.
 * - The browser formats C6 and never recomputes S, P or K_p: money arrives as integer minor
 *   units with a currency and is formatted here, once, at the display boundary.
 * - A metric has four states — known, unknown, stale, unassessed — and an unknown is never 0.
 * - A late answer never overwrites a newer one: a reading applies only its newest request's
 *   answer. `latestOnly()` (selected context plus generation) is for a polled resource the user
 *   selects, such as an execution's status; these reading screens select nothing.
 * - Text is English only, as the product is (system brief §15).
 */

import {
  computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, shallowRef, watch
} from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { logoMark } from '../components/logo.js'
import '@fontsource-variable/inter'
import '@fontsource-variable/source-serif-4'
import '../styles/tokens.css'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'
const SOURCE_URL = import.meta.env.VITE_SOURCE_URL || ''

// ------------------------------------------------------------------------------ transport

export class ApiError extends Error {
  constructor (status, code, detail) {
    super(detail || code)
    this.status = status
    this.code = code
  }
}

/**
 * The URL of an /api/v1 path under `base`: an absolute origin, a path prefix, or "/" for the
 * page's own origin (the image's setting), each with or without trailing slashes. Exactly one
 * slash joins them: "//api/v1/…" would be a protocol-relative URL to a host called "api".
 */
export function apiUrl (path, base = BASE) {
  const tail = path.replace(/^\/+/, '')
  return `${base.replace(/\/+$/, '')}/api/v1${tail && `/${tail}`}`
}

/** One request to /api/v1, no retry. A C6 ErrorResponse becomes an ApiError with its code. */
export async function request (path, { method = 'GET', body, token, signal } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  let response
  try {
    response = await fetch(apiUrl(path), {
      method, headers, signal, body: body === undefined ? undefined : JSON.stringify(body)
    })
  } catch (error) {
    throw new ApiError(0, 'unreachable', `the API did not answer: ${error.message}`)
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const error = payload?.error || {}
    throw new ApiError(response.status, error.code || 'http_error',
      error.detail || `HTTP ${response.status}`)
  }
  return payload
}

export const getOverview = (opts) => request('/overview', opts)
export const getTreasury = (opts) => request('/treasury', opts)
export const getLending = (opts) => request('/lending', opts)

/** A reading refused because no demonstration run is prepared: the shell explains it, never an error. */
export const NO_DEMO_RUN = 'no_demo_run'
export const noDemoRun = () => new ApiError(404, NO_DEMO_RUN, 'No demonstration run is prepared')

// ------------------------------------------------------------------------ late responses

/** The context an answer belongs to: never merge two of these into one apparent state. */
export function contextKey ({ mode, snapshot_id: snapshot, run_id: run, branch_id: branch } = {}) {
  return [mode ?? '', snapshot ?? '', run ?? '', branch ?? ''].join('|')
}

/**
 * A guard for one polled resource. `select(key)` names the context on screen; `issue()` stamps
 * a request; `accept(ticket, key)` says whether its answer may be applied: only for the selected
 * context, and never one older than an answer already applied (out-of-order polls).
 * `current(ticket, key)` asks the same without recording it: a failed request is not an answer,
 * so it must not discard the answers to requests issued before it.
 */
export function latestOnly (selected = null) {
  let issued = 0
  let applied = 0
  let context = selected
  const current = (ticket, key = ticket.context) =>
    ticket.context === context && key === context && ticket.generation >= applied
  return {
    select (key) {
      if (key !== context) applied = 0
      context = key
    },
    issue () {
      issued += 1
      return { generation: issued, context }
    },
    current,
    accept (ticket, key = ticket.context) {
      if (!current(ticket, key)) return false
      applied = ticket.generation
      return true
    }
  }
}

// ------------------------------------------------------------------------------ formatting

const EXPONENT = { JPY: 0 }

/** "70,000.00" from 7000000: integer minor units, no float arithmetic. */
export function formatAmount (minor, currency) {
  if (!Number.isSafeInteger(minor)) return 'Unrepresentable amount'
  const exponent = EXPONENT[currency] ?? 2
  const digits = String(Math.abs(minor)).padStart(exponent + 1, '0')
  const whole = digits.slice(0, digits.length - exponent)
  const fraction = exponent ? `.${digits.slice(digits.length - exponent)}` : ''
  return `${minor < 0 ? '-' : ''}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction}`
}

/** "USD 70,000.00". */
export function formatMoney (minor, currency) {
  return `${currency} ${formatAmount(minor, currency)}`
}

/** A C6 Money (`{minor, currency}`) as "USD 70,000.00". */
export const money = (m) => formatMoney(m.minor, m.currency)

/** A machine kind as words: "exchange_withdrawal" reads "exchange withdrawal". */
export const kindText = (kind) => String(kind ?? '').replace(/_/g, ' ')

/** A C6 metric as text: a value only when known or stale; unknown and unassessed say so. */
export function metricText (metric) {
  if (!metric) return 'Unavailable'
  switch (metric.status) {
    case 'known': return money(metric)
    case 'stale': return `${money(metric)} · stale`
    case 'unknown': return 'Unknown'
    case 'unassessed': return 'Not assessed'
    default: return 'Unavailable'
  }
}

/** A metric as a bare figure for a calculation line ("70,000.00"), or its state in words. */
export function amountText (metric) {
  return metric.minor === null ? metricText(metric) : formatAmount(metric.minor, metric.currency)
}

/** Icon + word for every state: status is never colour alone. */
export const STATES = {
  known: { icon: '●', word: 'Known', tone: 'muted' },
  unknown: { icon: '?', word: 'Unknown', tone: 'warn' },
  stale: { icon: '◷', word: 'Stale', tone: 'warn' },
  unassessed: { icon: '–', word: 'Not assessed', tone: 'muted' },
  kept: { icon: '✓', word: 'Floor kept', tone: 'ok' },
  breached: { icon: '✕', word: 'Floor breached', tone: 'bad' },
  error: { icon: '!', word: 'Last loaded, not current', tone: 'bad' }
}

export const stateOf = (status) => STATES[status] || STATES.unassessed

/** A metric's status line, "● Known as of 2026-01-01 00:00 UTC" or "? Unknown": never colour alone. */
export function metricStatus (metric) {
  const s = stateOf(metric?.status)
  const at = metric?.as_of ? ` as of ${formatTime(metric.as_of).utc}` : ''
  return `${s.icon} ${s.word}${at}`
}

/** A not-current account (completeness.accounts, Lending's capacity.unobserved) with its own
 * reason: a stale one was
 * observed and carries its as_of; an unknown one was not and carries none. ``text`` reads
 * "lender/venue · ? Unknown" or "lender/operating · ◷ Stale, as of 2026-01-05 12:00 UTC". */
export function freshness (account) {
  const s = stateOf(account.status)
  const at = account.status === 'stale' && account.as_of ? formatTime(account.as_of).utc : null
  return {
    ...s, id: account.account_id, at,
    text: `${account.account_id} · ${s.icon} ${s.word}${at ? `, as of ${at}` : ''}`
  }
}

/** The stale ones of not-current accounts, as `freshness()` reads them: the shell's stale band. */
export const staleOf = (accounts) => (accounts ?? []).filter((a) => a.status === 'stale').map(freshness)

/** Floor kept or breached, read off an API headroom metric (P minimum − floor). */
export function floorState (headroom) {
  if (!headroom || headroom.status === 'unknown' || headroom.minor == null) {
    return headroom?.status === 'unassessed' ? 'unassessed' : 'unknown'
  }
  if (headroom.status === 'unassessed') return 'unassessed'
  return headroom.minor >= 0 ? 'kept' : 'breached'
}

/**
 * A value against a floor, both API metrics: the state and the gap in minor units (value −
 * floor). Unknown when either has no value; Not assessed when the floor was never assessed.
 */
export function againstFloor (value, floor) {
  if (!floor || floor.status === 'unassessed') return { state: 'unassessed', gap: null }
  if (value?.minor == null || floor.minor == null) return { state: 'unknown', gap: null }
  const gap = value.minor - floor.minor
  return { state: gap >= 0 ? 'kept' : 'breached', gap }
}

const pad = (n) => String(n).padStart(2, '0')
const LOCAL = new Intl.DateTimeFormat(undefined, {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  timeZoneName: 'short'
})

/** Absolute UTC, and the browser's local time labelled separately. */
export function formatTime (iso) {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return { utc: 'Unavailable', local: '' }
  const utc = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  return { utc, local: `local ${LOCAL.format(d)}` }
}

/** "t=40 h": whole hours from the response's as_of (simulated hours on a frozen snapshot). */
export function hoursFrom (asOf, at) {
  const hours = Math.round((Date.parse(at) - Date.parse(asOf)) / 3_600_000)
  return Number.isNaN(hours) ? 't unavailable' : `t=${hours} h`
}

const byTime = (key) => (x, y) => Date.parse(x[key]) - Date.parse(y[key])

// ---------------------------------------------------------------- the terms of projected cash

/** Obligations P counts: open or missed (a missed obligation is still owed). */
export const OWED = new Set(['open', 'missed'])

/**
 * The terms the API's P[a, t] is made of, for display beside the API's own result. The rule is
 * the ledger's: settled, + arrivals due by t, − outflows due by t, − obligations due by t, an
 * obligation whose reservation is committed counted once, through its outflow. Nothing is summed.
 */
export function projectionTerms (account, t, obligations, asOf) {
  const at = Date.parse(t)
  const isDue = (iso) => Date.parse(iso) <= at
  const c = account.currency
  const b = account.buckets
  const terms = [b.settled ? `${formatAmount(b.settled.minor, c)} settled` : 'Unknown settled']
  const excluded = []
  const take = (flows, sign, direction) => {
    for (const f of flows) {
      if (isDue(f.expected_at)) terms.push(`${sign} ${formatAmount(f.amount.minor, c)} ${kindText(f.kind)}`)
      else excluded.push(`${kindText(f.kind)} ${f.flow_id} ${direction} (expected ${hoursFrom(asOf, f.expected_at)})`)
    }
  }
  take(b.pending_in, '+', 'in')
  take(b.pending_out, '-', 'out')
  const carried = new Set(b.pending_out.map((f) => f.reservation_id).filter(Boolean))
  for (const o of obligations) {
    if (o.account !== account.id || !OWED.has(o.state ?? 'open')) continue
    if (o.reservation_id && carried.has(o.reservation_id)) continue // counted as its outflow
    if (isDue(o.due_at)) terms.push(`- ${formatAmount(o.amount.minor, c)} ${kindText(o.kind)}`)
    else excluded.push(`${kindText(o.kind)} ${o.obligation_id} due (${hoursFrom(asOf, o.due_at)})`)
  }
  const result = account.projected.find((p) => p.t === t)?.value
  return {
    line: `${terms.join(' ')} = ${result ? amountText(result) : 'Unavailable'}`,
    excluded: excluded.length ? `excluded at ${hoursFrom(asOf, t)}: ${excluded.join(', ')}` : ''
  }
}

/** An account's pending flows, both directions, in time order. */
export function pendingFlows (account) {
  return [
    ...account.buckets.pending_in.map((f) => ({ ...f, direction: 'in' })),
    ...account.buckets.pending_out.map((f) => ({ ...f, direction: 'out' }))
  ].sort(byTime('expected_at'))
}

// ------------------------------------------------------------------------ labels, screens

export const LABELS = {
  fake: 'Simulated provider',
  sandbox: 'Airwallex sandbox',
  synthetic: 'Synthetic snapshot',
  branch: 'Hypothetical branch',
  replay: 'Replay',
  search: 'Search result, not a forecast'
}

/**
 * The cash owner's words for the honesty labels and the floor (prp/2026-10-29-ux-pass/COPY.md);
 * the technical term each replaces stays in the panel's How we know.
 */
export const PLAIN = {
  fake: 'Simulated bank connection',
  sandbox: 'Sandbox bank',
  scripted: 'Scripted agents',
  branch: 'What-if'
}

export const FLOOR_WORDS = {
  kept: 'Above your safety minimum',
  breached: 'Below your safety minimum',
  unknown: 'Unknown',
  unassessed: 'Not assessed'
}

/** "2 Jan", the UTC day of an instant, for a lead sentence. */
export function dayText (iso) {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return 'an unknown date'
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
}

/** A metric as an amount in a sentence: its text when it has a value, else "an unknown amount". */
export const amountWords = (metric) => (metric?.minor == null ? 'an unknown amount' : metricText(metric))

/** What a response's figures are: a replay, a hypothetical branch, or the observed snapshot. */
export function sourceLabel (body) {
  if (body.replay) {
    const of = body.branch_id ? `${LABELS.branch} ${body.branch_id}` : (body.run_id ?? body.snapshot_id)
    return `${LABELS.replay} · ${of}`
  }
  if (body.branch_id) return `${LABELS.branch} ${body.branch_id}`
  return `${LABELS.synthetic} ${body.snapshot_id}`
}

/** The six screens, in reading order; the shell links each one whose route is registered. */
export const SCREENS = [
  { path: '/overview', label: 'Overview', icon: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z' },
  { path: '/treasury', label: 'Treasury', icon: 'M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18' },
  { path: '/lending', label: 'Lending', icon: 'M4 8h15l-4-4M20 16H5l4 4' },
  { path: '/simulation', label: 'Live simulation', icon: 'M3 12h4l3-7 4 14 3-7h4' },
  { path: '/decisions', label: 'Decisions', icon: 'M6 4v6a4 4 0 0 0 4 4h9M15 10l4 4-4 4M6 20v-4' },
  { path: '/execution', label: 'Execution', icon: 'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM8 12.5l2.7 2.7L16 9.5' }
]

/** Whether the app has a route for ``path`` (a screen another build step adds may be absent). */
export function routeExists (router, path) {
  return router.getRoutes().some((r) => r.path === path)
}

// ---------------------------------------------------------------------------- one reading

/**
 * Load a read when mounted and on `refresh()`. Only the newest request's answer is applied; an
 * older one arriving first is dropped. A failed refresh keeps the last body, labelled not
 * current; an answer in another context (mode or snapshot changed) replaces the old body whole
 * and is announced, never merged into it.
 */
export function useReading (load) {
  const state = shallowReactive({ status: 'loading', body: null, error: null, contextChanged: false })
  let newest = 0
  async function refresh () {
    const mine = ++newest
    state.status = 'loading'
    try {
      const body = await load()
      if (mine !== newest) return
      state.contextChanged = state.body !== null && contextKey(state.body) !== contextKey(body)
      state.body = body
      state.error = null
      state.status = 'loaded'
    } catch (error) {
      if (mine !== newest) return
      state.error = error
      state.contextChanged = false
      state.status = 'error'
    }
  }
  onMounted(refresh)
  return { state, refresh }
}

// ----------------------------------------------------------------------- deep links

/**
 * A link to a row on another screen, in the snapshot the link was made in: `focus` names the
 * row (`account:<id>`, `obligation:<id>`), `snapshot` the observed snapshot it was read from.
 */
export const rowLink = (path, focus, snapshot) => ({ path, query: { focus, snapshot } })

/**
 * The row a deep link names, focused once the screen has its answer: the element marked
 * `data-focus="<focus>"` scrolls into view and takes focus (the screen marks it with `focus`).
 * `moved` names the link's snapshot when it is no longer the one shown.
 */
export function useFocusTarget (reading) {
  const route = useRoute()
  const wanted = computed(() => (typeof route.query.focus === 'string' ? route.query.focus : null))
  const moved = computed(() => {
    const from = route.query.snapshot
    return typeof from === 'string' && !!reading.body && reading.body.snapshot_id !== from ? from : null
  })
  let done = null
  watch([() => reading.status, wanted], async ([status, focus]) => {
    if (status !== 'loaded' || !focus || done === focus) return
    await nextTick()
    const el = [...document.querySelectorAll('[data-focus]')].find((e) => e.dataset.focus === focus)
    if (!el) return
    done = focus
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'center' })
    el.focus({ preventScroll: true })
  }, { immediate: true })
  return { focus: wanted, moved }
}

// ------------------------------------------------------------------------------ the shell

function icon (d) {
  return h('svg', {
    viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false'
  }, [h('path', { d })])
}

let health = null
/**
 * The model the deployment runs its agents on, from /health: read once per page load when it
 * answers, read again by the next screen when it did not; null while unknown.
 */
export function modelSource () {
  health ??= request('/health').then((b) => b?.model ?? null).catch(() => {
    health = null
    return null
  })
  return health
}

/** A panel's element id from its label: stable, unique on the page. */
function panelId (label, taken) {
  const base = `panel-${String(label).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`
  let id = base
  for (let n = 2; taken.has(id); n++) id = `${base}-${n}`
  taken.add(id)
  return id
}

const PHONE = '(max-width: 767px)'
const SETTLE = 150 // ms: with no scrollend, a choice's scroll not moving by then, or no longer moving, is over
const LONGEST = 2000 // ms: where the browser sends scrollend, the longest a choice's scroll goes without one
const INTENT = 250 // ms: a page scroll this soon after the reader's wheel, touch, pointer or scroll key is theirs
const SCROLL_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '])


/**
 * One screen, in the handoff's shell (prp/2026-10-29-ux-shell/design.md): the logo and six
 * labelled links with the current one marked (a 208 px sidebar, a 72 px icon rail below 1200 px,
 * a 48 px header with a menu drawer below 768 px); then the main region — breadcrumb and context
 * bar (mode, model, as of, snapshot, Refresh; kept in view while scrolling), the title, the panel
 * index, the reading's error and context notices, and the screen itself, rendered only once there
 * is a body. The mode label is shown only from a loaded answer: nothing inherits an authoritative
 * badge from an earlier render.
 *
 * The handoff's loading, empty and failure states, the same on every screen: before the first
 * answer, skeleton tiles where the figures go and one polite "Loading"; a reading refused because
 * no run is prepared (`noDemoRun()`) is an inline explanation of what is missing, not an
 * error and not a chart; a failed first read says Could not load with Retry; a failed refresh
 * keeps the last body, labelled last loaded and not current, with Retry; `stale` (the screen's
 * stale accounts, `staleOf()`) draws a warning band naming each one and its as of.
 *
 * The drawer is modal while open: the page behind it is inert, Escape, the scrim or any link
 * closes it, and leaving the phone width closes it. The panel index lists every element the
 * screen marks `data-panel="<name>"`; the one at the top of the view carries aria-current while
 * the page scrolls. Choosing one scrolls to it and leaves focus where it was; it stays marked through
 * that scroll, and after it while in view, until the reader moves the page themselves (a scroll
 * right after their wheel, touch, scrollbar press or scroll key) or the route changes.
 */
export const ScreenShell = defineComponent({
  name: 'ScreenShell',
  props: {
    title: { type: String, required: true },
    reading: { type: Object, required: true },
    refresh: { type: Function, required: true },
    stale: { type: Array, default: () => [] }
  },
  setup (props, { slots }) {
    const route = useRoute()
    const router = useRouter()
    const screens = computed(() => SCREENS.filter((s) => routeExists(router, s.path)))
    const model = ref(null)
    const menu = ref(false)
    const panels = shallowRef([])
    const active = ref(null)
    const pageEl = ref(null)
    const mainEl = ref(null)
    const contextEl = ref(null)
    const indexEl = ref(null)
    const menuButton = ref(null)
    let elements = [] // the panels' elements, in page order
    let pinned = null // the panel last chosen from the index
    let flight = 0 // the timer that ends the scroll a choice started; 0 once that scroll is over
    let ends = false // whether the browser says when that scroll stops (scrollend)
    let reached = -Infinity // when the reader last reached for the page: wheel, touch, pointer, scroll key
    let stickyH = 0
    let frame = 0
    let stale = { panels: true, size: true }
    let mutations = null
    let resizes = null
    let phone = null

    /** The sticky context bar's height, and the bottom of the sticky header the panels scroll under. */
    function measure () {
      const page = pageEl.value
      if (!page) return
      const ctx = contextEl.value
      const contextH = ctx && getComputedStyle(ctx).position === 'sticky' ? ctx.offsetHeight : 0
      page.style.setProperty('--lw-context-h', `${contextH}px`)
      const index = indexEl.value
      stickyH = index ? (parseFloat(getComputedStyle(index).top) || 0) + index.offsetHeight : 0
      page.style.setProperty('--lw-sticky-h', `${stickyH}px`)
    }

    /**
     * The panels as drawn: top to bottom, then left to right within a row. A screen's grid may
     * place them out of DOM order (Simulation at two columns), so the reading order is read off
     * their boxes, never off the markup.
     */
    function drawn () {
      return elements.map((el) => {
        const box = el.getBoundingClientRect()
        return { el, top: Math.round(box.top), left: box.left }
      }).sort((a, b) => a.top - b.top || a.left - b.left)
    }

    /**
     * The panel at the top of the view: the chosen one while the scroll it started is under way;
     * else the first in the lowest drawn row whose top has reached the sticky header; at the
     * page's end, the chosen one while it is in view, else the first in the bottom row.
     */
    function track () {
      if (!elements.length) return
      if (flight && elements.some((el) => el.id === pinned)) {
        active.value = pinned // its target may still be below the view
        return
      }
      const order = drawn()
      const chosen = pinned && order.find((p) => p.el.id === pinned)
      let current = order[0]
      for (const p of order) {
        if (p.top <= stickyH + 16 && p.top > current.top) current = p
      }
      if (!chosen || chosen.top < 0 || chosen.top >= window.innerHeight) pinned = null
      const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
      if (atEnd && window.scrollY > 0) {
        current = pinned ? chosen : order.find((p) => p.top === order[order.length - 1].top)
      }
      active.value = current.el.id
    }

    /** Whether the marked panels changed since the last look. */
    function collect () {
      const taken = new Set()
      const found = mainEl.value ? [...mainEl.value.querySelectorAll('[data-panel]')] : []
      for (const el of found) {
        if (!el.id || taken.has(el.id)) el.id = panelId(el.dataset.panel, taken)
        else taken.add(el.id)
      }
      const same = found.length === elements.length &&
        found.every((el, n) => el === elements[n] && el.dataset.panel === panels.value[n].label)
      elements = found
      if (!same) panels.value = found.map((el) => ({ id: el.id, label: el.dataset.panel }))
      return !same
    }

    /** Batch the work into one frame: re-read the panels or the sizes only when they may have changed. */
    function schedule (what) {
      if (what) stale = { ...stale, [what]: true }
      if (frame) return
      frame = requestAnimationFrame(async () => {
        frame = 0
        const { panels: rescan, size } = stale
        stale = { panels: false, size: false }
        if (rescan && collect()) await nextTick() // the index renders before it is measured
        if (rescan || size) measure()
        track()
      })
    }
    /** A choice's scroll is over. */
    function ground () {
      clearTimeout(flight)
      flight = 0
    }
    /** It stopped: from here the page decides, the chosen panel kept while in view. */
    function land () {
      ground()
      schedule()
    }
    /** It is over once a while passes with no scroll event: SETTLE, or LONGEST where scrollend says so first. */
    function hold () {
      clearTimeout(flight)
      flight = setTimeout(land, ends ? LONGEST : SETTLE)
    }
    /** The reader moved the page themselves: the choice is over, and the index follows the page again. */
    function release () {
      ground()
      pinned = null
    }
    const reach = () => { reached = performance.now() }
    /** A press on the page's own scrollbar; a click on anything in the page is not a scroll. */
    const onPointer = (event) => { if (event.target === document.documentElement) reach() }

    const onScroll = () => {
      if (performance.now() - reached < INTENT) release()
      else if (flight) hold()
      schedule()
    }
    const onScrollEnd = () => { if (flight) land() }
    const onResize = () => schedule('size')

    function closeMenu (refocus) {
      if (!menu.value) return
      menu.value = false
      // the page stops being inert on the next render; only then can Menu take focus
      if (refocus) nextTick(() => menuButton.value?.focus())
    }

    function onKey (event) {
      if (event.key === 'Escape') closeMenu(true)
      else if (SCROLL_KEYS.has(event.key) && !event.target?.closest?.('input, textarea, select, [contenteditable]')) reach()
    }

    function onPhone (event) {
      if (!event.matches) closeMenu(false)
    }

    watch(() => route.fullPath, () => {
      closeMenu(false)
      release()
      schedule()
    })
    watch(menu, async (open) => {
      if (!open) return
      await nextTick()
      const nav = document.getElementById('lw-nav')
      ;(nav?.querySelector('a[aria-current="page"]') ?? nav?.querySelector('ul a'))?.focus()
    })

    onMounted(() => {
      modelSource().then((m) => { model.value = m })
      mutations = new MutationObserver(() => schedule('panels'))
      mutations.observe(mainEl.value, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-panel'] })
      if (window.ResizeObserver) {
        resizes = new ResizeObserver(onResize)
        resizes.observe(contextEl.value)
      }
      phone = window.matchMedia?.(PHONE)
      phone?.addEventListener?.('change', onPhone)
      window.addEventListener('scroll', onScroll, { passive: true })
      window.addEventListener('scrollend', onScrollEnd)
      window.addEventListener('wheel', reach, { passive: true })
      window.addEventListener('touchmove', reach, { passive: true })
      window.addEventListener('pointerdown', onPointer, { passive: true })
      window.addEventListener('resize', onResize)
      window.addEventListener('keydown', onKey)
      schedule('panels')
    })
    onBeforeUnmount(() => {
      mutations?.disconnect()
      resizes?.disconnect()
      phone?.removeEventListener?.('change', onPhone)
      if (frame) cancelAnimationFrame(frame)
      ground()
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('scrollend', onScrollEnd)
      window.removeEventListener('wheel', reach)
      window.removeEventListener('touchmove', reach)
      window.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('keydown', onKey)
    })

    /** A link to Overview that is never marked current: the nav link and the crumb say where you are. */
    function home (attrs, children) {
      return h(RouterLink, { to: '/overview', custom: true }, {
        default: ({ href, navigate }) => h('a', {
          ...attrs,
          href,
          onClick: (event) => { closeMenu(false); navigate(event) }
        }, children)
      })
    }

    function jump (event, id) {
      event.preventDefault()
      const el = document.getElementById(id)
      if (!el) return
      const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      reached = -Infinity // the click that chose it is not the reader scrolling
      pinned = id
      active.value = id
      ends = 'onscrollend' in window
      hold()
      el.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' })
    }

    return () => {
      const { status, error, contextChanged } = props.reading
      // nothing prepared to read, now or since the last answer: explained in place of the screen
      // and of any figures shown before, never an error
      const absent = error?.code === NO_DEMO_RUN
      const body = absent ? null : props.reading.body
      const busy = status === 'loading'
      const time = formatTime(body?.as_of)
      const mode = body ? (LABELS[body.mode] || body.mode) : 'Provider mode not loaded'
      const brand = (attrs) => home({ class: 'lw-brand', 'aria-label': 'LedgerWorld, Overview', ...attrs },
        [logoMark(), h('span', 'LedgerWorld')])

      const topbar = h('header', { class: 'lw-topbar', inert: menu.value }, [
        brand(),
        h('span', { class: 'lw-topbar__mode' }, body ? mode : ''),
        h('button', {
          type: 'button', class: 'lw-menu', ref: menuButton, 'data-test': 'menu',
          'aria-expanded': menu.value ? 'true' : 'false', 'aria-controls': 'lw-nav',
          onClick: () => { menu.value = !menu.value }
        }, [icon('M4 7h16M4 12h16M4 17h16'), h('span', 'Menu')])
      ])

      const nav = h('nav', { id: 'lw-nav', class: ['lw-nav', { 'is-open': menu.value }], 'aria-label': 'Screens' }, [
        brand({ 'data-test': 'brand-nav' }),
        h('ul', screens.value.map((s) => h('li', { key: s.path }, [
          h(RouterLink, {
            to: s.path,
            'aria-current': route.path === s.path ? 'page' : undefined,
            onClick: () => closeMenu(false)
          }, () => [icon(s.icon), h('span', s.label)])
        ])))
      ])
      const scrim = menu.value && h('div', { class: 'lw-scrim', 'aria-hidden': 'true', onClick: () => closeMenu(true) })

      const queried = typeof route.query.run_id === 'string' ? route.query.run_id : null
      const run = body?.run_id ?? queried
      const crumbs = h('nav', { class: 'lw-crumbs', 'aria-label': 'Breadcrumb', 'data-test': 'breadcrumb' }, [
        h('ol', [
          h('li', [home({}, 'LedgerWorld')]),
          h('li', { 'aria-current': run ? undefined : 'page' }, props.title),
          run && h('li', { 'aria-current': 'page' }, `Run ${run}`)
        ])
      ])
      const context = h('div', { class: 'lw-context', ref: contextEl, 'data-test': 'banner' }, [
        crumbs,
        h('div', { class: 'lw-context__bar' }, [
          h('span', { class: 'lw-context__mode', 'data-test': 'mode' }, mode),
          model.value && h('span', { class: 'lw-context__item', 'data-test': 'model' }, ['Model ', h('b', model.value)]),
          body && h('span', { class: 'lw-context__item', 'data-test': 'context-as-of' },
            ['As of ', h('b', time.utc), ` · ${time.local}`]),
          body && h('span', { class: 'lw-context__item', 'data-test': 'source' }, sourceLabel(body)),
          h('button', {
            type: 'button', class: 'lw-button lw-button--quiet', 'data-test': 'refresh',
            disabled: busy, onClick: () => props.refresh()
          }, error && !absent ? 'Retry' : 'Refresh')
        ])
      ])

      const index = panels.value.length > 0 && h('nav', {
        class: 'lw-panels', ref: indexEl, 'aria-label': 'Panels on this page', 'data-test': 'panel-index'
      }, [
        h('ol', panels.value.map((p) => h('li', { key: p.id }, [
          h('a', {
            href: `#${p.id}`, 'data-test': 'panel-link',
            'aria-current': active.value === p.id ? 'true' : undefined,
            onClick: (event) => jump(event, p.id)
          }, p.label)
        ])))
      ])

      const retry = h('button', {
        type: 'button', class: 'lw-button lw-button--quiet', 'data-test': 'retry',
        disabled: busy, onClick: () => props.refresh()
      }, 'Retry')
      const stale = body && props.stale.length > 0 && h('p', {
        class: 'lw-band lw-band--stale', role: 'status', 'data-test': 'stale-band'
      }, [
        h('strong', `${STATES.stale.icon} ${STATES.stale.word}: `),
        `last observed values for ${props.stale.map((f) => `${f.id}${f.at ? `, as of ${f.at}` : ''}`).join('; ')}. ` +
        'Refresh the evidence before acting on them; they are not current authority.'
      ])
      const notices = [
        error && !absent && h('div', { class: 'lw-alert', role: 'alert', 'data-test': 'error' }, [
          h('strong', `${STATES.error.icon} ${body ? `Could not refresh. ${STATES.error.word}` : 'Could not load'}. `),
          error.message, ' ', retry
        ]),
        stale,
        contextChanged && body && h('p', { class: 'lw-note', role: 'status', 'data-test': 'context-changed' },
          `The provider mode or snapshot changed; every figure below was reloaded for ` +
          `${LABELS[body.mode] || body.mode}, ${sourceLabel(body)}.`)
      ]
      const skeleton = () => h('article', { class: 'lw-tile' }, [
        h('span', { class: 'lw-skeleton lw-skeleton--label' }),
        h('span', { class: 'lw-skeleton lw-skeleton--figure' })
      ])
      let content
      if (body) content = slots.default?.({ body, busy })
      else if (absent) {
        content = h('section', { class: 'lw-empty', 'aria-labelledby': 'lw-empty-heading', 'data-test': 'empty' }, [
          h('h2', { id: 'lw-empty-heading' }, 'No prepared run'),
          h('p', `${error.message}. ${props.title} reads a prepared run; there is none to show, so nothing is drawn here.`),
          h('p', { class: 'lw-time' },
            'An operator prepares one with the demo command, then Refresh. The browser never starts a run or shows a receipt on its own.'),
          home({ class: 'lw-button lw-button--quiet', 'data-test': 'empty-overview' }, 'Open Overview')
        ])
      } else {
        // one element, never a bare array: an array would be patched in place into the screen's
        // compiled slot fragment once the answer arrives, leaving stale nodes behind
        content = h('div', { class: 'lw-pending' }, [
          busy && h('p', { class: 'lw-loading', role: 'status', 'data-test': 'loading' }, `Loading ${props.title}…`),
          h('div', { class: 'lw-strip', 'data-test': 'skeleton', 'aria-hidden': 'true' },
            [skeleton(), skeleton(), skeleton(), skeleton()])
        ])
      }
      const footer = SOURCE_URL && h('p', { class: 'lw-source' }, [
        h('a', { href: SOURCE_URL }, 'Source code (AGPL-3.0)')
      ])
      const main = h('main', { class: 'lw-main', ref: mainEl, inert: menu.value, 'aria-busy': busy ? 'true' : 'false' }, [
        context, h('h1', props.title), index, ...notices, content, footer
      ])
      return h('div', { class: 'lw-page', ref: pageEl }, [topbar, nav, scrim, main])
    }
  }
})

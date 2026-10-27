/**
 * The /api/v1 client and the shared screen shell (system brief §11–12, contract C6).
 *
 * - Reads are public; a write takes the operator's token as an argument, kept in memory by the
 *   caller and never written to storage, a URL or a log. No request is retried: a financial POST
 *   that times out is resolved by a GET, never by sending it again.
 * - The browser formats C6 and never recomputes S, P or K_p: money arrives as integer minor
 *   units with a currency and is formatted here, once, at the display boundary.
 * - A metric has four states — known, unknown, stale, unassessed — and an unknown is never 0.
 * - A late answer never overwrites a newer one: `latestOnly()` drops an answer for a context
 *   that is no longer selected, or one older than the answer already applied.
 */

import { computed, defineComponent, h, onMounted, reactive } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
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

/** One request to /api/v1, no retry. A C6 ErrorResponse becomes an ApiError with its code. */
export async function request (path, { method = 'GET', body, token, signal } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  let response
  try {
    response = await fetch(`${BASE}/api/v1${path}`, {
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

export const getHealth = (opts) => request('/health', opts)
export const getOverview = (opts) => request('/overview', opts)
export const getTreasury = (opts) => request('/treasury', opts)
export const getLending = (opts) => request('/lending', opts)

// ------------------------------------------------------------------------ late responses

/** The context an answer belongs to: never merge two of these into one apparent state. */
export function contextKey ({ mode, snapshot_id: snapshot, run_id: run, branch_id: branch } = {}) {
  return [mode ?? '', snapshot ?? '', run ?? '', branch ?? ''].join('|')
}

/**
 * A guard for one resource. `select(key)` names the context on screen; `issue()` stamps a
 * request; `accept(ticket, key)` says whether its answer may be applied: only for the selected
 * context, and never one older than an answer already applied (out-of-order polls).
 */
export function latestOnly (selected = null) {
  let issued = 0
  let applied = 0
  let context = selected
  return {
    select (key) {
      if (key !== context) applied = 0
      context = key
    },
    issue () {
      issued += 1
      return { generation: issued, context }
    },
    accept (ticket, key = ticket.context) {
      if (ticket.context !== context || key !== context) return false
      if (ticket.generation < applied) return false
      applied = ticket.generation
      return true
    }
  }
}

// ------------------------------------------------------------------------------ formatting

const EXPONENT = { JPY: 0 }

/** "70,000.00" from 7000000: integer minor units, no float arithmetic. */
export function formatAmount (minor, currency) {
  const exponent = EXPONENT[currency] ?? 2
  const negative = minor < 0
  const digits = String(Math.abs(minor)).padStart(exponent + 1, '0')
  const whole = digits.slice(0, digits.length - exponent) || '0'
  const fraction = exponent ? `.${digits.slice(digits.length - exponent)}` : ''
  return `${negative ? '-' : ''}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction}`
}

/** "USD 70,000.00". */
export function formatMoney (minor, currency) {
  return `${currency} ${formatAmount(minor, currency)}`
}

/** A C6 metric as text: a value only when known or stale; unknown and unassessed say so. */
export function metricText (metric) {
  if (!metric) return 'Unavailable'
  switch (metric.status) {
    case 'known': return formatMoney(metric.minor, metric.currency)
    case 'stale': return `${formatMoney(metric.minor, metric.currency)} · stale`
    case 'unknown': return 'Unknown'
    case 'unassessed': return 'Not assessed'
    default: return 'Unavailable'
  }
}

/** Icon + word for every state: status is never colour alone. */
export const STATES = {
  known: { icon: '●', word: 'Known', tone: 'muted' },
  unknown: { icon: '?', word: 'Unknown', tone: 'warn' },
  stale: { icon: '◷', word: 'Stale', tone: 'warn' },
  unassessed: { icon: '–', word: 'Not assessed', tone: 'muted' },
  kept: { icon: '✓', word: 'Floor kept', tone: 'ok' },
  breached: { icon: '✕', word: 'Floor breached', tone: 'bad' },
  loading: { icon: '…', word: 'Loading', tone: 'muted' },
  error: { icon: '!', word: 'Last loaded, not current', tone: 'bad' }
}

/** Floor kept or breached, read off an API headroom metric (P minimum − floor). */
export function floorState (headroom) {
  if (!headroom || headroom.status === 'unknown') return 'unknown'
  if (headroom.status === 'unassessed') return 'unassessed'
  return headroom.minor >= 0 ? 'kept' : 'breached'
}

const pad = (n) => String(n).padStart(2, '0')

/** Absolute UTC, and the browser's local time labelled separately. */
export function formatTime (iso) {
  if (!iso) return { utc: 'Unavailable', local: '' }
  const d = new Date(iso)
  const utc = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  const local = new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    timeZoneName: 'short'
  }).format(d)
  return { utc, local: `local ${local}` }
}

/** "t=40 h": whole hours from the response's as_of (simulated hours on a frozen snapshot). */
export function hoursFrom (asOf, at) {
  const hours = Math.round((Date.parse(at) - Date.parse(asOf)) / 3_600_000)
  return `t=${hours} h`
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

/** The six screens, in reading order; the shell links each one whose route is registered. */
export const SCREENS = [
  { path: '/overview', label: 'Overview' },
  { path: '/treasury', label: 'Treasury' },
  { path: '/lending', label: 'Lending' },
  { path: '/simulation', label: 'Live simulation' },
  { path: '/decisions', label: 'Decisions' },
  { path: '/execution', label: 'Execution' }
]

/** Whether the app has a route for ``path`` (a screen another build step adds may be absent). */
export function routeExists (router, path) {
  return router.getRoutes().some((r) => r.path === path)
}

// ---------------------------------------------------------------------------- one reading

/**
 * Load a read when mounted and on `refresh()`. Only the newest request's answer is applied. A
 * failed refresh keeps the last body, labelled not current; an answer in another context (mode
 * or snapshot changed) replaces the old body whole instead of merging into it.
 */
export function useReading (load) {
  const state = reactive({ status: 'loading', body: null, error: null, contextChanged: false })
  const guard = latestOnly()
  async function refresh () {
    const ticket = guard.issue()
    state.status = 'loading'
    try {
      const body = await load()
      if (!guard.accept(ticket)) return
      const key = contextKey(body)
      state.contextChanged = state.body !== null && contextKey(state.body) !== key
      state.body = body
      state.error = null
      state.status = 'loaded'
    } catch (error) {
      if (!guard.accept(ticket)) return
      state.error = error
      state.status = 'error'
    }
  }
  onMounted(refresh)
  return { state, refresh }
}

// ------------------------------------------------------------------------------ the shell

/**
 * Banner (mode and source, kept in view while scrolling), screen navigation and the main region
 * (title, as_of and Refresh, then the screen). The mode label is shown
 * only from a loaded answer: nothing inherits an authoritative badge from an earlier render.
 */
export const ScreenShell = defineComponent({
  name: 'ScreenShell',
  props: {
    title: { type: String, required: true },
    body: { type: Object, default: null },
    busy: { type: Boolean, default: false },
    refresh: { type: Function, default: null }
  },
  setup (props, { slots }) {
    const route = useRoute()
    const router = useRouter()
    const screens = computed(() => SCREENS.filter((s) => routeExists(router, s.path)))
    return () => {
      const body = props.body
      const time = formatTime(body?.as_of)
      const banner = h('header', { class: 'lw-banner', 'data-test': 'banner' }, [
        h('span', { class: 'lw-banner__mode', 'data-test': 'mode' },
          body ? (LABELS[body.mode] || body.mode) : 'Provider mode not loaded'),
        body && h('span', { 'data-test': 'source' },
          `${LABELS.synthetic} ${body.snapshot_id}`)
      ])
      const asOf = h('div', { class: 'lw-asof' }, [
        body && h('span', { class: 'lw-time' }, `as of ${time.utc} · ${time.local}`),
        props.refresh && h('button', {
          type: 'button', class: 'lw-button lw-button--quiet', 'data-test': 'refresh',
          disabled: props.busy, onClick: () => props.refresh()
        }, 'Refresh')
      ])
      const nav = h('nav', { class: 'lw-nav', 'aria-label': 'Screens' }, [
        h('ul', screens.value.map((s) => h('li', { key: s.path }, [
          h(RouterLink, {
            to: s.path,
            'aria-current': route.path === s.path ? 'page' : undefined
          }, () => s.label)
        ])))
      ])
      const footer = SOURCE_URL && h('p', { class: 'lw-source' }, [
        h('a', { href: SOURCE_URL }, 'Source code (AGPL-3.0)')
      ])
      const main = h('main', { class: 'lw-main', 'aria-busy': props.busy ? 'true' : 'false' }, [
        h('h1', props.title),
        asOf,
        slots.default?.(),
        footer
      ])
      return h('div', { class: 'lw-page' }, [banner, nav, main])
    }
  }
})

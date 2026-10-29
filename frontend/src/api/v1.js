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
  computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, watch
} from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import PageHero from '../components/PageHero.vue'
import Tip from '../components/Tip.vue'
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

const SYMBOL = { USD: '$', EUR: '€', GBP: '£' }

/**
 * "$70,000", "$1,234.50", "-$50,000", "CHF 12.30": the mockups' figure (prp/2026-10-29-ux-pass/
 * MATCH.md, item 5) — the currency's symbol where it has one, else its code, and whole units
 * when the minor part is zero.
 */
export function formatMoney (minor, currency) {
  const amount = formatAmount(minor, currency)
  if (!Number.isSafeInteger(minor)) return amount
  const plain = amount.replace(/^-/, '').replace(/\.0+$/, '')
  const sign = minor < 0 ? '-' : ''
  return SYMBOL[currency] ? `${sign}${SYMBOL[currency]}${plain}` : `${sign}${currency} ${plain}`
}

/** A C6 Money (`{minor, currency}`) as "$70,000". */
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
 * observed and carries its as_of; an unknown one was not and carries none. ``name`` is the
 * account in words, its owner first (`accountName()`); ``text`` reads "Lender venue account · ?
 * Unknown" or "Lender operating account · ◷ Stale, as of 2026-01-05 12:00 UTC". */
export function freshness (account) {
  const s = stateOf(account.status)
  const at = account.status === 'stale' && account.as_of ? formatTime(account.as_of).utc : null
  const name = accountName(account.account_id, { owner: true })
  return {
    ...s, id: account.account_id, name, at,
    text: `${name} · ${s.icon} ${s.word}${at ? `, as of ${at}` : ''}`
  }
}

const capital = (word) => word.charAt(0).toUpperCase() + word.slice(1)

/**
 * An account in the cash owner's words, from its id "<owner>/<kind>" (prp/2026-10-29-ux-pass/
 * COPY.md): "treasury/operating" reads "Operating account", with ``currency`` "Operating account ·
 * USD", and with ``owner`` (an account of any party) "Treasury operating account". The id itself
 * belongs in the panel's How we know.
 */
export function accountName (id, { currency, owner = false } = {}) {
  const text = String(id ?? '')
  const cut = text.indexOf('/')
  if (cut < 0) return text ? `${capital(text.replace(/[-_]+/g, ' '))} account${currency ? ` · ${currency}` : ''}` : 'An unnamed account'
  const who = text.slice(0, cut).replace(/[-_]+/g, ' ')
  const kind = text.slice(cut + 1).replace(/[-_/]+/g, ' ')
  // a kind that is the currency itself ("treasury/eur") is named by its code, and once
  if (currency && kind.toUpperCase() === currency) return owner ? `${capital(who)} ${currency} account` : `${currency} account`
  const name = owner ? `${capital(who)} ${kind} account` : `${capital(kind)} account`
  return currency ? `${name} · ${currency}` : name
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

/** "1 Jan, 00:00 UTC": an instant for the context bar; the full date and local time go in How we know. */
export function asOfText (iso) {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return 'Unavailable'
  return `${dayText(iso)}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
}

/**
 * "in 40 hours", "in 2 days", "now" or "3 hours ago": the time from the response's as_of to
 * ``at`` in whole hours (simulated hours on a frozen snapshot), in words (`hoursWords()`).
 */
export function hoursFrom (asOf, at) {
  const hours = Math.round((Date.parse(at) - Date.parse(asOf)) / 3_600_000)
  if (Number.isNaN(hours)) return 'at an unknown time'
  if (hours === 0) return 'now'
  return hours > 0 ? `in ${hoursWords(hours)}` : `${hoursWords(-hours)} ago`
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
    excluded: excluded.length ? `due after this point (${hoursFrom(asOf, t)}), so not counted: ${excluded.join(', ')}` : ''
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
  branch: 'What-if',
  replay: 'Replay'
}

/** The agents' model kind (/health `model`) in the cash owner's words; its own keyspace, never a mode's. */
export const AGENTS = { scripted: 'Scripted agents', live: 'Live AI agents' }

/** The bar's tag for figures that are not the observed snapshot: "What-if", "Replay", or both. */
export const contextTag = (body) =>
  [body?.replay && PLAIN.replay, body?.branch_id && PLAIN.branch].filter(Boolean).join(' · ')

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

/**
 * A metric as an amount in a lead sentence: its money, or "an unknown amount". A stale value
 * carries no tag here; `lastSeen()` says it once after the sentence.
 */
export const amountWords = (metric) => (metric?.minor == null ? 'an unknown amount' : money(metric))

/** The three plans in the cash owner's words (COPY.md glossary); the policy id stays in How we know. */
export const PLANS = { 'no-action': 'Do nothing', 'fixed-reserve': 'Keep a fixed buffer', integrated: 'Borrow just enough' }
/** The same plans as the subject of a sentence: "Borrowing just enough keeps you covered". */
export const PLANS_DOING = { 'no-action': 'Doing nothing', 'fixed-reserve': 'Keeping a fixed buffer', integrated: 'Borrowing just enough' }

/**
 * A provider's decimal amount ("10000.00") as integer minor units in ``currency``, by string
 * arithmetic only (no float); null when it is not a plain decimal with at most the currency's digits.
 */
export function decimalMinor (amount, currency) {
  const exponent = EXPONENT[currency] ?? 2
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(amount ?? ''))
  if (!m || (m[3] ?? '').length > exponent) return null
  const minor = Number(`${m[2]}${(m[3] ?? '').padEnd(exponent, '0')}`)
  return Number.isSafeInteger(minor) ? (m[1] ? -minor : minor) : null
}

/** A plan's funding cost summed over its what-if rows: integer minor units, one currency, or say so. */
export function feesAcross (rows) {
  const currency = rows[0].funding_cost.currency
  if (rows.some((r) => r.funding_cost.currency !== currency)) return 'Mixed currencies; not summed'
  const total = rows.reduce((sum, r) => sum + r.funding_cost.minor, 0)
  return `${formatMoney(total, currency)} across ${rows.length} what-if${rows.length === 1 ? '' : 's'}`
}

/** "240 h" as words for a sentence: "10 days" when it is whole days, else "240 hours". */
export function hoursWords (h) {
  if (!Number.isInteger(h) || h < 0) return 'an unknown time'
  if (h && h % 24 === 0) return h === 24 ? '1 day' : `${h / 24} days`
  return h === 1 ? '1 hour' : `${h} hours`
}

/** "payroll", "payroll and rent", "payroll, rent and tax". */
export function listWords (items) {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}

/** "Some figures were last seen 2026-01-05 12:00 UTC.", the oldest stale one, or '' when none is stale. */
export function lastSeen (...metrics) {
  const stale = metrics.filter((m) => m?.status === 'stale')
  if (!stale.length) return ''
  const at = stale.map((m) => m.as_of).filter(Boolean).sort()[0]
  return `Some figures were last seen ${at ? formatTime(at).utc : 'at an unknown time'}.`
}

/** What a response's figures are: a replay, a hypothetical branch, or the observed snapshot. */
export function sourceLabel (body) {
  if (body.replay) {
    const of = body.branch_id ? `${LABELS.branch} ${body.branch_id}` : (body.run_id ?? body.snapshot_id)
    return `${LABELS.replay} · ${of}`
  }
  if (body.branch_id) return `${LABELS.branch} ${body.branch_id}`
  return `${LABELS.synthetic} ${body.snapshot_id}`
}

/** The six screens, in reading order, with the mockups' icons; the shell links each one whose route is registered. */
export const SCREENS = [
  { path: '/overview', label: 'Overview', icon: 'M3 11l9-7 9 7M5 9.5V20h5v-6h4v6h5V9.5' },
  { path: '/treasury', label: 'Treasury', icon: 'M6 20v-8M12 20V5M18 20v-11' },
  { path: '/lending', label: 'Lending', icon: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3' },
  { path: '/simulation', label: 'Simulation', icon: 'M3 12h4l3-7 4 14 3-7h4' },
  { path: '/decisions', label: 'Decisions', icon: 'M6 3h12v18H6zM9 8h6M9 12h6M9 16h4' },
  { path: '/execution', label: 'Execution', icon: 'M7 4l13 8-13 8z' }
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

let company = null
/**
 * The company the treasury belongs to, from /overview's `company`, for the sidebar's company
 * block: read once per page load, again by the next screen when it did not answer; null while
 * unknown, and the block is left out.
 */
export function companySource () {
  company ??= getOverview().then((b) => b?.company ?? null).catch(() => {
    company = null
    return null
  })
  return company
}

/**
 * "Northwind Parts treasury (synthetic)" as the mockups' company block: the company's name
 * ("Northwind Parts") and whether the API marks it synthetic.
 */
export function companyName (party) {
  const raw = String(party?.name ?? '').trim()
  if (!raw) return null
  const synthetic = /\(synthetic\)\s*$/i.test(raw)
  const name = raw.replace(/\s*\(synthetic\)\s*$/i, '').replace(/\s+treasury$/i, '')
  return { name, treasury: `${name} treasury`, synthetic }
}

/** "January 1, 2026": the header's date, the UTC day of the reading's as_of. */
export function longDate (iso) {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return 'Date unavailable'
  return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
}

/** The reading's currency: the first one its figures name; '' when none does. */
export function currencyOf (body) {
  const seen = new Set()
  const find = (v, depth) => {
    if (!v || typeof v !== 'object' || depth > 6 || seen.has(v)) return ''
    seen.add(v)
    if (typeof v.currency === 'string') return v.currency
    for (const child of Array.isArray(v) ? v : Object.values(v)) {
      const c = find(child, depth + 1)
      if (c) return c
    }
    return ''
  }
  return find(body, 0)
}

/** The figures' kind for the header's second line: the observed snapshot is synthetic data. */
export function dataKind (body) {
  if (body?.replay) return PLAIN.replay
  if (body?.branch_id) return 'What-if branch'
  return 'Synthetic data'
}

const PHONE = '(max-width: 767px)'

/**
 * One screen, in the mockups' shell (prp/2026-10-29-ux-pass/MATCH.md, items 1–3): the logo, six
 * links with the mockups' icons and the current one marked, and the company block at the bottom
 * (a 208 px sidebar, a 72 px icon rail below 1200 px, a 48 px header with a menu drawer below
 * 768 px); then the main region — the header, the page hero, the reading's notices and the
 * screen itself, rendered only once there is a body.
 *
 * The header reads as the mockups do: "LedgerWorld / Page" left; "Simulated provider · Scripted
 * agents" and the reading's date right; a second line "Snapshot <id> · USD · Synthetic data".
 * Provider, model, full time, source and run sit in tooltips (`Tip`), never on the page. There is
 * no Refresh button: a screen reads again, silently, when its tab becomes visible again; a failed
 * read still says Could not load, with Retry. The hero (`PageHero`) carries the screen's
 * headline, subtitle and lead tooltip, and the `action` slot is its one primary button.
 *
 * Loading, empty and failure states are the same on every screen: before the first answer,
 * skeleton tiles and one polite "Loading"; a reading refused because no run is prepared
 * (`noDemoRun()`) is an inline explanation with the one action that fixes it; a failed refresh
 * keeps the last body, labelled not current, with Retry; `stale` (`staleOf()`) draws a warning
 * band naming each stale account and its as of.
 *
 * The drawer is modal while open: the page behind it is inert, Escape, the scrim or any link
 * closes it, and leaving the phone width closes it.
 */
export const ScreenShell = defineComponent({
  name: 'ScreenShell',
  props: {
    title: { type: String, required: true },
    headline: { type: String, default: '' },
    subtitle: { type: String, default: '' },
    lead: { type: String, default: '' },
    reading: { type: Object, required: true },
    refresh: { type: Function, required: true },
    stale: { type: Array, default: () => [] }
  },
  setup (props, { slots }) {
    const route = useRoute()
    const router = useRouter()
    const screens = computed(() => SCREENS.filter((s) => routeExists(router, s.path)))
    const model = ref(null)
    const party = ref(null)
    const menu = ref(false)
    const menuButton = ref(null)
    let phone = null

    function closeMenu (refocus) {
      if (!menu.value) return
      menu.value = false
      // the page stops being inert on the next render; only then can Menu take focus
      if (refocus) nextTick(() => menuButton.value?.focus())
    }
    const onKey = (event) => { if (event.key === 'Escape') closeMenu(true) }
    const onPhone = (event) => { if (!event.matches) closeMenu(false) }
    /** Back on the tab: read again, quietly, unless a read is under way. */
    const onVisible = () => {
      if (document.visibilityState === 'visible' && props.reading.status !== 'loading') props.refresh()
    }

    watch(() => route.fullPath, () => closeMenu(false))
    // the company block: the screen's own answer when it names the company, else /overview's,
    // asked once the screen has its answer so the two reads never run side by side
    watch(() => props.reading.status, (status) => {
      if (status !== 'loaded' || party.value || props.reading.body?.company) return
      companySource().then((c) => { party.value = c })
    }, { immediate: true })
    watch(menu, async (open) => {
      if (!open) return
      await nextTick()
      const nav = document.getElementById('lw-nav')
      ;(nav?.querySelector('a[aria-current="page"]') ?? nav?.querySelector('ul a'))?.focus()
    })

    onMounted(() => {
      modelSource().then((m) => { model.value = m })
      phone = window.matchMedia?.(PHONE)
      phone?.addEventListener?.('change', onPhone)
      window.addEventListener('keydown', onKey)
      document.addEventListener('visibilitychange', onVisible)
    })
    onBeforeUnmount(() => {
      phone?.removeEventListener?.('change', onPhone)
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('visibilitychange', onVisible)
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

    return () => {
      const { status, error, contextChanged } = props.reading
      // nothing prepared to read, now or since the last answer: explained in place of the screen
      // and of any figures shown before, never an error
      const absent = error?.code === NO_DEMO_RUN
      const body = absent ? null : props.reading.body
      const busy = status === 'loading'
      const time = formatTime(body?.as_of)
      const tag = body ? contextTag(body) : ''
      const mode = body ? (LABELS[body.mode] || PLAIN[body.mode] || body.mode) : 'Provider not loaded'
      const agents = model.value ? (AGENTS[model.value] || `Agents on ${model.value}`) : ''
      const firm = companyName(body?.company ?? party.value)
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
        ]))),
        firm && h('div', { class: 'lw-nav__company', 'data-test': 'company' }, [
          h('b', firm.name),
          firm.synthetic && h('span', 'Synthetic company')
        ])
      ])
      const scrim = menu.value && h('div', { class: 'lw-scrim', 'aria-hidden': 'true', onClick: () => closeMenu(true) })

      const queried = typeof route.query.run_id === 'string' ? route.query.run_id : null
      const run = body?.run_id ?? queried
      const crumbs = h('nav', { class: 'lw-crumbs', 'aria-label': 'Breadcrumb', 'data-test': 'breadcrumb' }, [
        h('ol', [
          h('li', [home({}, 'LedgerWorld')]),
          h('li', { 'aria-current': 'page' }, props.title)
        ])
      ])
      const facts = body && h('dl', { class: 'lw-context__facts' }, [
        h('div', [h('dt', 'Provider'), h('dd', { 'data-test': 'context-provider' }, LABELS[body.mode] || body.mode)]),
        h('div', [h('dt', 'Agents'), h('dd', model.value || 'Not reported')]),
        h('div', [h('dt', 'As of'), h('dd', `${time.utc} · ${time.local}`)]),
        h('div', [h('dt', 'Figures'), h('dd', { 'data-test': 'source' }, sourceLabel(body))]),
        h('div', [h('dt', 'Snapshot'), h('dd', { 'data-test': 'context-bar-snapshot' }, body.snapshot_id ?? 'Not named by the API')]),
        run && h('div', [h('dt', 'Run'), h('dd', { 'data-test': 'context-run' }, run)])
      ])
      const context = h('div', { class: 'lw-context', 'data-test': 'banner' }, [
        h('div', { class: 'lw-context__row' }, [
          crumbs,
          h('div', { class: 'lw-context__bar' }, [
            h(Tip, { test: 'how-context-bar' }, {
              default: () => h('span', { class: 'lw-context__item', 'data-test': 'mode' },
                [mode, agents && ` · ${agents}`, tag && ` · ${tag}`]),
              tip: () => facts || 'The provider is named once this page has loaded.'
            }),
            body && h(Tip, { class: 'lw-context__date', text: `As of ${time.utc} · ${time.local}` },
              () => h('span', { 'data-test': 'context-as-of' }, longDate(body.as_of)))
          ])
        ]),
        body && h('p', { class: 'lw-context__line', 'data-test': 'context-line' },
          [body.snapshot_id && `Snapshot ${body.snapshot_id}`, currencyOf(body), dataKind(body)].filter(Boolean).join(' · '))
      ])

      const hero = h(PageHero, { headline: props.headline || props.title, subtitle: body ? props.subtitle : '', lead: body ? props.lead : '' },
        body && slots.action ? () => slots.action({ body, busy }) : undefined)

      const retry = h('button', {
        type: 'button', class: 'lw-button lw-button--quiet', 'data-test': 'retry',
        disabled: busy, onClick: () => props.refresh()
      }, 'Retry')
      const stale = body && props.stale.length > 0 && h('p', {
        class: 'lw-band lw-band--stale', role: 'status', 'data-test': 'stale-band'
      }, [
        h('strong', `${STATES.stale.icon} ${STATES.stale.word}: `),
        `last observed values for ${props.stale.map((f) => `${f.name}${f.at ? `, as of ${f.at}` : ''}`).join('; ')}. ` +
        'Reload the page before acting on them; they are not current authority.'
      ])
      const notices = [
        error && !absent && h('div', { class: 'lw-alert', role: 'alert', 'data-test': 'error' }, [
          h('strong', `${STATES.error.icon} ${body ? `Could not refresh. ${STATES.error.word}` : 'Could not load'}. `),
          error.message, ' ', retry
        ]),
        stale,
        contextChanged && body && h('p', { class: 'lw-note', role: 'status', 'data-test': 'context-changed' },
          `The bank connection or the data behind this page changed; every figure below was reloaded for ${mode}.`)
      ]
      const skeleton = () => h('article', { class: 'lw-tile' }, [
        h('span', { class: 'lw-skeleton lw-skeleton--label' }),
        h('span', { class: 'lw-skeleton lw-skeleton--figure' })
      ])
      let content
      if (body) content = slots.default?.({ body, busy })
      else if (absent) {
        content = h('section', { class: 'lw-empty', 'aria-labelledby': 'lw-empty-heading', 'data-test': 'empty' }, [
          h('h2', { id: 'lw-empty-heading' }, 'No prepared run yet'),
          h('p', `${props.title} reads a prepared run, and there is none. An operator prepares one with the demo command.`),
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
      const main = h('main', { class: 'lw-main', inert: menu.value, 'aria-busy': busy ? 'true' : 'false' }, [
        context, hero, ...notices, content, footer
      ])
      return h('div', { class: 'lw-page' }, [topbar, nav, scrim, main])
    }
  }
})

/**
 * The narrated machine take (goal g5): a 3-second opening card that names the voice as synthetic,
 * then the seven timed beats of docs/video-script.md in real time on the deployed app, each with
 * its spoken line as a subtitle. scripts/narrated_take.sh lays the voice over the video afterwards.
 *
 * The plan is scripts/walkthrough_plan.py's (NARRATED_PLAN), the card scripts/voiceover.py's
 * (NARRATED_LABEL). Beats move as walkthrough.spec.ts's do: each opens its screen on the prepared
 * demonstration run and holds to its planned end; a late beat makes the next start at once.
 *
 * Three beats carry the script's operator actions, sent with LEDGERWORLD_DEMO_TOKEN from a request
 * context of their own, off-screen; the browser stays read-only (guard.ts) and never holds the token:
 *   Fork     start a run of the prepared scenario, fork it at the prepared checkpoint with the
 *            prepared policies, and show its screens as they arrive (the prepared run refuses forks)
 *   Execute  ask an approval for the fresh run's selected policy (else the prepared run's); a 409 is
 *            shown as the refusal it is. POST /executions is never sent.
 *   Explain  interview the lender at the checkpoint round of the prepared run's base branch
 * Each answer is shown on the caption as an off-screen operator action. Without a token none is
 * sent and the caption says so. Per-beat timing and every action (method, path, status, at; never
 * a header) go to $NARRATED_OUT/beats.json after every beat, with the card's length as `offset`.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, request as http, test, type APIRequestContext, type Page } from '@playwright/test'
import { readOnly } from './guard'

interface Beat { beat: string, start: number, end: number, route: string, subtitle: string }
interface Action { method: string, path: string, status: number | string, at: number, detail: string }
interface Result {
  beat: string, url: string, planned_start: number, planned_end: number, began: number,
  ready: number | null, left: number, reached: boolean, error: string, actions: Action[]
}
interface Answer { status: number | string, body: any }

const PLAN = process.env.NARRATED_PLAN
const OUT = process.env.NARRATED_OUT
const LABEL = process.env.NARRATED_LABEL
if (!PLAN || !OUT || !LABEL) throw new Error('NARRATED_PLAN, NARRATED_OUT and NARRATED_LABEL are not set: run scripts/narrated_take.sh URL')
const BEATS: Beat[] = JSON.parse(readFileSync(PLAN, 'utf-8')).beats
const CARD: { seconds: number, title: string, lines: string[] } = JSON.parse(readFileSync(LABEL, 'utf-8'))
const TOKEN = process.env.LEDGERWORLD_DEMO_TOKEN ?? ''

const SCENARIO = { family: 'delayed-receipt', seed: 7 } // the prepared run's own: backend/app/demo/prepare.py
const ROUNDS = 5
const GRACE_S = 20 // how far past its beat a fresh run may run before the take moves on
const QUESTION = 'What did you observe in this round, and why did you act as you did?'

const mmss = (s: number): string => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

let api: APIRequestContext
let actions: Action[] = []
let started = 0
const now = (): number => (performance.now() - started) / 1000

/** A read or an operator write to the API; a write is logged without its headers. */
async function call (method: 'GET' | 'POST', path: string, data?: object, timeout = 30_000): Promise<Answer> {
  let answer: Answer
  try {
    const r = await api.fetch(`/api/v1${path}`, {
      method, data, timeout, failOnStatusCode: false,
      headers: method === 'POST' ? { Authorization: `Bearer ${TOKEN}` } : {}
    })
    answer = { status: r.status(), body: await r.json().catch(() => null) }
  } catch (error) {
    answer = { status: 'no answer', body: { message: String((error as Error).message).split('\n')[0] } }
  }
  if (method === 'POST') {
    const b = answer.body ?? {}
    const detail = typeof answer.status === 'number' && answer.status < 300 ? '' : `${b.code ?? ''} ${b.message ?? b.detail ?? ''}`.trim()
    actions.push({ method, path, status: answer.status, at: now(), detail })
  }
  return answer
}

const refusal = (a: Answer): string => `${a.status}${a.body?.code ? ` ${a.body.code}` : ''}${a.body?.message ? `: ${a.body.message}` : ''}`

/** The caption box: fixed over the bottom of the screen, never in the way of a click. */
async function caption (page: Page, title: string, text: string, notes: string[]): Promise<void> {
  await page.evaluate(({ title, text, notes }) => {
    let box = document.getElementById('lw-narrated-caption')
    if (!box) {
      box = document.createElement('div')
      box.id = 'lw-narrated-caption'
      box.setAttribute('aria-hidden', 'true')
      box.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;' +
        'pointer-events:none;padding:10px 16px;background:rgba(10,12,16,.88);color:#fff;' +
        'font:13px/1.4 system-ui,sans-serif;max-height:38vh;overflow:hidden'
      document.body.appendChild(box)
    }
    box.innerHTML = ''
    const head = document.createElement('strong')
    head.textContent = title
    const body = document.createElement('div')
    body.textContent = text
    box.append(head, body)
    for (const note of notes) {
      const line = document.createElement('em')
      line.style.display = 'block'
      line.textContent = note
      box.append(line)
    }
  }, { title, text, notes }).catch(() => {})
}

/** Loaded means the screen's reading arrived: a source label and no load error. */
async function ready (page: Page): Promise<void> {
  await expect(page.locator('h1')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('main.lw-main')).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 })
  await expect(page.locator('[data-test="error"]'), 'the screen shows a load error').toHaveCount(0)
  await expect(page.locator('[data-test="source"]').first()).not.toBeEmpty({ timeout: 5_000 })
}

/** Scroll through the screen evenly over the time left, until `until`. */
async function hold (page: Page, until: number): Promise<void> {
  const steps = Math.max(1, Math.ceil(until - now()))
  for (let i = 1; i <= steps && now() < until; i++) {
    await page.evaluate((f) => window.scrollTo({ top: f * (document.documentElement.scrollHeight - innerHeight) }), i / steps)
      .catch(() => {})
    await page.waitForTimeout(Math.max(0, Math.min(1000, (until - now()) * 1000)))
  }
}

/** Poll a read until `done` says so or the deadline passes; the last answer either way. */
async function until (path: string, done: (a: Answer) => boolean, deadline: number): Promise<Answer> {
  let a = await call('GET', path)
  while (!done(a) && now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2_000))
    a = await call('GET', path)
  }
  return a
}

interface Fresh { run: string, status: string, selected: string | null }
interface Stage { say: (note: string) => Promise<void>, show: (url: string) => Promise<void> }

/** Fork: a fresh run of the prepared scenario, forked at the prepared checkpoint. */
async function fork (stage: Stage, page: Page, beat: Beat, prepared: any): Promise<Fresh | null> {
  await hold(page, Math.min(beat.end, now() + 12)) // the prepared comparison first
  if (!TOKEN) {
    await stage.say('Not performed: the fresh branch is an operator POST and no demo token was given.')
    return null
  }
  const deadline = beat.end + GRACE_S
  const overview = await call('GET', '/overview')
  const run = await call('POST', '/runs', { snapshot_id: overview.body?.snapshot_id, scenario: SCENARIO, rounds: ROUNDS })
  if (run.status !== 202) {
    await stage.say(`Off-screen operator POST /runs was refused (${refusal(run)}); no fresh branch this take.`)
    return null
  }
  const id: string = run.body.run_id
  await stage.show(`/simulation?run_id=${encodeURIComponent(id)}`)
  await stage.say(`Off-screen operator POST /runs → 202: a new run ${id} of the same scenario starts now.`)
  const ran = await until(`/runs/${encodeURIComponent(id)}`, (a) => ['done', 'failed', 'cancelled'].includes(a.body?.status), deadline)
  if (ran.body?.status !== 'done') {
    await stage.say(`Run ${id} is ${ran.body?.status ?? refusal(ran)} at the beat's end; its fork is not shown.`)
    return null
  }
  await stage.show(`/simulation?run_id=${encodeURIComponent(id)}`)
  const forked = await call('POST', `/runs/${encodeURIComponent(id)}/fork`, {
    checkpoint_round: prepared.checkpoint_round,
    policies: (prepared.results ?? []).map((r: any) => r.policy)
  })
  if (forked.status !== 202) {
    await stage.say(`Off-screen operator POST /runs/${id}/fork was refused (${refusal(forked)}).`)
    return null
  }
  await stage.say(`Off-screen operator POST /runs/${id}/fork → 202: ${forked.body.branch_ids.length} fresh branches at round ${prepared.checkpoint_round}.`)
  const decided = await until(`/decisions/${encodeURIComponent(id)}`, (a) => a.status !== 200 || a.body?.status !== 'pending', deadline)
  if (decided.status !== 200 || decided.body?.status === 'pending') {
    await stage.say(`The fresh branches had not decided by the beat's end (${decided.status === 200 ? 'pending' : refusal(decided)}).`)
    return null
  }
  await stage.show(`/decisions?run_id=${encodeURIComponent(id)}`)
  await stage.say(`Fresh branches of ${id}: ${decided.body.status}${decided.body.selected ? `, selected ${decided.body.selected}` : ''}.`)
  return { run: id, status: decided.body.status, selected: decided.body.selected ?? null }
}

/** Execute: an approval request, shown as its answer; never an execution. */
async function approve (stage: Stage, fresh: Fresh | null, prepared: any): Promise<void> {
  if (!TOKEN) {
    await stage.say('Not performed: the approval request is an operator POST and no demo token was given. What follows is an inspection of the saved receipt.')
    return
  }
  const own = fresh?.status === 'selected' && fresh.selected
  const runId = own ? fresh.run : prepared.run_id
  const policy = own ? fresh.selected : prepared.selected
  const a = await call('POST', '/approvals', { run_id: runId, policy })
  if (a.status === 201) {
    const ap = a.body.approval
    const legs = (ap.legs ?? []).map((l: any) => `${l.kind} ${l.amount?.currency} ${l.amount?.minor} minor units`).join(', ')
    await stage.say(`Off-screen operator POST /approvals → 201 for ${runId} (${policy}): approval ${ap.approval_id}, ${legs}; plan ${String(ap.plan_hash).slice(0, 12)}…, snapshot ${ap.snapshot_id}, expires ${ap.expires_at}, mode ${ap.mode}.`)
    await stage.say('It is not executed in this take and expires unused. The prepared execution\'s own receipt is on screen.')
  } else {
    await stage.say(`Off-screen operator POST /approvals for ${runId} (${policy}) → ${refusal(a)}. Approval is one-shot, so this is an inspection of the saved approval's receipt, not a new approval.`)
  }
}

/** Explain: one read-only interview question to the lender at the checkpoint round. */
async function interview (stage: Stage, prepared: any): Promise<void> {
  if (!TOKEN) {
    await stage.say('Not performed: the interview is an operator POST and no demo token was given.')
    return
  }
  const run = await call('GET', `/runs/${encodeURIComponent(prepared.run_id)}`)
  const base = (run.body?.branches ?? []).find((b: any) => !b.parent_branch_id)?.branch_id
  const intents = (run.body?.rounds ?? []).filter((r: any) => r.branch_id === base).flatMap((r: any) => r.intents)
  const pick = intents.find((i: any) => i.actor_id === 'lender' && i.round === prepared.checkpoint_round) ??
    intents.find((i: any) => i.actor_id === 'lender') ?? intents[0]
  if (!pick) {
    await stage.say('Not performed: the prepared run shows no actor to interview.')
    return
  }
  const a = await call('POST', '/interview', {
    run_id: prepared.run_id, branch_id: base, round: pick.round, actor_id: pick.actor_id, question: QUESTION
  }, 90_000)
  await stage.say(`Off-screen operator POST /interview, ${pick.actor_id} at round ${pick.round}: “${QUESTION}”`)
  if (a.status === 200) {
    const answer = String(a.body.answer)
    await stage.say(`Answer (read-only, replay ${a.body.replay}): ${answer.length > 300 ? `${answer.slice(0, 300)}…` : answer}`)
    await stage.say(`Evidence: ${(a.body.evidence_ids ?? []).map((e: string) => e.slice(0, 12)).join(', ') || 'none'}`)
  } else {
    await stage.say(`Refused: ${refusal(a)}.`)
  }
}

test('narrated take: opening card, seven timed beats, off-screen operator actions', async ({ page, baseURL }) => {
  mkdirSync(OUT, { recursive: true })
  api = await http.newContext({ baseURL, userAgent: 'ledgerworld-narrated-take/1' })
  const writes = await readOnly(page, baseURL!)

  // the card, on a blank page before the app: the first thing the video shows
  const t0 = performance.now()
  await page.setContent('<main id="card"></main>')
  await page.evaluate(({ title, lines }) => {
    const card = document.getElementById('card')!
    card.style.cssText = 'position:fixed;inset:0;display:flex;flex-direction:column;justify-content:center;' +
      'padding:0 12%;background:#0a0c10;color:#fff;font:22px/1.5 system-ui,sans-serif'
    const head = document.createElement('h1')
    head.textContent = title
    card.append(head, ...lines.map((text) => Object.assign(document.createElement('p'), { textContent: text })))
  }, CARD)
  await page.waitForTimeout(CARD.seconds * 1000)
  const offset = (performance.now() - t0) / 1000

  const overview = await call('GET', '/overview')
  const runId: string | null = overview.body?.demo?.run_id ?? null
  const decisions = runId ? await call('GET', `/decisions/${encodeURIComponent(runId)}`) : null
  const prepared = { ...(decisions?.body ?? {}), run_id: runId }

  started = performance.now()
  const results: Result[] = []
  let fresh: Fresh | null = null
  let shown = ''
  for (const beat of BEATS) {
    actions = []
    const query = (run: string | null): string => run && beat.route !== '/overview' ? `?run_id=${encodeURIComponent(run)}` : ''
    const url = beat.route + query(beat.beat === 'Break' && fresh ? fresh.run : runId)
    const result: Result = {
      beat: beat.beat, url, planned_start: beat.start, planned_end: beat.end, began: now(),
      ready: null, left: 0, reached: false, error: '', actions
    }
    const title = `Machine take · synthetic voice — ${beat.beat} ${mmss(beat.start)}–${mmss(beat.end)}`
    const notes: string[] = []
    const stage: Stage = {
      say: async (note) => { notes.push(note); await caption(page, title, beat.subtitle, notes) },
      show: async (to) => {
        await page.goto(to, { timeout: 30_000 }).then(async () => await ready(page)).catch(() => {})
        shown = to
        await caption(page, title, beat.subtitle, notes)
      }
    }
    try {
      if (url !== shown) {
        shown = ''
        await page.goto(url, { timeout: 30_000 })
        shown = url
      }
      await ready(page)
      result.reached = true
    } catch (error) {
      result.error = String((error as Error).message ?? error).split('\n')[0]
    }
    result.ready = result.reached ? now() : null
    await caption(page, title, beat.subtitle, notes)
    if (beat.beat === 'Fork') fresh = await fork(stage, page, beat, prepared)
    if (beat.beat === 'Execute') await approve(stage, fresh, prepared)
    if (beat.beat === 'Explain') await interview(stage, prepared)
    await hold(page, beat.end)
    result.left = now()
    results.push(result)
    writeFileSync(join(OUT, 'beats.json'), JSON.stringify({ offset, operator: TOKEN !== '', writes, beats: results }, null, 2))
  }
  await api.dispose()

  expect(writes, 'the browser sent a write').toEqual([])
  expect(results.filter((r) => !r.reached).map((r) => `${r.beat} ${r.url}: ${r.error}`),
    'beats whose screen did not load').toEqual([])
})

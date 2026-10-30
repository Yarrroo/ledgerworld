<template>
  <ScreenShell title="Simulation" headline="See the crisis before it spreads." :subtitle="subtitle" :lead="lead"
               :reading="shellReading" :refresh="reload">
    <template #action>
      <RouterLink v-if="compareTarget" class="lw-button" :to="compareTarget" data-test="compare">
        Compare policies<Arrow />
      </RouterLink>
      <Tip v-else :text="compareWhy" test="compare-why">
        <button type="button" class="lw-button" disabled data-test="compare">Compare policies</button>
      </Tip>
    </template>
    <template #default>
    <div class="lw-live" :class="{ 'is-graph-expanded': graphExpanded }" data-test="graph">
      <section class="lw-sim__context" aria-label="Run and scenario context" data-test="run-context">
        <div class="lw-sim__selector"><span>Scenario</span><Tip :text="`Run ${body?.run_id ?? runId}`"><b>Demo run</b></Tip></div>
        <div class="lw-sim__selector"><span>Branch</span><Tip :text="`${base.branch_id} · ${provenance(base.replay)} · ${checkpoints}`"><b>Base</b></Tip></div>
        <div class="lw-sim__selector"><span>Cohort</span><Tip :text="family?.about ?? 'No scenario family named by this run'"><b data-test="cohort-name">{{ family ? family.id.replaceAll('-', ' ') : 'Not named' }}</b></Tip></div>
        <Tip text="Inspect the prepared scenario families; opening settings changes nothing."><button type="button" class="lw-button lw-button--quiet" data-test="settings" @click="settingsOpen = true">Scenario settings</button></Tip>
        <HowWeKnow test="how-run">
          <span data-test="run-id">{{ body?.run_id ?? runId }}</span> · {{ base.branch_id }} · {{ provenance(base.replay) }} · {{ checkpoints }} · {{ LABELS[body?.mode] }}
          <span data-test="family">{{ family?.id ?? 'not named by this run' }}</span>
          <span data-test="hypothetical">{{ PLAIN.branch }}</span>
          <span v-if="handoff" data-test="handoff">{{ handoff }}</span>
        </HowWeKnow>
        <p v-if="handoffMismatch" class="lw-note lw-sim__handoff" role="status" data-test="handoff-mismatch">{{ handoffMismatch }}</p>
      </section>

      <section class="lw-live__graph" aria-label="World map and actor inspector" data-test="relationships">
        <div class="lw-sim__map">
          <h2 data-test="relationships-title">Market relationships at round {{ display ?? '–' }}</h2>
          <p class="lw-sim__sub">{{ worldMap.nodes.length }} actors · Cash flows and information</p>
          <WorldMap :nodes="worldMap.nodes" :edges="worldMap.edges" :selected="mapSelected" :layout="MAP_LAYOUT" :legend="false"
                    label="Actors and their typed relationships at the selected round"
                    :empty="current ? 'No actor to draw' : 'Round not loaded'" @select="pickMap" />
        </div>
        <div class="lw-live__inspector" data-test="inspector">
          <h2>{{ actorInfo?.label ?? 'Select an actor' }}</h2>
          <p class="lw-sim__sub" data-test="selected-round">Selected actor · Round {{ display ?? '–' }}</p>
          <p v-if="!current" class="lw-live-empty">Round not loaded</p>
          <article v-else-if="actorInfo" class="lw-sim__actor" data-test="actor-detail">
            <h3>What changed</h3>
            <ol v-if="actorTimeline.length" class="lw-sim__timeline" data-test="actor-actions">
              <li v-for="x in actorTimeline" :key="x.id"><Tip :text="x.detail"><b>h{{ x.hour }} · {{ x.title }}</b><span>{{ x.text }}</span></Tip></li>
            </ol>
            <p v-else class="lw-sim__sub">No change recorded by this round.</p>
            <HowWeKnow test="how-actor"><span>Role: {{ actorInfo.role }}. Objective: {{ actorInfo.objective }}. Observes: {{ actorInfo.sees }}.</span>
              <span v-for="x in actorInfo.actions" :key="x.id">{{ x.id }} · {{ x.verdict }} · journal {{ x.journal ?? 'none' }} · evidence {{ x.evidence || 'none cited' }}</span>
            </HowWeKnow>
          </article>
          <form class="lw-live__interview" data-test="interview" @submit.prevent="interview">
            <label><span>Ask this actor</span><input v-model="question" maxlength="2000" placeholder="Why did this change?" data-test="question"></label>
            <Tip test="ask-tip"><button type="submit" class="lw-button" :disabled="Boolean(interviewWhy)" data-test="ask">Interview</button>
              <template #tip>Read-only: the answer changes nothing.<span v-if="interviewWhy" data-test="interview-why"> {{ interviewWhy }}.</span></template></Tip>
          </form>
          <label class="lw-live__token"><span>Operator access{{ token ? '' : ' required' }}</span><Tip text="Kept in this tab's memory only; never stored or exported."><input v-model="token" type="password" autocomplete="off" spellcheck="false" data-test="token" aria-label="Operator access"></Tip></label>
          <button v-if="token" type="button" class="lw-button lw-button--quiet" data-test="forget" @click="token = ''">Forget access</button>
          <p v-if="interviewError" class="lw-alert" role="alert" data-test="interview-error">{{ interviewError }}</p>
          <article v-if="answer" class="lw-live__answer" data-test="answer">
            <Tip :text="`Read-only answer · branch ${answer.branch_id}${answer.replay ? ` · ${PLAIN.replay}` : ''}`">{{ nameOf(answer.actor_id) }} at round {{ answer.round }}</Tip><p>{{ answer.answer }}</p>
            <HowWeKnow v-if="answer.evidence_ids.length" test="how-answer">evidence: {{ answer.evidence_ids.join(', ') }}</HowWeKnow>
          </article>
          <a href="#simulation-evidence" class="lw-sim__source" @click.prevent="sourceOpen = !sourceOpen">Source evidence →</a>
        </div>
      </section>

      <section class="lw-live__controls" aria-label="Round and controls" data-test="controls">
        <div class="lw-sim__round-row">
          <Tip :text="playing ? 'Pause local playback; the simulation job continues.' : 'Play committed rounds only; no financial action is created.'"><button type="button" class="lw-button lw-button--quiet" data-test="play" :disabled="!ticks.length" @click="playing ? pause() : play()">{{ playing ? 'Pause playback' : 'Play' }}</button></Tip>
          <Scrubber :model-value="display" :rounds="ticks" :loaded="loadedRounds" :t-hours="current?.t_hours ?? null" :horizon="world ? HORIZON_ROUNDS : 0" :marks="shockMarks"
                    :hint="`Round n is simulated hour ${ROUND_HOURS}n. ←/→ step, Home and End jump; moving the cursor never creates a financial action.`" @update:model-value="scrub" />
          <div class="lw-sim__fork">
            <Tip test="fork-tip"><button type="button" class="lw-button lw-button--quiet" data-test="fork" :disabled="Boolean(forkWhy)" :aria-expanded="confirming ? 'true' : 'false'" @click="confirming = true">Fork checkpoint</button>
              <template #tip><span data-test="fork-what">Tries each plan from round {{ display ?? '–' }} in its own what-if; approves nothing.</span><span v-if="forkWhy" data-test="fork-why"> {{ forkWhy }}.</span></template></Tip>
            <small>Playback only · No funds move</small>
          </div>
        </div>
        <Tip test="phase-tip"><span class="lw-live__phase" :class="`is-${phase.tone}`" role="status" data-test="phase">{{ phase.icon }} {{ phase.text }}</span>
          <template #tip>{{ phase.text }} · {{ base.branch_id }}<span v-if="base.replay" data-test="replay-note"> Replay: these rounds were replayed, not run fresh.</span></template></Tip>
        <p v-if="paused" class="lw-sim__sub" data-test="paused">Playback paused; simulation may continue</p>
        <div v-if="confirming && !forkWhy" class="lw-sim__confirm" role="group" aria-label="Confirm the fork" data-test="fork-confirm-panel">
          <p>Try {{ listWords(POLICIES.map((p) => PLANS[p])) }} from round {{ display }}, each in its own fresh what-if. It creates no approval and moves no money.</p>
          <Tip :text="`Forks ${base.branch_id} at committed round ${display} into ${POLICIES.join(', ')}.`"><button type="button" class="lw-button" data-test="fork-confirm" @click="confirmFork">Try the plans</button></Tip>
          <button type="button" class="lw-button lw-button--quiet" data-test="fork-cancel" @click="confirming = false">Cancel</button>
        </div>
        <p v-if="forked" role="status" data-test="forked"><Tip :text="`Branches: ${forked.branch_ids.join(', ') || 'none named yet'}`">Fork accepted at round {{ forked.round }} · {{ forked.done ? 'branches and cash paths loaded' : 'running; its branches appear here when it finishes' }}</Tip></p>
        <p v-if="forked?.lag" role="status" data-test="fork-lag">Fork progress not read: {{ forked.lag }}; still checking</p>
        <p v-if="forkError" class="lw-alert" role="alert" data-test="fork-error">{{ forkError }}</p>
      </section>

      <CashPaths class="lw-live__cash" :round="display" :at="roundAt" :paths="body?.cash_paths ?? []" :branches="body?.branches ?? []" :account="cashAccount" :epoch="epoch" />

      <details id="simulation-evidence" class="lw-sim__source-evidence" :open="sourceOpen" @toggle="sourceOpen = $event.target.open">
        <summary>Source evidence</summary>
        <ul class="lw-live__actors" aria-label="Actors, the keyboard way to the map">
          <li v-for="a in actors" :key="a.id"><Tip :text="`${a.id}${a.active ? ' · acted this round' : ''}`"><button type="button" class="lw-button lw-button--quiet" :aria-pressed="a.id === actor ? 'true' : 'false'" :data-actor="a.id" @click="selectActor(a.id)">{{ a.name }}<span v-if="a.active"> · acted this round</span></button></Tip></li>
        </ul>
        <a v-if="exportHref" class="lw-button lw-button--quiet" :href="exportHref" :download="exportName" data-test="export">Export round {{ display }}</a>
        <ActionFeed class="lw-live__feed" :round="display" :loaded="Boolean(current)" :posts="roundPosts" :intents="current?.intents ?? []" :cleared="current?.cleared ?? []" :replay="base.replay" :highlight="actor" @pick="pickEvent" />
        <details class="lw-sim__evidence" :open="graphExpanded" @toggle="evidenceToggled"><summary>Evidence graph: posts and the citations behind each intent</summary>
          <div class="lw-live__graph-view"><LiveGraph ref="graphPanel" :graph-data="graphData" :loading="busy" :is-simulating="phase.running" @refresh="reload" @toggle-maximize="graphExpanded = !graphExpanded" /></div>
        </details>
      </details>
    </div>

    <DetailSheet :open="Boolean(evidence)" :title="evidence?.title ?? 'Evidence'" test="evidence-sheet" @close="evidence = null">
      <dl v-if="evidence" data-test="evidence-detail">
        <template v-for="row in evidence.rows" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template>
      </dl>
      <p v-if="evidence?.note" class="lw-time">{{ evidence.note }}</p>
    </DetailSheet>

    <DetailSheet :open="settingsOpen" title="Scenario settings" test="settings-sheet" @close="settingsOpen = false">
      <p class="lw-time">Read-only: the prepared scenario families. Custom parameters and new runs need API support that does not exist yet.</p>
      <ol class="lw-sim__families" data-test="families">
        <li v-for="f in FAMILIES" :key="f.id" :class="{ 'is-current': f.id === family?.id }" :data-family="f.id">
          <strong>{{ f.id }}</strong><template v-if="f.id === family?.id"> · this run</template>
          <p>{{ f.about }}</p>
          <p class="lw-time">{{ Object.entries(f.params).map(([k, v]) => `${k} ${v}`).join(' · ') || 'no parameters' }}</p>
        </li>
      </ol>
    </DetailSheet>
    </template>
  </ScreenShell>
</template>

<script setup>
/**
 * Simulation (system brief §11–13, ui HANDOFF Simulation row, fixture scrubber.json).
 *
 * One committed-round cursor drives the cash paths, the action feed, the graph and the actor
 * inspector. Only rounds 1..committed_round enter the scrubber; a round the API did not return
 * reads "Round not loaded" in every panel, never the latest data. A round sits at the base
 * branch's first cash point plus its `t_hours`, and a cash point matches only at that instant.
 * Pause stops local playback; the job keeps running and keeps being polled. Fork and the
 * read-only interview carry the selected round and need operator access, a token that lives in this
 * component's memory only — never storage, the URL, the export or a log. An accepted fork is
 * followed until its branches arrive or it fails. No POST is retried.
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import LiveGraph from '../components/LiveGraph.vue'
import Scrubber from '../components/Scrubber.vue'
import ActionFeed from '../components/ActionFeed.vue'
import CashPaths from '../components/CashPaths.vue'
import DetailSheet from '../components/DetailSheet.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
import Tip from '../components/Tip.vue'
import Arrow from '../components/Arrow.vue'
import WorldMap from '../components/WorldMap.vue'
import { FAMILIES, ROUND_HOURS, familyOf, observedBy, worldFor } from '../api/world.js'
import {
  LABELS, PLAIN, PLANS, ScreenShell, formatMoney, getOverview, getTreasury, hoursWords, kindText, listWords, money,
  noDemoRun, request, routeExists, sourceLabel, useReading
} from '../api/v1.js'

const HORIZON_ROUNDS = 18
const POLICIES = ['no-action', 'fixed-reserve', 'integrated']
const PLAY_MS = 1500
const POLL_MS = 4000

const route = useRoute()
const router = useRouter()
/** A query value the link carried — the run, or what a handoff brought — when there is one. */
const handedOff = (key) => (typeof route.query[key] === 'string' && route.query[key]) || null
const runId = computed(() => handedOff('run_id'))

// With no run named (the nav link), the prepared demonstration run, as Decisions and Execution
// read it, named in the URL by this read (so the run watcher does not read it again), and only
// while the URL is still the one it was asked from; with none prepared, the shell explains it.
let adopted = null
const treasury = shallowRef(null)
const { state, refresh } = useReading(async () => {
  let run = runId.value
  if (!run) {
    const asked = route.fullPath
    run = (await getOverview()).demo?.run_id ?? null
    if (!run) throw noDemoRun()
    if (route.fullPath === asked) {
      adopted = run
      await router.replace({ query: { ...route.query, run_id: run } }).finally(() => { adopted = null })
    }
  }
  const body = await request(`/runs/${encodeURIComponent(run)}`)
  // the treasury on the run's snapshot, read once per snapshot (not on every poll) and after the
  // run, never beside it: the offline app's SQLite refuses a ledger read beside a job-store read
  // a read that failed is read again on the next load; one that answered for another snapshot is kept
  const key = `${body.snapshot_id}|${body.run_id}`
  if (treasury.value?.for !== key || treasury.value.failed) {
    const t = await getTreasury().catch(() => null)
    const same = t && t.mode === body.mode && (t.snapshot_id === body.snapshot_id || observedBy(t.snapshot_id, body.run_id))
    treasury.value = { for: key, failed: !t, body: same ? t : null }
  }
  return body
})

const body = computed(() => state.body)
// A background poll is not a user-visible load: the screen keeps its controls while it runs.
const polling = ref(false)
const busy = computed(() => state.status === 'loading' && !polling.value)
// The body on screen is the selected run's current answer: not another run's, not a failed reload.
const currentRun = computed(() => body.value?.run_id === runId.value && !state.error)
const committed = computed(() => body.value?.committed_round ?? null)

const base = computed(() => {
  const b = body.value?.branches.find((x) => x.parent_branch_id === null)
  return b ?? { branch_id: body.value?.rounds[0]?.branch_id ?? null, replay: false }
})

// The banner names the branch these rounds belong to, and Replay when they were replayed.
const shellReading = computed(() => ({
  status: polling.value && body.value ? 'loaded' : state.status,
  error: state.error,
  contextChanged: state.contextChanged,
  body: body.value && { ...body.value, branch_id: base.value.branch_id, replay: base.value.replay }
}))

const ticks = computed(() => Array.from({ length: committed.value ?? 0 }, (_, i) => i + 1))
const byRound = computed(() => new Map((body.value?.rounds ?? [])
  .filter((r) => r.branch_id === base.value.branch_id && r.round <= (committed.value ?? -1))
  .map((r) => [r.round, r])))
const loadedRounds = computed(() => ticks.value.filter((r) => byRound.value.has(r)))

const selected = ref(null)
const display = computed(() => (ticks.value.includes(selected.value)
  ? selected.value
  : (ticks.value[ticks.value.length - 1] ?? null)))
const current = computed(() => byRound.value.get(display.value) ?? null)

const epoch = computed(() => {
  const path = body.value?.cash_paths.find((p) => p.branch_id === base.value.branch_id)
  const times = (path?.points ?? []).map((p) => Date.parse(p.t)).filter((t) => !Number.isNaN(t))
  return times.length ? Math.min(...times) : null
})
const roundAt = computed(() => (current.value && epoch.value !== null
  ? epoch.value + current.value.t_hours * 3_600_000
  : null))

const roundPosts = computed(() => (current.value
  ? body.value.feed.filter((p) => p.round === display.value && p.branch_id === base.value.branch_id)
  : []))

const phase = computed(() => {
  const s = body.value?.status
  const c = committed.value
  if (s === 'failed') return { tone: 'bad', icon: '✕', text: `Branch invalid at round ${(c ?? 0) + 1}`, invalid: true }
  if (s === 'running' || s === 'queued') {
    return {
      tone: 'warn', icon: '◷', running: true,
      text: c === null
        ? (s === 'queued' ? 'Queued; no round committed yet' : 'Round 1 running; no round committed yet')
        : `Round ${c + 1} running; showing committed round ${display.value}`
    }
  }
  if (s === 'cancelled') return { tone: 'warn', icon: '–', text: `Run cancelled after round ${c ?? 0}` }
  return { tone: 'ok', icon: '●', text: `Run complete · ${c ?? 0} rounds committed · showing round ${display.value ?? '–'}` }
})

// ----------------------------------------------------------- run context, world map, inspector

const world = computed(() => worldFor(body.value?.snapshot_id))
const family = computed(() => familyOf((body.value?.branches ?? []).map((b) => b.branch_id).join(' ')))
const checkpoints = computed(() => {
  const rounds = [...new Set((body.value?.branches ?? []).map((b) => b.checkpoint_round).filter((r) => r != null))]
  return rounds.length ? rounds.map((r) => `round ${r}`).join(', ') : 'none forked yet'
})
const settingsOpen = ref(false)

/** The pending flow the run's scenario family delays, from the treasury on the run's snapshot. */
const delayed = computed(() => {
  const id = family.value?.params.flow_id
  const t = treasury.value?.for === `${body.value?.snapshot_id}|${body.value?.run_id}` ? treasury.value.body : null
  if (!id || !t) return null
  return t.accounts.flatMap((a) => a.buckets.pending_in ?? []).find((f) => f.flow_id === id) ?? null
})

const RIPPLE = 'Watch how it ripples through your partners, round by round.'

/**
 * The finance lead's question, first (COPY.md, Simulation): the what-if this run plays. The
 * amount and kind are the treasury's pending flow the family delays; the delay is the family's.
 */
const lead = computed(() => {
  const f = family.value
  if (!f) return `What happens to your cash in this what-if? ${RIPPLE}`
  if (f.params.flow_id && Number.isInteger(f.params.delay_h)) {
    const flow = delayed.value
    const what = flow ? `${money(flow.amount)} ${kindText(flow.kind)}` : 'expected payment'
    return `What if your ${what} arrives ${hoursWords(f.params.delay_h)} late? ${RIPPLE}`
  }
  return `What if the ${f.id.replace(/-/g, ' ')} shock hits? ${RIPPLE}`
})

/** The hero's one line: the branch this screen plays and the scenario family it names. */
const subtitle = computed(() => {
  const f = family.value
  const name = f ? f.id.replace(/[-_]/g, ' ').replace(/^./, (c) => c.toUpperCase()) : ''
  return [base.value.replay && PLAIN.replay, `${PLAIN.branch} branch`, name].filter(Boolean).join(' · ')
})

/** What a handoff from Treasury (account) or Lending (a scenario this run plays) carried, echoed behind the (i). */
const handoff = computed(() => {
  const [account, scenario] = [handedOff('account'), handedOff('scenario')]
  const parts = []
  if (account) parts.push(`Rehearsing for account ${account}.`)
  if (scenario && !scenarioMismatch.value) parts.push(`Scenario asked for: ${scenario}.`)
  return parts.join(' ')
})

/** The scenario a handoff asked for, when the loaded run does not play it. */
const scenarioMismatch = computed(() => {
  const scenario = handedOff('scenario')
  return Boolean(scenario && body.value && family.value?.id !== scenario)
})

/**
 * Where the handoff and this run disagree — another snapshot, another scenario — said on the page,
 * never only in a tooltip: a reader handed onto a different run must be told without asking.
 */
const handoffMismatch = computed(() => {
  const [snapshot, scenario] = [handedOff('snapshot'), handedOff('scenario')]
  const parts = []
  if (scenarioMismatch.value) {
    parts.push(`Scenario asked for: ${scenario}; this run plays ${family.value?.id ?? 'no named scenario'}.`)
  }
  const runSnapshot = body.value?.snapshot_id
  if (snapshot && runSnapshot && snapshot !== runSnapshot && !observedBy(snapshot, body.value.run_id)) {
    parts.push(`The handoff was made on snapshot ${snapshot}; this run is on ${runSnapshot}.`)
  }
  return parts.join(' ')
})

const sourceOpen = ref(false)
function selectActor (id) { actor.value = id }

const nameOf = (id) => world.value?.actors.find((a) => a.id === id)?.label ?? id

const VERDICT_WORD = { accepted: ['Accepted', 'ok'], rejected: ['Rejected', 'bad'], pending: ['Pending', 'warn'] }

/** A cleared action as the screen says it: its word with the coordinator's reason, its tone, its journal. */
function verdictOf (c) {
  const [word, tone] = c ? VERDICT_WORD[c.status] ?? [c.status, 'muted'] : ['No verdict recorded', 'muted']
  return { text: `${word}${c?.reason ? ` · ${c.reason}` : ''}`, tone, accepted: c?.status === 'accepted', journal: c?.journal_id ?? null }
}

/** Why an intent moved no cash, or nothing when its journal says it did. */
function ledgerNote (v) {
  if (v.journal) return ''
  return v.accepted
    ? 'Accepted with no journal: it changed no ledger.'
    : 'A proposal is not a ledger change until it is accepted and journalled.'
}

const actorInfo = computed(() => {
  if (!actor.value || !current.value) return null
  const w = world.value?.actors.find((a) => a.id === actor.value)
  const actions = []
  for (const [r, view] of byRound.value) {
    if (r > display.value) continue
    const verdicts = new Map(view.cleared.map((c) => [c.intent_id, c]))
    for (const i of view.intents.filter((x) => x.actor_id === actor.value)) {
      const v = verdictOf(verdicts.get(i.intent_id))
      actions.push({
        id: i.intent_id, round: r, type: kindText(i.type), tone: v.tone,
        verdict: v.text, journal: v.journal,
        evidence: (i.evidence_ids ?? []).join(', ')
      })
    }
  }
  return {
    id: actor.value,
    label: nameOf(actor.value),
    role: w?.role ?? null,
    objective: w?.objective ?? null,
    sees: w ? w.sees.map(kindText).join(', ') : 'its own scoped observations',
    actions: actions.sort((x, y) => x.round - y.round)
  }
})

/** The rounds up to the cursor, and the request ids they minted: read by the map and the graph. */
const shownViews = computed(() => [...byRound.value].filter(([n]) => n <= (display.value ?? -1)).map(([, v]) => v))
const shownOwners = computed(() => requestOwners(shownViews.value))

/**
 * The map at the cursor: the world's actors and structural edges (contracts, obligations, shared
 * venues, prices), then what the rounds up to the cursor add — each request for funds, each post
 * an intent cites (information, never cash), each request a lender answers. An answer is financial
 * only when it was accepted and journalled; a rejected, pending or unverdicted one is a proposal,
 * and it and an accepted one with no journal are drawn as part of the request. Every intent edge
 * carries its clearing verdict. Nothing after the cursor is drawn.
 */
const MAP_LAYOUT = { treasury: [0.44, 0.56], lender: [0.44, 0.12], 'borrower-b': [0.13, 0.32],
  'borrower-c': [0.74, 0.3], feed: [0.86, 0.08], payroll: [0.86, 0.57], venue: [0.17, 0.9], 'market-maker': [0.77, 0.9] }
const ICON = { bank: 'M3 9l9-6 9 6H3M5 11v8m5-8v8m4-8v8m5-8v8M3 21h18',
  company: 'M4 21V7h9v14M13 12h7v9M7 10h3m-3 4h3m-3 4h3m6-3h2',
  paper: 'M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h8',
  chart: 'M3 21V14m6 7V9m6 12V4m6 17V1' }
const cashAccount = computed(() => {
  const t = treasury.value?.for === `${body.value?.snapshot_id}|${body.value?.run_id}` ? treasury.value.body : null
  return t?.accounts?.find((a) => a.id === 'treasury/operating') ?? t?.accounts?.[0] ?? null
})
const shockMarks = computed(() => family.value?.startsRound ? { [family.value.startsRound]: 'Shock event' } : {})
const worldMap = computed(() => {
  if (!current.value) return { nodes: [], edges: [] }
  const w = world.value
  const nodes = new Map((w?.actors ?? []).map((a) => [a.id, { id: a.id, label: a.label, role: a.role,
    icon: ['treasury', 'lender'].includes(a.id) ? ICON.bank : a.role === 'borrower' ? ICON.company : a.id === 'venue' || a.id === 'market-maker' ? ICON.chart : ICON.paper }]))
  const node = (id) => nodes.has(id) || nodes.set(id, { id, label: id, role: null })
  const edges = new Map((w?.edges ?? []).map((e) => [e.id, { ...e, source: `world file, snapshot ${w.snapshotId}` }]))
  const r = display.value
  const views = shownViews.value
  const authors = new Map((body.value.feed ?? [])
    .filter((p) => p.round <= r && p.branch_id === base.value.branch_id).map((p) => [p.post_id, p.author]))
  const owners = shownOwners.value
  for (const v of views) {
    const verdicts = new Map(v.cleared.map((c) => [c.intent_id, c]))
    for (const i of v.intents) {
      node(i.actor_id)
      const verdict = verdictOf(verdicts.get(i.intent_id))
      const moved = verdict.accepted && Boolean(verdict.journal)
      const to = i.params?.from
      if (i.type === 'request_advance' && typeof to === 'string') {
        node(to)
        const amount = i.params.amount
        edges.set(`intent:${i.intent_id}`, { id: `intent:${i.intent_id}`, from: i.actor_id, to, type: 'request',
          label: `request advance${amount ? ` ${formatMoney(amount.minor, amount.currency)}` : ''} · round ${i.round}`,
          tag: 'request advance', source: `intent ${i.intent_id}`, verdict })
      }
      for (const e of i.evidence_ids ?? []) {
        const author = authors.get(e)
        if (author && author !== i.actor_id) {
          node(author)
          edges.set(`cite:${i.intent_id}:${e}`, { id: `cite:${i.intent_id}:${e}`, from: author, to: i.actor_id,
            type: 'information', label: `post ${e}, cited by ${i.intent_id}`, tag: 'cited post', source: `intent ${i.intent_id}` })
        }
        const owner = owners.get(e)
        if (owner && owner !== i.actor_id) {
          edges.set(`cite:${i.intent_id}:${e}`, { id: `cite:${i.intent_id}:${e}`, from: i.actor_id, to: owner,
            type: moved ? 'financial' : 'request',
            label: `${verdict.accepted ? '' : 'proposed '}${kindText(i.type)} on ${e} · round ${i.round}`,
            tag: `${verdict.accepted ? '' : 'proposed '}${kindText(i.type)}`, source: `intent ${i.intent_id}`, verdict })
        }
      }
    }
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()].map((e) => {
    if (e.source?.startsWith('intent ')) {
      const view = views.find((v) => v.intents.some((i) => e.source === `intent ${i.intent_id}`))
      return { ...e, causal: true, tag: `h${view?.t_hours ?? '?'} ${e.tag}` }
    }
    return e
  }) }
})

const mapSelected = computed(() => (actor.value ? { kind: 'node', id: actor.value } : null))
const evidence = ref(null)
const INFORMATION_NOTE = 'Information only: a post or a price never moves cash.'

function pickMap ({ kind, id }) {
  if (kind === 'node') return selectActor(id)
  const e = worldMap.value.edges.find((x) => x.id === id)
  if (!e) return
  const v = e.verdict
  evidence.value = {
    title: `${nameOf(e.from)} → ${nameOf(e.to)}`,
    rows: [['Type', e.type], ['Relation', e.label], ['Source', e.source], ['Round', `up to round ${display.value}`],
      ...(v ? [['Verdict', v.text], ['Journal', v.journal || 'no ledger change']] : [])],
    note: e.type === 'information' ? INFORMATION_NOTE : (v ? ledgerNote(v) : '')
  }
}

/** A feed item: its actor is selected and its evidence opens. */
function pickEvent (item) {
  actor.value = item.actor
  const v = item.status ? verdictOf(current.value?.cleared.find((c) => c.intent_id === item.id)) : null
  evidence.value = {
    title: `${item.kind} ${item.id}`,
    rows: [['Actor', nameOf(item.actor)], ['Round', String(display.value)], ['What', item.text || '–'],
      ['Verdict', v ? v.text : 'a public post'],
      ['Journal', item.journal || 'no ledger change'], ['Evidence', item.evidence.join(', ') || 'none cited']],
    note: v ? ledgerNote(v) : INFORMATION_NOTE
  }
}

// A selection belongs to its run and round: another run or round closes the evidence detail.
watch([runId, display], () => { evidence.value = null })

// ------------------------------------------------------------------------- the world graph

const actors = computed(() => {
  const seen = new Map()
  for (const [r, view] of byRound.value) {
    if (r > (display.value ?? -1)) continue
    for (const i of view.intents) {
      const a = seen.get(i.actor_id) ?? { id: i.actor_id, active: false }
      a.active = a.active || r === display.value
      seen.set(i.actor_id, a)
    }
  }
  return [...seen.values()].map((a) => ({ ...a, name: nameOf(a.id) })).sort((x, y) => x.name.localeCompare(y.name))
})

const graphData = computed(() => {
  if (!current.value) return { nodes: [], edges: [] }
  const r = display.value
  const posts = (body.value.feed ?? []).filter((p) => p.round <= r && p.branch_id === base.value.branch_id)
  const views = shownViews.value
  const intents = views.flatMap((v) => v.intents)
  const nodes = new Map()
  const node = (uuid, name, label) => nodes.has(uuid) || nodes.set(uuid, { uuid, name, labels: ['Entity', label] })
  const edges = []
  const owner = new Map()
  for (const p of posts) {
    node(`actor:${p.author}`, p.author, 'Actor')
    node(`post:${p.post_id}`, p.post_id, 'Post')
    owner.set(p.post_id, `post:${p.post_id}`)
    edges.push({ uuid: `posted:${p.post_id}`, name: 'POSTED', fact: p.text,
      source_node_uuid: `actor:${p.author}`, target_node_uuid: `post:${p.post_id}` })
  }
  for (const i of intents) {
    node(`actor:${i.actor_id}`, i.actor_id, 'Actor')
    owner.set(i.intent_id, `actor:${i.actor_id}`)
  }
  for (const [id, actorId] of shownOwners.value) owner.set(id, `actor:${actorId}`)
  for (const i of intents) {
    for (const e of i.evidence_ids ?? []) {
      const target = owner.get(e)
      if (target) {
        edges.push({ uuid: `${i.intent_id}->${e}`, name: i.type.toUpperCase(),
          fact: `${i.intent_id} cites ${e}`, source_node_uuid: `actor:${i.actor_id}`, target_node_uuid: target })
      }
    }
  }
  return same({ nodes: [...nodes.values()], edges })
})

/**
 * The request messages the shown rounds minted, each to the borrower that asked. The coordinator
 * turns a `request_advance` that drew on no offer (accepted, no journal) into the message
 * `req:<actor>:r<round>`, then `-2`, `-3`… for that actor's later ones in the same round, and a
 * lender cites that id, never the intent. An id no shown intent minted resolves to nothing.
 */
function requestOwners (views) {
  const owners = new Map()
  const minted = new Map()
  for (const v of views) {
    const asked = new Set(v.cleared
      .filter((c) => c.status === 'accepted' && !c.journal_id)
      .map((c) => c.intent_id))
    for (const i of v.intents) {
      if (i.type !== 'request_advance' || !asked.has(i.intent_id)) continue
      const base = `req:${i.actor_id}:r${i.round}`
      const n = (minted.get(base) ?? 0) + 1
      minted.set(base, n)
      owners.set(n === 1 ? base : `${base}-${n}`, i.actor_id)
    }
  }
  return owners
}

// A poll that changes nothing the graph shows hands back the same object, so the graph view
// keeps its layout, zoom and selection instead of re-rendering every few seconds.
let shownGraph = { key: '', data: null }
function same (graph) {
  const key = JSON.stringify(graph)
  if (key !== shownGraph.key) shownGraph = { key, data: graph }
  return shownGraph.data
}

const graphExpanded = ref(false)
const actor = ref(null)
watch([current, world], () => {
  if (!actor.value && current.value) actor.value = world.value?.actors.find((a) => a.id === 'lender')?.id ?? actors.value.find((a) => a.id === 'lender')?.id ?? actors.value[0]?.id ?? null
}, { immediate: true })

const actorTimeline = computed(() => {
  if (!actorInfo.value) return []
  return shownViews.value.flatMap((v) => v.intents.filter((i) => i.type !== 'no_action' &&
    (i.actor_id === actor.value || (i.type === 'request_advance' && i.params?.from === actor.value)))
    .map((i) => {
      const verdict = verdictOf(v.cleared.find((c) => c.intent_id === i.intent_id))
      return { id: i.intent_id, hour: v.t_hours,
        title: `${nameOf(i.actor_id)} · ${kindText(i.type)}`,
        text: `${i.params?.amount ? money(i.params.amount) + ' · ' : ''}${verdict.text}`,
        detail: `${i.intent_id} · ${verdict.journal ? `journal ${verdict.journal}` : ledgerNote(verdict)} · evidence ${(i.evidence_ids ?? []).join(', ') || 'none cited'}` }
    })).sort((a, b) => a.hour - b.hour).slice(-3)
})

// A node or edge picked in the graph belongs to the run and round it was picked in: moving the
// cursor (an unloaded round included) or showing another run closes its details. A poll that
// moves neither keeps them.
const graphPanel = ref(null)
watch([runId, () => body.value?.run_id, display], () => graphPanel.value?.closeDetailPanel())

// The graph is drawn while its disclosure is closed, at 0×0: opening it redraws the round on the
// cursor at the size it now has.
function evidenceToggled (event) {
  graphExpanded.value = event.target.open
  if (event.target.open) graphPanel.value?.redraw()
}

// ----------------------------------------------------------------------- local playback

const playing = ref(false)
const paused = ref(false)
let player = null

function play () {
  if (display.value === ticks.value[ticks.value.length - 1]) selected.value = ticks.value[0]
  playing.value = true
  paused.value = false
  player = setInterval(() => {
    const i = ticks.value.indexOf(display.value)
    if (i < ticks.value.length - 1) selected.value = ticks.value[i + 1]
    else if (!phase.value.running) stopPlaying() // played to the end: finished, not paused
  }, PLAY_MS)
}

function stopPlaying () {
  clearInterval(player)
  player = null
  playing.value = false
}

/** The operator paused: local playback stops, the job does not. */
function pause () {
  if (playing.value) paused.value = true
  stopPlaying()
}

/** The operator moved the cursor: playback stops where they put it. */
function scrub (round) {
  if (playing.value) pause()
  selected.value = round
}

// ------------------------------------------------------------- polling a running job

/** A reload someone asked for (or the run changed): shown as loading, never as a poll. */
function reload () {
  polling.value = false
  return refresh()
}

let poller = null
/** A quiet re-read; false when a load already in flight meant nothing was read. */
async function poll () {
  if (state.status === 'loading') return false
  polling.value = true
  try {
    await refresh()
  } finally {
    polling.value = false
  }
  return true
}
watch(() => phase.value.running, (running) => {
  clearInterval(poller)
  poller = running ? setInterval(poll, POLL_MS) : null
}, { immediate: true })

onBeforeUnmount(() => {
  clearInterval(player)
  clearInterval(poller)
  forked.value = null // a fork check still in flight finds no fork to follow on
  clearTimeout(forkTimer)
})

// --------------------------------------------------------------------- fork, interview

const token = ref('')
const forking = ref(false)
const forked = ref(null)
const forkError = ref('')
const question = ref('')
const asking = ref(false)
const answer = ref(null)
const interviewError = ref('')

watch(runId, (id) => {
  if (id && id === adopted) return // the read that named it is already reading it
  selected.value = null
  actor.value = null
  forked.value = answer.value = null
  forkError.value = interviewError.value = ''
  follow()
  pause()
  paused.value = false
  reload()
})

const forkWhy = computed(() => {
  if (!currentRun.value) return 'Not current: load this run first'
  if (phase.value.invalid) return 'Branch invalid: there is no checkpoint to fork'
  if (body.value?.status !== 'done') return 'A fork needs a finished run'
  if (!current.value) return 'Round not loaded: nothing to fork from'
  if (display.value >= HORIZON_ROUNDS) return `Fork before the horizon round ${HORIZON_ROUNDS}`
  if (forked.value && !forked.value.done) return 'A fork is running: fork again once its branches arrive'
  if (!token.value) return 'Enter operator access to fork'
  if (forking.value) return 'Submitting the fork'
  return ''
})

/** Fork asks first, naming the checkpoint and the policies; only Confirm sends the one POST. */
const confirming = ref(false)
watch([runId, display], () => { confirming.value = false })
function confirmFork () {
  confirming.value = false
  return fork()
}

async function fork () {
  if (forkWhy.value) return
  const [run, round] = [runId.value, display.value]
  forking.value = true
  forked.value = null
  forkError.value = ''
  try {
    const accepted = await request(`/runs/${encodeURIComponent(run)}/fork`, {
      method: 'POST', token: token.value, body: { checkpoint_round: round, policies: POLICIES }
    })
    if (run !== runId.value) return // answered for a run no longer on screen
    forked.value = { round, branch_ids: accepted?.branch_ids ?? [], decided: false, done: false, lag: '', reads: 0 }
    follow() // the job was only queued: its branches are read once it has decided
  } catch (error) {
    if (run === runId.value) forkError.value = `Fork not accepted: ${error.message}`
  } finally {
    forking.value = false
  }
}

// An accepted fork is its own job, run after the run is done: the run's status never moves, so
// the fork is followed on its own. Its decisions are read until they leave `pending` (a failed or
// lost worker answers 409 fork_failed), then the run until every accepted branch is there from
// this fork's checkpoint — a re-fork reuses the branch ids — with its cash path. The worker writes
// the run right after the decisions, so a run that still lacks them after FORK_RUN_READS reads is
// reported, not polled forever. Only reads repeat; a read that fails otherwise is said and retried.
const FORK_RUN_READS = 5
let forkTimer = null

function follow () {
  clearTimeout(forkTimer)
  forkTimer = forked.value && !forked.value.done ? setTimeout(checkFork, POLL_MS) : null
}

function arrived (id, round) {
  return body.value.branches.some((b) => b.branch_id === id && b.checkpoint_round === round) &&
    body.value.cash_paths.some((p) => p.branch_id === id)
}

async function checkFork () {
  const f = forked.value
  if (!f) return
  try {
    if (!f.decided) {
      const decided = await request(`/decisions/${encodeURIComponent(runId.value)}`)
      if (forked.value !== f) return // another fork or run took the screen
      f.decided = decided.status !== 'pending'
      f.lag = ''
    }
    if (f.decided && await poll()) { // false: a load in flight, so nothing was read this time
      if (forked.value !== f) return
      if (!currentRun.value) {
        f.lag = state.error?.message ?? 'the run was not re-read'
      } else {
        f.lag = ''
        f.done = f.branch_ids.every((id) => arrived(id, f.round))
        if (!f.done && ++f.reads >= FORK_RUN_READS) {
          forked.value = null
          forkError.value = 'Fork decided, but its branches have not reached the run: reload the page, or fork again'
        }
      }
    }
  } catch (error) {
    if (forked.value !== f) return
    if (error.code === 'fork_failed') {
      forked.value = null
      forkError.value = `Fork failed: ${error.message}`
    } else {
      f.lag = error.message
    }
  }
  follow()
}

const interviewWhy = computed(() => {
  if (!currentRun.value) return 'Not current: load this run first'
  if (!current.value) return 'Round not loaded: nothing to ask about'
  if (!actor.value) return 'Pick an actor above'
  if (!actors.value.some((a) => a.id === actor.value)) return `${nameOf(actor.value)} has not acted by round ${display.value}`
  if (!question.value.trim()) return 'Write a question'
  if (!token.value) return 'Enter operator access to interview'
  if (asking.value) return 'Asking'
  return ''
})

async function interview () {
  if (interviewWhy.value) return
  const run = runId.value
  asking.value = true
  answer.value = null
  interviewError.value = ''
  try {
    const reply = await request('/interview', {
      method: 'POST', token: token.value,
      body: { run_id: run, branch_id: base.value.branch_id, round: display.value,
        actor_id: actor.value, question: question.value.trim() }
    })
    if (run === runId.value) answer.value = reply // never another run's answer
  } catch (error) {
    if (run === runId.value) interviewError.value = `Interview not answered: ${error.message}`
  } finally {
    asking.value = false
  }
}

// ------------------------------------------------------------------- compare, export

const compareTarget = computed(() => (!phase.value.invalid && runId.value && routeExists(router, '/decisions')
  ? { path: '/decisions', query: { run_id: runId.value } }
  : null))
const compareWhy = computed(() => (phase.value.invalid
  ? 'Branch invalid: no comparison'
  : 'The decisions screen is not part of this build'))

const exportName = computed(() => `${runId.value}-${base.value.branch_id}-round-${display.value}.json`)
const provenance = (replay) => (replay === true ? LABELS.replay : replay === false ? 'Fresh run' : 'Provenance not loaded')

// Each exported cash row keeps its own branch's replay provenance; the document's label covers
// every branch in it (mixed when they differ) and `round_label` covers the base branch's round.
const exportHref = computed(() => {
  if (!current.value) return null
  const b = shellReading.value.body
  const meta = new Map((b.branches ?? []).map((x) => [x.branch_id, x]))
  const replayOf = (id) => {
    const replay = meta.get(id)?.replay
    return typeof replay === 'boolean' ? replay : null
  }
  const cash = (b.cash_paths ?? []).map((p) => {
    const branch = meta.get(p.branch_id)
    const replay = replayOf(p.branch_id)
    return {
      branch_id: p.branch_id,
      parent_branch_id: branch?.parent_branch_id ?? null,
      checkpoint_round: branch?.checkpoint_round ?? null,
      policy: branch?.policy ?? null,
      replay,
      label: provenance(replay),
      account_id: p.account_id,
      value: p.points.find((x) => Date.parse(x.t) === roundAt.value)?.value ?? null
    }
  })
  const roundLabel = provenance(replayOf(base.value.branch_id))
  const labels = [...new Set([roundLabel, ...cash.map((c) => c.label)])]
  const doc = {
    label: labels.length === 1 ? labels[0] : `Mixed: ${labels.join(' + ')}`,
    round_label: roundLabel,
    source: sourceLabel(b),
    mode: LABELS[b.mode] || b.mode,
    as_of: b.as_of,
    run_id: b.run_id,
    branch_id: base.value.branch_id,
    round: display.value,
    t_hours: current.value.t_hours,
    posts: roundPosts.value,
    intents: current.value.intents,
    cleared: current.value.cleared,
    journal_ids: current.value.journal_ids,
    cash
  }
  return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(doc, null, 2))}`
})
</script>

<style scoped>
.lw-live {
  --live-surface: var(--lw-surface); --live-raised: var(--lw-surface-raised);
  --live-ink: var(--lw-ink); --live-muted: var(--lw-ink-muted); --live-rule: var(--lw-rule);
  --live-brand: var(--lw-brand); --live-ok: var(--lw-ok-text); --live-warn: var(--lw-warn-text); --live-bad: var(--lw-bad-text);
  display: grid; gap: 20px; min-width: 0; color: var(--lw-ink);
}
.lw-live > *, .lw-live__graph > * { min-width: 0; }
.lw-live :deep(h2) { font-family: var(--lw-font-heading); font-size: 26px; line-height: 1.2; margin: 0 0 6px; }
.lw-sim__context { display: flex; flex-wrap: wrap; gap: 16px 28px; align-items: center; border-bottom: 1px solid var(--lw-rule); padding: 12px 0; }
.lw-sim__selector { display: flex; align-items: center; gap: 12px; font-size: 14px; }
.lw-sim__selector > span, .lw-sim__sub { color: var(--lw-ink-muted); }
.lw-sim__selector b { display: inline-flex; min-height: 44px; align-items: center; border: 1px solid var(--lw-rule); border-radius: 4px; padding: 0 12px; font-weight: 500; text-transform: capitalize; }
.lw-sim__handoff { flex-basis: 100%; margin: 0; }
.lw-live__graph { display: grid; gap: 24px; }
.lw-live__inspector { border-top: 1px solid var(--lw-rule); padding-top: 20px; }
.lw-sim__sub { margin: 0 0 16px; font-size: 14px; }
.lw-live :deep(.lw-cash-panel h2) { font: 600 15px var(--lw-font-text); margin: 0 0 12px; }
.lw-sim__actor h3 { font-family: var(--lw-font-heading); font-size: 23px; font-weight: 500; margin: 24px 0 16px; }
.lw-sim__timeline { margin: 0; padding: 0 0 0 16px; list-style: none; }
.lw-sim__timeline li { position: relative; border-left: 1px solid var(--lw-warn); padding: 0 0 18px 20px; }
.lw-sim__timeline li::before { content: ''; position: absolute; width: 10px; height: 10px; background: var(--lw-warn); border-radius: 50%; left: -6px; top: 5px; }
.lw-sim__timeline b, .lw-sim__timeline span:not(.lw-tip) { display: block; }
.lw-sim__timeline b { font-size: 14px; font-weight: 600; }
.lw-sim__timeline li .lw-tip > span:not(.lw-tip__bubble) { color: var(--lw-ink-muted); font-size: 13px; margin-top: 4px; }
.lw-live__interview { display: flex; align-items: end; gap: 10px; border-top: 1px solid var(--lw-rule); padding-top: 18px; margin-top: 14px; }
.lw-live__interview label { display: grid; gap: 8px; flex: 1; min-width: 0; font-family: var(--lw-font-heading); font-size: 22px; }
.lw-live input { width: 100%; box-sizing: border-box; min-height: 44px; padding: 8px 10px; border: 1px solid var(--lw-rule); border-radius: 4px; background: var(--lw-surface-raised); color: var(--lw-ink); font: 14px var(--lw-font-text); }
.lw-live input:focus-visible { outline: 3px solid var(--lw-focus); outline-offset: 2px; }
.lw-live__token { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; font-size: 12px; color: var(--lw-ink-muted); }
.lw-live__token :deep(input) { max-width: 150px; }
.lw-sim__source { display: inline-block; color: var(--lw-brand); margin-top: 12px; min-height: 44px; line-height: 44px; }
.lw-live__controls { border-block: 1px solid var(--lw-rule); padding: 12px 0; }
.lw-sim__round-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.lw-sim__round-row :deep(.lw-scrubber) { flex: 1 1 520px; }
.lw-sim__round-row :deep(.lw-scrubber__track) { flex-basis: 280px; }
.lw-sim__round-row :deep(.lw-scrubber__tick) { flex-basis: 22px; }
.lw-sim__fork { display: grid; gap: 4px; text-align: right; }
.lw-sim__fork small { color: var(--lw-ink-muted); font-size: 11px; }
.lw-live__phase { font-size: 12px; color: var(--lw-ink-muted); }
.lw-live__phase.is-bad { color: var(--lw-bad-text); }
.lw-live__phase.is-warn { color: var(--lw-warn-text); }
.lw-sim__confirm { margin-top: 12px; padding: 12px; background: var(--lw-selected); }
.lw-sim__source-evidence summary, .lw-sim__evidence summary { cursor: pointer; color: var(--lw-brand); min-height: 44px; line-height: 44px; }
.lw-live__actors { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.lw-live__actors [aria-pressed='true'] { background: var(--lw-selected); }
.lw-live__graph-view { height: 360px; overflow: hidden; }
.is-graph-expanded .lw-live__graph-view { height: 70vh; }
.lw-live__answer { background: var(--lw-selected); padding: 12px; margin-top: 12px; }
.lw-sim__families { list-style: none; padding: 0; }
.lw-sim__families li { padding: 12px; border-bottom: 1px solid var(--lw-rule); }
@media (min-width: 1200px) {
  .lw-live__graph { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
  .lw-live__inspector { border-top: 0; border-left: 1px solid var(--lw-rule); padding: 0 0 0 24px; }
}
</style>

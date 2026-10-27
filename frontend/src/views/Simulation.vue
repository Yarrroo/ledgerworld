<template>
  <ScreenShell title="Live simulation" :reading="shellReading" :refresh="refresh">
    <div class="lw-live" :class="{ 'is-graph-expanded': graphExpanded }">
      <section class="lw-live-panel lw-live__controls" aria-label="Round and controls" data-test="controls">
        <p class="lw-live__phase" :class="`is-${phase.tone}`" role="status" data-test="phase">
          {{ phase.icon }} {{ phase.text }}
        </p>
        <p v-if="base.replay" class="lw-live__phase" data-test="replay-note">
          <span class="lw-live-tag">Replay</span> these rounds were replayed, not run fresh
        </p>
        <Scrubber :model-value="display" :rounds="ticks" :loaded="loadedRounds" :round-hours="ROUND_HOURS"
                  @update:model-value="scrub" />
        <div class="lw-live__row">
          <button type="button" class="lw-button" data-test="play" :disabled="!ticks.length"
                  @click="playing ? pause() : play()">
            {{ playing ? 'Pause playback' : 'Play' }}
          </button>
          <span v-if="paused" class="lw-live__note" data-test="paused">Playback paused; simulation may continue</span>
        </div>

        <div class="lw-live__row">
          <label class="lw-live__token">
            <span>Demo token (kept in this tab's memory only)</span>
            <input v-model="token" type="password" autocomplete="off" spellcheck="false" data-test="token">
          </label>
        </div>
        <div class="lw-live__row">
          <button type="button" class="lw-button" data-test="fork" :disabled="Boolean(forkWhy)"
                  :aria-describedby="forkWhy ? 'fork-why' : undefined" @click="fork">
            Fork this checkpoint
          </button>
          <RouterLink v-if="compareTarget" class="lw-button lw-button--quiet" :to="compareTarget"
                      data-test="compare">Compare policies</RouterLink>
          <button v-else type="button" class="lw-button lw-button--quiet" disabled data-test="compare"
                  :aria-describedby="'compare-why'">Compare policies</button>
          <a v-if="exportHref" class="lw-button lw-button--quiet" :href="exportHref" :download="exportName"
             data-test="export">Export round {{ display }}</a>
        </div>
        <p class="lw-live__note" data-test="fork-what">
          Forks {{ base.branch_id }} at round {{ display ?? '–' }} into one fresh branch per policy;
          creates no approval.
        </p>
        <p v-if="forkWhy" id="fork-why" class="lw-live__note" data-test="fork-why">{{ forkWhy }}</p>
        <p v-if="!compareTarget" id="compare-why" class="lw-live__note" data-test="compare-why">{{ compareWhy }}</p>
        <p v-if="forked" class="lw-live__note" role="status" data-test="forked">
          Fork accepted at round {{ forked.round }}: {{ forked.branch_ids.join(', ') }}
        </p>
        <p v-if="forkError" class="lw-alert" role="alert" data-test="fork-error">{{ forkError }}</p>
      </section>

      <CashPaths class="lw-live__cash" :round="display" :at="roundAt" :paths="body?.cash_paths ?? []"
                 :branches="body?.branches ?? []" />

      <ActionFeed class="lw-live__feed" :round="display" :loaded="Boolean(current)" :posts="roundPosts"
                  :intents="current?.intents ?? []" :cleared="current?.cleared ?? []"
                  :replay="base.replay" :highlight="actor" />

      <section class="lw-live-panel lw-live__graph" aria-label="Graph and actor inspector" data-test="graph">
        <div class="lw-live__graph-view">
          <GraphPanel :graph-data="graphData" :loading="busy" :is-simulating="phase.running"
                      @refresh="refresh" @toggle-maximize="graphExpanded = !graphExpanded" />
        </div>
        <div class="lw-live__inspector" data-test="inspector">
          <h2>Actors up to round {{ display ?? '–' }}</h2>
          <p v-if="!current" class="lw-live-empty">Round not loaded</p>
          <ul v-else class="lw-live__actors">
            <li v-for="a in actors" :key="a.id">
              <button type="button" class="lw-button lw-button--quiet" :aria-pressed="a.id === actor ? 'true' : 'false'"
                      :data-actor="a.id" @click="actor = a.id">
                {{ a.id }}<template v-if="a.active"> · acted this round</template>
              </button>
            </li>
          </ul>
          <form class="lw-live__interview" data-test="interview" @submit.prevent="interview">
            <label>
              <span>Ask {{ actor ?? 'an actor' }} about round {{ display ?? '–' }} (read-only)</span>
              <textarea v-model="question" rows="2" maxlength="2000" data-test="question" />
            </label>
            <button type="submit" class="lw-button" :disabled="Boolean(interviewWhy)" data-test="ask">
              Interview
            </button>
            <p v-if="interviewWhy" class="lw-live__note" data-test="interview-why">{{ interviewWhy }}</p>
          </form>
          <p v-if="interviewError" class="lw-alert" role="alert" data-test="interview-error">{{ interviewError }}</p>
          <article v-if="answer" class="lw-live__answer" data-test="answer">
            <p class="lw-live__note">
              Read-only answer · {{ answer.actor_id }} at round {{ answer.round }} · {{ answer.branch_id }}
              <span v-if="answer.replay" class="lw-live-tag">Replay</span>
            </p>
            <p>{{ answer.answer }}</p>
            <p v-if="answer.evidence_ids.length" class="lw-live__note">evidence: {{ answer.evidence_ids.join(', ') }}</p>
          </article>
        </div>
      </section>
    </div>
  </ScreenShell>
</template>

<script setup>
/**
 * Live simulation (system brief §11–13, ui HANDOFF Simulation row, fixture scrubber.json).
 *
 * One committed-round cursor drives the cash paths, the action feed, the graph and the actor
 * inspector. Only rounds 1..committed_round enter the scrubber; a round the API did not return
 * reads "Round not loaded" in every panel, never the latest data. A round sits at the base
 * branch's first cash point plus its `t_hours`, and a cash point matches only at that instant.
 * Pause stops local playback; the job keeps running and keeps being polled. Fork and the
 * read-only interview carry the selected round and need the demo token, which lives in this
 * component's memory only — never storage, the URL, the export or a log. No POST is retried.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import GraphPanel from '../components/GraphPanel.vue'
import Scrubber from '../components/Scrubber.vue'
import ActionFeed from '../components/ActionFeed.vue'
import CashPaths from '../components/CashPaths.vue'
import { ApiError, LABELS, ScreenShell, request, routeExists, sourceLabel, useReading } from '../api/v1.js'

const ROUND_HOURS = 4
const HORIZON_ROUNDS = 18
const POLICIES = ['no-action', 'fixed-reserve', 'integrated']
const PLAY_MS = 1500
const POLL_MS = 4000

const route = useRoute()
const router = useRouter()
const runId = computed(() => (typeof route.query.run_id === 'string' && route.query.run_id) || null)

const { state, refresh } = useReading(() => runId.value
  ? request(`/runs/${encodeURIComponent(runId.value)}`)
  : Promise.reject(new ApiError(0, 'no_run', 'No run selected: open the simulation from Overview')))

const body = computed(() => state.body)
const busy = computed(() => state.status === 'loading')
const committed = computed(() => body.value?.committed_round ?? null)

const base = computed(() => {
  const b = body.value?.branches.find((x) => x.parent_branch_id === null)
  return b ?? { branch_id: body.value?.rounds[0]?.branch_id ?? null, replay: false }
})

// The banner names the branch these rounds belong to, and Replay when they were replayed.
const shellReading = computed(() => ({
  status: state.status,
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
  return [...seen.values()].sort((x, y) => x.id.localeCompare(y.id))
})

const graphData = computed(() => {
  if (!current.value) return { nodes: [], edges: [] }
  const r = display.value
  const posts = (body.value.feed ?? []).filter((p) => p.round <= r && p.branch_id === base.value.branch_id)
  const intents = [...byRound.value].filter(([n]) => n <= r).flatMap(([, v]) => v.intents)
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
  for (const i of intents) {
    for (const e of i.evidence_ids ?? []) {
      const target = owner.get(e)
      if (target) {
        edges.push({ uuid: `${i.intent_id}->${e}`, name: i.type.toUpperCase(),
          fact: `${i.intent_id} cites ${e}`, source_node_uuid: `actor:${i.actor_id}`, target_node_uuid: target })
      }
    }
  }
  return { nodes: [...nodes.values()], edges }
})

const graphExpanded = ref(false)
const actor = ref(null)

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
    else if (!phase.value.running) pause()
  }, PLAY_MS)
}

function pause () {
  clearInterval(player)
  player = null
  if (playing.value) paused.value = true
  playing.value = false
}

/** The operator moved the cursor: playback stops where they put it. */
function scrub (round) {
  if (playing.value) pause()
  selected.value = round
}

// ------------------------------------------------------------- polling a running job

let poller = null
watch(() => phase.value.running, (running) => {
  clearInterval(poller)
  poller = running ? setInterval(() => { if (!busy.value) refresh() }, POLL_MS) : null
}, { immediate: true })

onBeforeUnmount(() => {
  clearInterval(player)
  clearInterval(poller)
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

watch(runId, () => {
  selected.value = null
  actor.value = null
  forked.value = answer.value = null
  forkError.value = interviewError.value = ''
  pause()
  paused.value = false
  refresh()
})

const forkWhy = computed(() => {
  if (phase.value.invalid) return 'Branch invalid: there is no checkpoint to fork'
  if (body.value?.status !== 'done') return 'A fork needs a finished run'
  if (!current.value) return 'Round not loaded: nothing to fork from'
  if (display.value >= HORIZON_ROUNDS) return `Fork before the horizon round ${HORIZON_ROUNDS}`
  if (!token.value) return 'Enter the demo token to fork'
  if (forking.value) return 'Submitting the fork'
  return ''
})

async function fork () {
  if (forkWhy.value) return
  const round = display.value
  forking.value = true
  forkError.value = ''
  try {
    const accepted = await request(`/runs/${encodeURIComponent(runId.value)}/fork`, {
      method: 'POST', token: token.value, body: { checkpoint_round: round, policies: POLICIES }
    })
    forked.value = { round, branch_ids: accepted?.branch_ids ?? [] }
  } catch (error) {
    forkError.value = `Fork not accepted: ${error.message}`
  } finally {
    forking.value = false
  }
}

const interviewWhy = computed(() => {
  if (!current.value) return 'Round not loaded: nothing to ask about'
  if (!actor.value) return 'Pick an actor above'
  if (!question.value.trim()) return 'Write a question'
  if (!token.value) return 'Enter the demo token to interview'
  if (asking.value) return 'Asking'
  return ''
})

async function interview () {
  if (interviewWhy.value) return
  asking.value = true
  interviewError.value = ''
  try {
    answer.value = await request('/interview', {
      method: 'POST', token: token.value,
      body: { run_id: runId.value, branch_id: base.value.branch_id, round: display.value,
        actor_id: actor.value, question: question.value.trim() }
    })
  } catch (error) {
    interviewError.value = `Interview not answered: ${error.message}`
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
const exportHref = computed(() => {
  if (!current.value) return null
  const b = shellReading.value.body
  const doc = {
    label: base.value.replay ? LABELS.replay : 'Fresh run',
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
    cash: (b.cash_paths ?? []).map((p) => ({
      branch_id: p.branch_id,
      account_id: p.account_id,
      value: p.points.find((x) => Date.parse(x.t) === roundAt.value)?.value ?? null
    }))
  }
  return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(doc, null, 2))}`
})
</script>

<style scoped>
/* The live panel is an instrument: dark in both themes (system brief §12). */
.lw-live {
  --live-surface: #0E1520;
  --live-raised: #142030;
  --live-ink: #E6EEF6;
  --live-muted: #9AA6B2;
  --live-rule: #2A3646;
  --live-brand: #79A6FF;
  --live-ok: #3BE58F;
  --live-warn: #FFB43A;
  --live-bad: #FF5E54;
  display: grid;
  gap: var(--lw-space-3);
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  grid-template-areas:
    'controls controls'
    'graph feed'
    'cash cash';
  margin-top: var(--lw-space-4);
  padding: var(--lw-space-3);
  border-radius: var(--lw-radius);
  background: var(--live-surface);
  color: var(--live-ink);
}

.lw-live__controls { grid-area: controls; }
.lw-live__cash { grid-area: cash; }
.lw-live__feed { grid-area: feed; }
.lw-live__graph { grid-area: graph; }

.lw-live.is-graph-expanded {
  grid-template-areas:
    'controls controls'
    'graph graph'
    'feed feed'
    'cash cash';
}

.lw-live :deep(.lw-live-panel) {
  min-width: 0;
  padding: var(--lw-space-3);
  border: 1px solid var(--live-rule);
  border-radius: var(--lw-radius);
}

.lw-live :deep(h2) {
  margin: 0 0 var(--lw-space-2);
  font-size: 16px;
  color: var(--live-ink);
}

.lw-live :deep(.lw-live-tag) {
  display: inline-block;
  padding: 0 var(--lw-space-2);
  border: 1px solid var(--live-warn);
  border-radius: var(--lw-radius);
  color: var(--live-warn);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.lw-live :deep(.lw-live-empty),
.lw-live__note {
  margin: var(--lw-space-2) 0 0;
  color: var(--live-muted);
}

.lw-live :deep(.lw-button--quiet) { color: var(--live-brand); border-color: var(--live-brand); }
.lw-live :deep(.lw-button[disabled]) { color: var(--live-muted); border-color: var(--live-rule); }
.lw-live :deep(.lw-alert) { color: var(--live-bad); border-color: var(--live-bad); background: transparent; }

.lw-live__phase { margin: 0 0 var(--lw-space-2); font-weight: 700; }
.lw-live__phase.is-ok { color: var(--live-ok); }
.lw-live__phase.is-warn { color: var(--live-warn); }
.lw-live__phase.is-bad { color: var(--live-bad); }

.lw-live__row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-3);
  align-items: center;
  margin-top: var(--lw-space-3);
}

.lw-live__token,
.lw-live__interview label {
  display: grid;
  gap: var(--lw-space-1);
  width: min(100%, 420px);
  color: var(--live-muted);
}

.lw-live input,
.lw-live textarea {
  min-height: var(--lw-target);
  padding: var(--lw-space-2);
  border: 1px solid var(--live-rule);
  border-radius: var(--lw-radius);
  background: var(--live-raised);
  color: var(--live-ink);
  font: inherit;
}

.lw-live input:focus-visible,
.lw-live textarea:focus-visible {
  outline: 3px solid var(--live-brand);
  outline-offset: 2px;
}

.lw-live__graph {
  display: grid;
  gap: var(--lw-space-3);
}

.lw-live__graph-view {
  height: 360px;
  overflow: hidden;
  border-radius: var(--lw-radius);
}

.is-graph-expanded .lw-live__graph-view { height: 70vh; }

/* The reused graph is drawn on paper; inverted (hues kept) it sits in the dark instrument panel. */
.lw-live__graph-view :deep(.graph-panel) {
  filter: invert(1) hue-rotate(180deg);
}

/* The reused graph's toolbar keeps the 44 px touch target here. */
.lw-live__graph-view :deep(.tool-btn) {
  min-width: var(--lw-target);
  min-height: var(--lw-target);
}

.lw-live__actors {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2);
}

.lw-live__actors .lw-button[aria-pressed='true'] {
  background: var(--live-brand);
  color: var(--live-surface);
}

.lw-live__interview {
  display: grid;
  gap: var(--lw-space-2);
  margin-top: var(--lw-space-3);
}

.lw-live__answer {
  margin-top: var(--lw-space-3);
  padding: var(--lw-space-2) var(--lw-space-3);
  background: var(--live-raised);
}

/* Phone: the DOM order is the reading order — labels, scrubber and controls, cash, feed, graph. */
@media (max-width: 720px) {
  .lw-live,
  .lw-live.is-graph-expanded {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: none;
  }

  .lw-live__controls,
  .lw-live__cash,
  .lw-live__feed,
  .lw-live__graph { grid-area: auto; }
}
</style>

<template>
  <ScreenShell title="Live simulation" :reading="shellReading" :refresh="reload">
    <div class="lw-live" :class="{ 'is-graph-expanded': graphExpanded }">
      <section class="lw-sim__context" aria-labelledby="run-heading" data-panel="The what-if" data-test="run-context">
        <h2 id="run-heading" class="lw-visually-hidden">Run and scenario context</h2>
        <p class="lw-lead" data-test="lead">{{ lead }}</p>
        <div class="lw-labels" data-test="labels">
          <span v-if="body" class="lw-tag" data-test="plain-mode">{{ PLAIN[body.mode] || LABELS[body.mode] || body.mode }}</span>
          <span class="lw-tag" data-test="hypothetical">{{ PLAIN.branch }}</span>
          <span v-if="base.replay" class="lw-tag">Replay</span>
        </div>
        <HowWeKnow test="how-run">
          <dl>
            <div><dt>Run</dt><dd data-test="run-id">{{ body?.run_id ?? runId ?? '–' }}</dd></div>
            <div><dt>Branch</dt><dd>{{ base.branch_id ?? '–' }}</dd></div>
            <div><dt>Checkpoint</dt><dd>{{ checkpoints }}</dd></div>
            <div><dt>Scenario</dt><dd data-test="family">{{ family ? family.id : 'not named by this run' }}</dd></div>
            <div><dt>Provenance</dt><dd>{{ provenance(base.replay) }}</dd></div>
            <div><dt>Mode</dt><dd>{{ body ? (LABELS[body.mode] || body.mode) : '–' }}</dd></div>
          </dl>
          <p>The amount in the sentence above is the treasury's pending flow the scenario family delays
            ({{ family?.params.flow_id ?? 'none named' }}), read from the treasury on this run's snapshot;
            the delay is the family's delay_h.</p>
        </HowWeKnow>
        <p v-if="handoff" class="lw-live__note lw-sim__handoff" data-test="handoff">{{ handoff }}</p>
        <button type="button" class="lw-button lw-button--quiet" data-test="settings" @click="settingsOpen = true">
          Scenario settings
        </button>
      </section>

      <section class="lw-live-panel lw-live__controls" aria-label="Round and controls" data-test="controls" data-panel="Round and controls">
        <p class="lw-live__phase" :class="`is-${phase.tone}`" role="status" data-test="phase">
          {{ phase.icon }} {{ phase.text }}
        </p>
        <p v-if="base.replay" class="lw-live__phase" data-test="replay-note">
          <span class="lw-live-tag">Replay</span> these rounds were replayed, not run fresh
        </p>
        <Scrubber :model-value="display" :rounds="ticks" :loaded="loadedRounds" :t-hours="current?.t_hours ?? null"
                  @update:model-value="scrub" />
        <p class="lw-live__note">Round n is simulated hour {{ ROUND_HOURS }}n. ←/→ step, Home and End jump; moving the cursor never creates a financial action.</p>
        <div class="lw-live__row">
          <button type="button" class="lw-button" data-test="play" :disabled="!ticks.length"
                  @click="playing ? pause() : play()">
            {{ playing ? 'Pause playback' : 'Play' }}
          </button>
          <span v-if="paused" class="lw-live__note" data-test="paused">Playback paused; simulation may continue</span>
          <a v-if="exportHref" class="lw-button lw-button--quiet" :href="exportHref" :download="exportName"
             data-test="export">Export round {{ display }}</a>
        </div>

        <div class="lw-live__row lw-sim__access">
          <label class="lw-live__token">
            <span>Operator access (kept in this tab's memory only)</span>
            <input v-model="token" type="password" autocomplete="off" spellcheck="false" data-test="token">
          </label>
          <button v-if="token" type="button" class="lw-button lw-button--quiet" data-test="forget" @click="token = ''">
            Forget access
          </button>
        </div>
        <div class="lw-live__row">
          <button type="button" class="lw-button" data-test="fork" :disabled="Boolean(forkWhy)"
                  :aria-describedby="forkWhy ? 'fork-why' : undefined" :aria-expanded="confirming ? 'true' : 'false'"
                  @click="confirming = true">
            Try the plans on this shock
          </button>
          <RouterLink v-if="compareTarget" class="lw-button lw-button--quiet" :to="compareTarget"
                      data-test="compare">Compare policies</RouterLink>
          <button v-else type="button" class="lw-button lw-button--quiet" disabled data-test="compare"
                  :aria-describedby="'compare-why'">Compare policies</button>
        </div>
        <div v-if="confirming && !forkWhy" class="lw-sim__confirm" role="group" aria-label="Confirm the fork" data-test="fork-confirm-panel">
          <p>Try {{ listWords(POLICIES.map((p) => PLANS[p])) }} from round {{ display }}, each in its own
            fresh what-if. It creates no approval and moves no money.</p>
          <p class="lw-live__note">Forks {{ base.branch_id }} at committed round {{ display }} into {{ POLICIES.join(', ') }}.</p>
          <div class="lw-live__row">
            <button type="button" class="lw-button" data-test="fork-confirm" @click="confirmFork">Try the plans</button>
            <button type="button" class="lw-button lw-button--quiet" data-test="fork-cancel" @click="confirming = false">Cancel</button>
          </div>
        </div>
        <p class="lw-live__note" data-test="fork-what">
          Tries each plan from round {{ display ?? '–' }} in its own what-if; approves nothing.
        </p>
        <p v-if="forkWhy" id="fork-why" class="lw-live__note" data-test="fork-why">{{ forkWhy }}</p>
        <p v-if="!compareTarget" id="compare-why" class="lw-live__note" data-test="compare-why">{{ compareWhy }}</p>
        <p v-if="forked" class="lw-live__note" role="status" data-test="forked">
          Fork accepted at round {{ forked.round }}: {{ forked.branch_ids.join(', ') }} ·
          {{ forked.done ? 'branches and cash paths loaded' : 'running; its branches appear here when it finishes' }}
        </p>
        <p v-if="forked?.lag" class="lw-live__note" role="status" data-test="fork-lag">
          Fork progress not read: {{ forked.lag }}; still checking
        </p>
        <p v-if="forkError" class="lw-alert" role="alert" data-test="fork-error">{{ forkError }}</p>
      </section>

      <CashPaths class="lw-live__cash" data-panel="Cash paths" :round="display" :at="roundAt" :paths="body?.cash_paths ?? []"
                 :branches="body?.branches ?? []" />

      <ActionFeed class="lw-live__feed" data-panel="Event feed" :round="display" :loaded="Boolean(current)" :posts="roundPosts"
                  :intents="current?.intents ?? []" :cleared="current?.cleared ?? []"
                  :replay="base.replay" :highlight="actor" @pick="pickEvent" />

      <section class="lw-live-panel lw-live__graph" aria-label="World map and actor inspector" data-test="graph" data-panel="World map and actors">
        <div class="lw-live__inspector" data-test="inspector">
          <h2>Actors up to round {{ display ?? '–' }}</h2>
          <p v-if="!current" class="lw-live-empty">Round not loaded</p>
          <ul v-else class="lw-live__actors" aria-label="Actors, the keyboard way to the map">
            <li v-for="a in actors" :key="a.id">
              <button type="button" class="lw-button lw-button--quiet" :aria-pressed="a.id === actor ? 'true' : 'false'"
                      :data-actor="a.id" @click="selectActor(a.id)">
                <span>{{ a.name }}</span>
                <span class="lw-sim__actor-id">{{ a.id }}<template v-if="a.active"> · acted this round</template></span>
              </button>
            </li>
          </ul>

          <Teleport defer to="#lw-actor-sheet" :disabled="!phone">
            <article v-if="actorInfo" class="lw-sim__actor" data-test="actor-detail">
              <h3>{{ actorInfo.label }}</h3>
              <dl>
                <dt>Role</dt><dd>{{ actorInfo.role || 'not named by the world file' }}</dd>
                <dt>Objective</dt><dd>{{ actorInfo.objective || 'not named by the world file' }}</dd>
                <dt>Observes</dt><dd>{{ actorInfo.sees }}</dd>
              </dl>
              <h4>Actions up to round {{ display }}</h4>
              <ol v-if="actorInfo.actions.length" class="lw-sim__actions" data-test="actor-actions">
                <li v-for="x in actorInfo.actions" :key="x.id">
                  <span>Round {{ x.round }} · {{ x.type }}</span>
                  <span :class="`is-${x.tone}`">{{ x.verdict }}</span>
                </li>
              </ol>
              <HowWeKnow v-if="actorInfo.actions.length" test="how-actor">
                <ul class="lw-sim__actions">
                  <li v-for="x in actorInfo.actions" :key="x.id">
                    {{ x.id }}<template v-if="x.journal"> · journal {{ x.journal }}</template>
                    · evidence {{ x.evidence || 'none cited' }}
                  </li>
                </ul>
              </HowWeKnow>
              <p v-else class="lw-live-empty">No action by round {{ display }}</p>
            </article>
            <form class="lw-live__interview" data-test="interview" @submit.prevent="interview">
              <label>
                <span>Ask {{ actor ? nameOf(actor) : 'an actor' }} about round {{ display ?? '–' }} (read-only)</span>
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
                Read-only answer · {{ nameOf(answer.actor_id) }} at round {{ answer.round }} · {{ answer.branch_id }}
                <span v-if="answer.replay" class="lw-live-tag">Replay</span>
              </p>
              <p>{{ answer.answer }}</p>
              <HowWeKnow v-if="answer.evidence_ids.length" test="how-answer">
                <p>evidence: {{ answer.evidence_ids.join(', ') }}</p>
              </HowWeKnow>
            </article>
          </Teleport>
        </div>

        <div class="lw-sim__map">
          <h2>World map · round {{ display ?? '–' }} <span class="lw-live-tag">{{ PLAIN.branch }}</span></h2>
          <WorldMap :nodes="worldMap.nodes" :edges="worldMap.edges" :selected="mapSelected" :focus="actor"
                    label="Actors and their typed relationships at the selected round"
                    :empty="current ? 'No actor to draw' : 'Round not loaded'" @select="pickMap" />
          <details class="lw-sim__evidence" :open="graphExpanded" @toggle="evidenceToggled">
            <summary>Evidence graph: posts and the citations behind each intent</summary>
            <div class="lw-live__graph-view">
              <LiveGraph ref="graphPanel" :graph-data="graphData" :loading="busy" :is-simulating="phase.running"
                         @refresh="reload" @toggle-maximize="graphExpanded = !graphExpanded" />
            </div>
          </details>
        </div>
      </section>
    </div>

    <DetailSheet :open="actorSheet && phone" :title="actorInfo ? actorInfo.label : 'Actor'" test="actor-sheet"
                 @close="actorSheet = false">
      <div id="lw-actor-sheet" />
    </DetailSheet>

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
 * read-only interview carry the selected round and need operator access, a token that lives in this
 * component's memory only — never storage, the URL, the export or a log. An accepted fork is
 * followed until its branches arrive or it fails. No POST is retried.
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import LiveGraph from '../components/LiveGraph.vue'
import Scrubber from '../components/Scrubber.vue'
import ActionFeed from '../components/ActionFeed.vue'
import CashPaths from '../components/CashPaths.vue'
import DetailSheet from '../components/DetailSheet.vue'
import HowWeKnow from '../components/HowWeKnow.vue'
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
const runId = computed(() => (typeof route.query.run_id === 'string' && route.query.run_id) || null)

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

/** What a handoff from Treasury (account, snapshot) or Lending (scenario) carried, said back. */
const handoff = computed(() => {
  const q = route.query
  const said = (key) => (typeof q[key] === 'string' && q[key]) || null
  const [account, snapshot, scenario] = [said('account'), said('snapshot'), said('scenario')]
  if (!account && !snapshot && !scenario) return ''
  const parts = []
  if (account) parts.push(`Rehearsing for account ${account}.`)
  if (scenario) parts.push(`Scenario asked for: ${scenario}.`)
  const runSnapshot = body.value?.snapshot_id
  if (snapshot && runSnapshot && snapshot !== runSnapshot && !observedBy(snapshot, body.value.run_id)) {
    parts.push(`The handoff was made on snapshot ${snapshot}; this run is on ${runSnapshot}.`)
  }
  return parts.join(' ')
})

// A phone shows the selected actor in a full-height sheet; wider screens show it inline.
const phone = ref(false)
let phoneQuery = null
const onPhone = (event) => { phone.value = event.matches }
onMounted(() => {
  phoneQuery = window.matchMedia?.('(max-width: 767px)') ?? null
  phone.value = Boolean(phoneQuery?.matches)
  phoneQuery?.addEventListener?.('change', onPhone)
})
onBeforeUnmount(() => phoneQuery?.removeEventListener?.('change', onPhone))
const actorSheet = ref(false)

/** One actor is selected: the map, the actor list, the inspector and the feed highlight follow it. */
function selectActor (id) {
  actor.value = id
  if (phone.value) actorSheet.value = true
}

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
const worldMap = computed(() => {
  if (!current.value) return { nodes: [], edges: [] }
  const w = world.value
  const nodes = new Map((w?.actors ?? []).map((a) => [a.id, { id: a.id, label: a.label, role: a.role }]))
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
  return { nodes: [...nodes.values()], edges: [...edges.values()] }
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
          forkError.value = 'Fork decided, but its branches have not reached the run: Refresh, or fork again'
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
/* The live panel in the ivory system: the shared components read --live-* (Scrubber, ActionFeed,
   CashPaths), mapped here onto the design tokens, so both themes follow tokens.css. */
.lw-live {
  --live-surface: var(--lw-surface);
  --live-raised: var(--lw-surface-raised);
  --live-ink: var(--lw-ink);
  --live-muted: var(--lw-ink-muted);
  --live-rule: var(--lw-rule);
  --live-brand: var(--lw-brand);
  --live-ok: var(--lw-ok-text);
  --live-warn: var(--lw-warn-text);
  --live-bad: var(--lw-bad-text);
  display: grid;
  gap: var(--lw-space-6);
  grid-template-columns: minmax(0, 1fr);
  margin-top: var(--lw-space-4);
  color: var(--lw-ink);
}

.lw-live > * { min-width: 0; }

/* Desktop: map and inspector left, feed right; round controls and cash below. */
@media (min-width: 1200px) {
  .lw-live {
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    grid-template-areas:
      'context context'
      'graph feed'
      'controls cash';
    align-items: start;
  }

  .lw-sim__context { grid-area: context; }
  .lw-live__controls { grid-area: controls; }
  .lw-live__cash { grid-area: cash; }
  .lw-live__feed { grid-area: feed; }
  .lw-live__graph { grid-area: graph; }
}

.lw-live :deep(.lw-live-panel) {
  min-width: 0;
  padding: var(--lw-space-4);
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
}

.lw-live :deep(h2) {
  margin: 0 0 var(--lw-space-3);
  font-family: var(--lw-font-heading);
  font-size: 22px;
  line-height: 28px;
  color: var(--lw-ink);
}

.lw-live :deep(.lw-live-tag) {
  display: inline-block;
  padding: 0 var(--lw-space-2);
  border: 1px solid var(--lw-warn);
  border-radius: var(--lw-radius);
  color: var(--lw-warn-text);
  font-family: var(--lw-font-text);
  font-size: 12px;
  font-weight: 700;
  line-height: 20px;
  text-transform: uppercase;
  vertical-align: middle;
}

.lw-live :deep(.lw-live-empty),
.lw-live__note {
  margin: var(--lw-space-2) 0 0;
  color: var(--lw-ink-muted);
}

.lw-live__phase { margin: 0 0 var(--lw-space-2); font-weight: 700; }
.lw-live__phase.is-ok { color: var(--lw-ok-text); }
.lw-live__phase.is-warn { color: var(--lw-warn-text); }
.lw-live__phase.is-bad { color: var(--lw-bad-text); }

.lw-sim__context {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-3) var(--lw-space-6);
  align-items: center;
  justify-content: space-between;
  padding: var(--lw-space-3) 0;
  border-top: 1px solid var(--lw-rule);
  border-bottom: 1px solid var(--lw-rule);
}

/* the lead and its labels take the row; How we know and the settings share the next one */
.lw-sim__context > .lw-lead,
.lw-sim__context > .lw-labels { flex: 1 0 100%; margin-bottom: 0; }

.lw-sim__context dl {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-3) var(--lw-space-6);
  margin: 0;
  min-width: 0;
}

.lw-sim__context dt { font-size: 13px; color: var(--lw-ink-muted); }
.lw-sim__context dd { margin: 0; font-weight: 600; overflow-wrap: anywhere; }

.lw-live__row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-3);
  align-items: end;
  margin-top: var(--lw-space-3);
}

.lw-live__token,
.lw-live__interview label {
  display: grid;
  gap: var(--lw-space-1);
  width: min(100%, 420px);
  color: var(--lw-ink-muted);
}

.lw-live input,
.lw-live textarea,
.lw-sim__actor-sheet textarea {
  min-height: var(--lw-target);
  padding: var(--lw-space-2);
  border: 1px solid var(--lw-ink-muted);
  border-radius: var(--lw-radius);
  background: var(--lw-surface-raised);
  color: var(--lw-ink);
  font: inherit;
}

.lw-live input:focus-visible,
.lw-live textarea:focus-visible {
  outline: 3px solid var(--lw-focus);
  outline-offset: 2px;
}

.lw-sim__confirm {
  margin-top: var(--lw-space-3);
  padding: var(--lw-space-3);
  border-left: 4px solid var(--lw-brand);
  background: var(--lw-selected);
}

.lw-sim__confirm p { margin: 0; }

.lw-live__graph {
  display: grid;
  gap: var(--lw-space-4);
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
  background: var(--lw-brand);
  color: var(--lw-on-brand);
}

.lw-live__actors .lw-button {
  flex-direction: column;
  align-items: flex-start;
  padding-block: var(--lw-space-1);
  text-align: left;
}

.lw-sim__actor-id { font-size: 12px; font-weight: 400; }

.lw-sim__actor { margin-top: var(--lw-space-4); }
.lw-sim__actor h3 { margin: 0 0 var(--lw-space-2); font-size: 18px; }
.lw-sim__actor h4 { margin: var(--lw-space-3) 0 var(--lw-space-2); font-size: 15px; }

.lw-sim__actor dl {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 3fr);
  gap: var(--lw-space-1) var(--lw-space-3);
  margin: 0;
}

.lw-sim__actor dt { color: var(--lw-ink-muted); }
.lw-sim__actor dd { margin: 0; overflow-wrap: anywhere; }

.lw-sim__actions {
  list-style: none;
  margin: 0;
  padding: 0;
}

.lw-sim__actions li {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--lw-space-3);
  padding: var(--lw-space-1) 0;
  border-top: 1px solid var(--lw-rule);
  overflow-wrap: anywhere;
}

.lw-sim__actions .is-ok { color: var(--lw-ok-text); }
.lw-sim__actions .is-bad { color: var(--lw-bad-text); }
.lw-sim__actions .is-warn { color: var(--lw-warn-text); }
.lw-sim__actions .is-muted { color: var(--lw-ink-muted); }

.lw-live__interview {
  display: grid;
  gap: var(--lw-space-2);
  margin-top: var(--lw-space-4);
}

.lw-live__answer {
  margin-top: var(--lw-space-3);
  padding: var(--lw-space-2) var(--lw-space-3);
  background: var(--lw-selected);
}

/* From the tablet up the map leads its section; a phone reads the actor list first. */
@media (min-width: 768px) {
  .lw-sim__map { order: -1; }
}

.lw-sim__evidence { margin-top: var(--lw-space-3); }

.lw-sim__evidence summary {
  display: flex;
  align-items: center;
  min-height: var(--lw-target);
  color: var(--lw-brand);
  font-weight: 600;
  cursor: pointer;
}

.lw-live__graph-view {
  height: 360px;
  overflow: hidden;
  border: 1px solid var(--lw-rule);
  border-radius: var(--lw-radius);
}

.is-graph-expanded .lw-live__graph-view { height: 70vh; }

/* The reused graph's toolbar keeps the 44 px touch target here. */
.lw-live__graph-view :deep(.tool-btn) {
  min-width: var(--lw-target);
  min-height: var(--lw-target);
}

.lw-sim__families {
  list-style: none;
  margin: 0;
  padding: 0;
}

.lw-sim__families li {
  padding: var(--lw-space-3) 0;
  border-top: 1px solid var(--lw-rule);
}

.lw-sim__families li.is-current {
  padding-left: var(--lw-space-3);
  border-left: 4px solid var(--lw-brand);
  background: var(--lw-selected);
}

.lw-sim__families p { margin: var(--lw-space-1) 0 0; }
</style>

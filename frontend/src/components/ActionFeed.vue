<template>
  <section class="lw-live-panel" aria-labelledby="feed-title" data-test="feed">
    <h2 id="feed-title">Action feed · round {{ round ?? '–' }}</h2>
    <p v-if="!loaded" class="lw-live-empty" data-test="feed-unloaded">Round not loaded</p>
    <p v-else-if="!items.length" class="lw-live-empty">No posts or intents in this round</p>
    <ol v-else class="lw-feed">
      <li v-for="item in items" :key="item.id" class="lw-feed__item"
          :class="{ 'is-highlight': item.actor === highlight }" :data-id="item.id">
        <div class="lw-feed__head">
          <span class="lw-feed__kind">{{ item.kind }}</span>
          <Tip :text="tipOf(item)">
            <button type="button" class="lw-feed__open" data-test="feed-open"
                    :aria-label="`${item.kind} ${item.id} by ${item.actor}: open its evidence`"
                    @click="emit('pick', item)">{{ item.actor }}</button>
          </Tip>
        </div>
        <p v-if="item.text" class="lw-feed__text">{{ item.text }}</p>
        <p v-if="item.status" class="lw-feed__status" :class="`is-${item.status.tone}`">
          <Tip :text="item.journal ? `Journal ${item.journal}` : 'No ledger change'">
            {{ item.status.icon }} {{ item.status.word }}<template v-if="item.reason"> · {{ item.reason }}</template>
          </Tip>
        </p>
      </li>
    </ol>
  </section>
</template>

<script setup>
/**
 * One round's public posts and actor intents, each intent with the coordinator's verdict (C2).
 * Only the round handed in is shown; an unloaded round says so and lists nothing. An intent is
 * a proposal; only an accepted one with a journal changed the ledger, and each says which it is.
 * Choosing an item emits `pick` with it, for the screen to highlight its actor and open its evidence.
 */
import { computed } from 'vue'
import { PLAIN, formatMoney, kindText } from '../api/v1.js'
import Tip from './Tip.vue'

const props = defineProps({
  round: { type: Number, default: null },
  loaded: { type: Boolean, default: false },
  posts: { type: Array, default: () => [] },
  intents: { type: Array, default: () => [] },
  cleared: { type: Array, default: () => [] },
  replay: { type: Boolean, default: false },
  highlight: { type: String, default: null }
})
const emit = defineEmits(['pick'])

const VERDICT = {
  accepted: { icon: '✓', word: 'Accepted', tone: 'ok' },
  rejected: { icon: '✕', word: 'Rejected', tone: 'bad' },
  pending: { icon: '◷', word: 'Pending', tone: 'warn' }
}

/** What used to sit beside an item: its id, the evidence it cites, and Replay when the round was replayed. */
function tipOf (item) {
  return [item.id, item.evidence.length ? `evidence: ${item.evidence.join(', ')}` : '',
    props.replay ? PLAIN.replay : ''].filter(Boolean).join(' · ')
}

const items = computed(() => {
  const verdicts = new Map(props.cleared.map((c) => [c.intent_id, c]))
  const posts = props.posts.map((p) => ({
    id: p.post_id, kind: 'Post', actor: p.author, text: p.text, status: null, evidence: []
  }))
  const intents = props.intents.map((i) => {
    const c = verdicts.get(i.intent_id)
    const amount = i.params?.amount
    return {
      id: i.intent_id,
      kind: c?.journal_id ? 'Intent · ledger change' : 'Intent · proposed',
      actor: i.actor_id,
      text: `${kindText(i.type)}${amount ? ` ${formatMoney(amount.minor, amount.currency)}` : ''}`,
      status: c ? VERDICT[c.status] : { icon: '–', word: 'No verdict recorded', tone: 'muted' },
      reason: c?.reason ?? null,
      journal: c?.journal_id ?? null,
      evidence: i.evidence_ids ?? []
    }
  })
  return [...posts, ...intents]
})
</script>

<style scoped>
.lw-feed {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--lw-space-2);
}

.lw-feed__item {
  padding: var(--lw-space-2) var(--lw-space-3);
  border-left: 3px solid var(--live-rule);
  background: var(--live-raised);
}

.lw-feed__item.is-highlight {
  border-left: 5px solid var(--live-brand);
  background: var(--lw-selected, var(--live-raised));
}

.lw-feed__open {
  min-height: var(--lw-target);
  padding: 0;
  border: 0;
  background: none;
  color: var(--live-brand);
  font: inherit;
  font-weight: 700;
  text-decoration: underline;
  cursor: pointer;
}

.lw-feed__head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lw-space-2);
  align-items: baseline;
}

.lw-feed__kind {
  color: var(--live-muted);
  font-size: 12px;
}

.lw-feed__text,
.lw-feed__status { margin: var(--lw-space-1) 0 0; }

.lw-feed__status.is-ok { color: var(--live-ok); }
.lw-feed__status.is-bad { color: var(--live-bad); }
.lw-feed__status.is-warn { color: var(--live-warn); }
.lw-feed__status.is-muted { color: var(--live-muted); }
</style>

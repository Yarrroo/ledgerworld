<template>
  <GraphPanel ref="panel" :graph-data="shown" />
</template>

<script setup>
/**
 * The reused graph view, drawn from its first data (system brief §12, Live simulation graph).
 *
 * GraphPanel draws only when its `graphData` changes after it mounted; data it mounts with is never
 * drawn, and an unchanged reload hands it the same object, so a screen that mounts it with a body
 * already loaded showed a blank graph. This adapter mounts it with no data and hands the data over
 * once mounted, so the first graph is a change it draws. Every other attribute and event (loading,
 * isSimulating, refresh, toggle-maximize) falls through to GraphPanel unchanged, and its
 * `closeDetailPanel` is passed up for the screen that owns the round cursor.
 *
 * GraphPanel sizes its drawing from its box at the moment it draws, so a graph drawn while hidden
 * (inside a closed disclosure) is drawn at 0×0 and stays blank once shown. `redraw` hands the same
 * data over again as a new object, which GraphPanel draws at its box's size now; the screen calls it
 * when it shows the graph. The data itself does not change, so a later unchanged poll stays a no-op.
 */
import { onMounted, shallowRef, watch } from 'vue'
import GraphPanel from './GraphPanel.vue'

const props = defineProps({ graphData: Object })

const shown = shallowRef(null)
const panel = shallowRef(null)
defineExpose({
  closeDetailPanel: () => panel.value?.closeDetailPanel(),
  redraw: () => { if (props.graphData) shown.value = { ...props.graphData } }
})
onMounted(() => { shown.value = props.graphData })
watch(() => props.graphData, (graph) => { shown.value = graph })
</script>

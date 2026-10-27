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
 */
import { onMounted, shallowRef, watch } from 'vue'
import GraphPanel from './GraphPanel.vue'

const props = defineProps({ graphData: Object })

const shown = shallowRef(null)
const panel = shallowRef(null)
defineExpose({ closeDetailPanel: () => panel.value?.closeDetailPanel() })
onMounted(() => { shown.value = props.graphData })
watch(() => props.graphData, (graph) => { shown.value = graph })
</script>

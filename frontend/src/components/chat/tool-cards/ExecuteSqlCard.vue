<template>
  <div class="tool-card">
    <div class="tool-card__header">
      <span class="tool-card__step">[{{ stepNumber }}]</span>
      <Play
        :size="14"
        class="tool-card__icon"
      />
      <span class="tool-card__title">{{ displayName }}</span>
      <span
        v-if="isPending"
        class="tool-card__status tool-card__status--pending"
      >
        running...
      </span>
      <span
        v-else-if="parsed"
        class="tool-card__metrics"
      >
        <span class="tool-card__metric">
          <Rows3 :size="11" />
          {{ rowsLabel }}
        </span>
        <span
          v-if="parsed.hasInsights"
          class="tool-card__metric tool-card__metric--accent"
          title="Insights extracted"
        >
          <Sparkles :size="11" />
          insights
        </span>
        <span
          v-if="parsed.hasChart"
          class="tool-card__metric tool-card__metric--accent"
          title="Chart recommendation produced"
        >
          <BarChart3 :size="11" />
          chart
        </span>
        <span
          v-if="parsed.sampling"
          class="tool-card__metric tool-card__metric--warn"
          title="Result was sampled — not a full scan"
        >
          <Filter :size="11" />
          sampled
        </span>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { BarChart3, Filter, Play, Rows3, Sparkles } from 'lucide-vue-next'
import { parseExecuteResult, TOOL_DISPLAY_NAMES } from './parsers.js'

const props = defineProps({
  toolName: { type: String, required: true },
  args: { type: Object, default: () => ({}) },
  result: { type: String, default: '' },
  stepNumber: { type: Number, default: 0 },
  isPending: { type: Boolean, default: false }
})

const displayName = computed(
  () => TOOL_DISPLAY_NAMES[props.toolName] || 'Execute query'
)

const parsed = computed(() => parseExecuteResult(props.result))

const rowsLabel = computed(() => {
  if (!parsed.value) return '0 rows'
  const n = parsed.value.rowCount
  // Generic "results" wording — covers SQL rows + Mongo documents
  // + DynamoDB items in one phrase, matching the existing
  // AgentTimeline convention.
  return `${n.toLocaleString()} ${n === 1 ? 'result' : 'results'}`
})
</script>

<style scoped>
.tool-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: rgba(0, 0, 0, 0.15);
  padding: var(--space-xs) var(--space-sm);
  margin-bottom: var(--space-xs);
  font-size: 12px;
}

.tool-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  flex-wrap: wrap;
  color: var(--text-secondary);
}

.tool-card__step {
  color: var(--color-primary);
  font-weight: 600;
  min-width: 24px;
}

.tool-card__icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.tool-card__title {
  color: var(--text-primary);
  font-weight: 500;
}

.tool-card__metrics {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  flex-wrap: wrap;
}

.tool-card__metric {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-xs);
  background: var(--bg-input, rgba(255, 255, 255, 0.05));
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
}

.tool-card__metric--accent {
  color: var(--color-primary);
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.tool-card__metric--warn {
  color: var(--color-warning, #f59e0b);
  border-color: rgba(245, 158, 11, 0.3);
  background: rgba(245, 158, 11, 0.08);
}

.tool-card__status {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 11px;
}

.tool-card__status--pending {
  color: var(--color-primary);
}

.light-theme .tool-card {
  background: rgba(0, 0, 0, 0.03);
}
</style>

<template>
  <div class="tool-card">
    <div class="tool-card__header">
      <span class="tool-card__step">[{{ stepNumber }}]</span>
      <Eye
        :size="14"
        class="tool-card__icon"
      />
      <span class="tool-card__title">Sample data</span>
      <span
        v-if="tableTag"
        class="tool-card__chip"
      >
        <Database :size="11" />
        {{ tableTag }}
      </span>
      <span
        v-if="isPending"
        class="tool-card__status tool-card__status--pending"
      >
        sampling...
      </span>
      <span
        v-else-if="parsed && parsed.empty"
        class="tool-card__status tool-card__status--muted"
      >
        empty
      </span>
      <span
        v-else-if="parsed && parsed.sampleColumnCount"
        class="tool-card__status"
      >
        {{ parsed.sampleColumnCount }} columns inspected
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Database, Eye } from 'lucide-vue-next'
import { parseSampleDataResult } from './parsers.js'

const props = defineProps({
  toolName: { type: String, required: true },
  args: { type: Object, default: () => ({}) },
  result: { type: String, default: '' },
  stepNumber: { type: Number, default: 0 },
  isPending: { type: Boolean, default: false }
})

const parsed = computed(() => parseSampleDataResult(props.result))

const tableTag = computed(() => {
  if (parsed.value?.table) return parsed.value.table
  return props.args?.table_name || ''
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

.tool-card__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-xs);
  background: var(--bg-input, rgba(255, 255, 255, 0.05));
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
}

.tool-card__status {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 11px;
}

.tool-card__status--pending {
  color: var(--color-primary);
}

.tool-card__status--muted {
  color: var(--text-muted);
  font-style: italic;
}

.light-theme .tool-card {
  background: rgba(0, 0, 0, 0.03);
}
</style>

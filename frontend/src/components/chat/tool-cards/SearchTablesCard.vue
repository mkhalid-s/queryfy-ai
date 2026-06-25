<template>
  <div class="tool-card">
    <div class="tool-card__header">
      <span class="tool-card__step">[{{ stepNumber }}]</span>
      <Search
        :size="14"
        class="tool-card__icon"
      />
      <span class="tool-card__title">{{ displayName }}</span>
      <span
        v-if="query"
        class="tool-card__sub"
      >
        '{{ query }}'
      </span>
      <span
        v-if="isPending"
        class="tool-card__status tool-card__status--pending"
      >
        searching...
      </span>
    </div>

    <div
      v-if="!isPending && parsed"
      class="tool-card__body"
    >
      <div
        v-if="parsed.empty"
        class="tool-card__empty"
      >
        No tables found
      </div>
      <div
        v-else
        class="tool-card__chips"
      >
        <span
          v-for="table in parsed.tables"
          :key="table.name"
          class="tool-card__chip"
          :title="
            table.columns.length
              ? `Columns: ${table.columns.join(', ')}`
              : table.name
          "
        >
          <Database :size="11" />
          {{ table.name }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Database, Search } from 'lucide-vue-next'
import { parseSearchTablesResult, TOOL_DISPLAY_NAMES } from './parsers.js'

const props = defineProps({
  toolName: { type: String, required: true },
  args: { type: Object, default: () => ({}) },
  result: { type: String, default: '' },
  stepNumber: { type: Number, default: 0 },
  isPending: { type: Boolean, default: false }
})

const displayName = computed(
  () => TOOL_DISPLAY_NAMES[props.toolName] || 'Search tables'
)

const query = computed(() => props.args?.query || '')

const parsed = computed(() => parseSearchTablesResult(props.result))
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

.tool-card__sub {
  color: var(--text-muted);
  font-style: italic;
}

.tool-card__status {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 11px;
}

.tool-card__status--pending {
  color: var(--color-primary);
}

.tool-card__body {
  margin-top: var(--space-xs);
  padding-left: 28px;
}

.tool-card__empty {
  color: var(--text-muted);
  font-style: italic;
}

.tool-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
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

.light-theme .tool-card {
  background: rgba(0, 0, 0, 0.03);
}
</style>

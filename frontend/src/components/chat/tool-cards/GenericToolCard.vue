<template>
  <div class="tool-card">
    <div class="tool-card__header">
      <span class="tool-card__step">[{{ stepNumber }}]</span>
      <Cog
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
        v-else-if="resultPreview"
        class="tool-card__status"
        :title="result"
      >
        {{ resultPreview }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Cog } from 'lucide-vue-next'
import { TOOL_DISPLAY_NAMES } from './parsers.js'

const props = defineProps({
  toolName: { type: String, required: true },
  args: { type: Object, default: () => ({}) },
  result: { type: String, default: '' },
  stepNumber: { type: Number, default: 0 },
  isPending: { type: Boolean, default: false }
})

const displayName = computed(() => {
  if (TOOL_DISPLAY_NAMES[props.toolName]) return TOOL_DISPLAY_NAMES[props.toolName]
  // Humanize an unknown tool name: snake_case → Title Case
  return (
    props.toolName?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) ||
    'Tool'
  )
})

const resultPreview = computed(() => {
  if (!props.result) return ''
  // Truncate so the timeline doesn't unbalance on a multi-KB payload.
  const trimmed = props.result.trim().replace(/\s+/g, ' ')
  return trimmed.length > 80 ? trimmed.slice(0, 80) + '…' : trimmed
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

.tool-card__status {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 11px;
  font-family: var(--font-mono, monospace);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 50%;
}

.tool-card__status--pending {
  color: var(--color-primary);
}

.light-theme .tool-card {
  background: rgba(0, 0, 0, 0.03);
}
</style>

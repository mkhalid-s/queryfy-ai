<template>
  <div class="tool-card">
    <div class="tool-card__header">
      <span class="tool-card__step">[{{ stepNumber }}]</span>
      <BookOpen
        :size="14"
        class="tool-card__icon"
      />
      <span class="tool-card__title">Business term</span>
      <span
        v-if="termTag"
        class="tool-card__tag"
      >
        {{ termTag }}
      </span>
      <span
        v-if="isPending"
        class="tool-card__status tool-card__status--pending"
      >
        looking up...
      </span>
      <span
        v-else-if="parsed && !parsed.found"
        class="tool-card__status tool-card__status--muted"
      >
        not in dictionary
      </span>
    </div>

    <div
      v-if="!isPending && parsed && parsed.found && parsed.definition"
      class="tool-card__definition"
    >
      {{ parsed.definition }}
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { BookOpen } from 'lucide-vue-next'
import { parseBusinessTermResult } from './parsers.js'

const props = defineProps({
  toolName: { type: String, required: true },
  args: { type: Object, default: () => ({}) },
  result: { type: String, default: '' },
  stepNumber: { type: Number, default: 0 },
  isPending: { type: Boolean, default: false }
})

const parsed = computed(() => parseBusinessTermResult(props.result))

const termTag = computed(() => {
  // Prefer the parsed term when present (canonicalised by the backend);
  // fall back to the LLM-supplied arg.
  if (parsed.value?.found && parsed.value.term) return parsed.value.term
  return props.args?.term || ''
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

.tool-card__tag {
  display: inline-flex;
  align-items: center;
  padding: 2px var(--space-xs);
  background: var(--color-primary-light);
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  font-weight: 500;
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

.tool-card__definition {
  margin-top: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  padding-left: 28px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.5;
}

.light-theme .tool-card {
  background: rgba(0, 0, 0, 0.03);
}
</style>

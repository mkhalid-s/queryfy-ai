<template>
  <div
    v-if="suggestions.length"
    class="followup-suggestions"
  >
    <div class="suggestions-header">
      <Lightbulb class="header-icon" />
      <h4 class="header-title">
        Suggested Next Steps
      </h4>
    </div>

    <div class="suggestions-list">
      <button
        v-for="(suggestion, index) in suggestions"
        :key="index"
        class="suggestion-button"
        :class="`priority-${suggestion.priority}`"
        @click="handleSuggestionClick(suggestion)"
      >
        <div class="suggestion-content">
          <div class="suggestion-question">
            {{ suggestion.question }}
          </div>
          <div class="suggestion-rationale">
            {{ suggestion.rationale }}
          </div>
        </div>

        <div class="suggestion-meta">
          <span class="category-badge">{{ formatCategory(suggestion.category) }}</span>
          <ArrowRight class="action-icon" />
        </div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { Lightbulb, ArrowRight } from 'lucide-vue-next'

defineProps({
  suggestions: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['ask-question'])

function handleSuggestionClick(suggestion) {
  emit('ask-question', suggestion.question)
}

function formatCategory(category) {
  const labels = {
    drill_down: 'Drill Down',
    comparison: 'Compare',
    investigation: 'Investigate',
  }
  return labels[category] || category
}
</script>

<style scoped>
.followup-suggestions {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  margin-top: var(--space-md);
  border: 1px solid rgba(30, 183, 223, 0.2);
}

.suggestions-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
}

.header-icon {
  width: 20px;
  height: 20px;
  color: var(--color-info);
}

.header-title {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.suggestions-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.suggestion-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-input);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
  width: 100%;
}

.suggestion-button:hover {
  background: var(--bg-hover);
  border-color: var(--color-primary);
  transform: translateX(4px);
}

.suggestion-button.priority-high {
  border-left: 3px solid var(--color-success);
}

.suggestion-button.priority-medium {
  border-left: 3px solid var(--color-info);
}

.suggestion-button.priority-low {
  border-left: 3px solid var(--color-warning);
}

.suggestion-content {
  flex: 1;
}

.suggestion-question {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: var(--space-xs);
}

.suggestion-rationale {
  font-size: 0.8125rem;
  color: var(--text-muted);
  line-height: 1.4;
}

.suggestion-meta {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.category-badge {
  font-size: 0.75rem;
  color: var(--text-muted);
  padding: var(--space-xs) var(--space-sm);
  background: rgba(0, 115, 157, 0.1);
  border-radius: var(--radius-sm);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.action-icon {
  width: 16px;
  height: 16px;
  color: var(--color-primary);
  opacity: 0.6;
  transition: opacity 0.2s ease;
}

.suggestion-button:hover .action-icon {
  opacity: 1;
}
</style>

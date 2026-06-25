<template>
  <div class="suggestions-panel">
    <!-- Horizontal scrollable suggestions -->
    <div class="suggestions-scroll">
      <button
        v-for="(suggestion, index) in quickSuggestions"
        :key="`suggestion-${index}-${suggestion.text}`"
        class="suggestion-pill"
        @click="$emit('select', { type: 'suggestion', text: suggestion.text })"
      >
        <component
          :is="getIcon(suggestion.icon)"
          :size="14"
          class="pill-icon"
        />
        <span>{{ suggestion.label || truncateText(suggestion.text) }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  TrendingUp,
  Users,
  Package,
  Calendar,
  Table,
  Calculator,
  Database,
  FileText,
  Search
} from 'lucide-vue-next'

const props = defineProps({
  suggestions: {
    type: Array,
    default: () => []
  }
})

defineEmits(['select'])

// Icon mapping for dynamic icons
const iconMap = {
  TrendingUp,
  Users,
  Package,
  Calendar,
  Table,
  Calculator,
  Database,
  FileText,
  Search
}

// Get icon component from string name or return default
const getIcon = (icon) => {
  if (!icon) return Database
  if (typeof icon === 'string') return iconMap[icon] || Database
  return icon
}

// Truncate long text for display
const truncateText = (text, maxLength = 30) => {
  if (!text || text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

// Default quick suggestions (generic — works with any database)
const defaultSuggestions = [
  { text: 'Show all tables in the database', label: 'List tables', icon: 'Database' },
  { text: 'Describe the database schema', label: 'Schema info', icon: 'FileText' },
  { text: 'Show the most recent records', label: 'Recent data', icon: 'Calendar' },
  { text: 'What data is available?', label: 'Explore', icon: 'Search' }
]

// Use provided suggestions or fallback to defaults
const quickSuggestions = computed(() => {
  if (props.suggestions?.length) {
    return props.suggestions.filter(s => s && (s.text || s.label))
  }
  return defaultSuggestions
})
</script>

<style scoped>
.suggestions-panel {
  flex-shrink: 0;
  padding: var(--space-sm) 0;
  padding-bottom: var(--space-md);
  max-width: 760px;
  margin: 0 auto;
}

/* Wrap layout for suggestion pills */
.suggestions-scroll {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  padding: var(--space-xs) 0;
}

/* Suggestion pills */
.suggestion-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.suggestion-pill:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  color: var(--text-primary);
}

.suggestion-pill:active {
  transform: scale(0.98);
}

.pill-icon {
  color: var(--text-muted);
  flex-shrink: 0;
  transition: color 0.15s;
}

.suggestion-pill:hover .pill-icon {
  color: var(--color-primary);
}

/* Theme transition */
.suggestion-pill {
  transition: background var(--transition-normal, 0.2s),
              border-color var(--transition-normal, 0.2s),
              color var(--transition-normal, 0.2s);
}

/* Mobile - slightly smaller pills */
@media (max-width: 640px) {
  .suggestions-panel {
    padding: var(--space-sm);
    padding-bottom: var(--space-md);
  }

  .suggestion-pill {
    padding: 8px 12px;
    font-size: var(--text-xs);
  }
}
</style>

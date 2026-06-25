<template>
  <div
    class="insight-card"
    :class="`severity-${safeSeverity}`"
  >
    <div class="insight-header">
      <div
        class="severity-badge"
        :class="`severity-${safeSeverity}`"
      >
        <component
          :is="severityIcon"
          class="icon"
        />
        <span class="severity-text">{{ severityLabel }}</span>
      </div>
      <span class="insight-type">{{ insightTypeLabel }}</span>
    </div>

    <div class="insight-content">
      <h4 class="insight-title">
        {{ safeTitle }}
      </h4>
      <p class="insight-description">
        {{ safeDescription }}
      </p>

      <!-- Metrics -->
      <div
        v-if="hasMetrics"
        class="insight-metrics"
      >
        <div
          v-for="(value, key) in displayMetrics"
          :key="key"
          class="metric-item"
        >
          <span class="metric-label">{{ formatMetricLabel(key) }}:</span>
          <span class="metric-value">{{ formatMetricValue(value) }}</span>
        </div>
      </div>

      <!-- Recommendations -->
      <div
        v-if="insight.recommendations?.length"
        class="insight-recommendations"
      >
        <h5 class="recommendations-title">
          Recommended Actions:
        </h5>
        <ul class="recommendations-list">
          <li
            v-for="(rec, index) in insight.recommendations"
            :key="index"
            class="recommendation-item"
          >
            {{ rec }}
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { AlertCircle, AlertTriangle, Info } from 'lucide-vue-next'

const props = defineProps({
  insight: {
    type: Object,
    required: true,
  },
})

// Phase 2 Day 6: defensive defaults for every optional field on an insight.
// The backend's four detectors are all expected to populate severity/
// title/description, but a malformed payload or a new detector that
// forgets one of these fields previously crashed the card (calling
// .toUpperCase() on undefined) or rendered a visibly-broken shell.
const safeSeverity = computed(() => props.insight.severity || 'info')
const safeTitle = computed(() => props.insight.title || 'Insight')
const safeDescription = computed(
  () => props.insight.description || 'No description available.'
)

const severityIcon = computed(() => {
  switch (safeSeverity.value) {
    case 'high':
      return AlertCircle
    case 'medium':
      return AlertTriangle
    default:
      return Info
  }
})

const severityLabel = computed(() => safeSeverity.value.toUpperCase())

const insightTypeLabel = computed(() => {
  const types = {
    concentration: 'Concentration Risk',
    trend: 'Trend Analysis',
    anomaly: 'Anomaly Detected',
    comparison: 'Segment Comparison',
    business_insight: 'Business Insight',
    basic_stats: 'Summary',
    info: 'Note',
    warning: 'Note',
  }
  const t = props.insight.type
  return types[t] || t || 'Insight'
})

const hasMetrics = computed(() => {
  return props.insight.metrics && Object.keys(props.insight.metrics).length > 0
})

const displayMetrics = computed(() => {
  if (!props.insight.metrics) return {}

  // Exclude nested objects, only show simple metrics
  const metrics = {}
  for (const [key, value] of Object.entries(props.insight.metrics)) {
    if (typeof value !== 'object' || value === null) {
      metrics[key] = value
    }
  }
  return metrics
})

function formatMetricLabel(key) {
  // Convert snake_case to Title Case
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function formatMetricValue(value) {
  if (typeof value === 'number') {
    // Format numbers with appropriate precision
    if (Number.isInteger(value)) {
      return value.toLocaleString()
    }
    return value.toLocaleString(undefined, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 2
    })
  }
  return value
}
</script>

<style scoped>
.insight-card {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  margin-bottom: var(--space-md);
  border-left: 4px solid var(--color-info);
  transition: all 0.2s ease;
}

.insight-card:hover {
  background: var(--bg-hover);
}

.insight-card.severity-high {
  border-left-color: var(--color-error);
}

.insight-card.severity-medium {
  border-left-color: var(--color-warning);
}

.insight-card.severity-low {
  border-left-color: var(--color-info);
}

.insight-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-sm);
}

.severity-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.severity-badge.severity-high {
  background: var(--color-error-light);
  color: var(--color-error);
}

.severity-badge.severity-medium {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.severity-badge.severity-low {
  background: var(--color-info-light);
  color: var(--color-info);
}

.severity-badge .icon {
  width: 14px;
  height: 14px;
}

.insight-type {
  font-size: 0.875rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.insight-content {
  margin-top: var(--space-sm);
}

.insight-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-xs) 0;
}

.insight-description {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 var(--space-md) 0;
}

.insight-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-sm);
  padding: var(--space-sm);
  background: var(--bg-input);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-md);
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.metric-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-value {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}

.insight-recommendations {
  margin-top: var(--space-md);
}

.recommendations-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-sm) 0;
}

.recommendations-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.recommendation-item {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  padding: var(--space-xs) 0;
  padding-left: var(--space-md);
  position: relative;
}

.recommendation-item::before {
  content: '•';
  position: absolute;
  left: var(--space-xs);
  color: var(--color-primary);
  font-weight: bold;
}
</style>

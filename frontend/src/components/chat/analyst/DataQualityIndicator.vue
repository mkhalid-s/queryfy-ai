<template>
  <div class="data-quality-indicator">
    <div class="quality-header">
      <div
        class="quality-score"
        :class="scoreClass"
      >
        <Shield class="score-icon" />
        <span class="score-value">{{ quality.overall_score }}/100</span>
      </div>
      <span class="quality-label">Data Quality</span>
    </div>

    <!-- Expandable Details -->
    <button
      v-if="hasDetails"
      class="toggle-details"
      @click="showDetails = !showDetails"
    >
      <span>{{ showDetails ? 'Hide Details' : 'Show Details' }}</span>
      <ChevronDown
        class="toggle-icon"
        :class="{ rotated: showDetails }"
      />
    </button>

    <!-- Details Section -->
    <div
      v-if="showDetails"
      class="quality-details"
    >
      <!-- Completeness -->
      <div class="detail-item">
        <div class="detail-label">
          Completeness
        </div>
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: `${quality.completeness}%` }"
          />
        </div>
        <div class="detail-value">
          {{ quality.completeness?.toFixed(1) }}%
        </div>
      </div>

      <!-- Issues -->
      <div
        v-if="quality.issues?.length"
        class="issues-section"
      >
        <div class="issues-title">
          Issues Found ({{ quality.issues.length }})
        </div>
        <ul class="issues-list">
          <li
            v-for="(issue, index) in quality.issues"
            :key="index"
            class="issue-item"
            :class="`severity-${issue.severity}`"
          >
            <AlertCircle class="issue-icon" />
            <span>{{ issue.description }}</span>
          </li>
        </ul>
      </div>

      <!-- Additional Metrics -->
      <div class="metrics-grid">
        <div
          v-if="quality.duplicate_count !== undefined"
          class="metric"
        >
          <span class="metric-label">Duplicates</span>
          <span class="metric-value">{{ quality.duplicate_count }}</span>
        </div>
        <div
          v-if="quality.outlier_count !== undefined"
          class="metric"
        >
          <span class="metric-label">Outliers</span>
          <span class="metric-value">{{ quality.outlier_count }}</span>
        </div>
        <div
          v-if="quality.row_count !== undefined"
          class="metric"
        >
          <span class="metric-label">Rows</span>
          <span class="metric-value">{{ quality.row_count?.toLocaleString() }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Shield, ChevronDown, AlertCircle } from 'lucide-vue-next'

const props = defineProps({
  quality: {
    type: Object,
    required: true,
  },
})

const showDetails = ref(false)

const scoreClass = computed(() => {
  const score = props.quality.overall_score
  if (score >= 90) return 'excellent'
  if (score >= 75) return 'good'
  if (score >= 50) return 'fair'
  return 'poor'
})

const hasDetails = computed(() => {
  return (
    props.quality.completeness !== undefined ||
    props.quality.issues?.length > 0 ||
    props.quality.duplicate_count !== undefined ||
    props.quality.outlier_count !== undefined
  )
})
</script>

<style scoped>
.data-quality-indicator {
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.quality-header {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}

.quality-score {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  font-weight: 600;
}

.quality-score.excellent {
  background: var(--color-success-light);
  color: var(--color-success);
}

.quality-score.good {
  background: var(--color-info-light);
  color: var(--color-info);
}

.quality-score.fair {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.quality-score.poor {
  background: var(--color-error-light);
  color: var(--color-error);
}

.score-icon {
  width: 16px;
  height: 16px;
}

.score-value {
  font-size: 0.875rem;
}

.quality-label {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.toggle-details {
  background: none;
  border: none;
  color: var(--color-primary);
  font-size: 0.8125rem;
  padding: var(--space-xs) 0;
  margin-top: var(--space-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  transition: color 0.2s ease;
}

.toggle-details:hover {
  color: var(--color-primary-hover);
}

.toggle-icon {
  width: 14px;
  height: 14px;
  transition: transform 0.2s ease;
}

.toggle-icon.rotated {
  transform: rotate(180deg);
}

.quality-details {
  margin-top: var(--space-md);
  padding-top: var(--space-md);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.detail-item {
  margin-bottom: var(--space-md);
}

.detail-label {
  font-size: 0.8125rem;
  color: var(--text-muted);
  margin-bottom: var(--space-xs);
}

.progress-bar {
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-sm);
  overflow: hidden;
  margin-bottom: var(--space-xs);
}

.progress-fill {
  height: 100%;
  background: var(--color-success);
  transition: width 0.3s ease;
}

.detail-value {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.issues-section {
  margin-top: var(--space-md);
}

.issues-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-sm);
}

.issues-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.issue-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  padding: var(--space-xs) 0;
  font-size: 0.8125rem;
  line-height: 1.4;
}

.issue-item.severity-high {
  color: var(--color-error);
}

.issue-item.severity-medium {
  color: var(--color-warning);
}

.issue-item.severity-low {
  color: var(--text-secondary);
}

.issue-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  margin-top: 2px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: var(--space-md);
  margin-top: var(--space-md);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  padding: var(--space-sm);
  background: var(--bg-input);
  border-radius: var(--radius-sm);
}

.metric-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-value {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
}
</style>

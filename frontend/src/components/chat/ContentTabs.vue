<template>
  <div class="content-tabs">
    <!-- Tab buttons -->
    <div class="tab-bar">
      <button
        v-for="tab in availableTabs"
        :key="tab.id"
        :class="['tab-btn', { active: activeTab === tab.id }]"
        @click="activeTab = tab.id"
      >
        <component
          :is="tab.icon"
          :size="14"
        />
        <span>{{ tab.label }}</span>
        <span
          v-if="tab.badge"
          class="tab-badge"
        >{{ tab.badge }}</span>
      </button>

      <!-- Right-side actions -->
      <div class="tab-actions">
        <button
          v-if="activeTab === 'sql'"
          class="action-btn-sm"
          :title="copied ? 'Copied!' : 'Copy SQL'"
          @click="$emit('copy')"
        >
          <Check
            v-if="copied"
            :size="14"
            class="success"
          />
          <Copy
            v-else
            :size="14"
          />
        </button>
        <button
          v-if="activeTab === 'data' && hasData"
          class="action-btn-sm"
          title="Fullscreen"
          @click="$emit('fullscreen')"
        >
          <Maximize2 :size="14" />
        </button>
      </div>
    </div>

    <!-- Tab content -->
    <div class="tab-content">
      <!-- SQL Tab -->
      <div
        v-show="activeTab === 'sql'"
        class="sql-panel"
      >
        <pre class="sql-code"><code v-html="highlightedSql" /></pre>
      </div>

      <!-- Data Tab -->
      <div
        v-show="activeTab === 'data'"
        class="data-panel"
      >
        <div
          v-if="!hasData"
          class="empty-state"
        >
          <PlayCircle :size="24" />
          <p>Run the query to see results</p>
        </div>
        <ResultsExpander
          v-else
          :results="results"
          :is-latest="true"
          :session-id="sessionId"
          :dml-capabilities="dmlCapabilities"
          :sql="sql"
        />
      </div>

      <!-- Chart Tab - use v-if to prevent ECharts dimension issues when hidden -->
      <div
        v-if="activeTab === 'chart'"
        class="chart-panel"
      >
        <div
          v-if="!hasChart"
          class="empty-state"
        >
          <BarChart3 :size="24" />
          <p>{{ hasData ? 'Chart not available for this data' : 'Run query first' }}</p>
        </div>
        <ChartView
          v-else
          :results="results"
          :chart="chartSpec || undefined"
          :theme="isDark ? 'dark' : 'light'"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject, defineAsyncComponent } from 'vue'
import {
  Code2,
  Table2,
  BarChart3,
  Copy,
  Check,
  Maximize2,
  PlayCircle
} from 'lucide-vue-next'
import ResultsExpander from '../results/ResultsExpander.vue'
import DOMPurify from 'dompurify'

// Lazy load ChartView
const ChartView = defineAsyncComponent(() => import('../ChartView.vue'))

const props = defineProps({
  sql: {
    type: String,
    default: ''
  },
  results: {
    type: Object,
    default: null
  },
  chartSpec: {
    type: Object,
    default: null
  },
  sessionId: {
    type: String,
    default: null
  },
  dmlCapabilities: {
    type: Object,
    default: null
  }
})

defineEmits(['copy', 'fullscreen'])

const isDark = inject('isDark', ref(true))
const activeTab = ref('sql')
const copied = ref(false)

// Computed
const hasData = computed(() => {
  return props.results?.rows?.length > 0
})

const hasChart = computed(() => {
  return hasData.value
})

// No need for chartData transformation - pass results directly to ChartView
// ChartView handles client-side analysis if no chart spec is provided

const availableTabs = computed(() => {
  const tabs = [
    { id: 'sql', label: 'SQL', icon: Code2 }
  ]

  tabs.push({
    id: 'data',
    label: 'Data',
    icon: Table2,
    badge: hasData.value ? props.results.row_count : null
  })

  if (hasChart.value) {
    tabs.push({
      id: 'chart',
      label: 'Chart',
      icon: BarChart3
    })
  }

  return tabs
})

// SQL highlighting
const SQL_KEYWORDS = [
  'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN',
  'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS', 'ON',
  'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'DISTINCT',
  'AS', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'NULL', 'IS',
  'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'COALESCE', 'CAST',
  'UNION', 'ALL', 'EXISTS', 'ANY', 'ASC', 'DESC', 'WITH', 'OVER', 'PARTITION'
]

const highlightedSql = computed(() => {
  if (!props.sql) return ''

  let highlighted = props.sql
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Strings
  highlighted = highlighted.replace(
    /('[^']*'|"[^"]*")/g,
    '<span class="sql-string">$1</span>'
  )

  // Numbers
  highlighted = highlighted.replace(
    /\b(\d+\.?\d*)\b/g,
    '<span class="sql-number">$1</span>'
  )

  // Keywords
  SQL_KEYWORDS.forEach(keyword => {
    const regex = new RegExp(`\\b(${keyword})\\b`, 'gi')
    highlighted = highlighted.replace(regex, '<span class="sql-keyword">$1</span>')
  })

  // Comments
  highlighted = highlighted.replace(
    /(--[^\n]*)/g,
    '<span class="sql-comment">$1</span>'
  )

  return DOMPurify.sanitize(highlighted)
})
</script>

<style scoped>
.content-tabs {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-card);
}

/* Tab bar */
.tab-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid var(--border-subtle);
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.05);
}

.tab-btn.active {
  color: var(--text-primary);
  background: var(--bg-card);
}

.tab-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  color: white;
  font-weight: 600;
}

.tab-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding-right: 4px;
}

.action-btn-sm {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-btn-sm:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

.action-btn-sm .success {
  color: var(--color-success);
}

/* Tab content */
.tab-content {
  min-height: 100px;
  max-height: 350px;
  overflow: auto;
}

/* SQL Panel */
.sql-panel {
  padding: var(--space-md);
}

.sql-code {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
}

.sql-code :deep(.sql-keyword) {
  color: var(--code-keyword);
  font-weight: 600;
}

.sql-code :deep(.sql-string) {
  color: var(--code-string);
}

.sql-code :deep(.sql-number) {
  color: var(--code-number);
}

.sql-code :deep(.sql-comment) {
  color: var(--text-muted);
  font-style: italic;
}

/* Data Panel */
.data-panel {
  padding: var(--space-sm);
}

/* Chart Panel */
.chart-panel {
  padding: var(--space-md);
  min-height: 250px;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-xl);
  color: var(--text-muted);
  gap: var(--space-sm);
}

.empty-state p {
  margin: 0;
  font-size: var(--text-sm);
}
</style>

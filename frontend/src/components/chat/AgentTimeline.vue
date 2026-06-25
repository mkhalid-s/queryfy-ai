<template>
  <div class="agent-timeline">
    <!-- Collapsible header -->
    <button
      class="timeline-header"
      @click="isExpanded = !isExpanded"
    >
      <div class="header-left">
        <Terminal :size="14" />
        <span class="header-title">Agent Activity</span>
        <span class="step-count">({{ steps.length }} steps)</span>
      </div>
      <div class="header-right">
        <span
          v-if="totalDuration"
          class="duration"
        >
          {{ formatDuration(totalDuration) }}
        </span>
        <ChevronDown
          :size="16"
          :class="['chevron', { rotated: isExpanded }]"
        />
      </div>
    </button>

    <!-- Expanded content. Typed cards by default (A9, Reviewer D move B);
         legacy CLI fallback when ``useTypedCards=false`` for the
         operator-style monospaced view some users prefer. -->
    <transition name="expand">
      <div
        v-if="isExpanded"
        class="timeline-content"
      >
        <!-- Typed tool cards (default) -->
        <div
          v-if="useTypedCards"
          class="typed-cards"
        >
          <ToolCard
            v-for="card in typedCards"
            :key="`${card.stepNumber}-${card.toolName}`"
            :tool-name="card.toolName"
            :args="card.args"
            :result="card.result"
            :step-number="card.stepNumber"
            :is-pending="card.isPending"
          />
          <div
            v-if="isComplete"
            class="cli-line complete"
          >
            <div class="step-line">
              <span class="step-number">[✓]</span>
              <span class="step-description complete-text">Complete</span>
            </div>
          </div>
        </div>

        <!-- Legacy CLI view (kept for operator-style preference) -->
        <div
          v-else
          class="cli-output"
        >
          <div
            v-for="(step, index) in displaySteps"
            :key="index"
            :class="['cli-line', step.type]"
          >
            <div class="step-line">
              <span class="step-number">[{{ step.stepNumber }}]</span>
              <span class="step-description">{{ step.description }}</span>
            </div>
            <div
              v-if="step.result"
              class="result-line"
            >
              <span class="result-arrow">→</span>
              <span class="result-text">{{ step.result }}</span>
            </div>
          </div>

          <div
            v-if="isComplete"
            class="cli-line complete"
          >
            <div class="step-line">
              <span class="step-number">[✓]</span>
              <span class="step-description complete-text">Complete</span>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ChevronDown, Terminal } from 'lucide-vue-next'
import ToolCard from './tool-cards/ToolCard.vue'

const props = defineProps({
  steps: {
    type: Array,
    default: () => []
  },
  defaultExpanded: {
    type: Boolean,
    default: true  // Default to expanded for CLI view
  },
  isComplete: {
    type: Boolean,
    default: false
  },
  // A9: typed tool cards on by default. Set to false to keep the
  // legacy CLI step list (operator-style monospaced view).
  useTypedCards: {
    type: Boolean,
    default: true
  }
})

const isExpanded = ref(props.defaultExpanded)

// Tool name to human-readable description
const getToolDescription = (toolName, args = {}) => {
  const descriptions = {
    search_tables: () => `Searching for tables matching '${args.query || 'data'}'`,
    get_table_schema: () => `Getting schema for ${args.table_name || 'table'}`,
    lookup_business_term: () => `Looking up term '${args.term || 'term'}'`,
    find_similar_queries: () => `Finding similar query patterns`,
    get_sample_data: () => `Getting sample data from ${args.table_name || 'table'}`,
    execute_sql: () => `Executing query`,  // Generic for SQL/MQL/CQL/PartiQL
  }

  const formatter = descriptions[toolName]
  if (formatter) return formatter()
  return toolName?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Processing'
}

// Format tool result as brief summary
const getResultSummary = (step) => {
  // Use backend-provided summary if available
  if (step.summary) return step.summary

  const content = step.content || ''
  const toolName = step.tool || step.tool_name

  if (toolName === 'search_tables') {
    if (content.includes('Tables matching')) {
      const match = content.match(/- ([^\n]+)/g)
      if (match) {
        const tables = match.slice(0, 3).map(t => t.replace('- ', '').trim())
        return `Found: ${tables.join(', ')}${match.length > 3 ? '...' : ''}`
      }
    }
    return 'No tables found'
  }

  if (toolName === 'get_table_schema') {
    if (content.includes('Columns:')) {
      const colMatch = content.match(/- \w+/g)
      return colMatch ? `${colMatch.length} columns found` : 'Schema retrieved'
    }
    return 'Schema retrieved'
  }

  if (toolName === 'execute_sql') {
    try {
      const result = JSON.parse(content)
      const count = result.row_count || 0
      // Generic terminology: "documents" for NoSQL, "rows" for SQL (use generic "results")
      return `${count} ${count === 1 ? 'result' : 'results'} returned`
    } catch {
      const match = content.match(/(?:Rows|Documents|Results) returned: (\d+)/)
      if (match) return `${match[1]} results returned`
      return 'Query executed'
    }
  }

  if (toolName === 'get_sample_data') {
    if (content.includes('Sample data from')) return 'Sample data retrieved'
    if (content.includes('No data found')) return 'Table is empty'
    return 'Checked table'
  }

  if (toolName === 'find_similar_queries') {
    if (content.includes('Similar queries found')) return 'Found similar patterns'
    return 'No similar queries'
  }

  // Default: truncate content
  if (content.length > 60) return content.substring(0, 60) + '...'
  return content || 'Completed'
}

// Transform raw steps into CLI display format
const displaySteps = computed(() => {
  let stepNumber = 0
  const result = []

  for (const step of props.steps) {
    // Handle tool_call events
    if (step.type === 'tool_call') {
      stepNumber++
      result.push({
        type: 'tool_call',
        stepNumber: step.step_number || stepNumber,
        description: step.description || getToolDescription(step.tool_name || step.tool, step.tool_args || step.args),
        result: null,
        toolName: step.tool_name || step.tool
      })
    }
    // Handle tool_result events - attach to last tool_call
    else if (step.type === 'tool_result') {
      const summary = step.summary || getResultSummary(step)
      // Find the matching tool_call and add result
      const lastToolCall = result.findLast(s => s.type === 'tool_call' && !s.result)
      if (lastToolCall) {
        lastToolCall.result = summary
      } else {
        // Orphan result - create standalone entry
        result.push({
          type: 'tool_result',
          stepNumber: stepNumber || result.length + 1,
          description: step.tool_name || step.tool || 'Result',
          result: summary
        })
      }
    }
    // Handle executed event
    else if (step.type === 'executed') {
      const lastEntry = result[result.length - 1]
      if (lastEntry && lastEntry.toolName === 'execute_sql' && !lastEntry.result) {
        lastEntry.result = step.content || `${step.row_count || 0} rows returned`
      } else {
        // Add as standalone step if no matching execute_sql found
        stepNumber++
        result.push({
          type: 'executed',
          stepNumber,
          description: 'Query executed',
          result: step.content || `${step.row_count || 0} rows returned`
        })
      }
    }
    // Handle sql_generated event (works for SQL/MQL/CQL/PartiQL)
    else if (step.type === 'sql_generated' || step.type === 'sql') {
      // Add as a step for visibility (generic wording for all query languages)
      stepNumber++
      result.push({
        type: 'sql',
        stepNumber,
        description: 'Query generated',
        result: step.content || 'Ready to execute'
      })
    }
    // Handle executing event
    else if (step.type === 'executing') {
      stepNumber++
      result.push({
        type: 'executing',
        stepNumber,
        description: 'Executing query',
        result: step.content || 'Running...'
      })
    }
    // Handle thinking (skip for cleaner output, or show briefly)
    else if (step.type === 'thinking') {
      // Optional: Add thinking as a step
      // stepNumber++
      // result.push({
      //   type: 'thinking',
      //   stepNumber,
      //   description: 'Analyzing...',
      //   result: step.content?.substring(0, 80)
      // })
    }
  }

  return result
})

// A9: Pair each tool_call with its tool_result and emit per-card
// props so <ToolCard> can render the typed UI. Anything that isn't
// a tool_call (sql_generated, executing, thinking) is dropped from
// the typed view — those events have their own surfaces elsewhere
// (the ContentTabs SQL view, the streaming-status indicator).
const typedCards = computed(() => {
  const cards = []
  let stepNumber = 0
  for (const step of props.steps) {
    if (step.type === 'tool_call') {
      stepNumber++
      cards.push({
        toolName: step.tool_name || step.tool || '',
        args: step.tool_args || step.args || {},
        result: '',
        stepNumber: step.step_number || stepNumber,
        isPending: true
      })
    } else if (step.type === 'tool_result') {
      // Find the last pending tool_call and attach this result.
      const lastPending = cards.findLast((c) => c.isPending)
      if (lastPending) {
        lastPending.result = step.content || ''
        lastPending.isPending = false
      } else {
        // Orphan result — render with no preceding call. Rare; ride
        // the GenericToolCard path so the timeline doesn't have a hole.
        stepNumber++
        cards.push({
          toolName: step.tool_name || step.tool || 'result',
          args: {},
          result: step.content || '',
          stepNumber,
          isPending: false
        })
      }
    }
  }
  return cards
})

// Calculate total duration
const totalDuration = computed(() => {
  if (props.steps.length < 2) return null
  const first = props.steps[0]?.timestamp
  const last = props.steps[props.steps.length - 1]?.timestamp
  if (!first || !last) return null
  return last - first
})

const formatDuration = (ms) => {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<style scoped>
.agent-timeline {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  overflow: hidden;
  font-family: var(--font-mono, 'SF Mono', 'Monaco', 'Consolas', monospace);
}

/* Header */
.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all 0.15s ease;
}

.timeline-header:hover {
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-primary);
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.header-title {
  font-weight: 500;
  font-family: var(--font-sans);
}

.step-count {
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.duration {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.chevron {
  transition: transform 0.2s ease;
}

.chevron.rotated {
  transform: rotate(180deg);
}

/* CLI Output */
.timeline-content {
  padding: 0 var(--space-md) var(--space-md);
}

.cli-output {
  background: rgba(0, 0, 0, 0.2);
  border-radius: var(--radius-sm);
  padding: var(--space-sm) var(--space-md);
  font-size: 12px;
  line-height: 1.6;
}

/* Typed-cards view (A9) — denser, structured per-tool render */
.typed-cards {
  padding: var(--space-xs) var(--space-sm);
  display: flex;
  flex-direction: column;
  gap: 0;
}

.typed-cards .cli-line.complete {
  margin-top: var(--space-xs);
}

.cli-line {
  margin-bottom: var(--space-xs);
}

.cli-line:last-child {
  margin-bottom: 0;
}

.step-line {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
}

.step-number {
  color: var(--color-primary);
  font-weight: 600;
  min-width: 24px;
}

.step-description {
  color: var(--text-primary);
}

.result-line {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  padding-left: 28px;
  margin-top: 2px;
}

.result-arrow {
  color: var(--color-success);
  font-weight: 600;
}

.result-text {
  color: var(--text-muted);
}

/* Complete state */
.cli-line.complete .step-number {
  color: var(--color-success);
}

.complete-text {
  color: var(--color-success);
  font-weight: 500;
}

/* Separator line */
.cli-output::after {
  content: '';
  display: block;
  height: 1px;
  background: var(--border-subtle);
  margin-top: var(--space-sm);
  opacity: 0;
}

/* Transitions */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

/* Light theme adjustments */
.light-theme .cli-output {
  background: rgba(0, 0, 0, 0.05);
}
</style>

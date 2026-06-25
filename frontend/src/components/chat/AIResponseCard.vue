<template>
  <div :class="['ai-response-card', { 'generating': isGenerating }]">
    <!-- Minimal Header -->
    <div class="card-header">
      <div class="header-left">
        <div class="ai-avatar">
          <Sparkles
            v-if="isAnalystMode"
            :size="14"
          />
          <Bot
            v-else
            :size="14"
          />
        </div>
        <span class="ai-name">{{ isAnalystMode ? 'Analyst' : 'QueryfyAI' }}</span>
        <span
          v-if="isFollowUp"
          class="follow-up-dot"
          title="Follow-up query"
        />
      </div>
      <div class="header-right">
        <span class="message-time">{{ formatTime(message.timestamp) }}</span>
      </div>
    </div>

    <!-- Thinking/Loading State (Modern ChatGPT style) -->
    <div
      v-if="isGenerating"
      class="thinking-state"
    >
      <div class="thinking-indicator">
        <span class="thinking-dot" />
        <span class="thinking-dot" />
        <span class="thinking-dot" />
      </div>
      <span class="thinking-text">{{ thinkingText }}</span>
    </div>

    <!-- Main Content -->
    <div
      v-if="!isGenerating || answer || sql"
      class="card-content"
    >
      <!-- Analyst Answer -->
      <div
        v-if="isAnalystMode && answer"
        class="answer-section"
      >
        <div
          class="answer-text"
          v-html="formatExplanation(answer)"
        />

        <!-- Key Findings (compact) -->
        <div
          v-if="keyFindings.length > 0"
          class="key-findings"
        >
          <div
            v-for="(finding, i) in keyFindings"
            :key="i"
            class="finding-item"
          >
            <span class="finding-num">{{ i + 1 }}</span>
            <span>{{ finding }}</span>
          </div>
        </div>

        <!-- Data Quality Indicator -->
        <DataQualityIndicator
          v-if="dataQuality"
          :quality="dataQuality"
          class="quality-section"
        />

        <!-- Sampling notice as its own banner, not a polluting card
             inside the insights list. Renders above the insights
             section when backend flagged sampling. -->
        <div
          v-if="isAnalystMode && samplingUsed && samplingUsed.used"
          class="sampling-notice"
          :class="{ 'sampling-notice--warning': samplingUsed.warnings && samplingUsed.warnings.length > 0 }"
        >
          <Info
            :size="16"
            class="sampling-notice__icon"
          />
          <div class="sampling-notice__body">
            <p class="sampling-notice__title">
              Analysis based on a sample
            </p>
            <p class="sampling-notice__description">
              Analysed {{ samplingUsed.sample_size?.toLocaleString?.() || samplingUsed.sample_size }} of
              {{ samplingUsed.total_rows?.toLocaleString?.() || samplingUsed.total_rows }} rows.
              <template v-if="samplingUsed.stats_on_full_dataset">
                Statistics computed on the full dataset for accuracy.
              </template>
              <template v-else>
                Statistics also computed on the sample.
              </template>
            </p>
            <ul
              v-if="samplingUsed.warnings && samplingUsed.warnings.length > 0"
              class="sampling-notice__warnings"
            >
              <li
                v-for="(warning, idx) in samplingUsed.warnings"
                :key="idx"
              >
                {{ warning }}
              </li>
            </ul>
            <p
              v-if="samplingUsed.recommendation"
              class="sampling-notice__recommendation"
            >
              {{ samplingUsed.recommendation }}
            </p>
          </div>
        </div>

        <!-- Insights -->
        <div
          v-if="insights && insights.length > 0"
          class="insights-section"
        >
          <InsightCard
            v-for="(insight, index) in insights"
            :key="index"
            :insight="insight"
          />
        </div>
        <!-- Honest fallback when narrator degraded
             silently. Only renders in analyst mode AND only when the
             backend has sent a narrator_status that signals degradation.
             Standard mode and "ran_successfully with empty insights"
             keep the old hide-the-section behavior. -->
        <div
          v-else-if="isAnalystMode && narratorFallbackTitle"
          class="insights-fallback"
          :class="`fallback-${narratorStatus}`"
        >
          <Info
            :size="18"
            class="fallback-icon"
          />
          <div class="fallback-body">
            <p class="fallback-title">
              {{ narratorFallbackTitle }}
            </p>
            <p class="fallback-description">
              {{ narratorFallbackMessage }}
            </p>
          </div>
        </div>
      </div>

      <!-- Content Tabs (SQL/Data/Chart) -->
      <ContentTabs
        v-if="sql || rawResult"
        :sql="sql"
        :results="rawResult"
        :chart-spec="chartSpec"
        :session-id="sessionId"
        :dml-capabilities="dmlCapabilities"
        @copy="handleCopy"
        @fullscreen="showFullscreen = true"
      />

      <!-- Follow-Up Suggestions -->
      <FollowUpSuggestions
        v-if="followUpSuggestions && followUpSuggestions.length > 0"
        :suggestions="followUpSuggestions"
        @ask-question="handleFollowUpQuestion"
      />

      <!-- Collapsible Details Section (tools/steps - like ChatGPT) -->
      <div
        v-if="hasDetails && !isGenerating"
        class="details-section"
      >
        <button
          class="details-toggle"
          @click="showDetails = !showDetails"
        >
          <ChevronRight
            :size="14"
            :class="{ rotated: showDetails }"
          />
          <span>{{ detailsLabel }}</span>
        </button>
        <transition name="expand">
          <div
            v-if="showDetails"
            class="details-content"
          >
            <!-- Agent Timeline -->
            <AgentTimeline
              v-if="agentSteps.length > 0"
              :steps="agentSteps"
              :default-expanded="true"
            />
            <!-- Explanation -->
            <div
              v-if="message.content?.explanation"
              class="explanation-text"
              v-html="formatExplanation(message.content.explanation)"
            />
          </div>
        </transition>
      </div>
    </div>

    <!-- Action Footer -->
    <div
      v-if="!isGenerating && (sql || isAnalystMode)"
      class="card-footer"
    >
      <div class="actions-left">
        <button
          v-if="sql"
          :disabled="!isValid || isExecuting"
          class="action-btn primary"
          @click="$emit('run-query')"
        >
          <Loader2
            v-if="isExecuting"
            :size="14"
            class="spin"
          />
          <Play
            v-else
            :size="14"
          />
          <span>{{ isExecuting ? 'Running...' : 'Run' }}</span>
        </button>

        <button
          v-if="sql && !message.content?.explanation && !isExplaining"
          class="action-btn ghost"
          title="Explain SQL"
          @click="handleExplain"
        >
          <Lightbulb :size="14" />
        </button>

        <button
          v-if="sql"
          class="action-btn ghost"
          title="Copy SQL"
          @click="handleCopy"
        >
          <Check
            v-if="copied"
            :size="14"
          />
          <Copy
            v-else
            :size="14"
          />
        </button>

        <button
          v-if="sql"
          :disabled="!isValid || isGenerating || isExecuting"
          class="action-btn ghost"
          :title="
            (isGenerating || isExecuting)
              ? 'Wait for the current query to finish before exporting'
              : 'Export results'
          "
          @click="$emit('export')"
        >
          <Download :size="14" />
        </button>
      </div>

      <div class="actions-right">
        <button
          :class="['feedback-btn', { active: userFeedback === 1 }]"
          title="Good response"
          @click="handleFeedback(1)"
        >
          <ThumbsUp :size="14" />
        </button>
        <button
          :class="['feedback-btn', { active: userFeedback === -1 }]"
          title="Poor response"
          @click="handleFeedback(-1)"
        >
          <ThumbsDown :size="14" />
        </button>
      </div>
    </div>

    <!-- Fullscreen Modal for Results -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showFullscreen"
          class="modal-overlay"
          @click.self="showFullscreen = false"
        >
          <div class="modal-container">
            <div class="modal-header">
              <div class="modal-title">
                <Table2 :size="20" />
                <span>Results</span>
                <span
                  v-if="rawResult?.row_count"
                  class="modal-count"
                >
                  {{ rawResult.row_count.toLocaleString() }} rows
                </span>
              </div>
              <div class="modal-actions">
                <button
                  class="modal-btn"
                  @click="copyAsCSV"
                >
                  <Copy :size="16" />
                  CSV
                </button>
                <button
                  class="modal-btn"
                  @click="copyAsJSON"
                >
                  <Copy :size="16" />
                  JSON
                </button>
                <button
                  class="modal-close"
                  @click="showFullscreen = false"
                >
                  <X :size="20" />
                </button>
              </div>
            </div>
            <div class="modal-body">
              <ResultsTable
                v-if="rawResult"
                :columns="rawResult.columns"
                :rows="rawResult.rows"
                :row-count="rawResult.row_count"
                fullscreen
              />
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Toast -->
    <Transition name="toast">
      <div
        v-if="toastMessage"
        class="toast"
      >
        <Check :size="16" />
        {{ toastMessage }}
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import {
  Bot,
  Sparkles,
  Copy,
  Check,
  Play,
  Loader2,
  Lightbulb,
  ThumbsUp,
  ThumbsDown,
  ChevronRight,
  Table2,
  X,
  Download,
  Info
} from 'lucide-vue-next'
import AgentTimeline from './AgentTimeline.vue'
import ContentTabs from './ContentTabs.vue'
import ResultsTable from '../results/ResultsTable.vue'
import InsightCard from './analyst/InsightCard.vue'
import FollowUpSuggestions from './analyst/FollowUpSuggestions.vue'
import DataQualityIndicator from './analyst/DataQualityIndicator.vue'
import DOMPurify from 'dompurify'

const props = defineProps({
  message: {
    type: Object,
    required: true
  },
  isLatest: Boolean,
  isExecuting: Boolean,
  isExplaining: Boolean,
  sessionId: {
    type: String,
    default: null
  },
  dmlCapabilities: {
    type: Object,
    default: null
  }
})

const emit = defineEmits([
  'run-query',
  'explain',
  'copy',
  'export',
  'feedback',
  'stop',
  'ask-question'
])

// Local state
const copied = ref(false)
const showDetails = ref(false)
const showFullscreen = ref(false)
const userFeedback = ref(null)
const toastMessage = ref('')
let copyTimeout = null

// Computed - Basic
const sql = computed(() => props.message.content?.sql || '')
const isValid = computed(() => props.message.content?.isValid !== false)
const isGenerating = computed(() => props.message.content?.isGenerating === true)

// Computed - Analyst mode
const isAnalystMode = computed(() => props.message.content?.mode === 'analyst')
const answer = computed(() => props.message.content?.answer || '')
const keyFindings = computed(() => props.message.content?.keyFindings || props.message.content?.key_findings || [])
const chartSpec = computed(() => props.message.content?.chart || null)
const rawResult = computed(() => props.message.content?.rawResult || props.message.content?.raw_result || null)
const agentSteps = computed(() => props.message.content?.agentSteps || [])
const toolsUsed = computed(() => props.message.content?.toolsUsed || props.message.content?.tools_used || [])

// Computed - Analyst Intelligence Features
const insights = computed(() => props.message.content?.insights || [])
const dataQuality = computed(() => props.message.content?.dataQuality || props.message.content?.data_quality || null)
const followUpSuggestions = computed(() => props.message.content?.followUpSuggestions || props.message.content?.follow_up_suggestions || props.message.content?.suggestions || [])

// Sampling metadata as its own field — keeps the insights list pure.
// Renders as its own subtle banner so real business findings don't
// compete with meta-commentary about "this was a sampled run".
const samplingUsed = computed(() => props.message.content?.samplingUsed || props.message.content?.sampling_used || null)

// Narrator observability. When insights is empty
// we used to render an invisible blank strip, masking two distinct
// failure modes: narrator was silently skipped (no LLM config) vs
// narrator ran but produced no business insights. The backend now
// ships a narrator_status signal; render an honest fallback based
// on it so operators and users can tell "we looked and found nothing"
// from "the analyst narrator wasn't available on this session".
const narratorStatus = computed(() => props.message.content?.narratorStatus || props.message.content?.narrator_status || null)

const narratorFallbackTitle = computed(() => {
  switch (narratorStatus.value) {
    case 'skipped_no_llm_config':
      return 'Statistical analysis only'
    case 'ran_but_empty':
      return 'No notable patterns detected'
    case 'ran_without_question_anchor':
      return 'Analysis without question context'
    default:
      return null
  }
})

const narratorFallbackMessage = computed(() => {
  switch (narratorStatus.value) {
    case 'skipped_no_llm_config':
      return 'The business-insight narrator is not wired to this session (no LLM configured). Statistical analysis is shown above; open the data tab to inspect rows directly.'
    case 'ran_but_empty':
      return 'The analyzers looked for concentration, trends, and outliers but didn\'t find anything that stood out. Try a more specific question or inspect the data table.'
    case 'ran_without_question_anchor':
      return 'Analysis ran without your original question threaded through. The narrative may read generic — try re-asking with more context.'
    default:
      return null
  }
})

// Multi-turn conversation metadata
const isFollowUp = computed(() => props.message.content?.isFollowUp === true)

// Thinking text (unified for both Standard and Analyst modes)
const thinkingText = computed(() => {
  if (!agentSteps.value.length) {
    return 'Thinking...'
  }
  const last = agentSteps.value[agentSteps.value.length - 1]
  if (last?.type === 'tool_call') return `Using ${last.tool || 'tool'}...`
  if (last?.type === 'thinking') return 'Thinking...'
  if (last?.type === 'executing') return 'Running query...'
  if (last?.type === 'schema') return 'Reading schema...'
  return 'Processing...'
})

// Collapsible details
const hasDetails = computed(() => {
  return agentSteps.value.length > 0 || props.message.content?.explanation
})

const detailsLabel = computed(() => {
  const parts = []
  if (agentSteps.value.length > 0) parts.push(`${agentSteps.value.length} steps`)
  if (toolsUsed.value.length > 0) parts.push(`${toolsUsed.value.length} tools`)
  if (props.message.content?.explanation) parts.push('explanation')
  return parts.length ? `View details (${parts.join(', ')})` : 'View details'
})

// Auto-expand details when explanation is generated
watch(() => props.isExplaining, (newVal, oldVal) => {
  if (oldVal === true && newVal === false && props.message.content?.explanation) {
    showDetails.value = true
  }
})

// Handlers
const handleCopy = async () => {
  if (!sql.value) return
  if (copyTimeout) clearTimeout(copyTimeout)
  try {
    await navigator.clipboard.writeText(sql.value)
    copied.value = true
    emit('copy')
    copyTimeout = setTimeout(() => { copied.value = false }, 2000)
  } catch {
    // Fallback
    const textarea = document.createElement('textarea')
    textarea.value = sql.value
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    copied.value = true
    copyTimeout = setTimeout(() => { copied.value = false }, 2000)
  }
}

const handleFeedback = (rating) => {
  userFeedback.value = rating
  emit('feedback', rating > 0 ? 5 : 1)
}

const handleExplain = () => {
  emit('explain')
  showDetails.value = true
}

const handleFollowUpQuestion = (question) => {
  emit('ask-question', question)
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Copy functions for modal
const copyAsCSV = async () => {
  if (!rawResult.value) return
  try {
    const columns = rawResult.value.columns || []
    const rows = rawResult.value.rows || []
    const header = columns.join(',')
    const csvRows = rows.map(row =>
      columns.map(col => {
        const val = row[col]
        if (val === null || val === undefined) return ''
        if (typeof val === 'string') return `"${val.replace(/"/g, '""')}"`
        if (typeof val === 'object') return `"${JSON.stringify(val).replace(/"/g, '""')}"`
        return val
      }).join(',')
    )
    const csv = [header, ...csvRows].join('\n')
    await navigator.clipboard.writeText(csv)
    showToast('Copied as CSV!')
  } catch (e) {
    console.error('Copy failed:', e)
  }
}

const copyAsJSON = async () => {
  if (!rawResult.value) return
  try {
    const data = {
      columns: rawResult.value.columns || [],
      rows: rawResult.value.rows || []
    }
    await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
    showToast('Copied as JSON!')
  } catch (e) {
    console.error('Copy failed:', e)
  }
}

const showToast = (msg) => {
  toastMessage.value = msg
  setTimeout(() => { toastMessage.value = '' }, 2000)
}

// Format explanation with markdown-like parsing
const formatExplanation = (text) => {
  if (!text) return ''

  let formatted = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Section headers
  formatted = formatted.replace(/^##\s+(.+)$/gm, '<h4 class="exp-header">$1</h4>')
  formatted = formatted.replace(/^\*\*(.+?):\*\*\s*$/gm, '<h4 class="exp-header">$1</h4>')

  // Inline bold labels
  formatted = formatted.replace(/\*\*(.+?):\*\*\s+/g, '<strong class="exp-label">$1:</strong> ')

  // Remaining bold
  formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // Inline code
  formatted = formatted.replace(/`([^`]+)`/g, '<code class="exp-code">$1</code>')

  // Numbered lists
  formatted = formatted.replace(/^(\d+)\.\s+(.+)$/gm, '<div class="exp-list-item"><span class="exp-num">$1</span><span>$2</span></div>')

  // Bullet lists
  formatted = formatted.replace(/^[-*]\s+(.+)$/gm, '<div class="exp-bullet"><span class="exp-dot"></span><span>$1</span></div>')

  // Single line breaks (convert to <br> before paragraph processing)
  formatted = formatted.replace(/\n/g, '<br>')

  // Paragraphs (double line breaks already converted to <br><br>)
  formatted = formatted.replace(/<br><br>+/g, '</p><p class="exp-para">')
  formatted = '<p class="exp-para">' + formatted + '</p>'
  formatted = formatted.replace(/<p class="exp-para"><\/p>/g, '')

  return DOMPurify.sanitize(formatted)
}

// Cleanup
onUnmounted(() => {
  if (copyTimeout) clearTimeout(copyTimeout)
})
</script>

<style scoped>
/* Base Card */
.ai-response-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: background var(--transition-normal, 0.2s ease),
              border-color var(--transition-normal, 0.2s ease),
              box-shadow var(--transition-normal, 0.2s ease);
}

.ai-response-card.generating {
  border-color: rgba(99, 102, 241, 0.25);
}

/* Minimal Header */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border-subtle);
  transition: border-color var(--transition-normal, 0.2s ease);
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.ai-avatar {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.ai-name {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  transition: color var(--transition-normal, 0.2s ease);
}

.follow-up-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-info);
}

/* Removed stop button from card header - control is in input box */

.message-time {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* Thinking State (ChatGPT style) */
.thinking-state {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-md);
}

.thinking-indicator {
  display: flex;
  gap: 4px;
}

.thinking-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: thinking 1.4s ease-in-out infinite;
}

.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes thinking {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

.thinking-text {
  font-size: var(--text-sm);
  color: var(--text-muted);
  transition: color var(--transition-normal, 0.2s ease);
}

/* Card Content */
.card-content {
  padding: var(--space-md);
}

/* Answer Section */
.answer-section {
  margin-bottom: var(--space-md);
}

.answer-text {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--text-primary);
  transition: color var(--transition-normal, 0.2s ease);
}

.answer-text:last-child {
  margin-bottom: 0;
}

/* Key Findings (compact) */
.key-findings {
  margin-top: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  background: rgba(99, 102, 241, 0.05);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  transition: background var(--transition-normal, 0.2s ease);
}

.finding-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-sm);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.finding-num {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-primary);
  min-width: 16px;
}

/* Analyst Intelligence Features */
.quality-section {
  margin-top: var(--space-md);
}

.insights-section {
  margin-top: var(--space-md);
}

/* Sampling-notice banner — lives above the insights list. */
.sampling-notice {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  background: var(--bg-input);
  border-left: 4px solid var(--color-info);
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
  margin-top: var(--space-md);
  margin-bottom: var(--space-sm);
}

.sampling-notice--warning {
  border-left-color: var(--color-warning);
}

.sampling-notice__icon {
  color: var(--color-info);
  flex-shrink: 0;
  margin-top: 2px;
}

.sampling-notice--warning .sampling-notice__icon {
  color: var(--color-warning);
}

.sampling-notice__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.sampling-notice__title {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.sampling-notice__description {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

.sampling-notice__warnings {
  margin: 0;
  padding-left: var(--space-md);
  font-size: 0.8125rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

.sampling-notice__recommendation {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-primary);
  font-style: italic;
  line-height: 1.5;
}

/* Degraded-narrator fallback card */
.insights-fallback {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  background: var(--bg-input);
  border-left: 4px solid var(--color-info);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  margin-top: var(--space-md);
  margin-bottom: var(--space-md);
}

.insights-fallback.fallback-skipped_no_llm_config {
  border-left-color: var(--color-warning);
}

.fallback-icon {
  color: var(--color-info);
  flex-shrink: 0;
  margin-top: 2px;
}

.insights-fallback.fallback-skipped_no_llm_config .fallback-icon {
  color: var(--color-warning);
}

.fallback-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.fallback-title {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}

.fallback-description {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* Details Section (Collapsible) */
.details-section {
  margin-top: var(--space-sm);
  border-top: 1px solid var(--border-subtle);
  padding-top: var(--space-sm);
  transition: border-color var(--transition-normal, 0.2s ease);
}

.details-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) 0;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: color 0.15s;
}

.details-toggle:hover {
  color: var(--text-secondary);
}

.details-toggle svg {
  transition: transform 0.2s;
}

.details-toggle svg.rotated {
  transform: rotate(90deg);
}

.details-content {
  padding-top: var(--space-sm);
}

.explanation-text {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.6;
  padding: var(--space-sm);
  background: var(--bg-input);
  border-radius: var(--radius-md);
  margin-top: var(--space-sm);
  transition: background var(--transition-normal, 0.2s ease),
              color var(--transition-normal, 0.2s ease);
}

/* Expand transition */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

/* Card Footer */
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-top: 1px solid var(--border-subtle);
  transition: border-color var(--transition-normal, 0.2s ease);
}

.actions-left,
.actions-right {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

/* Action Buttons */
.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.action-btn.primary {
  background: var(--color-success);
  color: white;
}

.action-btn.primary:hover:not(:disabled) {
  filter: brightness(1.1);
}

.action-btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.ghost {
  background: transparent;
  color: var(--text-muted);
  padding: 6px;
}

.action-btn.ghost:hover {
  background: var(--bg-input);
  color: var(--text-secondary);
}

/* Feedback Buttons */
.feedback-btn {
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
  transition: all 0.15s;
}

.feedback-btn:hover {
  background: var(--bg-input);
  color: var(--text-secondary);
}

.feedback-btn.active {
  color: var(--color-primary);
}

/* Formatted text styles */
.answer-text :deep(.exp-para) {
  margin: 0 0 var(--space-sm);
}

.answer-text :deep(.exp-para:last-child) {
  margin-bottom: 0;
}

.answer-text :deep(.exp-list-item) {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-xs) 0;
}

.answer-text :deep(.exp-num) {
  min-width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-primary);
  color: white;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.answer-text :deep(.exp-bullet) {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-xs) 0;
}

.answer-text :deep(.exp-dot) {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-primary);
  flex-shrink: 0;
  margin-top: 8px;
}

.answer-text :deep(strong) {
  font-weight: 600;
}

.answer-text :deep(.exp-code) {
  font-family: var(--font-mono, monospace);
  font-size: 0.9em;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--bg-input);
}

.explanation-text :deep(.exp-para),
.explanation-text :deep(.exp-list-item),
.explanation-text :deep(.exp-bullet),
.explanation-text :deep(.exp-num),
.explanation-text :deep(.exp-dot),
.explanation-text :deep(strong),
.explanation-text :deep(.exp-code) {
  /* Inherit same styles */
}

/* Spinner */
.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-lg);
}

.modal-container {
  width: 100%;
  max-width: 1100px;
  max-height: 85vh;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: background var(--transition-normal, 0.2s ease),
              border-color var(--transition-normal, 0.2s ease);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border-subtle);
}

.modal-title {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.modal-count {
  font-size: var(--text-xs);
  color: var(--text-muted);
  padding: 2px 8px;
  background: var(--bg-input);
  border-radius: var(--radius-full);
}

.modal-actions {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.modal-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all 0.15s;
}

.modal-btn:hover {
  background: var(--bg-input);
  border-color: var(--color-primary);
}

.modal-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.modal-close:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

.modal-body {
  flex: 1;
  overflow: auto;
  padding: var(--space-md);
}

/* Modal transitions */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.96);
}

/* Toast */
.toast {
  position: fixed;
  bottom: var(--space-lg);
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-card);
  border: 1px solid var(--color-success);
  color: var(--color-success);
  font-size: var(--text-sm);
  border-radius: var(--radius-md);
  z-index: 1100;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.2s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(10px);
}

/* Mobile */
@media (max-width: 640px) {
  .card-footer {
    flex-direction: column;
    gap: var(--space-sm);
  }

  .actions-left,
  .actions-right {
    width: 100%;
    justify-content: center;
  }

  .action-btn span {
    display: none;
  }
}
</style>

<!--
============================================
QueryBar.vue
============================================
Unified floating input bar combining:
- Mode toggles (Standard/Analyst)
- Text input with send/stop
- Conversation controls (Continue/Fresh)

Gemini-inspired floating design with centered pill input.
-->
<template>
  <div class="query-bar-wrapper">
    <div class="query-bar">
      <!-- Main Input Row -->
      <div class="input-row">
        <!-- Mode indicator (inside input) -->
        <button
          type="button"
          class="mode-indicator"
          :title="isAnalystMode ? 'Analyst Mode - Click for Standard' : 'Standard Mode - Click for Analyst'"
          @click="toggleMode"
        >
          <BrainCircuit
            v-if="isAnalystMode"
            :size="16"
          />
          <Zap
            v-else
            :size="16"
          />
        </button>

        <!-- Text Input -->
        <textarea
          ref="textareaRef"
          v-model="query"
          :placeholder="placeholder"
          :disabled="disabled"
          rows="1"
          class="query-textarea"
          aria-label="Enter your natural language query"
          @keydown="handleKeydown"
          @input="adjustHeight"
        />

        <!-- Stop button (when generating) -->
        <button
          v-if="isGenerating"
          class="action-btn stop"
          title="Stop generation"
          @click="handleStop"
        >
          <Square :size="16" />
        </button>

        <!-- Send button -->
        <button
          v-else
          :disabled="disabled || !query.trim()"
          class="action-btn send"
          title="Send (Ctrl+Enter)"
          @click="handleSubmit"
        >
          <ArrowUp :size="16" />
        </button>
      </div>

      <!-- Options Row (below input) -->
      <div class="options-row">
        <!-- Mode Pills -->
        <div class="mode-pills">
          <button
            :class="['pill', { active: !isAnalystMode }]"
            @click="setResponseMode('standard')"
          >
            <Zap :size="12" />
            <span>Standard</span>
          </button>
          <button
            :class="['pill', 'analyst', { active: isAnalystMode }]"
            @click="setResponseMode('analyst')"
          >
            <BrainCircuit :size="12" />
            <span>Analyst</span>
          </button>
        </div>

        <!-- Conversation Controls (show after first message) -->
        <div
          v-if="showConversationControls"
          class="conversation-controls"
        >
          <button
            :class="['pill', 'small', { active: continueConversation }]"
            title="Continue from previous context"
            @click="setContinueMode(true)"
          >
            <MessageSquarePlus :size="12" />
            <span>Continue</span>
          </button>
          <button
            :class="['pill', 'small', { active: !continueConversation }]"
            title="Start fresh conversation"
            @click="handleFreshStart"
          >
            <RefreshCw :size="12" />
            <span>Fresh</span>
          </button>
          <span
            v-if="conversationTurn > 1"
            class="turn-badge"
          >
            Turn {{ conversationTurn }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import {
  Zap,
  BrainCircuit,
  ArrowUp,
  Square,
  MessageSquarePlus,
  RefreshCw
} from 'lucide-vue-next'
import { useQueryOptions } from '../../composables/useQueryOptions'
import { useConversationStore } from '../../stores/conversation'

const props = defineProps({
  disabled: Boolean,
  isGenerating: Boolean,
  placeholder: {
    type: String,
    default: 'Ask about your data...'
  }
})

const emit = defineEmits(['submit', 'stop'])

// Query options (mode)
const { isAnalystMode, setResponseMode } = useQueryOptions()

// Conversation store
const conversationStore = useConversationStore()
const { continueConversation, messageCount, currentConversationTurn } = storeToRefs(conversationStore)

// Local state
const query = ref('')
const textareaRef = ref(null)

// Computed
const showConversationControls = computed(() => messageCount.value > 0)
const conversationTurn = computed(() => currentConversationTurn.value)

// Toggle mode
const toggleMode = () => {
  setResponseMode(isAnalystMode.value ? 'standard' : 'analyst')
}

// Conversation controls
const setContinueMode = (value) => {
  conversationStore.setContinueConversation(value)
}

const handleFreshStart = () => {
  if (conversationTurn.value > 1) {
    const confirmed = window.confirm('Start a fresh conversation? This will clear the conversation context.')
    if (!confirmed) return
  }
  conversationStore.setContinueConversation(false)
  conversationStore.resetConversationContext()
}

// Auto-resize textarea
const adjustHeight = async () => {
  await nextTick()
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
    const newHeight = Math.min(textareaRef.value.scrollHeight, 150)
    textareaRef.value.style.height = `${newHeight}px`
  }
}

// Handle keyboard shortcuts
const handleKeydown = (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    handleSubmit()
  }
  // Allow Shift+Enter for new line
  if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    e.preventDefault()
    handleSubmit()
  }
}

// Submit query
const handleSubmit = () => {
  if (query.value.trim() && !props.disabled && !props.isGenerating) {
    emit('submit', query.value.trim())
    query.value = ''
    adjustHeight()
  }
}

// Stop generation
const handleStop = () => {
  emit('stop')
}

// Watch for query changes
watch(query, () => {
  adjustHeight()
})

// Focus the input
const focus = () => {
  textareaRef.value?.focus()
}

// Set query from outside
const setQuery = (text) => {
  query.value = text
  adjustHeight()
  focus()
}

// Expose methods
defineExpose({
  focus,
  setQuery
})
</script>

<style scoped>
.query-bar-wrapper {
  position: sticky;
  bottom: 0;
  padding: var(--space-lg) var(--space-md);
  padding-bottom: var(--space-2xl);
  background: linear-gradient(to top, var(--bg-app) 85%, transparent);
  pointer-events: none;
}

.query-bar {
  max-width: 760px;
  margin: 0 auto;
  pointer-events: auto;
}

/* Input Row */
.input-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 28px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
  transition: border-color 0.15s, box-shadow 0.15s;
}

.input-row:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2), 0 0 0 2px var(--color-primary-light);
}

/* Mode Indicator (inside input) */
.mode-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: var(--bg-input);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.mode-indicator:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* Textarea */
.query-textarea {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-base);
  font-family: inherit;
  line-height: 22px;
  resize: none;
  padding: 8px var(--space-sm);
  min-height: 22px;
  max-height: 150px;
}

.query-textarea::placeholder {
  color: var(--text-muted);
}

.query-textarea:focus {
  outline: none;
}

.query-textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Action Buttons */
.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.action-btn.send {
  background: var(--color-primary);
  color: white;
}

.action-btn.send:hover:not(:disabled) {
  background: var(--color-primary-hover);
  transform: scale(1.05);
}

.action-btn.send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.action-btn.stop {
  background: var(--color-error);
  color: white;
}

.action-btn.stop:hover {
  background: var(--color-error-hover);
}

/* Options Row */
.options-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-xs);
  gap: var(--space-sm);
}

.mode-pills,
.conversation-controls {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

/* Pills */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.pill:hover {
  border-color: var(--border-default);
  color: var(--text-secondary);
}

.pill.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: white;
}

.pill.analyst.active {
  background: var(--color-secondary);
  border-color: var(--color-secondary);
}

.pill.small {
  padding: 5px 12px;
  font-size: var(--text-xs);
}

.pill.small.active {
  background: rgba(99, 102, 241, 0.15);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* Turn Badge */
.turn-badge {
  font-size: 10px;
  font-weight: 500;
  color: var(--text-muted);
  padding: 2px 6px;
  background: var(--bg-input);
  border-radius: var(--radius-full);
}

/* Theme transition */
.query-bar-wrapper,
.input-row,
.pill {
  transition: background var(--transition-normal, 0.2s),
              border-color var(--transition-normal, 0.2s),
              color var(--transition-normal, 0.2s);
}

/* Mobile */
@media (max-width: 640px) {
  .query-bar-wrapper {
    padding: var(--space-sm);
    padding-bottom: max(var(--space-md), env(safe-area-inset-bottom));
  }

  .input-row {
    border-radius: 20px;
  }

  .query-textarea {
    font-size: 16px; /* Prevent iOS zoom */
  }

  .pill span {
    display: none;
  }

  .pill {
    padding: 6px;
  }

  .options-row {
    flex-wrap: wrap;
    justify-content: center;
  }
}
</style>

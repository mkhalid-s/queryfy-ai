<template>
  <div class="query-input-container">
    <!-- Mode Options (Stream/Agentic toggles) -->
    <InputOptions v-if="showOptions" />

    <div class="input-wrapper">
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

      <!-- Stop button (shown when generating) -->
      <button
        v-if="isGenerating"
        class="stop-btn"
        title="Stop generation"
        @click="handleStop"
      >
        <Square :size="18" />
      </button>

      <!-- Send button (shown when not generating) -->
      <button
        v-else
        :disabled="disabled || !query.trim()"
        class="send-btn"
        title="Send (Ctrl+Enter)"
        @click="handleSubmit"
      >
        <Send :size="18" />
      </button>
    </div>

    <div class="input-hint">
      <span v-if="!disabled">Press <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to send</span>
      <span
        v-else
        class="hint-warning"
      >Configure connection in settings to start</span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { Send, Square } from 'lucide-vue-next'
import InputOptions from './InputOptions.vue'

const props = defineProps({
  placeholder: {
    type: String,
    default: 'Ask about your data...'
  },
  disabled: Boolean,
  isGenerating: Boolean,
  showOptions: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['submit', 'stop'])

const query = ref('')
const textareaRef = ref(null)

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

// Watch for external query changes
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
.query-input-container {
  flex-shrink: 0;
  padding: var(--space-sm) 0 var(--space-md) 0;
  background: var(--bg-app);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: var(--space-sm);
  padding: var(--space-sm);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.input-wrapper:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.query-textarea {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-base);
  font-family: var(--font-sans);
  line-height: 1.5;
  resize: none;
  padding: var(--space-xs);
  min-height: 24px;
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

.send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: white;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
  transform: scale(1.05);
}

.send-btn:active:not(:disabled) {
  transform: scale(0.95);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.stop-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-error, #ef4444);
  color: white;
  cursor: pointer;
  transition: all var(--transition-smooth);
  flex-shrink: 0;
  box-shadow: var(--shadow-card);
  animation: pulseStop 2s ease-in-out infinite;
}

/* Subtle pulse to indicate it's the primary stop control */
@keyframes pulseStop {
  0%, 100% {
    box-shadow: var(--shadow-card);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.2), var(--shadow-card);
  }
}

.stop-btn:hover {
  background: var(--color-error-hover, #dc2626);
  transform: scale(1.05);
  animation: none;
  box-shadow: var(--shadow-elevated);
}

.stop-btn:active {
  transform: scale(0.95);
  box-shadow: var(--shadow-sm);
}

.input-hint {
  display: flex;
  justify-content: center;
  margin-top: var(--space-xs);
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.input-hint kbd {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  font-family: var(--font-mono);
  font-size: 10px;
}

.hint-warning {
  color: var(--color-warning);
}

/* Mobile responsive */
@media (max-width: 768px) {
  .query-input-container {
    padding: var(--space-xs) 0 var(--space-sm) 0;
    /* Account for safe area on iOS */
    padding-bottom: max(var(--space-sm), env(safe-area-inset-bottom));
  }

  .input-wrapper {
    padding: var(--space-xs);
    border-radius: var(--radius-md);
  }

  .query-textarea {
    font-size: 16px; /* Prevent iOS zoom */
  }

  .send-btn,
  .stop-btn {
    width: 36px;
    height: 36px;
  }

  .input-hint {
    display: none;
  }
}
</style>

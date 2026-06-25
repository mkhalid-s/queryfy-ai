<template>
  <div :class="['app-shell', { 'light-theme': !isDark }]">
    <!-- Header -->
    <AppHeader
      :is-dark="isDark"
      :has-session="!!session"
      @toggle-theme="$emit('toggle-theme')"
      @open-settings="settingsOpen = true"
      @open-context-studio="contextStudioOpen = true"
      @toggle-sidebar="$emit('toggle-sidebar')"
    />

    <!-- App Body (sidebar + main content) -->
    <div class="app-body">
      <!-- History Sidebar -->
      <HistorySidebar
        :open="sidebarOpen"
        @update:open="$emit('update:sidebarOpen', $event)"
        @select="handleHistorySelect"
      />

      <!-- Main Scroll Area (full width, content centered inside) -->
      <main
        ref="mainScrollRef"
        class="main-scroll-area"
      >
        <div class="content-wrapper">
          <!-- Chat Container (no internal scroll) -->
          <ChatContainer
            ref="chatContainerRef"
            :conversation="conversation"
            :is-generating="isGenerating"
            :is-executing="isExecuting"
            :is-explaining="isExplaining"
            :explaining-message-id="explainingMessageId"
            :session-id="session?.id"
            :dml-capabilities="session?.dml_capabilities"
            @run-query="$emit('run-query', $event)"
            @explain="$emit('explain', $event)"
            @copy="$emit('copy', $event)"
            @export="$emit('export', $event)"
            @feedback="$emit('feedback', $event)"
            @toggle-results="$emit('toggle-results', $event)"
            @toggle-chart="$emit('toggle-chart', $event)"
            @ask-follow-up="$emit('generate', $event)"
            @example-select="$emit('generate', $event)"
          />

          <!-- Suggestions Panel (above input) -->
          <SuggestionsPanel
            v-if="session && suggestions?.length"
            :suggestions="suggestions"
            @select="handleSuggestionSelect"
          />

          <!-- Phase 4 Batch D (H10): tell the user when schema is
               still indexing. Without this banner a query submitted
               in the first ~5s after session start hits the agent
               before it has any vector-DB schema context, the agent
               wanders, and the user blames the model. -->
          <div
            v-if="session && session.schema_ready === false && !session.schema_error"
            class="schema-indexing-banner"
          >
            Indexing your schema… first query may take a few extra seconds.
          </div>
          <div
            v-if="session && session.schema_error"
            class="schema-indexing-banner schema-indexing-banner-error"
          >
            Schema indexing failed: {{ session.schema_error }}
          </div>

          <!-- Floating Query Bar (sticky at bottom) -->
          <QueryBar
            ref="queryBarRef"
            :disabled="!session"
            :is-generating="isGenerating"
            :placeholder="inputPlaceholder"
            @submit="handleQuerySubmit"
            @stop="emit('stop')"
          />
        </div>
      </main>
    </div>

    <!-- Settings Drawer (slide-in) -->
    <SettingsDrawer
      :open="settingsOpen"
      :session="session"
      :llm-config="llmConfig"
      :db-config="dbConfig"
      :token-info="tokenInfo"
      :is-dark="isDark"
      :query-count="queryCount"
      :session-start-time="sessionStartTime"
      @close="settingsOpen = false"
      @update-llm="$emit('update-llm', $event)"
      @update-db="$emit('update-db', $event)"
      @start-session="$emit('start-session')"
      @reset-session="$emit('reset-session', $event)"
    />

    <!-- Context Studio Panel (slide-in) -->
    <ContextStudioPanel
      :open="contextStudioOpen"
      :session-id="session?.id"
      @close="contextStudioOpen = false"
    />

    <!-- Setup Wizard (first-time flow) -->
    <SetupWizard
      v-if="showSetupWizard"
      :db-config="dbConfig"
      :llm-config="llmConfig"
      :is-dark="isDark"
      @update-llm="$emit('update-llm', $event)"
      @update-db="$emit('update-db', $event)"
      @complete="handleSetupComplete"
      @skip="showSetupWizard = false"
    />

    <!-- Toast Notifications -->
    <slot name="toast" />
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, defineAsyncComponent } from 'vue'
import AppHeader from './AppHeader.vue'
import ChatContainer from '../chat/ChatContainer.vue'
import QueryBar from '../input/QueryBar.vue'
import SuggestionsPanel from '../input/SuggestionsPanel.vue'

// Lazy load non-critical components to improve initial load time
const HistorySidebar = defineAsyncComponent(() => import('./HistorySidebar.vue'))
const SettingsDrawer = defineAsyncComponent(() => import('./SettingsDrawer.vue'))
const SetupWizard = defineAsyncComponent(() => import('../setup/SetupWizard.vue'))
const ContextStudioPanel = defineAsyncComponent(() => import('../context-studio/ContextStudioPanel.vue'))

const props = defineProps({
  session: {
    type: Object,
    default: null
  },
  conversation: {
    type: Array,
    default: null
  },
  history: {
    type: Array,
    default: null
  },
  suggestions: {
    type: Array,
    default: null
  },
  llmConfig: {
    type: Object,
    default: null
  },
  dbConfig: {
    type: Object,
    default: null
  },
  tokenInfo: {
    type: Object,
    default: null
  },
  isDark: Boolean,
  isGenerating: Boolean,
  isExecuting: Boolean,
  isExplaining: Boolean,
  explainingMessageId: {
    type: String,
    default: null
  },
  showSetup: Boolean,
  sidebarOpen: Boolean,
  queryCount: { type: Number, default: 0 },
  sessionStartTime: { type: [Date, String, Number], default: null }
})

const emit = defineEmits([
  'toggle-theme',
  'update-llm',
  'update-db',
  'start-session',
  'reset-session',
  'generate',
  'stop',
  'run-query',
  'explain',
  'copy',
  'export',
  'feedback',
  'toggle-results',
  'toggle-chart',
  'load-history',
  'toggle-sidebar',
  'update:sidebarOpen'
])

// Local state
const settingsOpen = ref(false)
const contextStudioOpen = ref(false)
const showSetupWizard = ref(false)

// Refs for child components
const mainScrollRef = ref(null)
const chatContainerRef = ref(null)
const queryBarRef = ref(null)

// Computed
const inputPlaceholder = computed(() => {
  if (!props.session) {
    return 'Configure connection to start...'
  }
  if (props.conversation.length === 0) {
    return 'Ask about your data...'
  }
  return 'Refine your query or ask something new...'
})

// Watch for session changes to show setup wizard
watch(() => props.showSetup, (show) => {
  showSetupWizard.value = show
}, { immediate: true })

// Scroll to bottom when conversation updates
watch(() => props.conversation.length, async () => {
  await nextTick()
  // Scroll the main area to bottom
  if (mainScrollRef.value) {
    mainScrollRef.value.scrollTop = mainScrollRef.value.scrollHeight
  }
})

// Handlers
const handleQuerySubmit = (query) => {
  emit('generate', query)
}

const handleSuggestionSelect = (suggestion) => {
  queryBarRef.value?.setQuery(suggestion.text)
}

const handleHistorySelect = (query) => {
  emit('load-history', query)
}

const handleSetupComplete = () => {
  showSetupWizard.value = false
  emit('start-session')
}

// Expose methods for parent
defineExpose({
  openSettings: () => { settingsOpen.value = true },
  focusInput: () => { queryBarRef.value?.focus() },
  scrollToBottom: () => {
    if (mainScrollRef.value) {
      mainScrollRef.value.scrollTop = mainScrollRef.value.scrollHeight
    }
  }
})
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh; /* Dynamic viewport height for mobile */
  background: var(--bg-app);
  color: var(--text-primary);
  overflow: hidden;
}

.app-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

/* Main scroll area - full width, scroll here (Gemini-like) */
.main-scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  scroll-behavior: smooth;
}

/* Content wrapper - centered with max-width */
.content-wrapper {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 var(--space-md);
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* Responsive adjustments */
@media (max-width: 768px) {
  .content-wrapper {
    padding: 0 var(--space-sm);
  }
}

@media (max-width: 480px) {
  .content-wrapper {
    padding: 0 var(--space-xs);
  }
}

/* Phase 4 Batch D: schema-indexing banner above the query bar */
.schema-indexing-banner {
  margin: 0 var(--space-md) var(--space-xs) var(--space-md);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  font-size: 12px;
  line-height: 1.4;
  background: rgba(59, 130, 246, 0.08);
  color: var(--text-secondary);
  border: 1px solid rgba(59, 130, 246, 0.4);
}
.schema-indexing-banner-error {
  background: rgba(239, 68, 68, 0.08);
  color: var(--text-primary);
  border-color: rgba(239, 68, 68, 0.4);
}
</style>

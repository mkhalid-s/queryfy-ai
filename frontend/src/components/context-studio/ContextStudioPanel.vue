<!--
============================================
ContextStudioPanel.vue
============================================
Main panel for Context Studio with tabbed navigation:
- Schema Explorer: Browse tables and add column descriptions
- Business Terms: Define business vocabulary and SQL expressions
- Query Patterns: Manage few-shot learning examples
- Import/Export: Bulk data operations
-->
<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <transition name="fade">
      <div
        v-if="open"
        class="drawer-backdrop"
        @click="handleClose"
      />
    </transition>

    <!-- Drawer -->
    <transition name="slide">
      <div
        v-if="open"
        class="context-studio-drawer"
      >
        <!-- Header -->
        <div class="drawer-header">
          <div class="header-left">
            <BookOpen
              :size="20"
              class="header-icon"
            />
            <h2>Context Studio</h2>
          </div>
          <div class="header-right">
            <div
              v-if="stats"
              class="stats-badges"
            >
              <span
                class="badge"
                :title="`${stats.total_terms} business terms`"
              >
                <Tag :size="12" />
                {{ stats.total_terms }}
              </span>
              <span
                class="badge"
                :title="`${stats.total_patterns} query patterns`"
              >
                <FileCode :size="12" />
                {{ stats.total_patterns }}
              </span>
              <span
                class="badge"
                :title="`${stats.total_columns} column descriptions`"
              >
                <Columns :size="12" />
                {{ stats.total_columns }}
              </span>
            </div>
            <button
              class="close-btn"
              @click="handleClose"
            >
              <X :size="20" />
            </button>
          </div>
        </div>

        <!-- Tabs -->
        <div class="tabs-container">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            :class="['tab-btn', { active: activeTab === tab.id }]"
            @click="activeTab = tab.id"
          >
            <component
              :is="tab.icon"
              :size="16"
            />
            <span>{{ tab.label }}</span>
          </button>
        </div>

        <!-- Content -->
        <div class="drawer-content">
          <!-- No Session State -->
          <div
            v-if="!sessionId"
            class="no-session-state"
          >
            <AlertCircle :size="24" />
            <p>Please connect to a database first to use Context Studio.</p>
          </div>

          <!-- Loading State -->
          <div
            v-else-if="isLoading && !hasData"
            class="loading-state"
          >
            <Loader2
              :size="24"
              class="spin"
            />
            <span>Loading data dictionary...</span>
          </div>

          <!-- Error State -->
          <div
            v-else-if="error"
            class="error-state"
          >
            <AlertCircle :size="24" />
            <p>{{ error }}</p>
            <button
              class="btn btn-secondary"
              @click="loadData"
            >
              <RefreshCw :size="14" />
              Retry
            </button>
          </div>

          <!-- Tab Content -->
          <template v-else>
            <SchemaExplorerTab
              v-if="activeTab === 'schema'"
              :session-id="sessionId"
            />
            <BusinessTermsTab
              v-else-if="activeTab === 'terms'"
              :session-id="sessionId"
            />
            <QueryPatternsTab
              v-else-if="activeTab === 'patterns'"
              :session-id="sessionId"
            />
            <ImportExportTab
              v-else-if="activeTab === 'import'"
              :session-id="sessionId"
            />
          </template>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, onMounted, markRaw } from 'vue'
import {
  X,
  BookOpen,
  Database,
  Tag,
  FileCode,
  Upload,
  Columns,
  Loader2,
  AlertCircle,
  RefreshCw
} from 'lucide-vue-next'
import { useDataDictionaryStore } from '@/stores/dataDictionary'
import { storeToRefs } from 'pinia'

// Tab components (lazy loaded for better performance)
import { defineAsyncComponent } from 'vue'
const SchemaExplorerTab = defineAsyncComponent(() => import('./SchemaExplorerTab.vue'))
const BusinessTermsTab = defineAsyncComponent(() => import('./BusinessTermsTab.vue'))
const QueryPatternsTab = defineAsyncComponent(() => import('./QueryPatternsTab.vue'))
const ImportExportTab = defineAsyncComponent(() => import('./ImportExportTab.vue'))

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  sessionId: {
    type: String,
    default: null
  }
})

const emit = defineEmits(['close', 'update'])

// Store
const store = useDataDictionaryStore()
const { stats, isLoading, hasData } = storeToRefs(store)

// Local state
const activeTab = ref('schema')
const error = ref(null)

// Tab definitions
const tabs = [
  { id: 'schema', label: 'Schema', icon: markRaw(Database) },
  { id: 'terms', label: 'Terms', icon: markRaw(Tag) },
  { id: 'patterns', label: 'Patterns', icon: markRaw(FileCode) },
  { id: 'import', label: 'Import/Export', icon: markRaw(Upload) }
]

// Load data when panel opens
async function loadData() {
  if (!props.sessionId) return
  error.value = null

  try {
    await store.loadAll(props.sessionId)
  } catch (e) {
    error.value = e.userMessage || e.message || 'Failed to load data dictionary'
  }
}

// Handle close
function handleClose() {
  emit('close')
}

// Watch for panel open
watch(() => props.open, (isOpen) => {
  if (isOpen && props.sessionId) {
    loadData()
  }
})

// Watch for session changes
watch(() => props.sessionId, (newId) => {
  if (newId && props.open) {
    store.reset()
    loadData()
  }
})

// Load on mount if already open
onMounted(() => {
  if (props.open && props.sessionId) {
    loadData()
  }
})
</script>

<style scoped>
/* Backdrop */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  z-index: 999;
}

/* Drawer */
.context-studio-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  max-width: 600px;
  background: var(--bg-app);
  border-left: 1px solid var(--border-subtle);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Header */
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.header-icon {
  color: var(--color-primary);
}

.drawer-header h2 {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}

.stats-badges {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: var(--radius-full);
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 500;
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

/* Tabs */
.tabs-container {
  display: flex;
  gap: 2px;
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--color-primary);
  color: white;
}

/* Content */
.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-md);
}

/* Loading State */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  padding: var(--space-xl);
  color: var(--text-muted);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Error State */
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  padding: var(--space-xl);
  color: var(--color-error);
  text-align: center;
}

.error-state p {
  color: var(--text-secondary);
  margin: 0;
}

/* No Session State */
.no-session-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  padding: var(--space-xl);
  color: var(--color-warning);
  text-align: center;
}

.no-session-state p {
  color: var(--text-secondary);
  margin: 0;
}

/* Buttons */
.btn {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-secondary {
  background: var(--bg-input);
  color: var(--text-primary);
}

.btn-secondary:hover {
  background: var(--border-subtle);
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}

/* Mobile */
@media (max-width: 640px) {
  .context-studio-drawer {
    max-width: 100%;
  }

  .tabs-container {
    overflow-x: auto;
  }

  .tab-btn span {
    display: none;
  }

  .stats-badges {
    display: none;
  }
}
</style>

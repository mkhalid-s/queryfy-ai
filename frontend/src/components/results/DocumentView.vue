<template>
  <div class="document-viewer">
    <!-- Header Bar -->
    <div class="viewer-header">
      <div class="header-info">
        <div class="result-badge">
          <Database :size="16" />
          <span>{{ documents.length }} Document{{ documents.length !== 1 ? 's' : '' }}</span>
        </div>
        <div
          v-if="analysis?.metrics?.avgNestedDepth > 1"
          class="depth-indicator"
        >
          <Layers :size="14" />
          <span>Nested</span>
        </div>
      </div>

      <div class="header-actions">
        <button
          class="action-btn"
          @click="viewMode = viewMode === 'cards' ? 'raw' : 'cards'"
        >
          <component
            :is="viewMode === 'cards' ? Code2 : LayoutGrid"
            :size="16"
          />
          {{ viewMode === 'cards' ? 'Raw' : 'Cards' }}
        </button>
        <button
          class="action-btn primary"
          @click="copyAll"
        >
          <Copy :size="16" />
          Export
        </button>
      </div>
    </div>

    <!-- Cards View -->
    <div
      v-if="viewMode === 'cards'"
      class="cards-view"
    >
      <div class="cards-scroll">
        <div
          v-for="(doc, index) in paginatedDocuments"
          :key="index"
          class="document-card"
          :class="{ 'is-expanded': expandedDoc === (index + startIndex) }"
          @click="toggleExpand(index + startIndex)"
        >
          <!-- Compact Card Row -->
          <div class="card-row">
            <div class="card-left">
              <span class="doc-index">#{{ index + startIndex + 1 }}</span>
              <ChevronRight
                :size="14"
                class="expand-icon"
                :class="{ rotated: expandedDoc === (index + startIndex) }"
              />
              <span
                v-if="getDocId(doc)"
                class="doc-id"
              >{{ getDocId(doc) }}</span>
              <span class="doc-preview">{{ getInlinePreview(doc) }}</span>
            </div>
            <div class="card-right">
              <span class="field-count">{{ Object.keys(doc).length }}</span>
              <button
                class="mini-btn"
                title="Copy"
                @click.stop="copyDoc(doc)"
              >
                <Copy :size="14" />
              </button>
              <button
                class="mini-btn"
                title="Expand"
                @click.stop="openFullView(doc, index + startIndex)"
              >
                <Maximize2 :size="14" />
              </button>
            </div>
          </div>

          <!-- Expanded Content -->
          <Transition name="card-content">
            <div
              v-if="expandedDoc === (index + startIndex)"
              class="card-content"
            >
              <div class="json-container">
                <JsonTreeModern
                  :data="doc"
                  :root="true"
                />
              </div>
            </div>
          </Transition>
        </div>
      </div>

      <!-- Pagination -->
      <div
        v-if="totalPages > 1"
        class="pagination-bar"
      >
        <div class="page-info-text">
          {{ startIndex + 1 }}-{{ Math.min(startIndex + pageSize, documents.length) }} of {{ documents.length }}
        </div>
        <div class="page-nav">
          <button
            :disabled="currentPage === 1"
            class="nav-btn"
            @click="currentPage--"
          >
            <ChevronLeft :size="18" />
          </button>
          <div class="page-dots">
            <button
              v-for="page in visiblePages"
              :key="page"
              :class="['page-dot', { active: currentPage === page }]"
              @click="currentPage = page"
            >
              {{ page }}
            </button>
          </div>
          <button
            :disabled="currentPage === totalPages"
            class="nav-btn"
            @click="currentPage++"
          >
            <ChevronRight :size="18" />
          </button>
        </div>
      </div>
    </div>

    <!-- Raw JSON View -->
    <div
      v-else
      class="raw-view"
    >
      <div class="raw-container">
        <pre class="raw-json">{{ JSON.stringify(documents, null, 2) }}</pre>
      </div>
    </div>

    <!-- Full Document Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="fullViewDoc"
          class="modal-overlay"
          @click.self="fullViewDoc = null"
        >
          <div class="modal-container">
            <div class="modal-header">
              <div class="modal-title">
                <FileJson :size="20" />
                <span>Document #{{ fullViewIndex + 1 }}</span>
                <span
                  v-if="getDocId(fullViewDoc)"
                  class="modal-id"
                >{{ getDocId(fullViewDoc) }}</span>
              </div>
              <div class="modal-actions">
                <button
                  class="modal-btn"
                  @click="copyDoc(fullViewDoc)"
                >
                  <Copy :size="16" />
                  Copy
                </button>
                <button
                  class="modal-close"
                  @click="fullViewDoc = null"
                >
                  <X :size="20" />
                </button>
              </div>
            </div>
            <div class="modal-body">
              <JsonTreeModern
                :data="fullViewDoc"
                :root="true"
                :expanded-default="true"
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
import { ref, computed, watch } from 'vue'
import {
  Database,
  Layers,
  Copy,
  Code2,
  LayoutGrid,
  ChevronLeft,
  ChevronRight,
  Maximize2,
  FileJson,
  X,
  Check
} from 'lucide-vue-next'
import JsonTreeModern from './JsonTreeModern.vue'

const props = defineProps({
  results: { type: Object, required: true },
  analysis: { type: Object, default: null }
})

// State
const viewMode = ref('cards')
const currentPage = ref(1)
const pageSize = 5
const expandedDoc = ref(0)
const fullViewDoc = ref(null)
const fullViewIndex = ref(0)
const toastMessage = ref('')

// Computed
const documents = computed(() => props.results?.rows || [])
const totalPages = computed(() => Math.ceil(documents.value.length / pageSize))
const startIndex = computed(() => (currentPage.value - 1) * pageSize)
const paginatedDocuments = computed(() =>
  documents.value.slice(startIndex.value, startIndex.value + pageSize)
)

const visiblePages = computed(() => {
  const pages = []
  const total = totalPages.value
  const current = currentPage.value

  if (total <= 5) {
    for (let i = 1; i <= total; i++) pages.push(i)
  } else {
    if (current <= 3) {
      pages.push(1, 2, 3, 4, 5)
    } else if (current >= total - 2) {
      for (let i = total - 4; i <= total; i++) pages.push(i)
    } else {
      for (let i = current - 2; i <= current + 2; i++) pages.push(i)
    }
  }
  return pages
})

// Methods
const toggleExpand = (index) => {
  expandedDoc.value = expandedDoc.value === index ? -1 : index
}

const openFullView = (doc, index) => {
  fullViewDoc.value = doc
  fullViewIndex.value = index
}

const getDocId = (doc) => {
  const idFields = ['_id', 'id', 'ID', 'pk', 'PK', 'key', 'documentId', 'uuid']
  for (const field of idFields) {
    if (doc[field] !== undefined) {
      const val = doc[field]
      if (typeof val === 'object' && val !== null) {
        return val.$oid || val.S || String(Object.values(val)[0]).slice(0, 20)
      }
      return String(val).slice(0, 28)
    }
  }
  return null
}

const getInlinePreview = (doc) => {
  const entries = Object.entries(doc)
    .filter(([k]) => !['_id', 'id', 'ID', 'pk', 'PK'].includes(k))
    .slice(0, 3)

  return entries.map(([k, v]) => {
    let val = v
    if (v === null) val = 'null'
    else if (typeof v === 'string') val = v.length > 20 ? `"${v.slice(0, 20)}..."` : `"${v}"`
    else if (typeof v === 'number') val = v.toLocaleString()
    else if (typeof v === 'boolean') val = v.toString()
    else if (Array.isArray(v)) val = `[${v.length}]`
    else if (typeof v === 'object') val = `{...}`
    return `${k}: ${val}`
  }).join(' · ')
}

const copyDoc = async (doc) => {
  try {
    await navigator.clipboard.writeText(JSON.stringify(doc, null, 2))
    showToast('Copied!')
  } catch (e) {
    console.error('Copy failed:', e)
  }
}

const copyAll = async () => {
  try {
    await navigator.clipboard.writeText(JSON.stringify(documents.value, null, 2))
    showToast('All copied!')
  } catch (e) {
    console.error('Copy failed:', e)
  }
}

const showToast = (msg) => {
  toastMessage.value = msg
  setTimeout(() => { toastMessage.value = '' }, 2000)
}

watch(() => props.results, () => {
  currentPage.value = 1
  expandedDoc.value = 0
})
</script>

<style scoped>
.document-viewer {
  display: flex;
  flex-direction: column;
  background: var(--bg-app);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

/* Header */
.viewer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md) var(--space-lg);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-subtle);
}

.header-info {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}

.result-badge {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.depth-indicator {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--text-sm);
  color: var(--color-primary);
  padding: var(--space-xs) var(--space-sm);
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.action-btn {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.action-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-primary);
}

.action-btn.primary {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--bg-app);
}

.action-btn.primary:hover {
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
}

/* Cards View */
.cards-view {
  display: flex;
  flex-direction: column;
}

.cards-scroll {
  padding: var(--space-md);
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 500px;
  overflow-y: auto;
}

/* Compact Document Card */
.document-card {
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s ease;
}

.document-card:hover {
  background: var(--bg-hover);
}

.document-card.is-expanded {
  background: var(--bg-input);
  border-radius: var(--radius-md);
  margin: var(--space-xs) 0;
}

/* Compact Card Row */
.card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  gap: var(--space-md);
}

.card-left {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.doc-index {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-muted);
  min-width: 28px;
}

.expand-icon {
  color: var(--text-muted);
  flex-shrink: 0;
  transition: transform 0.2s ease, color 0.15s ease;
}

.expand-icon.rotated {
  transform: rotate(90deg);
  color: var(--color-primary);
}

.doc-id {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--color-primary);
  padding: 2px 6px;
  background: var(--color-primary-light);
  border-radius: var(--radius-xs);
  white-space: nowrap;
}

.doc-preview {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-right {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  flex-shrink: 0;
}

.field-count {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-muted);
  padding: 2px 8px;
  background: var(--bg-input);
  border-radius: var(--radius-full);
}

.mini-btn {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s ease;
}

.document-card:hover .mini-btn {
  opacity: 1;
}

.mini-btn:hover {
  background: var(--bg-card);
  color: var(--color-primary);
}

/* Card Content (Expanded) */
.card-content {
  background: var(--bg-card);
  border-top: 1px solid var(--border-subtle);
  border-radius: 0 0 var(--radius-md) var(--radius-md);
}

.json-container {
  padding: var(--space-md) var(--space-lg);
  max-height: 350px;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-default) transparent;
}

.json-container::-webkit-scrollbar {
  width: 6px;
}

.json-container::-webkit-scrollbar-track {
  background: transparent;
}

.json-container::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 3px;
}

.json-container::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

/* Pagination */
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md) var(--space-lg);
  background: var(--bg-card);
  border-top: 1px solid var(--border-subtle);
}

.page-info-text {
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.page-nav {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.nav-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.nav-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-primary);
}

.nav-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-dots {
  display: flex;
  gap: var(--space-xs);
}

.page-dot {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.page-dot:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.page-dot.active {
  background: var(--color-primary);
  color: var(--bg-app);
}

/* Raw View */
.raw-view {
  padding: var(--space-lg);
}

.raw-container {
  max-height: 520px;
  overflow: auto;
  background: var(--bg-card);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
}

.raw-json {
  margin: 0;
  padding: var(--space-lg);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal);
  padding: var(--space-lg);
}

.modal-container {
  width: 100%;
  max-width: 900px;
  max-height: 85vh;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-lg);
  border-bottom: 1px solid var(--border-subtle);
}

.modal-title {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.modal-id {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-primary);
  padding: var(--space-xs) var(--space-sm);
  background: var(--color-primary-light);
  border-radius: var(--radius-xs);
}

.modal-actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.modal-btn {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.modal-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.modal-close {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.modal-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.modal-body {
  flex: 1;
  overflow: auto;
  padding: var(--space-lg);
}

/* Toast */
.toast {
  position: fixed;
  bottom: var(--space-xl);
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-lg);
  background: var(--color-success);
  color: white;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  z-index: var(--z-toast);
}

/* Transitions */
.modal-enter-active,
.modal-leave-active {
  transition: all var(--transition-slow);
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.95) translateY(20px);
}

.toast-enter-active,
.toast-leave-active {
  transition: all var(--transition-slow);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(16px);
}

/* Card content transitions */
.card-content-enter-active {
  transition: opacity 0.2s ease, max-height 0.25s ease;
}

.card-content-leave-active {
  transition: opacity 0.15s ease, max-height 0.2s ease;
}

.card-content-enter-from,
.card-content-leave-to {
  opacity: 0;
  max-height: 0;
  overflow: hidden;
}

.card-content-enter-to,
.card-content-leave-from {
  max-height: 400px;
}

/* Mobile */
@media (max-width: 768px) {
  .viewer-header {
    flex-direction: column;
    gap: var(--space-sm);
    padding: var(--space-sm);
  }

  .header-info,
  .header-actions {
    width: 100%;
    justify-content: space-between;
  }

  .cards-scroll {
    padding: var(--space-sm);
    max-height: 400px;
  }

  .card-row {
    padding: var(--space-xs) var(--space-sm);
  }

  .doc-preview {
    display: none;
  }

  .mini-btn {
    opacity: 1;
  }

  .modal-container {
    max-height: 90vh;
  }
}
</style>

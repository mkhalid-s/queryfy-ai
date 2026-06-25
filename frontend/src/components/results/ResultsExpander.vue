<template>
  <div class="results-expander">
    <!-- Results Header -->
    <button
      class="results-header"
      @click="expanded = !expanded"
    >
      <div class="header-left">
        <Table :size="14" />
        <span class="results-label">
          Results
          <span
            v-if="results?.row_count"
            class="row-count"
          >({{ results.row_count.toLocaleString() }} rows)</span>
        </span>
        <span
          v-if="results?.has_more"
          class="truncated-badge"
        >
          <AlertTriangle :size="12" />
          Truncated
        </span>
      </div>
      <div class="header-right">
        <!-- View Mode Toggle - Only show for NoSQL databases -->
        <div
          v-if="results?.rows?.length && isNoSqlDatabase"
          class="view-toggle-group"
        >
          <button
            :class="['view-toggle-btn', { active: effectiveViewMode === 'table' }]"
            title="Table view"
            @click.stop="setViewMode('table')"
          >
            <Rows3 :size="14" />
          </button>
          <button
            :class="['view-toggle-btn', { active: effectiveViewMode === 'document' }]"
            title="Document view"
            @click.stop="setViewMode('document')"
          >
            <FileJson :size="14" />
          </button>
        </div>
        <button
          v-if="results?.rows?.length"
          class="fullscreen-btn"
          title="View in fullscreen"
          @click.stop="openFullscreen"
        >
          <Maximize2 :size="14" />
        </button>
        <ChevronDown
          :size="16"
          :class="['expand-icon', { rotated: expanded }]"
        />
      </div>
    </button>

    <!-- Expandable Content -->
    <transition name="expand">
      <div
        v-if="expanded"
        class="results-content"
      >
        <!-- Document View (for NoSQL/nested data) -->
        <div
          v-if="effectiveViewMode === 'document'"
          class="document-section"
        >
          <DocumentView
            :results="results"
            :analysis="resultAnalysis"
          />
        </div>

        <!-- Table View -->
        <div
          v-else
          class="table-section"
        >
          <!-- Truncation Warning -->
          <div
            v-if="results?.has_more"
            class="truncation-notice"
          >
            <AlertTriangle :size="14" />
            <span>Showing {{ results.row_count.toLocaleString() }} rows. Export for full dataset.</span>
          </div>

          <!-- Quick Stats Bar -->
          <div
            v-if="numericStats.length > 0"
            class="stats-bar"
          >
            <div
              class="stats-toggle"
              @click="showStats = !showStats"
            >
              <Calculator :size="12" />
              <span>Quick Stats</span>
              <ChevronDown
                :size="12"
                :class="{ rotated: showStats }"
              />
            </div>
            <transition name="expand">
              <div
                v-if="showStats"
                class="stats-content"
              >
                <div
                  v-for="stat in numericStats"
                  :key="stat.column"
                  class="stat-item"
                >
                  <span class="stat-column">{{ stat.column }}</span>
                  <div class="stat-values">
                    <span class="stat-value"><span class="stat-label">Min:</span> {{ stat.min }}</span>
                    <span class="stat-value"><span class="stat-label">Max:</span> {{ stat.max }}</span>
                    <span class="stat-value"><span class="stat-label">Avg:</span> {{ stat.avg }}</span>
                  </div>
                </div>
              </div>
            </transition>
          </div>

          <!-- Phase 4 Batch C banners: tell the user when the table
               is showing a subset (preview only / loading full / cache
               expired) — without these the row counts in the header
               and the rows on screen disagree silently. -->
          <div
            v-if="isFetchingFullRows"
            class="results-banner results-banner-info"
          >
            Loading full dataset…
          </div>
          <div
            v-else-if="fetchError"
            class="results-banner results-banner-warn"
          >
            {{ fetchError }}
          </div>
          <div
            v-else-if="shouldShowPreviewOnlyBanner"
            class="results-banner results-banner-warn"
          >
            Preview only — re-run the query to load all
            {{ totalRowCount.toLocaleString() }} rows.
          </div>

          <!-- Data Table -->
          <div
            v-if="results?.rows?.length"
            class="table-wrapper"
          >
            <table class="data-table">
              <thead>
                <tr>
                  <th
                    v-for="col in allColumns"
                    :key="col"
                    :class="{ sortable: true, sorted: sortColumn === col }"
                    @click="toggleSort(col)"
                  >
                    <div class="th-content">
                      <component
                        :is="getColumnIcon(col)"
                        :size="12"
                        class="col-type-icon"
                      />
                      <span class="col-name">{{ col }}</span>
                      <ArrowUpDown
                        v-if="sortColumn !== col"
                        :size="12"
                        class="sort-icon inactive"
                      />
                      <ArrowUp
                        v-else-if="sortDirection === 'asc'"
                        :size="12"
                        class="sort-icon"
                      />
                      <ArrowDown
                        v-else
                        :size="12"
                        class="sort-icon"
                      />
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, i) in sortedPaginatedRows"
                  :key="i"
                >
                  <td
                    v-for="col in allColumns"
                    :key="col"
                    :class="getCellClass(row[col])"
                    :title="getTruncatedTitle(row[col])"
                  >
                    <span class="cell-content">{{ formatCell(row[col]) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Empty State -->
          <div
            v-else
            class="empty-results"
          >
            <Table :size="24" />
            <p>No results returned</p>
          </div>

          <!-- Pagination -->
          <div
            v-if="totalPages > 1"
            class="pagination"
          >
            <span class="page-summary">
              {{ ((currentPage - 1) * pageSize) + 1 }}-{{ Math.min(currentPage * pageSize, sortedRows.length) }} of {{ sortedRows.length }}
            </span>
            <div class="page-controls">
              <button
                :disabled="currentPage === 1"
                class="page-btn"
                title="First page"
                @click="currentPage = 1"
              >
                <ChevronsLeft :size="14" />
              </button>
              <button
                :disabled="currentPage === 1"
                class="page-btn"
                title="Previous page"
                @click="currentPage--"
              >
                <ChevronLeft :size="14" />
              </button>

              <span class="page-info">
                {{ currentPage }} / {{ totalPages }}
              </span>

              <button
                :disabled="currentPage === totalPages"
                class="page-btn"
                title="Next page"
                @click="currentPage++"
              >
                <ChevronRight :size="14" />
              </button>
              <button
                :disabled="currentPage === totalPages"
                class="page-btn"
                title="Last page"
                @click="currentPage = totalPages"
              >
                <ChevronsRight :size="14" />
              </button>
            </div>
          </div>

          <!-- DML Actions Bar -->
          <div
            v-if="showDmlActions"
            class="dml-actions-bar"
          >
            <div class="dml-actions-header">
              <Database :size="14" />
              <span>Data Operations</span>
            </div>
            <div class="dml-actions-buttons">
              <button
                class="dml-btn insert"
                @click="handleDmlInsert"
              >
                <Plus :size="14" />
                Insert Row
              </button>
              <button
                class="dml-btn update"
                @click="handleDmlUpdate"
              >
                <Edit :size="14" />
                Update
              </button>
              <button
                class="dml-btn delete"
                @click="handleDmlDelete"
              >
                <Trash2 :size="14" />
                Delete
              </button>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- DML Preview Modal -->
    <DmlPreviewModal
      :show="dmlState.showPreviewModal"
      :operation="dmlState.operation"
      :sql="dmlState.previewData?.sql"
      :preview="dmlState.previewData"
      :sandbox-result="dmlState.sandboxResult"
      :supports-sandbox="dmlCapabilities?.sandbox_available"
      :loading="dmlState.loading"
      @close="closeDmlModal"
      @test-sandbox="handleTestSandbox"
      @confirm="handleConfirmExecution"
    />

    <!-- Fullscreen Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showFullscreen"
          class="modal-overlay"
          @click.self="closeFullscreen"
        >
          <div class="modal-container">
            <div class="modal-header">
              <div class="modal-title">
                <Table :size="20" />
                <span>Results</span>
                <span
                  v-if="results?.row_count"
                  class="modal-count"
                >
                  {{ results.row_count.toLocaleString() }} rows
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
                  @click="copyAllData"
                >
                  <Copy :size="16" />
                  JSON
                </button>
                <button
                  class="modal-close"
                  @click="closeFullscreen"
                >
                  <X :size="20" />
                </button>
              </div>
            </div>
            <div class="modal-body">
              <div class="modal-table-wrapper">
                <table class="data-table modal-table">
                  <thead>
                    <tr>
                      <th
                        v-for="col in allColumns"
                        :key="col"
                        :class="{ sortable: true, sorted: sortColumn === col }"
                        @click="toggleSort(col)"
                      >
                        <div class="th-content">
                          <component
                            :is="getColumnIcon(col)"
                            :size="12"
                            class="col-type-icon"
                          />
                          <span class="col-name">{{ col }}</span>
                          <ArrowUpDown
                            v-if="sortColumn !== col"
                            :size="12"
                            class="sort-icon inactive"
                          />
                          <ArrowUp
                            v-else-if="sortDirection === 'asc'"
                            :size="12"
                            class="sort-icon"
                          />
                          <ArrowDown
                            v-else
                            :size="12"
                            class="sort-icon"
                          />
                        </div>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(row, i) in modalPaginatedRows"
                      :key="i"
                    >
                      <td
                        v-for="col in allColumns"
                        :key="col"
                        :class="getCellClass(row[col])"
                        :title="getTruncatedTitle(row[col])"
                      >
                        <span class="cell-content">{{ formatCell(row[col]) }}</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <!-- Modal Pagination -->
              <div
                v-if="modalTotalPages > 1"
                class="modal-pagination"
              >
                <span class="page-summary">
                  {{ ((modalPage - 1) * modalPageSize) + 1 }}-{{ Math.min(modalPage * modalPageSize, sortedRows.length) }} of {{ sortedRows.length }}
                </span>
                <div class="page-controls">
                  <button
                    :disabled="modalPage === 1"
                    class="page-btn"
                    title="First page"
                    @click="modalPage = 1"
                  >
                    <ChevronsLeft :size="14" />
                  </button>
                  <button
                    :disabled="modalPage === 1"
                    class="page-btn"
                    title="Previous page"
                    @click="modalPage--"
                  >
                    <ChevronLeft :size="14" />
                  </button>

                  <span class="page-info">
                    {{ modalPage }} / {{ modalTotalPages }}
                  </span>

                  <button
                    :disabled="modalPage === modalTotalPages"
                    class="page-btn"
                    title="Next page"
                    @click="modalPage++"
                  >
                    <ChevronRight :size="14" />
                  </button>
                  <button
                    :disabled="modalPage === modalTotalPages"
                    class="page-btn"
                    title="Last page"
                    @click="modalPage = modalTotalPages"
                  >
                    <ChevronsRight :size="14" />
                  </button>
                </div>
              </div>
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
import { ref, computed, watch, onMounted } from 'vue'
import {
  Table,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  AlertTriangle,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Calculator,
  Hash,
  Type,
  Calendar,
  ToggleLeft,
  FileJson,
  Rows3,
  Maximize2,
  X,
  Copy,
  Check,
  Database,
  Plus,
  Edit,
  Trash2
} from 'lucide-vue-next'

import DocumentView from './DocumentView.vue'
import DmlPreviewModal from '../modals/DmlPreviewModal.vue'
import { analyzeResults } from '@/utils/resultAnalyzer'
import api from '@/utils/api'
import { useToast } from '@/composables/useToast'

const props = defineProps({
  results: {
    type: Object,
    default: null
  },
  isLatest: Boolean,
  dmlCapabilities: {
    type: Object,
    default: null
  },
  sessionId: {
    type: String,
    default: null
  },
  sql: {
    type: String,
    default: null
  }
})

// NoSQL database types that should show document view option
const NOSQL_DB_TYPES = ['mongodb', 'dynamodb', 'cosmosdb', 'couchdb', 'firestore', 'cassandra', 'redis']

// Check if current database is NoSQL (from results.db_type)
const isNoSqlDatabase = computed(() => {
  const type = props.results?.db_type?.toLowerCase() || ''
  return NOSQL_DB_TYPES.some(nosql => type.includes(nosql))
})

// Local state
const expanded = ref(true)
const currentPage = ref(1)
const pageSize = 25
const sortColumn = ref(null)
const sortDirection = ref('asc')
const showStats = ref(false)
const viewModeOverride = ref(null) // null = auto, 'table', 'document'
const showFullscreen = ref(false)
const toastMessage = ref('')

// Toast composable
const toast = useToast()

// DML state
const dmlState = ref({
  operation: null,
  showPreviewModal: false,
  previewData: null,
  sandboxResult: null,
  loading: false
})

// Phase 4.3: full row set fetched lazily from /api/v1/results/{rows_ref}.
// While ``fullRows`` is null we render whatever ``props.results.rows``
// gave us (typically the 20-row preview from execute_and_analyze).
// Once the fetch finishes, sorted/paginated views switch over to the
// complete dataset transparently.
const fullRows = ref(null)
const isFetchingFullRows = ref(false)
const fetchError = ref(null)

const rowsRef = computed(() => props.results?.rows_ref || null)
const totalRowCount = computed(
  () => props.results?.row_count ?? props.results?.rows?.length ?? 0,
)
const previewRowCount = computed(
  () => props.results?.preview_row_count ?? props.results?.rows?.length ?? 0,
)
const hasMoreThanPreview = computed(
  () => totalRowCount.value > previewRowCount.value,
)

// Phase 4 hotfix: the "Preview only" banner should fire in THREE cases:
//   a) rows_persisted === false  — restored-from-localStorage message
//      whose rows were stripped for quota safety.
//   b) rows_cached === false AND rows_ref is null — live query where
//      the cache write failed (Redis outage / oversized payload) and
//      we only have the 20-row preview the LLM saw.
//   c) rows_truncated === true — explicit backend signal that rows
//      are a subset. Most specific; preferred when present.
// The old template only checked (a); live cache failures silently
// showed the preview as if it were complete.
const shouldShowPreviewOnlyBanner = computed(() => {
  if (!props.results) return false
  if (!hasMoreThanPreview.value) return false
  // Don't double-paint while the fetch is still in flight.
  if (isFetchingFullRows.value) return false
  // If a rows_ref exists and fetch hasn't errored, we're on the
  // normal lazy-load path; no banner needed.
  if (rowsRef.value && !fetchError.value) return false
  return (
    props.results.rows_persisted === false ||
    props.results.rows_cached === false ||
    props.results.rows_truncated === true
  )
})

async function fetchFullRowsFromCache() {
  if (!rowsRef.value || !hasMoreThanPreview.value) return
  if (isFetchingFullRows.value) return
  isFetchingFullRows.value = true
  fetchError.value = null
  try {
    // total cap — the backend caps page at 1000 so loop until done
    const accumulated = []
    let columns = props.results?.columns || []
    let offset = 0
    const pageSize = 1000
    let hasMore = true
    while (hasMore) {
      const page = await api.getCachedResult(rowsRef.value, {
        offset,
        limit: pageSize,
      })
      accumulated.push(...(page.rows || []))
      columns = page.columns || columns
      hasMore = !!page.has_more
      offset = accumulated.length
      // Safety guard so a runaway response can't lock the browser.
      if (accumulated.length >= 100000) break
    }
    fullRows.value = accumulated
  } catch (err) {
    // 404 = cache expired; UI keeps the preview rows + a small note.
    fetchError.value =
      err?.response?.status === 404
        ? 'Full results expired (>30 min). Re-run the query for the complete dataset.'
        : 'Could not load full results — showing preview only.'
    console.warn('ResultsExpander: cache fetch failed', err)
  } finally {
    isFetchingFullRows.value = false
  }
}

// Modal pagination (separate from inline)
const modalPage = ref(1)
const modalPageSize = 50

// Analyze results to determine best view (for nested data detection)
const resultAnalysis = computed(() => {
  return analyzeResults(props.results)
})

// Determine effective view mode
const effectiveViewMode = computed(() => {
  if (viewModeOverride.value) return viewModeOverride.value
  // For NoSQL databases, default to document view
  // For SQL databases, default to table view
  if (isNoSqlDatabase.value) return 'document'
  return resultAnalysis.value.isDocument ? 'document' : 'table'
})

// Check if document view is recommended (for indicator dot)
// Set view mode explicitly
const setViewMode = (mode) => {
  viewModeOverride.value = mode
}

// Detect all unique columns from all rows (fixes NoSQL varying schemas)
const allColumns = computed(() => {
  if (!props.results?.rows?.length) return props.results?.columns || []

  // Start with provided columns
  const uniqueColumns = new Set(props.results.columns || [])

  // Scan rows to detect additional columns (limit to first 100 for performance)
  const maxRowsToScan = Math.min(props.results.rows.length, 100)
  for (let i = 0; i < maxRowsToScan; i++) {
    const row = props.results.rows[i]
    if (row && typeof row === 'object') {
      Object.keys(row).forEach(key => uniqueColumns.add(key))
    }
  }

  return Array.from(uniqueColumns)
})

// Detect column types based on data
const columnTypes = computed(() => {
  if (!props.results?.rows?.length || !allColumns.value?.length) return {}
  const types = {}
  for (const col of allColumns.value) {
    const sampleValues = props.results.rows
      .slice(0, 20)
      .map(row => row[col])
      .filter(v => v !== null && v !== undefined)

    if (sampleValues.length === 0) {
      types[col] = 'text'
    } else if (sampleValues.every(v => typeof v === 'number')) {
      types[col] = 'number'
    } else if (sampleValues.every(v => typeof v === 'boolean')) {
      types[col] = 'boolean'
    } else if (sampleValues.some(v => {
      if (typeof v !== 'string') return false
      return /^\d{4}-\d{2}-\d{2}/.test(v) || !isNaN(Date.parse(v))
    })) {
      types[col] = 'date'
    } else {
      types[col] = 'text'
    }
  }
  return types
})

// Get icon component based on column type
const getColumnIcon = (col) => {
  const type = columnTypes.value[col]
  switch (type) {
    case 'number': return Hash
    case 'date': return Calendar
    case 'boolean': return ToggleLeft
    default: return Type
  }
}

// Calculate numeric stats
// Phase 4 Batch C (M6): read from ``effectiveRows`` so the Quick Stats
// min/max/avg update transparently after the lazy fetch swaps the
// preview for the full dataset. Previously locked to props.results.rows
// (the 20-row preview), so stats never reflected the real distribution.
const numericStats = computed(() => {
  const rowsForStats = effectiveRows.value
  if (!rowsForStats?.length) return []
  const stats = []
  for (const col of allColumns.value) {
    if (columnTypes.value[col] === 'number') {
      const values = rowsForStats
        .map(row => row[col])
        .filter(v => typeof v === 'number' && !isNaN(v))
      if (values.length > 0) {
        const min = Math.min(...values)
        const max = Math.max(...values)
        const avg = values.reduce((a, b) => a + b, 0) / values.length
        stats.push({
          column: col,
          min: min.toLocaleString(undefined, { maximumFractionDigits: 2 }),
          max: max.toLocaleString(undefined, { maximumFractionDigits: 2 }),
          avg: avg.toLocaleString(undefined, { maximumFractionDigits: 2 })
        })
      }
    }
  }
  return stats.slice(0, 4) // Limit to 4 stats
})

// Sorting
const toggleSort = (col) => {
  if (sortColumn.value === col) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = col
    sortDirection.value = 'asc'
  }
  currentPage.value = 1
}

// Phase 4.3: prefer the lazily-fetched full row set; fall back to the
// preview rows in props.results.rows while the fetch is in flight or
// when there's no rows_ref (cache disabled / unavailable).
const effectiveRows = computed(
  () => fullRows.value ?? props.results?.rows ?? [],
)

const sortedRows = computed(() => {
  if (!effectiveRows.value.length) return []
  if (!sortColumn.value) return effectiveRows.value

  return [...effectiveRows.value].sort((a, b) => {
    const aVal = a[sortColumn.value]
    const bVal = b[sortColumn.value]

    // Handle nulls
    if (aVal === null || aVal === undefined) return 1
    if (bVal === null || bVal === undefined) return -1

    const comparison = (typeof aVal === 'number' && typeof bVal === 'number')
      ? aVal - bVal
      : String(aVal).localeCompare(String(bVal))

    return sortDirection.value === 'asc' ? comparison : -comparison
  })
})

// Computed
const totalPages = computed(() => {
  if (!sortedRows.value.length) return 0
  return Math.ceil(sortedRows.value.length / pageSize)
})

const sortedPaginatedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return sortedRows.value.slice(start, start + pageSize)
})

// Reset page and view mode when results change
watch(() => props.results, () => {
  currentPage.value = 1
  sortColumn.value = null
  sortDirection.value = 'asc'
  viewModeOverride.value = null // Reset to auto-detect
  // Phase 4.3: drop any previously-fetched rows so we don't show stale
  // data when the user runs a new query in the same card.
  fullRows.value = null
  fetchError.value = null
  fetchFullRowsFromCache()
})

// First mount — kick off the lazy fetch if we already have a rows_ref.
onMounted(() => {
  fetchFullRowsFromCache()
})

// Auto-expand when latest
watch(() => props.isLatest, (latest) => {
  if (latest) expanded.value = true
}, { immediate: true })

// Get cell class for styling
const getCellClass = (value) => {
  if (value === null || value === undefined) return 'cell-null'
  if (typeof value === 'number') return 'cell-number'
  if (typeof value === 'boolean') return 'cell-boolean'
  if (typeof value === 'object') return 'cell-json'
  return ''
}

// Get title for truncated cells (shows full content on hover)
const getTruncatedTitle = (value) => {
  if (typeof value === 'string' && value.length > 100) {
    return value
  }
  // Show full JSON for truncated objects
  if (typeof value === 'object' && value !== null) {
    try {
      const jsonStr = JSON.stringify(value, null, 2)
      if (jsonStr.length > 100) {
        return jsonStr
      }
    } catch {
      return undefined
    }
  }
  return undefined
}

// Format cell values - handles NoSQL nested documents
const formatCell = (value) => {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return value.toLocaleString()
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  // Handle nested objects/arrays (NoSQL documents)
  if (typeof value === 'object') {
    try {
      const jsonStr = JSON.stringify(value)
      if (jsonStr.length > 100) {
        return jsonStr.substring(0, 100) + '…'
      }
      return jsonStr
    } catch {
      return '[Complex Object]'
    }
  }
  if (typeof value === 'string' && value.length > 100) {
    return value.substring(0, 100) + '…'
  }
  return String(value)
}

// Modal pagination computed
const modalTotalPages = computed(() => {
  if (!sortedRows.value.length) return 0
  return Math.ceil(sortedRows.value.length / modalPageSize)
})

const modalPaginatedRows = computed(() => {
  const start = (modalPage.value - 1) * modalPageSize
  return sortedRows.value.slice(start, start + modalPageSize)
})

// Fullscreen methods
const openFullscreen = () => {
  showFullscreen.value = true
  modalPage.value = 1
}

const closeFullscreen = () => {
  showFullscreen.value = false
}

// Copy methods
const copyAllData = async () => {
  try {
    const data = {
      columns: allColumns.value,
      rows: props.results?.rows || []
    }
    await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
    showToast('Copied all data!')
  } catch (e) {
    console.error('Copy failed:', e)
  }
}

const copyAsCSV = async () => {
  try {
    const columns = allColumns.value
    const rows = props.results?.rows || []
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

const showToast = (msg) => {
  toastMessage.value = msg
  setTimeout(() => { toastMessage.value = '' }, 2000)
}

// ============================================
// DML Operations
// ============================================

// Show DML actions only for SELECT queries with results
const showDmlActions = computed(() => {
  return props.dmlCapabilities?.supported_operations?.length > 0 &&
         props.results?.rows?.length > 0 &&
         props.sql && !props.sql.match(/^(INSERT|UPDATE|DELETE)/i)
})

// Extract table name from SQL for DML operations
function extractTableName(sql) {
  if (!sql) return 'table'
  const match = sql.match(/FROM\s+([`"]?)(\w+)\1/i)
  return match ? match[2] : 'table'
}

// Handle DML Insert
async function handleDmlInsert() {
  dmlState.value.operation = 'insert'
  dmlState.value.loading = true

  try {
    const table = extractTableName(props.sql)
    const insertSql = `INSERT INTO ${table} (column_name) VALUES ('value')`

    const preview = await api.dmlPreview(props.sessionId, insertSql)
    dmlState.value.previewData = preview
    dmlState.value.showPreviewModal = true
  } catch (error) {
    toast.error(error.userMessage || 'Failed to preview insert')
  } finally {
    dmlState.value.loading = false
  }
}

// Handle DML Update
async function handleDmlUpdate() {
  dmlState.value.operation = 'update'
  dmlState.value.loading = true

  try {
    const table = extractTableName(props.sql)
    const updateSql = `UPDATE ${table} SET column_name = 'new_value' WHERE id = 1`

    const preview = await api.dmlPreview(props.sessionId, updateSql)
    dmlState.value.previewData = preview
    dmlState.value.showPreviewModal = true
  } catch (error) {
    toast.error(error.userMessage || 'Failed to preview update')
  } finally {
    dmlState.value.loading = false
  }
}

// Handle DML Delete
async function handleDmlDelete() {
  dmlState.value.operation = 'delete'
  dmlState.value.loading = true

  try {
    const table = extractTableName(props.sql)
    const deleteSql = `DELETE FROM ${table} WHERE id = 1`

    const preview = await api.dmlPreview(props.sessionId, deleteSql)
    dmlState.value.previewData = preview
    dmlState.value.showPreviewModal = true
  } catch (error) {
    toast.error(error.userMessage || 'Failed to preview delete')
  } finally {
    dmlState.value.loading = false
  }
}

// Test DML in sandbox
async function handleTestSandbox() {
  dmlState.value.loading = true

  try {
    const result = await api.dmlExecute(
      props.sessionId,
      dmlState.value.previewData.sql,
      'sandbox'
    )
    dmlState.value.sandboxResult = result
    toast.success('Sandbox test successful - changes rolled back')
  } catch (error) {
    toast.error(error.userMessage || 'Sandbox test failed')
  } finally {
    dmlState.value.loading = false
  }
}

// Confirm and execute DML
async function handleConfirmExecution() {
  dmlState.value.loading = true

  try {
    const mode = dmlState.value.sandboxResult ? 'confirm' : 'preview'
    const result = await api.dmlExecute(
      props.sessionId,
      dmlState.value.previewData.sql,
      mode
    )

    const message = `${dmlState.value.operation} completed: ${result.rows_affected} rows affected`
    toast.success(message)
    showToast(message)
    closeDmlModal()
  } catch (error) {
    toast.error(error.userMessage || 'Execution failed')
  } finally {
    dmlState.value.loading = false
  }
}

// Close DML modal
function closeDmlModal() {
  dmlState.value.showPreviewModal = false
  dmlState.value.previewData = null
  dmlState.value.sandboxResult = null
  dmlState.value.operation = null
}
</script>

<style scoped>
.results-expander {
  border-top: 1px solid var(--border-subtle);
}

/* Results Header */
.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.results-header:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.results-label {
  font-size: var(--text-sm);
  font-weight: 500;
}

.row-count {
  color: var(--text-muted);
  font-weight: 400;
}

.truncated-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: rgba(245, 158, 11, 0.15);
  color: var(--color-warning);
}

/* View Toggle Group */
.view-toggle-group {
  display: flex;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.view-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.view-toggle-btn:first-child {
  border-right: 1px solid var(--border-subtle);
}

.view-toggle-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
}

.view-toggle-btn.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.expand-icon {
  transition: transform 0.2s ease;
}

.expand-icon.rotated {
  transform: rotate(180deg);
}

/* Results Content */
.results-content {
  border-top: 1px solid var(--border-subtle);
}

/* Phase 4 Batch C: subtle banners for preview / loading / cache-expired */
.results-banner {
  margin: var(--space-sm) var(--space-md) 0 var(--space-md);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  font-size: 12px;
  line-height: 1.4;
}
.results-banner-info {
  background: var(--bg-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}
.results-banner-warn {
  background: rgba(251, 191, 36, 0.08);
  color: var(--text-primary);
  border: 1px solid rgba(251, 191, 36, 0.4);
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

/* Document Section (NoSQL) */
.document-section {
  padding: 0;
}

/* Table Section */
.table-section {
  padding: var(--space-sm);
}

.truncation-notice {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  margin-bottom: var(--space-sm);
  border-radius: var(--radius-md);
  background: rgba(245, 158, 11, 0.1);
  color: var(--color-warning);
  font-size: var(--text-sm);
}

/* Stats Bar */
.stats-bar {
  margin-bottom: var(--space-sm);
  border-radius: var(--radius-md);
  background: rgba(var(--color-primary-rgb, 167, 139, 250), 0.08);
  overflow: hidden;
}

.stats-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.stats-toggle:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.stats-toggle svg:last-child {
  margin-left: auto;
  transition: transform 0.2s ease;
}

.stats-toggle svg:last-child.rotated {
  transform: rotate(180deg);
}

.stats-content {
  padding: 0 var(--space-md) var(--space-sm);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-md);
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-sm);
  background: rgba(0, 0, 0, 0.15);
  border-radius: var(--radius-sm);
  min-width: 140px;
}

.stat-column {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-primary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.stat-values {
  display: flex;
  gap: var(--space-md);
  flex-wrap: wrap;
}

.stat-value {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.stat-label {
  color: var(--text-muted);
  margin-right: 4px;
}

/* Table */
.table-wrapper {
  overflow-x: auto;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  max-height: 400px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  /* Firefox scrollbar */
  scrollbar-width: thin;
  scrollbar-color: var(--text-muted) var(--bg-input);
}

/* Webkit scrollbars (Chrome, Safari, Edge) */
.table-wrapper::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.table-wrapper::-webkit-scrollbar-track {
  background: var(--bg-input);
  border-radius: 4px;
}

.table-wrapper::-webkit-scrollbar-thumb {
  background: var(--text-muted);
  border-radius: 4px;
  border: 2px solid var(--bg-input);
}

.table-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

.table-wrapper::-webkit-scrollbar-corner {
  background: var(--bg-input);
}

.data-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.data-table th {
  position: sticky;
  top: 0;
  background: var(--bg-input);
  font-weight: 600;
  color: var(--text-primary);
  z-index: 1;
  user-select: none;
}

.data-table th.sortable {
  cursor: pointer;
  transition: background 0.15s ease;
}

.data-table th.sortable:hover {
  background: rgba(255, 255, 255, 0.08);
}

.data-table th.sorted {
  background: rgba(var(--color-primary-rgb, 167, 139, 250), 0.15);
}

.th-content {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-sm) var(--space-md);
}

.col-type-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.col-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sort-icon {
  flex-shrink: 0;
  color: var(--color-primary);
  transition: opacity 0.15s ease;
}

.sort-icon.inactive {
  opacity: 0.3;
  color: var(--text-muted);
}

.data-table td {
  padding: var(--space-sm) var(--space-md);
  text-align: left;
  border-bottom: 1px solid var(--border-subtle);
  white-space: nowrap;
  color: var(--text-secondary);
  min-width: 80px;
  max-width: 400px;
}

.data-table td .cell-content {
  display: block;
  max-width: 350px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.data-table tbody tr {
  transition: background 0.1s ease;
}

.data-table tbody tr:nth-child(even) {
  background: rgba(0, 0, 0, 0.03);
}

.data-table tbody tr:hover {
  background: var(--bg-input);
}

/* Cell type styling */
.cell-null {
  color: var(--text-muted);
  font-style: italic;
}

.cell-number {
  font-family: var(--font-mono);
  text-align: right;
}

.cell-boolean {
  font-weight: 500;
}

.cell-json {
  font-family: var(--font-mono);
  font-size: 0.85em;
  color: var(--color-primary);
  cursor: help;
}

/* Empty State */
.empty-results {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-xl);
  color: var(--text-muted);
  gap: var(--space-sm);
}

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-top: 1px solid var(--border-subtle);
  background: rgba(0, 0, 0, 0.05);
}

.page-summary {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.page-controls {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.page-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.page-btn:hover:not(:disabled) {
  background: var(--bg-input);
  color: var(--text-primary);
  border-color: var(--color-primary);
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-info {
  font-size: var(--text-sm);
  color: var(--text-muted);
  min-width: 60px;
  text-align: center;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .data-table {
    font-size: var(--text-xs);
  }

  .th-content {
    padding: var(--space-xs) var(--space-sm);
  }

  .data-table td {
    padding: var(--space-xs) var(--space-sm);
  }

  .table-wrapper {
    max-height: 250px;
  }

  .stats-content {
    flex-direction: column;
  }

  .stat-item {
    min-width: 100%;
  }

  .pagination {
    flex-direction: column;
    gap: var(--space-sm);
  }
}

/* Fullscreen Button */
.fullscreen-btn {
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

.fullscreen-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-secondary);
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay, rgba(0, 0, 0, 0.75));
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal, 1000);
  padding: var(--space-lg);
}

.modal-container {
  width: 100%;
  max-width: 1200px;
  max-height: 90vh;
  background: var(--bg-card);
  border-radius: var(--radius-xl, 16px);
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-lg, 0 25px 50px -12px rgba(0, 0, 0, 0.25));
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md) var(--space-lg);
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-input);
}

.modal-title {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}

.modal-count {
  font-size: var(--text-sm);
  font-weight: 400;
  color: var(--text-muted);
  padding: var(--space-xs) var(--space-sm);
  background: var(--bg-app);
  border-radius: var(--radius-full);
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
  transition: all 0.15s ease;
}

.modal-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-primary);
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
  transition: all 0.15s ease;
}

.modal-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.modal-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-table-wrapper {
  flex: 1;
  overflow: auto;
  /* Firefox scrollbar */
  scrollbar-width: thin;
  scrollbar-color: var(--text-muted) var(--bg-input);
}

.modal-table-wrapper::-webkit-scrollbar {
  width: 12px;
  height: 12px;
}

.modal-table-wrapper::-webkit-scrollbar-track {
  background: var(--bg-input);
}

.modal-table-wrapper::-webkit-scrollbar-thumb {
  background: var(--text-muted);
  border-radius: 6px;
  border: 3px solid var(--bg-input);
}

.modal-table-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

.modal-table-wrapper::-webkit-scrollbar-corner {
  background: var(--bg-input);
}

.modal-table {
  width: max-content;
  min-width: 100%;
}

.modal-table td {
  max-width: 500px;
}

.modal-table td .cell-content {
  max-width: 450px;
}

.modal-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-input);
}

/* Modal transitions */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.25s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.95) translateY(20px);
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
  background: var(--color-success, #22c55e);
  color: white;
  font-size: var(--text-sm);
  font-weight: 500;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md, 0 4px 6px -1px rgba(0, 0, 0, 0.1));
  z-index: var(--z-toast, 1100);
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(16px);
}

/* Modal mobile responsive */
@media (max-width: 768px) {
  .modal-overlay {
    padding: var(--space-sm);
  }

  .modal-container {
    max-height: 95vh;
  }

  .modal-header {
    flex-direction: column;
    gap: var(--space-sm);
    padding: var(--space-sm);
  }

  .modal-title,
  .modal-actions {
    width: 100%;
    justify-content: space-between;
  }
}

/* DML Actions Bar */
.dml-actions-bar {
  margin-top: var(--space-md);
  padding: var(--space-md);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary, var(--bg-card));
}

.dml-actions-header {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  margin-bottom: var(--space-sm);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
}

.dml-actions-buttons {
  display: flex;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.dml-btn {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all 0.2s;
}

.dml-btn:hover {
  background: var(--bg-hover);
  border-color: var(--text-secondary);
}

.dml-btn.insert:hover {
  border-color: #10b981;
  color: #10b981;
}

.dml-btn.update:hover {
  border-color: #3b82f6;
  color: #3b82f6;
}

.dml-btn.delete:hover {
  border-color: #ef4444;
  color: #ef4444;
}
</style>

<template>
  <div :class="['results-table', { compact, fullscreen }]">
    <!-- Empty State -->
    <div
      v-if="!rowsData.length"
      class="empty-state"
    >
      <Table2 :size="24" />
      <p>No data available</p>
    </div>

    <!-- Table -->
    <template v-else>
      <div class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th
                v-for="col in columnsData"
                :key="col"
                class="sortable"
                :class="{ sorted: sortColumn === col }"
                @click="toggleSort(col)"
              >
                <div class="th-content">
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
              v-for="(row, i) in paginatedRows"
              :key="i"
            >
              <td
                v-for="col in columnsData"
                :key="col"
                :class="getCellClass(row[col])"
                :title="getCellTitle(row[col])"
              >
                <span class="cell-content">{{ formatCell(row[col]) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div
        v-if="totalPages > 1"
        class="pagination"
      >
        <span class="page-info">
          {{ ((currentPage - 1) * pageSize) + 1 }}-{{ Math.min(currentPage * pageSize, sortedRows.length) }} of {{ sortedRows.length }}
        </span>
        <div class="page-controls">
          <button
            :disabled="currentPage === 1"
            class="page-btn"
            @click="currentPage--"
          >
            <ChevronLeft :size="14" />
          </button>
          <span class="page-current">{{ currentPage }}/{{ totalPages }}</span>
          <button
            :disabled="currentPage === totalPages"
            class="page-btn"
            @click="currentPage++"
          >
            <ChevronRight :size="14" />
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import {
  Table2,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown
} from 'lucide-vue-next'

const props = defineProps({
  // Support both individual props and results object
  columns: {
    type: Array,
    default: null
  },
  rows: {
    type: Array,
    default: null
  },
  rowCount: {
    type: Number,
    default: 0
  },
  // Legacy: results object
  results: {
    type: Object,
    default: null
  },
  compact: {
    type: Boolean,
    default: false
  },
  fullscreen: {
    type: Boolean,
    default: false
  },
  maxRows: {
    type: Number,
    default: 100
  }
})

// Local state
const currentPage = ref(1)
const sortColumn = ref(null)
const sortDirection = ref('asc')

// Computed - support both individual props and results object
const columnsData = computed(() => props.columns || props.results?.columns || [])
const rowsData = computed(() => props.rows || props.results?.rows || [])
const pageSize = computed(() => {
  if (props.fullscreen) return 50
  if (props.compact) return 10
  return 25
})

const sortedRows = computed(() => {
  if (!sortColumn.value) return rowsData.value

  return [...rowsData.value].sort((a, b) => {
    const aVal = a[sortColumn.value]
    const bVal = b[sortColumn.value]

    if (aVal === null || aVal === undefined) return 1
    if (bVal === null || bVal === undefined) return -1

    let comparison = 0
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      comparison = aVal - bVal
    } else {
      comparison = String(aVal).localeCompare(String(bVal))
    }

    return sortDirection.value === 'asc' ? comparison : -comparison
  })
})

const totalPages = computed(() => {
  return Math.ceil(sortedRows.value.length / pageSize.value)
})

const paginatedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return sortedRows.value.slice(start, start + pageSize.value)
})

// Methods
const toggleSort = (col) => {
  if (sortColumn.value === col) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = col
    sortDirection.value = 'asc'
  }
  currentPage.value = 1
}

const getCellClass = (value) => {
  if (value === null || value === undefined) return 'cell-null'
  if (typeof value === 'number') return 'cell-number'
  if (typeof value === 'boolean') return 'cell-boolean'
  return ''
}

const getCellTitle = (value) => {
  if (typeof value === 'string' && value.length > 50) return value
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2)
  }
  return undefined
}

const formatCell = (value) => {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return value.toLocaleString()
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  if (typeof value === 'object') {
    const str = JSON.stringify(value)
    return str.length > 50 ? str.substring(0, 50) + '...' : str
  }
  if (typeof value === 'string' && value.length > 50) {
    return value.substring(0, 50) + '...'
  }
  return String(value)
}

// Reset page when results change
watch(() => props.results, () => {
  currentPage.value = 1
  sortColumn.value = null
})
</script>

<style scoped>
.results-table {
  width: 100%;
}

.table-wrapper {
  overflow-x: auto;
  overflow-y: auto;
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

/* Container max-height applied at parent level, not here */
.results-table.compact .table-wrapper {
  /* Compact mode styling handled by parent container */
}

/* Fullscreen mode */
.results-table.fullscreen .table-wrapper {
  max-height: none;
  border-radius: 0;
  border: none;
}

.data-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.results-table.compact .data-table {
  font-size: var(--text-xs);
}

.data-table th {
  position: sticky;
  top: 0;
  background: var(--bg-input);
  font-weight: 600;
  color: var(--text-primary);
  z-index: 1;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease;
}

.data-table th:hover {
  background: rgba(255, 255, 255, 0.08);
}

.data-table th.sorted {
  background: rgba(var(--color-primary-rgb), 0.15);
}

.th-content {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-sm) var(--space-md);
}

.results-table.compact .th-content {
  padding: var(--space-xs) var(--space-sm);
}

.col-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sort-icon {
  flex-shrink: 0;
  color: var(--color-primary);
}

.sort-icon.inactive {
  opacity: 0.3;
  color: var(--text-muted);
}

.data-table td {
  padding: var(--space-sm) var(--space-md);
  text-align: left;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  white-space: nowrap;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.results-table.compact .data-table td {
  padding: var(--space-xs) var(--space-sm);
  max-width: 150px;
}

.data-table tbody tr:nth-child(even) {
  background: rgba(0, 0, 0, 0.03);
}

.data-table tbody tr:hover {
  background: var(--bg-input);
}

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

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-lg);
  color: var(--text-muted);
  gap: var(--space-sm);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm);
  border-top: 1px solid var(--border-subtle);
}

.page-info {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.page-controls {
  display: flex;
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
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>

/**
 * Data Dictionary Store (Pinia)
 *
 * Manages data dictionary state:
 * - Business terms (definitions, SQL expressions)
 * - Query patterns (few-shot learning examples)
 * - Column descriptions (semantic column info)
 * - Enhanced schema (merged with descriptions)
 * - Import/export functionality
 * - Statistics
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/utils/api'

export const useDataDictionaryStore = defineStore('dataDictionary', () => {
  // ============================================
  // STATE
  // ============================================

  // Business Terms
  const businessTerms = ref([])
  const businessTermsTotal = ref(0)
  const businessTermsLoading = ref(false)
  const businessTermsError = ref(null)

  // Query Patterns
  const queryPatterns = ref([])
  const queryPatternsTotal = ref(0)
  const queryPatternsLoading = ref(false)
  const queryPatternsError = ref(null)

  // Column Descriptions
  const columnDescriptions = ref([])
  const columnDescriptionsTotal = ref(0)
  const columnDescriptionsLoading = ref(false)
  const columnDescriptionsError = ref(null)

  // Enhanced Schema
  const enhancedSchema = ref(null)
  const enhancedSchemaLoading = ref(false)
  const enhancedSchemaError = ref(null)

  // Import History
  const importHistory = ref([])
  const importHistoryLoading = ref(false)

  // Statistics
  const stats = ref({
    total_terms: 0,
    total_patterns: 0,
    total_columns: 0,
    curated_patterns: 0
  })
  const statsLoading = ref(false)

  // Current editing item
  const editingItem = ref(null)
  const editingType = ref(null) // 'term', 'pattern', 'column'

  // Filters
  const filters = ref({
    terms: { category: null, scope_type: null, search: '' },
    patterns: { is_curated: null, complexity: null, search: '' },
    columns: { table_name: null, schema_name: null, search: '' }
  })

  // ============================================
  // COMPUTED
  // ============================================

  const hasData = computed(() =>
    businessTerms.value.length > 0 ||
    queryPatterns.value.length > 0 ||
    columnDescriptions.value.length > 0
  )

  const isLoading = computed(() =>
    businessTermsLoading.value ||
    queryPatternsLoading.value ||
    columnDescriptionsLoading.value ||
    enhancedSchemaLoading.value
  )

  // Group column descriptions by table
  const columnsByTable = computed(() => {
    const grouped = {}
    for (const col of columnDescriptions.value) {
      const key = col.schema_name ? `${col.schema_name}.${col.table_name}` : col.table_name
      if (!grouped[key]) {
        grouped[key] = []
      }
      grouped[key].push(col)
    }
    return grouped
  })

  // Get unique categories from terms
  const termCategories = computed(() => {
    const cats = new Set()
    for (const term of businessTerms.value) {
      if (term.category) cats.add(term.category)
    }
    return Array.from(cats).sort()
  })

  // Get unique tags from patterns
  const patternTags = computed(() => {
    const tags = new Set()
    for (const pattern of queryPatterns.value) {
      if (pattern.tags) {
        pattern.tags.forEach(t => tags.add(t))
      }
    }
    return Array.from(tags).sort()
  })

  // Enhanced schema tables (for tree view)
  const schemaTables = computed(() => {
    if (!enhancedSchema.value) return []
    return enhancedSchema.value.tables || []
  })

  // ============================================
  // ACTIONS - Business Terms
  // ============================================

  async function fetchBusinessTerms(sessionId, params = {}) {
    businessTermsLoading.value = true
    businessTermsError.value = null
    try {
      const mergedParams = { ...filters.value.terms, ...params }
      const result = await api.listBusinessTerms(sessionId, mergedParams)
      businessTerms.value = result.items
      businessTermsTotal.value = result.total
      return result
    } catch (error) {
      businessTermsError.value = error.userMessage || error.message
      throw error
    } finally {
      businessTermsLoading.value = false
    }
  }

  async function createBusinessTerm(sessionId, termData) {
    const created = await api.createBusinessTerm(sessionId, termData)
    businessTerms.value.unshift(created)
    businessTermsTotal.value++
    stats.value.total_terms++
    return created
  }

  async function updateBusinessTerm(termId, updates) {
    const updated = await api.updateBusinessTerm(termId, updates)
    const index = businessTerms.value.findIndex(t => t.id === termId)
    if (index !== -1) {
      businessTerms.value[index] = updated
    }
    return updated
  }

  async function deleteBusinessTerm(termId, hardDelete = false) {
    await api.deleteBusinessTerm(termId, hardDelete)
    businessTerms.value = businessTerms.value.filter(t => t.id !== termId)
    businessTermsTotal.value--
    stats.value.total_terms--
  }

  // ============================================
  // ACTIONS - Query Patterns
  // ============================================

  async function fetchQueryPatterns(sessionId, params = {}) {
    queryPatternsLoading.value = true
    queryPatternsError.value = null
    try {
      const mergedParams = { ...filters.value.patterns, ...params }
      const result = await api.listQueryPatterns(sessionId, mergedParams)
      queryPatterns.value = result.items
      queryPatternsTotal.value = result.total
      return result
    } catch (error) {
      queryPatternsError.value = error.userMessage || error.message
      throw error
    } finally {
      queryPatternsLoading.value = false
    }
  }

  async function createQueryPattern(sessionId, patternData) {
    const created = await api.createQueryPattern(sessionId, patternData)
    queryPatterns.value.unshift(created)
    queryPatternsTotal.value++
    stats.value.total_patterns++
    if (created.is_curated) stats.value.curated_patterns++
    return created
  }

  async function updateQueryPattern(patternId, updates) {
    const updated = await api.updateQueryPattern(patternId, updates)
    const index = queryPatterns.value.findIndex(p => p.id === patternId)
    if (index !== -1) {
      queryPatterns.value[index] = updated
    }
    return updated
  }

  async function deleteQueryPattern(patternId, hardDelete = false) {
    await api.deleteQueryPattern(patternId, hardDelete)
    queryPatterns.value = queryPatterns.value.filter(p => p.id !== patternId)
    queryPatternsTotal.value--
    stats.value.total_patterns--
  }

  async function rateQueryPattern(patternId, rating) {
    await api.rateQueryPattern(patternId, rating)
    const pattern = queryPatterns.value.find(p => p.id === patternId)
    if (pattern) {
      pattern.rating = rating
    }
  }

  // ============================================
  // ACTIONS - Column Descriptions
  // ============================================

  async function fetchColumnDescriptions(sessionId, params = {}) {
    columnDescriptionsLoading.value = true
    columnDescriptionsError.value = null
    try {
      const mergedParams = { ...filters.value.columns, ...params }
      const result = await api.listColumnDescriptions(sessionId, mergedParams)
      columnDescriptions.value = result.items
      columnDescriptionsTotal.value = result.total
      return result
    } catch (error) {
      columnDescriptionsError.value = error.userMessage || error.message
      throw error
    } finally {
      columnDescriptionsLoading.value = false
    }
  }

  async function createColumnDescription(sessionId, columnData) {
    const created = await api.createColumnDescription(sessionId, columnData)
    columnDescriptions.value.unshift(created)
    columnDescriptionsTotal.value++
    stats.value.total_columns++
    return created
  }

  async function updateColumnDescription(columnId, updates) {
    const updated = await api.updateColumnDescription(columnId, updates)
    const index = columnDescriptions.value.findIndex(c => c.id === columnId)
    if (index !== -1) {
      columnDescriptions.value[index] = updated
    }
    return updated
  }

  async function deleteColumnDescription(columnId, hardDelete = false) {
    await api.deleteColumnDescription(columnId, hardDelete)
    columnDescriptions.value = columnDescriptions.value.filter(c => c.id !== columnId)
    columnDescriptionsTotal.value--
    stats.value.total_columns--
  }

  // ============================================
  // ACTIONS - Enhanced Schema
  // ============================================

  async function fetchEnhancedSchema(sessionId) {
    enhancedSchemaLoading.value = true
    enhancedSchemaError.value = null
    try {
      const schema = await api.getEnhancedSchema(sessionId)
      enhancedSchema.value = schema
      return schema
    } catch (error) {
      enhancedSchemaError.value = error.userMessage || error.message
      throw error
    } finally {
      enhancedSchemaLoading.value = false
    }
  }

  // ============================================
  // ACTIONS - Import/Export
  // ============================================

  async function importTerms(sessionId, file) {
    const result = await api.importBusinessTerms(sessionId, file)
    // Refresh terms list and stats in parallel after import
    await Promise.all([fetchBusinessTerms(sessionId), fetchStats(sessionId)])
    return result
  }

  async function importColumns(sessionId, file) {
    const result = await api.importColumnDescriptions(sessionId, file)
    // Refresh columns list and stats in parallel after import
    await Promise.all([fetchColumnDescriptions(sessionId), fetchStats(sessionId)])
    return result
  }

  async function fetchImportHistory(sessionId, limit = 20) {
    importHistoryLoading.value = true
    try {
      const history = await api.getImportHistory(sessionId, limit)
      importHistory.value = history
      return history
    } finally {
      importHistoryLoading.value = false
    }
  }

  async function exportTerms(sessionId, format = 'json') {
    const result = await api.exportBusinessTerms(sessionId, format)
    downloadExport(result)
    return result
  }

  async function exportColumns(sessionId, format = 'json') {
    const result = await api.exportColumnDescriptions(sessionId, format)
    downloadExport(result)
    return result
  }

  // Helper to trigger download
  function downloadExport(result) {
    const content = result.format === 'json'
      ? JSON.stringify(result.content, null, 2)
      : result.content

    const blob = new Blob([content], {
      type: result.format === 'json' ? 'application/json' : 'text/csv'
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = result.filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  // ============================================
  // ACTIONS - Statistics
  // ============================================

  async function fetchStats(sessionId) {
    statsLoading.value = true
    try {
      const result = await api.getDataDictionaryStats(sessionId)
      stats.value = result
      return result
    } finally {
      statsLoading.value = false
    }
  }

  // ============================================
  // ACTIONS - Editing
  // ============================================

  function startEditing(item, type) {
    editingItem.value = { ...item }
    editingType.value = type
  }

  function cancelEditing() {
    editingItem.value = null
    editingType.value = null
  }

  function setFilter(type, key, value) {
    if (filters.value[type]) {
      filters.value[type][key] = value
    }
  }

  function clearFilters(type) {
    if (type === 'terms') {
      filters.value.terms = { category: null, scope_type: null, search: '' }
    } else if (type === 'patterns') {
      filters.value.patterns = { is_curated: null, complexity: null, search: '' }
    } else if (type === 'columns') {
      filters.value.columns = { table_name: null, schema_name: null, search: '' }
    }
  }

  // ============================================
  // ACTIONS - Load All
  // ============================================

  async function loadAll(sessionId) {
    await Promise.all([
      fetchStats(sessionId),
      fetchEnhancedSchema(sessionId),
      fetchBusinessTerms(sessionId, { limit: 100 }),
      fetchQueryPatterns(sessionId, { limit: 100 }),
      fetchColumnDescriptions(sessionId, { limit: 500 })
    ])
  }

  function reset() {
    businessTerms.value = []
    businessTermsTotal.value = 0
    businessTermsError.value = null
    queryPatterns.value = []
    queryPatternsTotal.value = 0
    queryPatternsError.value = null
    columnDescriptions.value = []
    columnDescriptionsTotal.value = 0
    columnDescriptionsError.value = null
    enhancedSchema.value = null
    enhancedSchemaError.value = null
    importHistory.value = []
    stats.value = { total_terms: 0, total_patterns: 0, total_columns: 0, curated_patterns: 0 }
    editingItem.value = null
    editingType.value = null
    filters.value = {
      terms: { category: null, scope_type: null, search: '' },
      patterns: { is_curated: null, complexity: null, search: '' },
      columns: { table_name: null, schema_name: null, search: '' }
    }
  }

  // ============================================
  // RETURN
  // ============================================

  return {
    // State - Business Terms
    businessTerms,
    businessTermsTotal,
    businessTermsLoading,
    businessTermsError,

    // State - Query Patterns
    queryPatterns,
    queryPatternsTotal,
    queryPatternsLoading,
    queryPatternsError,

    // State - Column Descriptions
    columnDescriptions,
    columnDescriptionsTotal,
    columnDescriptionsLoading,
    columnDescriptionsError,

    // State - Schema
    enhancedSchema,
    enhancedSchemaLoading,
    enhancedSchemaError,

    // State - Import
    importHistory,
    importHistoryLoading,

    // State - Stats
    stats,
    statsLoading,

    // State - Editing
    editingItem,
    editingType,
    filters,

    // Computed
    hasData,
    isLoading,
    columnsByTable,
    termCategories,
    patternTags,
    schemaTables,

    // Actions - Business Terms
    fetchBusinessTerms,
    createBusinessTerm,
    updateBusinessTerm,
    deleteBusinessTerm,

    // Actions - Query Patterns
    fetchQueryPatterns,
    createQueryPattern,
    updateQueryPattern,
    deleteQueryPattern,
    rateQueryPattern,

    // Actions - Column Descriptions
    fetchColumnDescriptions,
    createColumnDescription,
    updateColumnDescription,
    deleteColumnDescription,

    // Actions - Schema
    fetchEnhancedSchema,

    // Actions - Import/Export
    importTerms,
    importColumns,
    fetchImportHistory,
    exportTerms,
    exportColumns,

    // Actions - Stats
    fetchStats,

    // Actions - Editing
    startEditing,
    cancelEditing,
    setFilter,
    clearFilters,

    // Actions - Utility
    loadAll,
    reset
  }
})

export default useDataDictionaryStore

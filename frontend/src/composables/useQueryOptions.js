/**
 * useQueryOptions Composable
 *
 * Manages query generation mode options:
 * - Streaming mode (real-time SQL generation)
 * - Response mode: Standard (SQL only) or Analyst (insights + SQL)
 *
 * Persists preferences to localStorage
 */

import { ref, computed, watch } from 'vue'

// ============================================
// SINGLETON STATE (shared across all instances)
// ============================================

const STORAGE_KEY = 'queryfyai-query-options'

// Response modes
export const ResponseMode = {
  STANDARD: 'standard',  // SQL generation only
  ANALYST: 'analyst',    // Insight-rich answers with SQL
}

// Default options
const defaultOptions = {
  streamMode: true,           // Enable streaming by default
  responseMode: ResponseMode.STANDARD,  // Standard mode by default
  /**
   * @deprecated Use responseMode: 'analyst' instead. agenticMode will be removed in a future version.
   * Migration: Replace agenticMode: true with responseMode: ResponseMode.ANALYST
   */
  agenticMode: false
}

// Load saved preferences or use defaults
const loadOptions = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      return { ...defaultOptions, ...parsed }
    }
  } catch (e) {
    console.warn('Failed to load query options:', e)
  }
  return { ...defaultOptions }
}

// Singleton state
const options = ref(loadOptions())

// ============================================
// COMPOSABLE EXPORT
// ============================================

export function useQueryOptions() {
  // Computed getters for individual options
  const streamMode = computed({
    get: () => options.value.streamMode,
    set: (value) => {
      options.value.streamMode = value
    }
  })

  const responseMode = computed({
    get: () => options.value.responseMode || ResponseMode.STANDARD,
    set: (value) => {
      options.value.responseMode = value
    }
  })

  const isAnalystMode = computed(() => options.value.responseMode === ResponseMode.ANALYST)
  const isStandardMode = computed(() => options.value.responseMode === ResponseMode.STANDARD)

  // Legacy agenticMode - maps to analyst mode
  const agenticMode = computed({
    get: () => options.value.agenticMode || options.value.responseMode === ResponseMode.ANALYST,
    set: (value) => {
      options.value.agenticMode = value
      if (value) {
        options.value.responseMode = ResponseMode.ANALYST
        options.value.streamMode = true
      }
    }
  })

  // Computed for display/UI purposes
  const modeLabel = computed(() => {
    if (options.value.responseMode === ResponseMode.ANALYST) return 'Analyst'
    if (options.value.streamMode) return 'Stream'
    return 'Standard'
  })

  const modeDescription = computed(() => {
    if (options.value.responseMode === ResponseMode.ANALYST) {
      return 'AI Data Analyst with insights, charts, and key findings'
    }
    if (options.value.streamMode) {
      return 'Real-time SQL generation with progressive display'
    }
    return 'Standard SQL generation'
  })

  // Toggle functions
  const toggleStreamMode = () => {
    // Can't disable streaming when analyst mode is on
    if (options.value.responseMode === ResponseMode.ANALYST && options.value.streamMode) {
      return
    }
    options.value.streamMode = !options.value.streamMode
  }

  const setResponseMode = (mode) => {
    options.value.responseMode = mode
    // Analyst mode uses streaming by default
    if (mode === ResponseMode.ANALYST) {
      options.value.streamMode = true
    }
  }

  const toggleAnalystMode = () => {
    if (options.value.responseMode === ResponseMode.ANALYST) {
      options.value.responseMode = ResponseMode.STANDARD
    } else {
      options.value.responseMode = ResponseMode.ANALYST
      options.value.streamMode = true
    }
  }

  // Legacy toggle - maps to analyst mode
  const toggleAgenticMode = () => {
    toggleAnalystMode()
  }

  // Reset to defaults
  const resetOptions = () => {
    options.value = { ...defaultOptions }
  }

  // Persist to localStorage on change
  watch(options, (newOptions) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newOptions))
    } catch (e) {
      console.warn('Failed to save query options:', e)
    }
  }, { deep: true })

  return {
    // Reactive state
    options,
    streamMode,
    responseMode,
    agenticMode,  // Legacy

    // Computed booleans
    isAnalystMode,
    isStandardMode,

    // Computed labels
    modeLabel,
    modeDescription,

    // Actions
    toggleStreamMode,
    setResponseMode,
    toggleAnalystMode,
    toggleAgenticMode,  // Legacy
    resetOptions,

    // Constants
    ResponseMode,
  }
}

export default useQueryOptions

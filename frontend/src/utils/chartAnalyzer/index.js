/**
 * Chart Analyzer Module
 * Main entry point for SQL query result visualization
 */

import { analyzeColumns } from './dataTypeInference.js'
import { recommendCharts, getBestChart, ChartTypes } from './chartRecommendation.js'
import { transformForChart, shouldUseDataZoom, getDataZoomConfig } from './chartTransformers.js'

// ============================================
// MEMOIZATION CACHE
// ============================================

const analysisCache = new Map()
const MAX_CACHE_SIZE = 10
const CACHE_TTL = 60000 // 1 minute

/**
 * Generate a hash key for data
 */
function generateDataHash(columns, rows) {
  // Use column names + row count + sample of first/last rows
  const colKey = columns.join('|')
  const rowCount = rows.length
  const sampleSize = Math.min(3, rows.length)

  // Sample first few rows for hash
  const firstRows = rows.slice(0, sampleSize).map(r =>
    columns.map(c => String(r[c] ?? '')).join(',')
  ).join(';')

  // Sample last few rows if different
  const lastRows = rows.length > sampleSize
    ? rows.slice(-sampleSize).map(r =>
        columns.map(c => String(r[c] ?? '')).join(',')
      ).join(';')
    : ''

  return `${colKey}:${rowCount}:${firstRows}:${lastRows}`
}

/**
 * Get cached analysis or null
 */
function getCachedAnalysis(hash) {
  const cached = analysisCache.get(hash)
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.result
  }
  // Remove stale entry
  if (cached) {
    analysisCache.delete(hash)
  }
  return null
}

/**
 * Cache analysis result
 */
function cacheAnalysis(hash, result) {
  // Evict oldest entries if cache is full
  if (analysisCache.size >= MAX_CACHE_SIZE) {
    const oldestKey = analysisCache.keys().next().value
    analysisCache.delete(oldestKey)
  }
  analysisCache.set(hash, {
    result,
    timestamp: Date.now()
  })
}

/**
 * Clear the analysis cache
 */
export function clearAnalysisCache() {
  analysisCache.clear()
}

// ============================================
// DATA SUMMARY GENERATION
// ============================================

/**
 * Generate a human-readable summary of the data
 */
function generateDataSummary(columnAnalysis, rows) {
  const rowCount = rows.length
  const parts = []

  // Count column types
  const numericCols = columnAnalysis.filter(c =>
    ['integer', 'float', 'percentage', 'currency'].includes(c.type)
  )
  const categoricalCols = columnAnalysis.filter(c => c.type === 'categorical')
  const temporalCols = columnAnalysis.filter(c =>
    ['date', 'datetime', 'year', 'month'].includes(c.type)
  )
  const geoCols = columnAnalysis.filter(c =>
    ['country', 'country_code', 'us_state', 'coordinates'].includes(c.type)
  )

  // Row count
  parts.push(`${rowCount.toLocaleString()} row${rowCount !== 1 ? 's' : ''}`)

  // Data characteristics
  const characteristics = []

  if (numericCols.length > 0) {
    characteristics.push(`${numericCols.length} numeric`)
  }
  if (categoricalCols.length > 0) {
    const maxCardinality = Math.max(...categoricalCols.map(c => c.metadata?.cardinality || 0))
    characteristics.push(`${categoricalCols.length} categorical (up to ${maxCardinality} unique)`)
  }
  if (temporalCols.length > 0) {
    // Try to detect date range
    const dateCol = temporalCols[0]
    const dateValues = rows.map(r => new Date(r[dateCol.name])).filter(d => !isNaN(d.getTime()))
    if (dateValues.length > 1) {
      const minDate = new Date(Math.min(...dateValues.map(d => d.getTime())))
      const maxDate = new Date(Math.max(...dateValues.map(d => d.getTime())))
      const dateFormat = { month: 'short', year: 'numeric' }
      characteristics.push(`time series (${minDate.toLocaleDateString('en-US', dateFormat)} - ${maxDate.toLocaleDateString('en-US', dateFormat)})`)
    } else {
      characteristics.push('time series')
    }
  }
  if (geoCols.length > 0) {
    characteristics.push('geographic')
  }

  if (characteristics.length > 0) {
    parts.push(characteristics.join(', '))
  }

  return parts.join(' • ')
}

// ============================================
// MAIN ANALYSIS FUNCTION
// ============================================

/**
 * Analyze query results and recommend charts
 * @param {Array<string>} columns - Column names
 * @param {Array<Object>} rows - Row data
 * @returns {Object} Analysis results with recommendations
 */
export function analyzeAndRecommend(columns, rows) {
  // Handle empty data
  if (!columns || !rows || columns.length === 0 || rows.length === 0) {
    return {
      columnAnalysis: [],
      recommendations: [{
        type: ChartTypes.TABLE,
        score: 0.30,
        reason: 'No data available',
        config: {}
      }],
      bestChart: {
        type: ChartTypes.TABLE,
        score: 0.30,
        reason: 'No data available',
        config: {}
      }
    }
  }

  // Check cache first
  const dataHash = generateDataHash(columns, rows)
  const cached = getCachedAnalysis(dataHash)
  if (cached) {
    return cached
  }

  // Analyze column types
  const columnAnalysis = analyzeColumns(columns, rows)

  // Get chart recommendations
  const recommendations = recommendCharts(columnAnalysis, rows)

  // Get best chart
  const bestChart = getBestChart(columnAnalysis, rows)

  // Generate human-readable data summary
  const dataSummary = generateDataSummary(columnAnalysis, rows)

  const result = {
    columnAnalysis,
    recommendations,
    bestChart,
    dataSummary,
    dataStats: {
      rowCount: rows.length,
      columnCount: columns.length,
      hasNumeric: columnAnalysis.some(c =>
        ['integer', 'float', 'percentage', 'currency'].includes(c.type)
      ),
      hasCategorical: columnAnalysis.some(c => c.type === 'categorical'),
      hasTemporal: columnAnalysis.some(c =>
        ['date', 'datetime', 'year', 'month'].includes(c.type)
      )
    }
  }

  // Cache the result
  cacheAnalysis(dataHash, result)

  return result
}

/**
 * Get chart options for rendering
 * @param {Object} recommendation - Chart recommendation from analyzeAndRecommend
 * @param {Array<string>} columns - Column names
 * @param {Array<Object>} rows - Row data
 * @returns {Object|null} ECharts option object
 */
export function getChartOptions(recommendation, columns, rows) {
  if (!recommendation || recommendation.type === ChartTypes.TABLE) {
    return null
  }

  const options = transformForChart(
    recommendation.type,
    columns,
    rows,
    recommendation.config || {}
  )

  if (!options) return null

  // Add DataZoom for large datasets on cartesian charts
  const cartesianCharts = [
    ChartTypes.BAR, ChartTypes.BAR_HORIZONTAL, ChartTypes.LINE,
    ChartTypes.AREA, ChartTypes.SCATTER, ChartTypes.MULTI_LINE,
    ChartTypes.STACKED_AREA, ChartTypes.GROUPED_BAR, ChartTypes.STACKED_BAR,
    ChartTypes.HISTOGRAM, ChartTypes.HEATMAP
  ]

  if (cartesianCharts.includes(recommendation.type) && shouldUseDataZoom(rows.length)) {
    const dataZoomConfig = getDataZoomConfig(rows.length)
    if (dataZoomConfig) {
      // Adjust grid to make room for DataZoom slider
      return {
        ...options,
        ...dataZoomConfig,
        grid: {
          ...options.grid,
          bottom: '15%'
        }
      }
    }
  }

  return options
}

/**
 * Check if data is chartable (has at least one numeric column and enough data)
 * @param {Array<string>} columns - Column names
 * @param {Array<Object>} rows - Row data
 * @returns {boolean}
 */
export function isChartable(columns, rows) {
  if (!columns || !rows || columns.length < 1 || rows.length === 0) {
    return false
  }

  // Quick check: see if any column has numeric values
  for (const col of columns) {
    const values = rows.slice(0, 10).map(r => r[col]) // Sample first 10 rows
    const numericCount = values.filter(v => typeof v === 'number' || !isNaN(Number(v))).length
    if (numericCount > values.length * 0.5) {
      return true
    }
  }

  // Full analysis fallback
  const columnAnalysis = analyzeColumns(columns, rows)
  const hasNumeric = columnAnalysis.some(c =>
    ['integer', 'float', 'percentage', 'currency'].includes(c.type)
  )

  return hasNumeric
}

// Re-export types and utilities
export { ColumnTypes } from './dataTypeInference.js'
export { ChartTypes, ChartLabels } from './chartRecommendation.js'
export { transformForChart, shouldUseDataZoom, getDataZoomConfig } from './chartTransformers.js'

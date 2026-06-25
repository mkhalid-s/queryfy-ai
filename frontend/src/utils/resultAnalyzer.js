/**
 * Result Analyzer - Detects data structure type for optimal display
 *
 * Analyzes query results to determine if they should be displayed
 * as a traditional table (flat/SQL data) or document view (nested/NoSQL data)
 */

// Common NoSQL ID field names
const NOSQL_ID_FIELDS = ['_id', 'pk', 'PK', 'SK', 'sk', 'partitionKey', 'sortKey', 'documentId', 'docId']

// Patterns that suggest NoSQL ObjectId or UUID
const NOSQL_ID_PATTERNS = [
  /^[a-f0-9]{24}$/i,           // MongoDB ObjectId
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i, // UUID
  /^\d+#\w+/,                   // DynamoDB composite key pattern
]

/**
 * Check if a value looks like a NoSQL ID
 */
const looksLikeNoSqlId = (value) => {
  if (typeof value === 'object' && value !== null) {
    // MongoDB ObjectId object: { $oid: "..." }
    if (value.$oid) return true
    // DynamoDB attribute value: { S: "..." } or { N: "..." }
    if (value.S || value.N) return true
  }
  if (typeof value === 'string') {
    return NOSQL_ID_PATTERNS.some(pattern => pattern.test(value))
  }
  return false
}

/**
 * Check if a value contains nested structure (object or array with objects)
 */
const hasNestedStructure = (value) => {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) {
    return value.length > 0 && value.some(item =>
      typeof item === 'object' && item !== null
    )
  }
  if (typeof value === 'object') {
    return Object.keys(value).length > 0
  }
  return false
}

/**
 * Calculate nesting depth of an object
 */
const getMaxDepth = (obj, currentDepth = 0, maxDepth = 5) => {
  if (currentDepth >= maxDepth) return currentDepth
  if (obj === null || typeof obj !== 'object') return currentDepth

  let max = currentDepth
  const items = Array.isArray(obj) ? obj : Object.values(obj)

  for (const value of items.slice(0, 10)) { // Sample first 10 items
    if (typeof value === 'object' && value !== null) {
      const depth = getMaxDepth(value, currentDepth + 1, maxDepth)
      if (depth > max) max = depth
    }
  }
  return max
}

/**
 * Analyze results structure and return display recommendation
 * @param {Object} results - Query results with columns and rows
 * @returns {Object} Analysis result with type and metrics
 */
export const analyzeResults = (results) => {
  if (!results?.rows?.length || !results?.columns?.length) {
    return {
      type: 'empty',
      isDocument: false,
      hasNoSqlIndicators: false,
      metrics: { rowCount: 0, columnCount: 0 }
    }
  }

  const rows = results.rows
  const columns = results.columns
  const sampleSize = Math.min(rows.length, 20)
  const sampleRows = rows.slice(0, sampleSize)

  // Metrics
  let nestedColumnCount = 0
  let totalNestedDepth = 0
  let arrayColumnCount = 0
  let hasVaryingSchema = false
  let hasNoSqlIdPattern = false

  // Check for NoSQL ID fields in column names
  const hasNoSqlIdField = columns.some(col => NOSQL_ID_FIELDS.includes(col))

  // Check each column for nested structures and NoSQL patterns
  const columnAnalysis = {}

  for (const col of columns) {
    const values = sampleRows.map(row => row[col]).filter(v => v != null)
    const nestedValues = values.filter(hasNestedStructure)
    const hasNested = nestedValues.length > values.length * 0.3 // 30% threshold

    if (hasNested) {
      nestedColumnCount++
      const depths = nestedValues.map(v => getMaxDepth(v))
      const avgDepth = depths.reduce((a, b) => a + b, 0) / depths.length
      totalNestedDepth += avgDepth
    }

    // Check for arrays
    const arrayValues = values.filter(v => Array.isArray(v))
    if (arrayValues.length > values.length * 0.3) {
      arrayColumnCount++
    }

    // Check for NoSQL ID patterns in values (especially in ID-like columns)
    if (NOSQL_ID_FIELDS.includes(col) || col.toLowerCase().includes('id')) {
      if (values.some(looksLikeNoSqlId)) {
        hasNoSqlIdPattern = true
      }
    }

    columnAnalysis[col] = {
      hasNested,
      isArray: arrayValues.length > 0,
      sampleDepth: hasNested ? getMaxDepth(nestedValues[0]) : 0
    }
  }

  // Check for varying schemas (different keys in different rows)
  if (nestedColumnCount > 0) {
    const keySignatures = sampleRows.map(row => {
      const keys = []
      for (const col of columns) {
        if (typeof row[col] === 'object' && row[col] !== null) {
          keys.push(...Object.keys(row[col]))
        }
      }
      return keys.sort().join(',')
    })
    const uniqueSignatures = new Set(keySignatures)
    hasVaryingSchema = uniqueSignatures.size > sampleSize * 0.5
  }

  // Detect if data looks like it came from NoSQL (even if flat)
  const hasNoSqlIndicators = hasNoSqlIdField || hasNoSqlIdPattern

  // Calculate document score (0-100)
  const nestedRatio = nestedColumnCount / columns.length
  const avgDepth = nestedColumnCount > 0 ? totalNestedDepth / nestedColumnCount : 0

  const documentScore = Math.min(100, Math.round(
    (nestedRatio * 40) +              // Weight for nested columns
    (avgDepth * 15) +                 // Weight for depth
    (arrayColumnCount > 0 ? 20 : 0) + // Bonus for arrays
    (hasVaryingSchema ? 25 : 0) +     // Bonus for varying schemas
    (hasNoSqlIdField ? 15 : 0) +      // Bonus for NoSQL ID field names
    (hasNoSqlIdPattern ? 15 : 0)      // Bonus for NoSQL ID patterns
  ))

  // Determine type based on score
  // Score >= 30 suggests document-oriented data
  // Also consider as document if NoSQL indicators present (even with lower score)
  const isDocument = documentScore >= 30 || hasNoSqlIndicators

  return {
    type: isDocument ? 'document' : 'tabular',
    isDocument,
    hasNoSqlIndicators,
    documentScore,
    metrics: {
      rowCount: rows.length,
      columnCount: columns.length,
      nestedColumnCount,
      arrayColumnCount,
      avgNestedDepth: Math.round(avgDepth * 10) / 10,
      hasVaryingSchema,
      hasNoSqlIdField,
      hasNoSqlIdPattern
    },
    columnAnalysis
  }
}

/**
 * Get a human-readable description of the data type
 */
export const getDataTypeDescription = (analysis) => {
  if (analysis.type === 'empty') return 'No data'
  if (analysis.type === 'tabular') return 'Tabular data'

  const { metrics } = analysis
  if (metrics.hasVaryingSchema) return 'Document collection (varying schema)'
  if (metrics.arrayColumnCount > 0) return 'Documents with arrays'
  if (metrics.avgNestedDepth > 2) return 'Deeply nested documents'
  if (metrics.hasNoSqlIdField || metrics.hasNoSqlIdPattern) return 'NoSQL documents'
  return 'Document data'
}

export default {
  analyzeResults,
  getDataTypeDescription
}

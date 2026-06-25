/**
 * Data Type Inference Module
 * Analyzes column values to determine data types with confidence scores
 */

export const ColumnTypes = {
  // Numeric types
  INTEGER: 'integer',
  FLOAT: 'float',
  PERCENTAGE: 'percentage',
  CURRENCY: 'currency',

  // Categorical types
  CATEGORICAL: 'categorical',
  BOOLEAN: 'boolean',

  // Temporal types
  DATE: 'date',
  DATETIME: 'datetime',
  TIME: 'time',
  YEAR: 'year',
  MONTH: 'month',

  // Geographic types
  COUNTRY: 'country',
  COUNTRY_CODE: 'country_code',
  US_STATE: 'us_state',
  COORDINATES: 'coordinates',

  // Special types
  ID: 'id',
  TEXT: 'text',
  NULL: 'null',
  MIXED: 'mixed'
}

// Common country names for geographic detection
const COMMON_COUNTRIES = new Set([
  'united states', 'usa', 'us', 'china', 'india', 'japan', 'germany', 'united kingdom',
  'uk', 'france', 'brazil', 'italy', 'canada', 'russia', 'south korea', 'spain',
  'australia', 'mexico', 'indonesia', 'netherlands', 'saudi arabia', 'turkey',
  'switzerland', 'poland', 'sweden', 'belgium', 'argentina', 'norway', 'austria',
  'uae', 'ireland', 'israel', 'singapore', 'hong kong', 'denmark', 'malaysia',
  'philippines', 'south africa', 'egypt', 'pakistan', 'bangladesh', 'vietnam',
  'thailand', 'nigeria', 'colombia', 'chile', 'peru', 'czechia', 'romania',
  'new zealand', 'portugal', 'greece', 'iraq', 'algeria', 'qatar', 'kazakhstan'
])

// US States
const US_STATES = new Set([
  'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado',
  'connecticut', 'delaware', 'florida', 'georgia', 'hawaii', 'idaho',
  'illinois', 'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana',
  'maine', 'maryland', 'massachusetts', 'michigan', 'minnesota', 'mississippi',
  'missouri', 'montana', 'nebraska', 'nevada', 'new hampshire', 'new jersey',
  'new mexico', 'new york', 'north carolina', 'north dakota', 'ohio', 'oklahoma',
  'oregon', 'pennsylvania', 'rhode island', 'south carolina', 'south dakota',
  'tennessee', 'texas', 'utah', 'vermont', 'virginia', 'washington',
  'west virginia', 'wisconsin', 'wyoming', 'district of columbia'
])

const US_STATE_ABBREVS = new Set([
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
  'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
  'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
  'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
  'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'
])

// Month names for temporal detection
const MONTH_NAMES = new Set([
  'january', 'february', 'march', 'april', 'may', 'june',
  'july', 'august', 'september', 'october', 'november', 'december',
  'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
])

/**
 * Main function to infer column type
 * @param {string} columnName - Name of the column
 * @param {Array} values - Array of values from the column
 * @returns {Object} { type, confidence, metadata }
 */
export function inferColumnType(columnName, values) {
  const analysis = {
    type: ColumnTypes.MIXED,
    confidence: 0,
    metadata: {
      nullCount: 0,
      uniqueCount: 0,
      sampleValues: [],
      statistics: null
    }
  }

  // Filter out null/undefined/empty values
  const validValues = values.filter(v => v !== null && v !== undefined && v !== '')
  analysis.metadata.nullCount = values.length - validValues.length
  analysis.metadata.uniqueCount = new Set(validValues).size
  analysis.metadata.sampleValues = validValues.slice(0, 5)

  if (validValues.length === 0) {
    return { ...analysis, type: ColumnTypes.NULL, confidence: 1 }
  }

  // Run type detectors in priority order
  const detectors = [
    detectBoolean,
    detectDateTime,
    detectDate,
    detectTime,
    detectYear,
    detectMonth,
    detectPercentage,
    detectCurrency,
    detectCoordinates,
    detectGeographic,
    detectId,
    detectNumeric,
    detectCategorical,
    detectText
  ]

  for (const detector of detectors) {
    const result = detector(columnName, validValues)
    if (result.confidence > analysis.confidence) {
      analysis.type = result.type
      analysis.confidence = result.confidence
      analysis.metadata = { ...analysis.metadata, ...result.metadata }
    }
  }

  return analysis
}

/**
 * Analyze all columns in the dataset
 * @param {Array<string>} columns - Column names
 * @param {Array<Object>} rows - Row data
 * @returns {Array<Object>} Analysis for each column
 */
export function analyzeColumns(columns, rows) {
  return columns.map(col => {
    const values = rows.map(row => row[col])
    return {
      name: col,
      ...inferColumnType(col, values)
    }
  })
}

// --- Individual Type Detectors ---

function detectBoolean(columnName, values) {
  const booleanValues = new Set(['true', 'false', '1', '0', 'yes', 'no', 'y', 'n', true, false, 1, 0])
  const normalizedValues = values.map(v => {
    if (typeof v === 'boolean') return v
    if (typeof v === 'number') return v
    return String(v).toLowerCase()
  })
  const matchCount = normalizedValues.filter(v => booleanValues.has(v)).length
  const confidence = matchCount / values.length

  return {
    type: ColumnTypes.BOOLEAN,
    confidence: confidence > 0.95 ? confidence : 0,
    metadata: { booleanPattern: true }
  }
}

function detectDateTime(columnName, values) {
  // ISO datetime format (from backend serialization)
  const isoDateTimeRegex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/
  const matchCount = values.filter(v => isoDateTimeRegex.test(String(v))).length
  const confidence = matchCount / values.length

  if (confidence > 0.9) {
    // Check if there's time variation (not just 00:00:00)
    const hasTimeVariation = values.some(v => {
      const timeMatch = String(v).match(/T(\d{2}:\d{2}:\d{2})/)
      return timeMatch && timeMatch[1] !== '00:00:00'
    })

    return {
      type: hasTimeVariation ? ColumnTypes.DATETIME : ColumnTypes.DATE,
      confidence,
      metadata: { format: 'iso', hasTimeComponent: hasTimeVariation }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectDate(columnName, values) {
  // Various date formats
  const datePatterns = [
    /^\d{4}-\d{2}-\d{2}$/,           // YYYY-MM-DD
    /^\d{2}\/\d{2}\/\d{4}$/,         // MM/DD/YYYY
    /^\d{2}-\d{2}-\d{4}$/,           // DD-MM-YYYY
    /^\d{4}\/\d{2}\/\d{2}$/          // YYYY/MM/DD
  ]

  const matchCount = values.filter(v => {
    const str = String(v)
    return datePatterns.some(pattern => pattern.test(str))
  }).length

  const confidence = matchCount / values.length

  if (confidence > 0.9) {
    return {
      type: ColumnTypes.DATE,
      confidence,
      metadata: { format: 'date' }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectTime(columnName, values) {
  const timeRegex = /^([01]?\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$/
  const matchCount = values.filter(v => timeRegex.test(String(v))).length
  const confidence = matchCount / values.length

  return {
    type: ColumnTypes.TIME,
    confidence: confidence > 0.9 ? confidence : 0,
    metadata: {}
  }
}

function detectYear(columnName, values) {
  const nameLower = columnName.toLowerCase()
  const isYearName = nameLower.includes('year') || nameLower === 'yr'

  const yearValues = values.filter(v => {
    const num = Number(v)
    return Number.isInteger(num) && num >= 1900 && num <= 2100
  })

  const confidence = yearValues.length / values.length

  if (confidence > 0.9 && (isYearName || new Set(values).size < values.length * 0.3)) {
    return {
      type: ColumnTypes.YEAR,
      confidence: isYearName ? confidence : confidence * 0.8,
      metadata: { isTemporalYear: true }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectMonth(columnName, values) {
  const nameLower = columnName.toLowerCase()
  const isMonthName = nameLower.includes('month') || nameLower === 'mon'

  const monthMatches = values.filter(v => {
    const str = String(v).toLowerCase()
    // Check month names or numbers 1-12
    if (MONTH_NAMES.has(str)) return true
    const num = Number(v)
    return Number.isInteger(num) && num >= 1 && num <= 12
  }).length

  const confidence = monthMatches / values.length

  if (confidence > 0.8 && (isMonthName || new Set(values).size <= 12)) {
    return {
      type: ColumnTypes.MONTH,
      confidence,
      metadata: { isTemporalMonth: true }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectPercentage(columnName, values) {
  const nameLower = columnName.toLowerCase()
  const isPercentName = nameLower.includes('percent') || nameLower.includes('pct') || nameLower.includes('rate')

  // Check for % suffix or values between 0-100
  const percentMatches = values.filter(v => {
    if (typeof v === 'string' && v.includes('%')) return true
    const num = Number(String(v).replace('%', ''))
    return !isNaN(num) && num >= 0 && num <= 100
  }).length

  const confidence = percentMatches / values.length

  if (confidence > 0.9 && isPercentName) {
    return {
      type: ColumnTypes.PERCENTAGE,
      confidence,
      metadata: { isPercentage: true }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectCurrency(columnName, values) {
  const nameLower = columnName.toLowerCase()
  const isCurrencyName = ['price', 'cost', 'amount', 'revenue', 'sales', 'total', 'salary', 'income', 'budget']
    .some(term => nameLower.includes(term))

  const currencyRegex = /^[$€£¥]?\s*[\d,]+\.?\d*$|^[\d,]+\.?\d*\s*[$€£¥]$/
  const currencyMatches = values.filter(v => currencyRegex.test(String(v))).length

  const confidence = currencyMatches / values.length

  if (confidence > 0.8 && isCurrencyName) {
    return {
      type: ColumnTypes.CURRENCY,
      confidence,
      metadata: { isCurrency: true }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectCoordinates(columnName, values) {
  const nameLower = columnName.toLowerCase()
  const isLatitude = nameLower.includes('lat')
  const isLongitude = nameLower.includes('lon') || nameLower.includes('lng')

  if (isLatitude) {
    const validLat = values.filter(v => {
      const num = Number(v)
      return !isNaN(num) && num >= -90 && num <= 90
    }).length
    if (validLat / values.length > 0.9) {
      return {
        type: ColumnTypes.COORDINATES,
        confidence: 0.95,
        metadata: { coordinateType: 'latitude' }
      }
    }
  }

  if (isLongitude) {
    const validLon = values.filter(v => {
      const num = Number(v)
      return !isNaN(num) && num >= -180 && num <= 180
    }).length
    if (validLon / values.length > 0.9) {
      return {
        type: ColumnTypes.COORDINATES,
        confidence: 0.95,
        metadata: { coordinateType: 'longitude' }
      }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectGeographic(columnName, values) {
  const nameLower = columnName.toLowerCase()

  // Country detection
  const countryMatches = values.filter(v =>
    COMMON_COUNTRIES.has(String(v).toLowerCase())
  ).length

  if (countryMatches / values.length > 0.5) {
    return {
      type: ColumnTypes.COUNTRY,
      confidence: countryMatches / values.length,
      metadata: { geoType: 'country_name' }
    }
  }

  // Country code detection (2-3 letter codes)
  const isCountryCode = nameLower.includes('country') && nameLower.includes('code')
  const codeMatches = values.filter(v => {
    const str = String(v).toUpperCase()
    return str.length >= 2 && str.length <= 3 && /^[A-Z]+$/.test(str)
  }).length

  if (isCountryCode && codeMatches / values.length > 0.8) {
    return {
      type: ColumnTypes.COUNTRY_CODE,
      confidence: 0.9,
      metadata: { geoType: 'country_code' }
    }
  }

  // US State detection
  const stateMatches = values.filter(v => {
    const str = String(v)
    return US_STATES.has(str.toLowerCase()) || US_STATE_ABBREVS.has(str.toUpperCase())
  }).length

  if (stateMatches / values.length > 0.5) {
    return {
      type: ColumnTypes.US_STATE,
      confidence: stateMatches / values.length,
      metadata: { geoType: 'us_state' }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectId(columnName, values) {
  const nameLower = columnName.toLowerCase()
  const isIdName = nameLower.endsWith('_id') || nameLower.endsWith('id') ||
                   nameLower === 'id' || nameLower.includes('uuid') || nameLower.includes('key')

  const uniqueRatio = new Set(values).size / values.length

  // IDs typically have very high uniqueness
  if (isIdName && uniqueRatio > 0.9) {
    return {
      type: ColumnTypes.ID,
      confidence: 0.95,
      metadata: { isIdentifier: true }
    }
  }

  return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
}

function detectNumeric(columnName, values) {
  const numericValues = values.filter(v => typeof v === 'number' && !isNaN(v))
  const stringNumericValues = values.filter(v => {
    if (typeof v === 'number') return true
    if (v === null || v === undefined || v === '') return false
    const num = Number(v)
    return !isNaN(num)
  })

  const confidence = Math.max(numericValues.length, stringNumericValues.length) / values.length

  // Lowered threshold from 0.85 to 0.6 for better detection
  if (confidence < 0.6) {
    return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
  }

  const nums = stringNumericValues.map(v => Number(v)).filter(n => !isNaN(n))
  if (nums.length === 0) {
    return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
  }

  const allIntegers = nums.every(v => Number.isInteger(v))

  const stats = {
    min: Math.min(...nums),
    max: Math.max(...nums),
    mean: nums.reduce((a, b) => a + b, 0) / nums.length,
    hasNegative: nums.some(v => v < 0),
    hasDecimal: !allIntegers
  }

  return {
    type: allIntegers ? ColumnTypes.INTEGER : ColumnTypes.FLOAT,
    confidence,
    metadata: { statistics: stats }
  }
}

function detectCategorical(columnName, values) {
  const uniqueValues = new Set(values)
  const uniqueRatio = uniqueValues.size / values.length

  // High cardinality = likely not categorical
  if (uniqueRatio > 0.5 && values.length > 20) {
    return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
  }

  const stringValues = values.filter(v => typeof v === 'string')
  if (stringValues.length < values.length * 0.8) {
    return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
  }

  const avgLength = stringValues.reduce((sum, v) => sum + v.length, 0) / stringValues.length

  // Categorical values typically have short-to-medium length
  if (avgLength > 100) {
    return { type: ColumnTypes.TEXT, confidence: 0.7, metadata: {} }
  }

  let confidence = 0.85
  if (uniqueValues.size <= 10) confidence = 0.92
  if (uniqueValues.size <= 5) confidence = 0.95

  return {
    type: ColumnTypes.CATEGORICAL,
    confidence,
    metadata: {
      cardinality: uniqueValues.size,
      categories: Array.from(uniqueValues).slice(0, 20)
    }
  }
}

function detectText(columnName, values) {
  const stringValues = values.filter(v => typeof v === 'string')
  if (stringValues.length < values.length * 0.8) {
    return { type: ColumnTypes.MIXED, confidence: 0, metadata: {} }
  }

  const avgLength = stringValues.reduce((sum, v) => sum + v.length, 0) / stringValues.length

  return {
    type: ColumnTypes.TEXT,
    confidence: avgLength > 50 ? 0.8 : 0.5,
    metadata: { avgLength }
  }
}

/**
 * Chart Recommendation Engine
 * Analyzes data patterns and recommends the best chart types
 */

import { ColumnTypes } from './dataTypeInference.js'

export const ChartTypes = {
  // Basic charts
  BAR: 'bar',
  BAR_HORIZONTAL: 'bar_horizontal',
  LINE: 'line',
  AREA: 'area',
  PIE: 'pie',
  DONUT: 'donut',

  // Statistical charts
  SCATTER: 'scatter',
  BUBBLE: 'bubble',
  HISTOGRAM: 'histogram',

  // Comparison charts
  GROUPED_BAR: 'grouped_bar',
  STACKED_BAR: 'stacked_bar',
  STACKED_AREA: 'stacked_area',
  MULTI_LINE: 'multi_line',

  // Specialized charts
  HEATMAP: 'heatmap',
  TREEMAP: 'treemap',
  RADAR: 'radar',
  FUNNEL: 'funnel',
  GAUGE: 'gauge',

  // Geographic charts
  GEO_MAP: 'geo_map',
  CHOROPLETH: 'choropleth',

  // Table (fallback)
  TABLE: 'table'
}

// Chart labels for display
export const ChartLabels = {
  [ChartTypes.BAR]: 'Bar Chart',
  [ChartTypes.BAR_HORIZONTAL]: 'Horizontal Bar',
  [ChartTypes.LINE]: 'Line Chart',
  [ChartTypes.AREA]: 'Area Chart',
  [ChartTypes.PIE]: 'Pie Chart',
  [ChartTypes.DONUT]: 'Donut Chart',
  [ChartTypes.SCATTER]: 'Scatter Plot',
  [ChartTypes.BUBBLE]: 'Bubble Chart',
  [ChartTypes.HISTOGRAM]: 'Histogram',
  [ChartTypes.GROUPED_BAR]: 'Grouped Bar',
  [ChartTypes.STACKED_BAR]: 'Stacked Bar',
  [ChartTypes.STACKED_AREA]: 'Stacked Area',
  [ChartTypes.MULTI_LINE]: 'Multi-Line',
  [ChartTypes.HEATMAP]: 'Heatmap',
  [ChartTypes.TREEMAP]: 'Treemap',
  [ChartTypes.RADAR]: 'Radar Chart',
  [ChartTypes.FUNNEL]: 'Funnel Chart',
  [ChartTypes.GAUGE]: 'Gauge',
  [ChartTypes.GEO_MAP]: 'Map',
  [ChartTypes.CHOROPLETH]: 'Choropleth Map',
  [ChartTypes.TABLE]: 'Table'
}

// Numeric type check
const NUMERIC_TYPES = new Set([
  ColumnTypes.INTEGER,
  ColumnTypes.FLOAT,
  ColumnTypes.PERCENTAGE,
  ColumnTypes.CURRENCY
])

// Temporal type check
const TEMPORAL_TYPES = new Set([
  ColumnTypes.DATE,
  ColumnTypes.DATETIME,
  ColumnTypes.YEAR,
  ColumnTypes.MONTH
])

// Geographic type check
const GEOGRAPHIC_TYPES = new Set([
  ColumnTypes.COUNTRY,
  ColumnTypes.COUNTRY_CODE,
  ColumnTypes.US_STATE,
  ColumnTypes.COORDINATES
])

/**
 * Analyze data structure and count column types
 */
function analyzeStructure(columnAnalysis) {
  return {
    total: columnAnalysis.length,
    numericCount: columnAnalysis.filter(c => NUMERIC_TYPES.has(c.type)).length,
    categoricalCount: columnAnalysis.filter(c => c.type === ColumnTypes.CATEGORICAL).length,
    temporalCount: columnAnalysis.filter(c => TEMPORAL_TYPES.has(c.type)).length,
    geographicCount: columnAnalysis.filter(c => GEOGRAPHIC_TYPES.has(c.type)).length,
    booleanCount: columnAnalysis.filter(c => c.type === ColumnTypes.BOOLEAN).length,
    textCount: columnAnalysis.filter(c => c.type === ColumnTypes.TEXT).length,
    idCount: columnAnalysis.filter(c => c.type === ColumnTypes.ID).length,

    numericColumns: columnAnalysis.filter(c => NUMERIC_TYPES.has(c.type)),
    categoricalColumns: columnAnalysis.filter(c => c.type === ColumnTypes.CATEGORICAL),
    temporalColumns: columnAnalysis.filter(c => TEMPORAL_TYPES.has(c.type)),
    geographicColumns: columnAnalysis.filter(c => GEOGRAPHIC_TYPES.has(c.type))
  }
}

/**
 * Detect time series pattern
 */
function detectTimeSeries(columnAnalysis, rows) {
  const temporalCols = columnAnalysis.filter(c => TEMPORAL_TYPES.has(c.type))

  if (temporalCols.length === 0) {
    return { detected: false }
  }

  const temporalCol = temporalCols[0]
  const values = rows.map(r => r[temporalCol.name])

  // Try to parse and sort dates
  const dates = values
    .map(v => new Date(v))
    .filter(d => !isNaN(d.getTime()))
    .map(d => d.getTime())

  if (dates.length < values.length * 0.8) {
    return { detected: false }
  }

  // Check if roughly sorted
  let sortedCount = 0
  for (let i = 1; i < dates.length; i++) {
    if (dates[i] >= dates[i - 1]) sortedCount++
  }
  const isSorted = dates.length <= 1 || sortedCount / (dates.length - 1) > 0.7

  // Detect granularity
  const intervals = []
  const sortedDates = [...dates].sort((a, b) => a - b)
  for (let i = 1; i < sortedDates.length; i++) {
    intervals.push(sortedDates[i] - sortedDates[i - 1])
  }

  let granularity = 'irregular'
  if (intervals.length > 0) {
    const avgInterval = intervals.reduce((a, b) => a + b, 0) / intervals.length
    const hour = 3600000, day = 86400000, week = 604800000
    const month = 2592000000, year = 31536000000

    if (avgInterval < hour * 2) granularity = 'hourly'
    else if (avgInterval < day * 2) granularity = 'daily'
    else if (avgInterval < week * 2) granularity = 'weekly'
    else if (avgInterval < month * 1.5) granularity = 'monthly'
    else if (avgInterval < month * 4) granularity = 'quarterly'
    else if (avgInterval < year * 1.5) granularity = 'yearly'
  }

  return {
    detected: true,
    column: temporalCol.name,
    columnType: temporalCol.type,
    isSorted,
    granularity,
    dateRange: {
      start: new Date(Math.min(...dates)),
      end: new Date(Math.max(...dates))
    }
  }
}

/**
 * Detect part-to-whole pattern (good for pie/donut)
 */
function detectPartToWhole(structure, rows) {
  const { numericColumns, categoricalColumns } = structure

  if (categoricalColumns.length !== 1 || numericColumns.length < 1) {
    return { detected: false }
  }

  const catCol = categoricalColumns[0]
  const numCol = numericColumns[0]

  // Check cardinality - pie charts work best with <= 10 categories
  if (catCol.metadata?.cardinality > 15) {
    return { detected: false }
  }

  const values = rows.map(r => r[numCol.name]).filter(v => typeof v === 'number')
  const sum = values.reduce((a, b) => a + b, 0)

  // Check for percentage (sums to ~100) or proportion (sums to ~1)
  const is100Percent = Math.abs(sum - 100) < 5
  const isProportion = Math.abs(sum - 1) < 0.05
  const allPositive = values.every(v => v >= 0)

  if (!allPositive) {
    return { detected: false }
  }

  return {
    detected: true,
    categoricalColumn: catCol.name,
    valueColumn: numCol.name,
    partCount: catCol.metadata.cardinality,
    sumType: is100Percent ? 'percentage' : (isProportion ? 'proportion' : 'discrete'),
    isIdealForPie: catCol.metadata.cardinality <= 6
  }
}

/**
 * Detect correlation/scatter pattern
 */
function detectCorrelation(structure, rows) {
  const { numericColumns } = structure

  if (numericColumns.length < 2) {
    return { detected: false, correlations: [] }
  }

  const correlations = []

  for (let i = 0; i < numericColumns.length; i++) {
    for (let j = i + 1; j < numericColumns.length; j++) {
      const col1 = numericColumns[i].name
      const col2 = numericColumns[j].name

      const pairs = rows
        .map(r => [r[col1], r[col2]])
        .filter(([a, b]) => typeof a === 'number' && typeof b === 'number')

      // Require at least 5 data pairs for correlation calculation.
      // Fewer than 5 pairs can lead to unreliable or spurious correlation results;
      // 5 is a commonly used minimum threshold for meaningful statistical analysis.
      if (pairs.length >= 5) {
        const x = pairs.map(p => p[0])
        const y = pairs.map(p => p[1])
        const correlation = calculatePearsonCorrelation(x, y)

        correlations.push({
          column1: col1,
          column2: col2,
          correlation,
          strength: Math.abs(correlation) > 0.7 ? 'strong' :
                    Math.abs(correlation) > 0.4 ? 'moderate' : 'weak'
        })
      }
    }
  }

  return {
    detected: correlations.length > 0,
    correlations,
    strongestPair: correlations.length > 0 ?
      correlations.reduce((best, curr) =>
        Math.abs(curr.correlation) > Math.abs(best.correlation) ? curr : best
      ) : null
  }
}

function calculatePearsonCorrelation(x, y) {
  const n = x.length
  if (n === 0) return 0

  const sumX = x.reduce((a, b) => a + b, 0)
  const sumY = y.reduce((a, b) => a + b, 0)
  const sumXY = x.reduce((sum, xi, i) => sum + xi * y[i], 0)
  const sumX2 = x.reduce((sum, xi) => sum + xi * xi, 0)
  const sumY2 = y.reduce((sum, yi) => sum + yi * yi, 0)

  const numerator = n * sumXY - sumX * sumY
  const denominator = Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY))

  return denominator === 0 ? 0 : numerator / denominator
}

/**
 * Detect geographic pattern
 */
function detectGeographic(structure) {
  const { geographicColumns, numericColumns } = structure

  if (geographicColumns.length === 0) {
    return { detected: false }
  }

  const geoCol = geographicColumns[0]

  return {
    detected: true,
    column: geoCol.name,
    geoType: geoCol.metadata.geoType || geoCol.type,
    hasValue: numericColumns.length > 0,
    valueColumn: numericColumns.length > 0 ? numericColumns[0].name : null
  }
}

/**
 * Main recommendation function
 */
export function recommendCharts(columnAnalysis, rows) {
  const recommendations = []
  const rowCount = rows.length

  // Analyze structure and patterns
  const structure = analyzeStructure(columnAnalysis)
  const timeSeries = detectTimeSeries(columnAnalysis, rows)
  const partToWhole = detectPartToWhole(structure, rows)
  const correlation = detectCorrelation(structure, rows)
  const geographic = detectGeographic(structure)

  // Rule 1: Time Series Data -> Line/Area charts
  if (timeSeries.detected && structure.numericCount >= 1) {
    const numericCols = structure.numericColumns.map(c => c.name)

    if (numericCols.length === 1) {
      recommendations.push({
        type: ChartTypes.LINE,
        score: 0.95,
        reason: 'Time series data with single metric - best shown as line chart',
        config: {
          xAxis: timeSeries.column,
          yAxis: numericCols[0],
          granularity: timeSeries.granularity
        }
      })
      recommendations.push({
        type: ChartTypes.AREA,
        score: 0.85,
        reason: 'Time series can also be visualized as area chart',
        config: {
          xAxis: timeSeries.column,
          yAxis: numericCols[0]
        }
      })
    } else {
      recommendations.push({
        type: ChartTypes.MULTI_LINE,
        score: 0.95,
        reason: 'Time series with multiple metrics - multi-line chart',
        config: {
          xAxis: timeSeries.column,
          series: numericCols
        }
      })
      recommendations.push({
        type: ChartTypes.STACKED_AREA,
        score: 0.80,
        reason: 'Multiple time series can be stacked',
        config: {
          xAxis: timeSeries.column,
          series: numericCols
        }
      })
    }
  }

  // Rule 2: Geographic Data -> Map charts
  if (geographic.detected && geographic.hasValue) {
    recommendations.push({
      type: ChartTypes.CHOROPLETH,
      score: 0.90,
      reason: `Geographic data (${geographic.geoType}) with values - choropleth map`,
      config: {
        geoColumn: geographic.column,
        valueColumn: geographic.valueColumn,
        geoType: geographic.geoType
      }
    })
  }

  // Rule 3: Part-to-Whole Data -> Pie/Donut/Treemap
  if (partToWhole.detected) {
    if (partToWhole.isIdealForPie) {
      recommendations.push({
        type: ChartTypes.PIE,
        score: 0.95,
        reason: `${partToWhole.partCount} categories with values - ideal for pie chart`,
        config: {
          categoryColumn: partToWhole.categoricalColumn,
          valueColumn: partToWhole.valueColumn
        }
      })
      recommendations.push({
        type: ChartTypes.DONUT,
        score: 0.90,
        reason: 'Donut chart offers similar view with center space',
        config: {
          categoryColumn: partToWhole.categoricalColumn,
          valueColumn: partToWhole.valueColumn
        }
      })
    } else {
      recommendations.push({
        type: ChartTypes.DONUT,
        score: 0.85,
        reason: `${partToWhole.partCount} categories - donut handles more categories`,
        config: {
          categoryColumn: partToWhole.categoricalColumn,
          valueColumn: partToWhole.valueColumn
        }
      })
      recommendations.push({
        type: ChartTypes.TREEMAP,
        score: 0.80,
        reason: 'Treemap works well for many categories',
        config: {
          categoryColumn: partToWhole.categoricalColumn,
          valueColumn: partToWhole.valueColumn
        }
      })
    }
  }

  // Rule 4: Strong Correlation -> Scatter plot
  if (correlation.detected && correlation.strongestPair) {
    const pair = correlation.strongestPair
    recommendations.push({
      type: ChartTypes.SCATTER,
      score: pair.strength === 'strong' ? 0.95 : 0.85,
      reason: `${pair.strength} correlation (${pair.correlation.toFixed(2)}) between ${pair.column1} and ${pair.column2}`,
      config: {
        xAxis: pair.column1,
        yAxis: pair.column2,
        correlation: pair.correlation
      }
    })

    // If there's a third numeric, suggest bubble
    if (structure.numericCount >= 3) {
      const thirdCol = structure.numericColumns.find(c =>
        c.name !== pair.column1 && c.name !== pair.column2
      )
      if (thirdCol) {
        recommendations.push({
          type: ChartTypes.BUBBLE,
          score: 0.80,
          reason: 'Three numeric columns - bubble chart shows 3 dimensions',
          config: {
            xAxis: pair.column1,
            yAxis: pair.column2,
            sizeColumn: thirdCol.name
          }
        })
      }
    }
  }

  // Rule 5: Single Numeric Distribution -> Histogram
  if (structure.numericCount === 1 && structure.categoricalCount === 0 && !timeSeries.detected) {
    recommendations.push({
      type: ChartTypes.HISTOGRAM,
      score: 0.85,
      reason: 'Single numeric column - histogram shows distribution',
      config: {
        column: structure.numericColumns[0].name
      }
    })
  }

  // Rule 6: Category + Numeric -> Bar Chart
  if (structure.categoricalCount >= 1 && structure.numericCount >= 1 && !timeSeries.detected) {
    const catCol = structure.categoricalColumns[0]
    const numCols = structure.numericColumns

    // High cardinality (>50 categories) makes bar charts unreadable - suggest scatter instead
    if (catCol.metadata?.cardinality > 50 && structure.numericCount >= 2) {
      recommendations.push({
        type: ChartTypes.SCATTER,
        score: 0.85,
        reason: `Too many categories (${catCol.metadata?.cardinality}) for bar chart - scatter shows patterns better`,
        config: {
          xAxis: numCols[0].name,
          yAxis: numCols[1].name
        }
      })
    } else if (numCols.length === 1) {
      const isHorizontalBetter = (catCol.metadata?.cardinality || 0) > 8 ||
        (catCol.metadata?.categories && catCol.metadata.categories.some(c => c.length > 15))

      // Skip bar chart if cardinality is too high for meaningful visualization
      if ((catCol.metadata?.cardinality || 0) <= 50) {
        recommendations.push({
          type: isHorizontalBetter ? ChartTypes.BAR_HORIZONTAL : ChartTypes.BAR,
          score: 0.90,
          reason: `Categorical (${catCol.metadata?.cardinality || 'N/A'} items) vs numeric - bar chart`,
          config: {
            categoryColumn: catCol.name,
            valueColumn: numCols[0].name
          }
        })
      }
    } else {
      recommendations.push({
        type: ChartTypes.GROUPED_BAR,
        score: 0.88,
        reason: 'Multiple metrics per category - grouped bar chart',
        config: {
          categoryColumn: catCol.name,
          valueColumns: numCols.map(c => c.name)
        }
      })
      recommendations.push({
        type: ChartTypes.STACKED_BAR,
        score: 0.82,
        reason: 'Multiple metrics can be stacked for total view',
        config: {
          categoryColumn: catCol.name,
          valueColumns: numCols.map(c => c.name)
        }
      })
    }
  }

  // Rule 7: Two Categories + Numeric -> Heatmap
  if (structure.categoricalCount >= 2 && structure.numericCount >= 1) {
    const cat1 = structure.categoricalColumns[0]
    const cat2 = structure.categoricalColumns[1]
    const numCol = structure.numericColumns[0]

    // Heatmap works best with reasonable cardinality (max 12x12 = 144 cells)
    if ((cat1.metadata?.cardinality || 0) <= 12 && (cat2.metadata?.cardinality || 0) <= 12) {
      recommendations.push({
        type: ChartTypes.HEATMAP,
        score: 0.85,
        reason: 'Two categorical dimensions with values - heatmap',
        config: {
          xAxis: cat1.name,
          yAxis: cat2.name,
          valueColumn: numCol.name
        }
      })
    }
  }

  // Rule 8: Multiple Numeric (no time) -> Radar (if small dataset)
  if (structure.numericCount >= 3 && structure.temporalCount === 0 &&
      rowCount <= 10 && structure.categoricalCount >= 1) {
    // Radar is ideal when 3-6 metrics with ≤5 rows - boost score significantly
    const isIdealForRadar = structure.numericCount >= 3 &&
                            structure.numericCount <= 6 &&
                            rowCount >= 1 && rowCount <= 5
    recommendations.push({
      type: ChartTypes.RADAR,
      score: isIdealForRadar ? 0.92 : 0.70,
      reason: isIdealForRadar
        ? `Ideal for radar: ${structure.numericCount} metrics across ${rowCount} items`
        : 'Multiple metrics per item - radar shows all dimensions',
      config: {
        categoryColumn: structure.categoricalColumns[0]?.name,
        valueColumns: structure.numericColumns.map(c => c.name)
      }
    })
  }

  // Rule 9: Single row with single numeric column - Gauge chart
  if (rowCount === 1 && structure.numericCount === 1) {
    recommendations.push({
      type: ChartTypes.GAUGE,
      score: 0.85,
      reason: 'Single metric value - gauge shows progress toward goal',
      config: {
        valueColumn: structure.numericColumns[0].name,
        label: structure.numericColumns[0].name
      }
    })
  }

  // Rule 10: Single row with multiple numeric columns - transpose to bar chart
  // Column names become categories, their values become the bars
  if (rowCount === 1 && structure.numericCount >= 2) {
    recommendations.push({
      type: ChartTypes.BAR,
      score: 0.85,
      reason: 'Single row metrics - comparing values across columns',
      config: {
        mode: 'transpose', // Special mode: columns as categories
        valueColumns: structure.numericColumns.map(c => c.name)
      }
    })
    recommendations.push({
      type: ChartTypes.PIE,
      score: 0.75,
      reason: 'Single row metrics as proportions',
      config: {
        mode: 'transpose',
        valueColumns: structure.numericColumns.map(c => c.name)
      }
    })
  }

  // Rule 10: Small dataset with numeric columns - simple bar chart
  if (structure.numericCount >= 1 && structure.categoricalCount >= 1 && recommendations.length === 0) {
    const numCol = structure.numericColumns[0]
    const catCol = structure.categoricalColumns[0]

    recommendations.push({
      type: ChartTypes.BAR,
      score: 0.75,
      reason: 'Simple bar chart for available data',
      config: {
        categoryColumn: catCol.name,
        valueColumn: numCol.name
      }
    })
  }

  // Rule 11: Multiple numeric columns - show as grouped bar even with few rows
  if (structure.numericCount >= 2 && rowCount <= 5 && recommendations.length === 0) {
    // Find the first non-ID, non-numeric column to use as category axis
    // Prefer categorical columns, then fall back to any non-ID/non-numeric column
    const categoryCol = structure.categoricalColumns[0] ||
      columnAnalysis.find(c => c.type !== ColumnTypes.ID && !NUMERIC_TYPES.has(c.type)) ||
      columnAnalysis[0]
    recommendations.push({
      type: ChartTypes.GROUPED_BAR,
      score: 0.70,
      reason: 'Multiple numeric values comparison',
      config: {
        categoryColumn: categoryCol.name,
        valueColumns: structure.numericColumns.map(c => c.name)
      }
    })
  }

  // Always add table as fallback
  recommendations.push({
    type: ChartTypes.TABLE,
    score: 0.30,
    reason: 'Raw data view',
    config: {}
  })

  // Sort by score and deduplicate
  const seen = new Set()
  return recommendations
    .sort((a, b) => b.score - a.score)
    .filter(rec => {
      if (seen.has(rec.type)) return false
      seen.add(rec.type)
      return true
    })
    .slice(0, 6) // Return top 6 recommendations
}

/**
 * Get the best chart recommendation
 */
export function getBestChart(columnAnalysis, rows) {
  const recommendations = recommendCharts(columnAnalysis, rows)
  return recommendations[0] || {
    type: ChartTypes.TABLE,
    score: 0.30,
    reason: 'Default to table view',
    config: {}
  }
}

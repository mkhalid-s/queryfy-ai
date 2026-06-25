/**
 * Chart Transformers
 * Convert query results into ECharts option format
 */

import { ChartTypes } from './chartRecommendation.js'

// ============================================
// LARGE DATASET HANDLING
// ============================================

const LARGE_DATASET_THRESHOLD = 500
const SAMPLE_SIZE = 200
const MAX_PIE_SLICES = 10
const PIE_AGGREGATION_THRESHOLD = 0.02 // 2% threshold for "Other"

/**
 * Sample rows for large datasets using stratified sampling
 */
function sampleRows(rows, maxSize = SAMPLE_SIZE) {
  if (rows.length <= maxSize) return rows

  // Use systematic sampling to maintain distribution
  const step = rows.length / maxSize
  const sampled = []
  for (let i = 0; i < maxSize; i++) {
    const idx = Math.floor(i * step)
    sampled.push(rows[idx])
  }
  return sampled
}

/**
 * Aggregate small pie chart slices into "Other" category
 */
function aggregatePieSlices(data, maxSlices = MAX_PIE_SLICES, thresholdPercent = PIE_AGGREGATION_THRESHOLD) {
  if (data.length <= maxSlices) return { data, aggregated: false, otherCount: 0 }

  const total = data.reduce((sum, d) => sum + d.value, 0)
  if (total === 0) return { data, aggregated: false, otherCount: 0 }

  // Sort by value descending
  const sorted = [...data].sort((a, b) => b.value - a.value)

  // Keep top slices and aggregate the rest
  const kept = []
  let otherValue = 0
  let otherCount = 0

  sorted.forEach((item, idx) => {
    const percentage = item.value / total
    // Keep if in top (maxSlices - 1) OR above threshold percentage
    if (idx < maxSlices - 1 || percentage >= thresholdPercent) {
      kept.push(item)
    } else {
      otherValue += item.value
      otherCount++
    }
  })

  // Add "Other" slice if we aggregated any
  if (otherCount > 0) {
    kept.push({
      name: `Other (${otherCount} items)`,
      value: otherValue,
      itemStyle: { color: '#9CA3AF' } // Gray color for "Other"
    })
  }

  return { data: kept, aggregated: otherCount > 0, otherCount }
}

/**
 * Smart truncate labels at word boundaries
 */
function smartTruncateLabel(label, maxLength = 20) {
  if (!label || label.length <= maxLength) return label

  // Find last space before maxLength
  const truncated = label.substring(0, maxLength)
  const lastSpace = truncated.lastIndexOf(' ')

  if (lastSpace > maxLength * 0.5) {
    return truncated.substring(0, lastSpace) + '...'
  }
  return truncated + '...'
}

/**
 * Check if dataset should use DataZoom
 */
export function shouldUseDataZoom(rowCount) {
  return rowCount > 50
}

/**
 * Get DataZoom configuration for large datasets
 */
export function getDataZoomConfig(rowCount) {
  if (rowCount <= 50) return null

  const startPercent = Math.max(0, 100 - (50 / rowCount * 100))

  return {
    dataZoom: [
      {
        type: 'slider',
        show: true,
        start: startPercent,
        end: 100,
        height: 20,
        bottom: 0,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255,255,255,0.05)',
        fillerColor: 'rgba(0, 115, 157, 0.2)',
        handleStyle: {
          color: '#00739d'
        }
      },
      {
        type: 'inside',
        start: startPercent,
        end: 100
      }
    ]
  }
}

/**
 * Main transformer entry point
 */
export function transformForChart(chartType, columns, rows, config) {
  const transformers = {
    [ChartTypes.BAR]: transformBarChart,
    [ChartTypes.BAR_HORIZONTAL]: transformHorizontalBarChart,
    [ChartTypes.LINE]: transformLineChart,
    [ChartTypes.AREA]: transformAreaChart,
    [ChartTypes.PIE]: transformPieChart,
    [ChartTypes.DONUT]: transformDonutChart,
    [ChartTypes.SCATTER]: transformScatterChart,
    [ChartTypes.BUBBLE]: transformBubbleChart,
    [ChartTypes.HISTOGRAM]: transformHistogramChart,
    [ChartTypes.MULTI_LINE]: transformMultiLineChart,
    [ChartTypes.STACKED_BAR]: transformStackedBarChart,
    [ChartTypes.GROUPED_BAR]: transformGroupedBarChart,
    [ChartTypes.STACKED_AREA]: transformStackedAreaChart,
    [ChartTypes.HEATMAP]: transformHeatmapChart,
    [ChartTypes.TREEMAP]: transformTreemapChart,
    [ChartTypes.RADAR]: transformRadarChart,
    [ChartTypes.FUNNEL]: transformFunnelChart,
    [ChartTypes.GAUGE]: transformGaugeChart,
    [ChartTypes.GEO_MAP]: transformGeoMapChart,
    [ChartTypes.CHOROPLETH]: transformChoroplethChart
  }

  const transformer = transformers[chartType]
  if (!transformer) {
    console.warn(`No transformer for chart type: ${chartType}`)
    return null
  }

  return transformer(columns, rows, config)
}

// --- Helper Functions ---

function formatAxisLabel(value) {
  if (value === null || value === undefined) return ''

  // Handle ISO datetime
  if (typeof value === 'string' && value.match(/^\d{4}-\d{2}-\d{2}/)) {
    const date = new Date(value)
    if (!isNaN(date.getTime())) {
      // Check if has time component
      if (value.includes('T') && !value.includes('T00:00:00')) {
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit' })
      }
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' })
    }
  }

  return String(value)
}

function sortByDate(rows, dateColumn) {
  return [...rows].sort((a, b) => {
    const dateA = new Date(a[dateColumn])
    const dateB = new Date(b[dateColumn])
    return dateA.getTime() - dateB.getTime()
  })
}

function getBaseGridOption() {
  return {
    left: '3%',
    right: '4%',
    bottom: '10%',
    top: '10%',
    containLabel: true
  }
}

// --- Chart Transformers ---

function transformBarChart(columns, rows, config) {
  const { categoryColumn, valueColumn, mode, valueColumns } = config

  // Handle transpose mode: column names as categories (for single row data)
  if (mode === 'transpose' && valueColumns && rows.length > 0) {
    const row = rows[0]
    const categories = valueColumns
    const values = valueColumns.map(col => Number(row[col]) || 0)

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' }
      },
      grid: getBaseGridOption(),
      xAxis: {
        type: 'category',
        data: categories,
        axisLabel: {
          rotate: categories.length > 6 ? 45 : 0,
          interval: 0,
          overflow: 'truncate',
          width: 100
        }
      },
      yAxis: {
        type: 'value',
        nameLocation: 'middle',
        nameGap: 50
      },
      series: [{
        type: 'bar',
        data: values,
        itemStyle: {
          borderRadius: [4, 4, 0, 0]
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0,0,0,0.3)'
          }
        }
      }]
    }
  }

  // Standard mode: rows as data points
  // Sample large datasets to prevent performance issues
  const displayRows = rows.length > LARGE_DATASET_THRESHOLD
    ? sampleRows(rows, SAMPLE_SIZE)
    : rows

  const categories = displayRows.map(r => smartTruncateLabel(String(r[categoryColumn]), 20))
  const values = displayRows.map(r => Number(r[valueColumn]) || 0)

  // Show sampling notice in title if data was sampled
  const titleConfig = rows.length > LARGE_DATASET_THRESHOLD ? {
    title: {
      text: `Sampled ${SAMPLE_SIZE} of ${rows.length} rows`,
      left: 'center',
      top: 0,
      textStyle: {
        fontSize: 12,
        fontWeight: 'normal',
        color: '#9CA3AF'
      }
    }
  } : {}

  return {
    ...titleConfig,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    grid: getBaseGridOption(),
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        rotate: categories.length > 6 ? 45 : 0,
        interval: 0,
        overflow: 'truncate',
        width: 100
      }
    },
    yAxis: {
      type: 'value',
      name: valueColumn,
      nameLocation: 'middle',
      nameGap: 50
    },
    series: [{
      type: 'bar',
      data: values,
      itemStyle: {
        borderRadius: [4, 4, 0, 0]
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowColor: 'rgba(0,0,0,0.3)'
        }
      }
    }]
  }
}

function transformHorizontalBarChart(columns, rows, config) {
  const { categoryColumn, valueColumn } = config

  const categories = rows.map(r => String(r[categoryColumn]))
  const values = rows.map(r => Number(r[valueColumn]) || 0)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    grid: {
      ...getBaseGridOption(),
      left: '15%'
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        overflow: 'truncate',
        width: 100
      }
    },
    xAxis: {
      type: 'value',
      name: valueColumn
    },
    series: [{
      type: 'bar',
      data: values,
      itemStyle: {
        borderRadius: [0, 4, 4, 0]
      }
    }]
  }
}

function transformLineChart(columns, rows, config) {
  const { xAxis, yAxis } = config

  // Sort by x-axis if temporal
  const sortedRows = sortByDate(rows, xAxis)

  const categories = sortedRows.map(r => formatAxisLabel(r[xAxis]))
  const values = sortedRows.map(r => Number(r[yAxis]) || 0)

  return {
    tooltip: {
      trigger: 'axis'
    },
    grid: getBaseGridOption(),
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: false,
      axisLabel: {
        rotate: categories.length > 10 ? 45 : 0
      }
    },
    yAxis: {
      type: 'value',
      name: yAxis,
      nameLocation: 'middle',
      nameGap: 50
    },
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      symbol: rows.length > 50 ? 'none' : 'circle',
      symbolSize: 6,
      lineStyle: { width: 2 },
      areaStyle: null
    }]
  }
}

function transformAreaChart(columns, rows, config) {
  const lineOption = transformLineChart(columns, rows, config)

  lineOption.series[0].areaStyle = {
    opacity: 0.3
  }

  return lineOption
}

function transformMultiLineChart(columns, rows, config) {
  const { xAxis, series: seriesColumns } = config

  const sortedRows = sortByDate(rows, xAxis)
  const categories = sortedRows.map(r => formatAxisLabel(r[xAxis]))

  const series = seriesColumns.map(col => ({
    type: 'line',
    name: col,
    data: sortedRows.map(r => Number(r[col]) || 0),
    smooth: true,
    symbol: rows.length > 30 ? 'none' : 'circle',
    symbolSize: 5
  }))

  return {
    tooltip: {
      trigger: 'axis'
    },
    legend: {
      data: seriesColumns,
      bottom: 0
    },
    grid: {
      ...getBaseGridOption(),
      bottom: '15%'
    },
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: false
    },
    yAxis: {
      type: 'value'
    },
    series
  }
}

function transformStackedAreaChart(columns, rows, config) {
  const multiLineOption = transformMultiLineChart(columns, rows, config)

  multiLineOption.series = multiLineOption.series.map(s => ({
    ...s,
    stack: 'Total',
    areaStyle: { opacity: 0.6 }
  }))

  return multiLineOption
}

function transformPieChart(columns, rows, config) {
  const { categoryColumn, valueColumn, mode, valueColumns } = config

  let rawData

  // Handle transpose mode: column names as categories (for single row data)
  if (mode === 'transpose' && valueColumns && rows.length > 0) {
    const row = rows[0]
    rawData = valueColumns.map(col => ({
      name: col,
      value: Number(row[col]) || 0
    }))
  } else {
    rawData = rows.map(r => ({
      name: String(r[categoryColumn]),
      value: Number(r[valueColumn]) || 0
    }))
  }

  // Filter negative values
  const negativeValues = rawData.filter(d => d.value < 0)
  if (negativeValues.length > 0) {
    console.warn('Negative values found in pie chart data and have been excluded:', negativeValues)
  }
  const positiveData = rawData.filter(d => d.value > 0)

  // Aggregate small slices into "Other" to prevent cluttered charts
  const { data, aggregated } = aggregatePieSlices(positiveData)

  // Build title if data was aggregated
  const titleConfig = aggregated ? {
    title: {
      text: `Showing top ${data.length - 1} of ${positiveData.length} items`,
      left: 'center',
      top: 0,
      textStyle: {
        fontSize: 12,
        fontWeight: 'normal',
        color: '#9CA3AF'
      }
    }
  } : {}

  return {
    ...titleConfig,
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)'
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      type: 'scroll'
    },
    series: [{
      type: 'pie',
      radius: '65%',
      center: ['40%', '50%'],
      data,
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowOffsetX: 0,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      },
      label: {
        formatter: '{b}: {d}%'
      }
    }]
  }
}

function transformDonutChart(columns, rows, config) {
  const pieOption = transformPieChart(columns, rows, config)

  pieOption.series[0].radius = ['40%', '70%']

  return pieOption
}

function transformScatterChart(columns, rows, config) {
  const { xAxis, yAxis, correlation } = config

  // Sample large datasets to prevent performance issues
  const displayRows = rows.length > LARGE_DATASET_THRESHOLD
    ? sampleRows(rows, SAMPLE_SIZE)
    : rows

  const data = displayRows
    .map(r => [Number(r[xAxis]), Number(r[yAxis])])
    .filter(([x, y]) => !isNaN(x) && !isNaN(y))

  // Show sampling notice in title if data was sampled
  const titleConfig = rows.length > LARGE_DATASET_THRESHOLD ? {
    title: {
      text: `Sampled ${SAMPLE_SIZE} of ${rows.length} points`,
      left: 'center',
      top: 0,
      textStyle: {
        fontSize: 12,
        fontWeight: 'normal',
        color: '#9CA3AF'
      }
    }
  } : {}

  const option = {
    ...titleConfig,
    tooltip: {
      trigger: 'item',
      formatter: params => `${xAxis}: ${params.value[0]}<br/>${yAxis}: ${params.value[1]}`
    },
    grid: getBaseGridOption(),
    xAxis: {
      type: 'value',
      name: xAxis,
      nameLocation: 'middle',
      nameGap: 30
    },
    yAxis: {
      type: 'value',
      name: yAxis,
      nameLocation: 'middle',
      nameGap: 50
    },
    series: [{
      type: 'scatter',
      data,
      symbolSize: rows.length > 100 ? 6 : 10,
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      }
    }]
  }

  // Add trend line if strong correlation
  if (correlation && Math.abs(correlation) > 0.5) {
    const xValues = data.map(d => d[0])
    const yValues = data.map(d => d[1])
    const { slope, intercept } = linearRegression(xValues, yValues)

    const minX = Math.min(...xValues)
    const maxX = Math.max(...xValues)

    option.series.push({
      type: 'line',
      data: [
        [minX, slope * minX + intercept],
        [maxX, slope * maxX + intercept]
      ],
      symbol: 'none',
      lineStyle: {
        type: 'dashed',
        opacity: 0.6
      }
    })
  }

  return option
}

function linearRegression(x, y) {
  const n = x.length
  if (n === 0) return { slope: 0, intercept: 0 }

  const sumX = x.reduce((a, b) => a + b, 0)
  const sumY = y.reduce((a, b) => a + b, 0)
  const sumXY = x.reduce((sum, xi, i) => sum + xi * y[i], 0)
  const sumX2 = x.reduce((sum, xi) => sum + xi * xi, 0)

  // Handle edge case: all x values are the same (vertical line of points)
  const denominator = n * sumX2 - sumX * sumX
  if (denominator === 0) {
    return { slope: 0, intercept: sumY / n } // Return horizontal line through mean
  }

  const slope = (n * sumXY - sumX * sumY) / denominator
  const intercept = (sumY - slope * sumX) / n

  return { slope, intercept }
}

function transformBubbleChart(columns, rows, config) {
  const { xAxis, yAxis, sizeColumn } = config

  const sizes = rows.map(r => Number(r[sizeColumn]) || 0)
  const maxSize = Math.max(...sizes)
  const minSize = Math.min(...sizes)

  const data = rows
    .map(r => {
      const x = Number(r[xAxis])
      const y = Number(r[yAxis])
      const size = Number(r[sizeColumn])
      if (isNaN(x) || isNaN(y) || isNaN(size)) return null

      // Normalize size to 10-50 range
      const normalizedSize = maxSize === minSize ? 20 :
        10 + ((size - minSize) / (maxSize - minSize)) * 40

      return [x, y, size, normalizedSize]
    })
    .filter(Boolean)

  return {
    tooltip: {
      trigger: 'item',
      formatter: params => `${xAxis}: ${params.value[0]}<br/>${yAxis}: ${params.value[1]}<br/>${sizeColumn}: ${params.value[2]}`
    },
    grid: getBaseGridOption(),
    xAxis: {
      type: 'value',
      name: xAxis,
      nameLocation: 'middle',
      nameGap: 30
    },
    yAxis: {
      type: 'value',
      name: yAxis,
      nameLocation: 'middle',
      nameGap: 50
    },
    series: [{
      type: 'scatter',
      data: data.map(d => ({
        value: [d[0], d[1], d[2]],
        symbolSize: d[3]
      }))
    }]
  }
}

function transformHistogramChart(columns, rows, config) {
  const { column } = config

  const values = rows.map(r => Number(r[column])).filter(v => !isNaN(v))

  if (values.length === 0) {
    return null
  }

  // Calculate histogram bins
  const min = Math.min(...values)
  const max = Math.max(...values)

  // Handle edge case: all values are the same
  if (min === max) {
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: getBaseGridOption(),
      xAxis: { type: 'category', data: [min.toFixed(1)], name: column },
      yAxis: { type: 'value', name: 'Frequency' },
      series: [{ type: 'bar', data: [values.length], barWidth: '50%' }]
    }
  }

  const binCount = Math.min(20, Math.ceil(Math.sqrt(values.length)))
  const binWidth = (max - min) / binCount

  const bins = Array(binCount).fill(0)
  const binLabels = []

  for (let i = 0; i < binCount; i++) {
    const binStart = min + i * binWidth
    const binEnd = binStart + binWidth
    binLabels.push(`${binStart.toFixed(1)}-${binEnd.toFixed(1)}`)
  }

  values.forEach(v => {
    const binIndex = Math.min(Math.floor((v - min) / binWidth), binCount - 1)
    bins[binIndex]++
  })

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    grid: getBaseGridOption(),
    xAxis: {
      type: 'category',
      data: binLabels,
      name: column,
      nameLocation: 'middle',
      nameGap: 35,
      axisLabel: {
        rotate: 45
      }
    },
    yAxis: {
      type: 'value',
      name: 'Frequency'
    },
    series: [{
      type: 'bar',
      data: bins,
      barWidth: '90%',
      itemStyle: {
        borderRadius: [2, 2, 0, 0]
      }
    }]
  }
}

function transformGroupedBarChart(columns, rows, config) {
  const { categoryColumn, valueColumns } = config

  const categories = rows.map(r => String(r[categoryColumn]))

  const series = valueColumns.map(col => ({
    type: 'bar',
    name: col,
    data: rows.map(r => Number(r[col]) || 0),
    itemStyle: {
      borderRadius: [4, 4, 0, 0]
    }
  }))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    legend: {
      data: valueColumns,
      bottom: 0
    },
    grid: {
      ...getBaseGridOption(),
      bottom: '15%'
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        rotate: categories.length > 6 ? 45 : 0
      }
    },
    yAxis: {
      type: 'value'
    },
    series
  }
}

function transformStackedBarChart(columns, rows, config) {
  const groupedOption = transformGroupedBarChart(columns, rows, config)

  groupedOption.series = groupedOption.series.map(s => ({
    ...s,
    stack: 'Total'
  }))

  return groupedOption
}

function transformHeatmapChart(columns, rows, config) {
  const { xAxis, yAxis, valueColumn } = config

  const xCategories = [...new Set(rows.map(r => String(r[xAxis])))]
  const yCategories = [...new Set(rows.map(r => String(r[yAxis])))]

  const data = []
  rows.forEach(r => {
    const xIdx = xCategories.indexOf(String(r[xAxis]))
    const yIdx = yCategories.indexOf(String(r[yAxis]))
    const value = Number(r[valueColumn]) || 0
    data.push([xIdx, yIdx, value])
  })

  const values = data.map(d => d[2])
  const minVal = Math.min(...values)
  const maxVal = Math.max(...values)

  return {
    tooltip: {
      position: 'top',
      formatter: params => {
        return `${xCategories[params.value[0]]}, ${yCategories[params.value[1]]}: ${params.value[2]}`
      }
    },
    grid: {
      top: '10%',
      left: '15%',
      right: '10%',
      bottom: '20%'
    },
    xAxis: {
      type: 'category',
      data: xCategories,
      splitArea: { show: true },
      axisLabel: { rotate: xCategories.length > 8 ? 45 : 0 }
    },
    yAxis: {
      type: 'category',
      data: yCategories,
      splitArea: { show: true }
    },
    visualMap: {
      min: minVal,
      max: maxVal,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: '0%'
    },
    series: [{
      type: 'heatmap',
      data,
      label: {
        show: data.length < 100
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      }
    }]
  }
}

function transformTreemapChart(columns, rows, config) {
  const { categoryColumn, valueColumn } = config

  const data = rows.map(r => ({
    name: String(r[categoryColumn]),
    value: Number(r[valueColumn]) || 0
  }))

  return {
    tooltip: {
      formatter: params => `${params.name}: ${params.value}`
    },
    series: [{
      type: 'treemap',
      data,
      leafDepth: 1,
      label: {
        show: true,
        formatter: '{b}'
      },
      breadcrumb: {
        show: false
      },
      levels: [{
        itemStyle: {
          borderWidth: 2,
          borderColor: '#fff',
          gapWidth: 2
        }
      }]
    }]
  }
}

function transformRadarChart(columns, rows, config) {
  const { categoryColumn, valueColumns } = config
  const MAX_RADAR_ITEMS = 5

  // Find max value for each indicator
  const indicators = valueColumns.map(col => {
    const values = rows.map(r => Number(r[col]) || 0)
    return {
      name: smartTruncateLabel(col, 15),
      max: Math.max(...values) * 1.2 // Add 20% padding
    }
  })

  const isTruncated = rows.length > MAX_RADAR_ITEMS
  const displayRows = rows.slice(0, MAX_RADAR_ITEMS)

  const data = displayRows.map(r => ({
    name: categoryColumn ? String(r[categoryColumn]) : `Item ${rows.indexOf(r) + 1}`,
    value: valueColumns.map(col => Number(r[col]) || 0)
  }))

  // Show truncation warning in title
  const titleConfig = isTruncated ? {
    title: {
      text: `Showing ${MAX_RADAR_ITEMS} of ${rows.length} items`,
      left: 'center',
      top: 0,
      textStyle: {
        fontSize: 12,
        fontWeight: 'normal',
        color: '#9CA3AF'
      }
    }
  } : {}

  return {
    ...titleConfig,
    tooltip: {
      trigger: 'item'
    },
    legend: {
      data: data.map(d => d.name),
      bottom: 0
    },
    radar: {
      indicator: indicators,
      shape: 'polygon'
    },
    series: [{
      type: 'radar',
      data
    }]
  }
}

function transformFunnelChart(columns, rows, config) {
  const { categoryColumn, valueColumn } = config

  // Sort by value descending for funnel effect
  const sortedRows = [...rows].sort((a, b) =>
    (Number(b[valueColumn]) || 0) - (Number(a[valueColumn]) || 0)
  )

  const data = sortedRows.map(r => ({
    name: String(r[categoryColumn]),
    value: Number(r[valueColumn]) || 0
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c}'
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center'
    },
    series: [{
      type: 'funnel',
      left: '10%',
      top: 60,
      bottom: 60,
      width: '60%',
      min: 0,
      max: Math.max(...data.map(d => d.value)),
      minSize: '0%',
      maxSize: '100%',
      sort: 'descending',
      gap: 2,
      label: {
        show: true,
        position: 'inside'
      },
      data
    }]
  }
}

function transformGaugeChart(columns, rows, config) {
  const { valueColumn, label, minValue = 0, maxValue = 100 } = config

  // Get the value from first row
  const value = rows.length > 0 ? Number(rows[0][valueColumn]) || 0 : 0
  const displayLabel = label || valueColumn

  // Calculate appropriate max if not provided and value exceeds default
  const effectiveMax = value > maxValue ? Math.ceil(value * 1.2) : maxValue

  return {
    tooltip: {
      formatter: '{b}: {c}'
    },
    series: [{
      type: 'gauge',
      min: minValue,
      max: effectiveMax,
      progress: {
        show: true,
        width: 18
      },
      axisLine: {
        lineStyle: {
          width: 18,
          color: [
            [0.3, '#67e0e3'],
            [0.7, '#37a2da'],
            [1, '#fd666d']
          ]
        }
      },
      axisTick: {
        show: false
      },
      splitLine: {
        length: 15,
        lineStyle: {
          width: 2,
          color: '#999'
        }
      },
      axisLabel: {
        distance: 25,
        color: '#999',
        fontSize: 12
      },
      anchor: {
        show: true,
        showAbove: true,
        size: 20,
        itemStyle: {
          borderWidth: 8
        }
      },
      pointer: {
        length: '75%',
        width: 8,
        offsetCenter: [0, '5%'],
        itemStyle: {
          color: 'auto'
        }
      },
      title: {
        show: true,
        offsetCenter: [0, '85%'],
        fontSize: 16
      },
      detail: {
        valueAnimation: true,
        fontSize: 28,
        fontWeight: 'bold',
        offsetCenter: [0, '65%'],
        formatter: '{value}'
      },
      data: [{
        value: value,
        name: displayLabel
      }]
    }]
  }
}

function transformGeoMapChart(columns, rows, config) {
  const { geoColumn, valueColumn, geoType = 'world' } = config

  // Map column types to actual map names
  const mapName = getMapName(geoType)

  const data = rows.map(r => ({
    name: normalizeGeoName(String(r[geoColumn]), mapName),
    value: Number(r[valueColumn]) || 0
  }))

  const values = data.map(d => d.value).filter(v => !isNaN(v))
  const minVal = values.length > 0 ? Math.min(...values) : 0
  const maxVal = values.length > 0 ? Math.max(...values) : 100

  return {
    tooltip: {
      trigger: 'item',
      formatter: params => {
        if (params.data) {
          return `${params.name}: ${params.data.value}`
        }
        return params.name
      }
    },
    visualMap: {
      min: minVal,
      max: maxVal,
      text: ['High', 'Low'],
      realtime: false,
      calculable: true,
      inRange: {
        color: ['#e0f3f8', '#abd9e9', '#74add1', '#4575b4', '#313695']
      },
      left: 'left',
      top: 'bottom'
    },
    series: [{
      type: 'map',
      map: mapName,
      roam: true,
      emphasis: {
        label: {
          show: true
        },
        itemStyle: {
          areaColor: '#ffd700'
        }
      },
      data
    }]
  }
}

// Helper: Map geographic column types to actual ECharts map names
function getMapName(geoType) {
  if (!geoType) return 'world'

  const normalizedType = String(geoType).toLowerCase()

  // US state maps
  if (normalizedType === 'us_state' || normalizedType === 'usa' || normalizedType.includes('state')) {
    return 'USA'
  }

  // World map for countries
  return 'world'
}

function transformChoroplethChart(columns, rows, config) {
  const { geoColumn, valueColumn, geoType = 'world' } = config

  // Map column types to actual map names
  const mapName = getMapName(geoType)

  const data = rows.map(r => ({
    name: normalizeGeoName(String(r[geoColumn]), mapName),
    value: Number(r[valueColumn]) || 0
  }))

  const values = data.map(d => d.value).filter(v => !isNaN(v))
  const minVal = values.length > 0 ? Math.min(...values) : 0
  const maxVal = values.length > 0 ? Math.max(...values) : 100

  return {
    tooltip: {
      trigger: 'item',
      formatter: params => {
        if (params.data) {
          return `<strong>${params.name}</strong><br/>${valueColumn}: ${params.data.value.toLocaleString()}`
        }
        return params.name
      }
    },
    visualMap: {
      type: 'continuous',
      min: minVal,
      max: maxVal,
      text: ['High', 'Low'],
      realtime: false,
      calculable: true,
      inRange: {
        color: ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026']
      },
      left: 'left',
      top: 'bottom',
      orient: 'horizontal'
    },
    series: [{
      type: 'map',
      map: mapName,
      roam: true,
      label: {
        show: false
      },
      emphasis: {
        label: {
          show: true,
          fontSize: 12
        },
        itemStyle: {
          areaColor: '#ffd700',
          shadowBlur: 20,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      },
      itemStyle: {
        borderColor: '#fff',
        borderWidth: 0.5
      },
      data
    }]
  }
}

// Helper: Normalize geographic names to match ECharts map data
function normalizeGeoName(name, geoType) {
  if (!name) return name

  // Common country name mappings
  const countryMappings = {
    'USA': 'United States',
    'US': 'United States',
    'U.S.': 'United States',
    'U.S.A.': 'United States',
    'UK': 'United Kingdom',
    'U.K.': 'United Kingdom',
    'GB': 'United Kingdom',
    'Russia': 'Russian Federation',
    'South Korea': 'Korea',
    'North Korea': 'Dem. Rep. Korea',
    'Iran': 'Iran (Islamic Republic of)',
    'Syria': 'Syrian Arab Republic',
    'Vietnam': 'Viet Nam',
    'Tanzania': 'United Republic of Tanzania',
    'Venezuela': 'Venezuela (Bolivarian Republic of)',
    'Bolivia': 'Bolivia (Plurinational State of)',
    'Czech Republic': 'Czechia',
    'Ivory Coast': "Côte d'Ivoire",
    'DR Congo': 'Democratic Republic of the Congo',
    'DRC': 'Democratic Republic of the Congo'
  }

  // US state abbreviation mappings
  const usStateMappings = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
  }

  const upperName = name.toUpperCase()

  // Check US state mappings first for USA map type
  if (geoType === 'USA' && usStateMappings[upperName]) {
    return usStateMappings[upperName]
  }

  // Check country mappings
  if (countryMappings[upperName] || countryMappings[name]) {
    return countryMappings[upperName] || countryMappings[name]
  }

  // Return original name with proper capitalization
  return name
}

/**
 * Chart Annotations Utility
 *
 * Adds intelligent annotations to ECharts options:
 * - Trend lines with equations
 * - Benchmark lines (average, median, previous period)
 * - Outlier markers
 * - Callouts for insights
 */

/**
 * Add annotations to ECharts options
 *
 * @param {Object} chartOptions - Base ECharts options
 * @param {Array} annotations - Annotations from backend
 * @returns {Object} Enhanced chart options with annotations
 */
export function addAnnotations(chartOptions, annotations) {
  if (!annotations || !annotations.length) {
    return chartOptions
  }

  const enhanced = { ...chartOptions }

  // Initialize markLine and markPoint if needed
  if (!enhanced.series) {
    return enhanced
  }

  // Process each annotation
  const markLines = []
  const markPoints = []
  const graphicElements = []

  for (const annotation of annotations) {
    switch (annotation.type) {
      case 'trend_line':
        addTrendLine(annotation, markLines, graphicElements)
        break

      case 'benchmark':
        addBenchmarkLine(annotation, markLines)
        break

      case 'outlier':
        addOutlierMarker(annotation, markPoints)
        break

      case 'callout':
        addCallout(annotation, graphicElements)
        break

      default:
        break
    }
  }

  // Add markLine to first series
  if (markLines.length > 0 && enhanced.series.length > 0) {
    const firstSeries = Array.isArray(enhanced.series) ? enhanced.series[0] : enhanced.series

    if (!firstSeries.markLine) {
      firstSeries.markLine = { data: [] }
    }

    firstSeries.markLine.data = [
      ...(firstSeries.markLine.data || []),
      ...markLines
    ]

    // Style markLine
    firstSeries.markLine.symbol = 'none'
    firstSeries.markLine.label = {
      show: true,
      position: 'end',
      formatter: '{b}',
      color: '#FFFFFF',
      fontSize: 11
    }
  }

  // Add markPoint to first series
  if (markPoints.length > 0 && enhanced.series.length > 0) {
    const firstSeries = Array.isArray(enhanced.series) ? enhanced.series[0] : enhanced.series

    if (!firstSeries.markPoint) {
      firstSeries.markPoint = { data: [] }
    }

    firstSeries.markPoint.data = [
      ...(firstSeries.markPoint.data || []),
      ...markPoints
    ]
  }

  // Add graphic elements for callouts
  if (graphicElements.length > 0) {
    enhanced.graphic = [
      ...(enhanced.graphic || []),
      ...graphicElements
    ]
  }

  return enhanced
}

/**
 * Add trend line annotation
 */
function addTrendLine(annotation, markLines, graphicElements) {
  // Add text element showing trend equation
  graphicElements.push({
    type: 'text',
    left: '10%',
    top: '5%',
    style: {
      text: annotation.equation || 'Trend Line',
      fill: '#1eb7df',
      font: '12px sans-serif'
    }
  })

  // Note: Actual trend line would require calculating points
  // For now, we add a text label
}

/**
 * Add benchmark line (average, median, previous period)
 */
function addBenchmarkLine(annotation, markLines) {
  const style = annotation.style || {}
  const color = style.color || '#1eb7df'
  const dashArray = style.dashArray || '5,5'

  markLines.push({
    name: annotation.label || 'Benchmark',
    yAxis: annotation.value,
    label: {
      formatter: annotation.label || '{b}',
      position: 'end'
    },
    lineStyle: {
      color: color,
      type: dashArray === '5,5' ? 'dashed' : dashArray === '2,2' ? 'dotted' : 'solid',
      width: 2
    }
  })
}

/**
 * Add outlier marker
 */
function addOutlierMarker(annotation, markPoints) {
  markPoints.push({
    name: 'Outlier',
    coord: [annotation.identifier, annotation.value],
    value: annotation.description,
    symbol: 'circle',
    symbolSize: 12,
    itemStyle: {
      color: '#f15f5c',
      borderColor: '#FFFFFF',
      borderWidth: 2
    },
    label: {
      show: false
    },
    emphasis: {
      label: {
        show: true,
        formatter: '{c}',
        position: 'top',
        color: '#FFFFFF',
        backgroundColor: 'rgba(241, 95, 92, 0.9)',
        padding: [4, 8],
        borderRadius: 4
      }
    }
  })
}

/**
 * Add callout annotation
 */
function addCallout(annotation, graphicElements) {
  // Add a text box with background
  graphicElements.push({
    type: 'group',
    left: '70%',
    top: '15%',
    children: [
      {
        type: 'rect',
        shape: {
          width: 200,
          height: 60
        },
        style: {
          fill: 'rgba(241, 95, 92, 0.15)',
          stroke: '#f15f5c',
          lineWidth: 2
        }
      },
      {
        type: 'text',
        left: 10,
        top: 10,
        style: {
          text: annotation.text || 'Alert',
          fill: '#f15f5c',
          font: 'bold 13px sans-serif',
          width: 180
        }
      },
      {
        type: 'text',
        left: 10,
        top: 30,
        style: {
          text: annotation.description || '',
          fill: '#FFFFFF',
          font: '11px sans-serif',
          width: 180,
          overflow: 'truncate'
        }
      }
    ]
  })
}

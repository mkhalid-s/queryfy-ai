<template>
  <div :class="['chart-wrapper', { fullscreen: isFullscreen }]">
    <!-- Chart Header -->
    <div class="chart-header">
      <div class="chart-info">
        <span
          v-if="bestChart && bestChart.type !== 'table'"
          class="chart-type-badge"
        >
          <component
            :is="getChartIcon(bestChart.type)"
            :size="14"
          />
          {{ getChartLabel(bestChart.type) }}
        </span>
        <span
          v-if="dataSummary"
          class="data-summary-badge"
        >{{ dataSummary }}</span>
        <span
          v-if="bestChart?.reason"
          class="chart-reason"
        >{{ bestChart.reason }}</span>
      </div>
      <div class="chart-actions">
        <button
          v-if="hasValidChart"
          :class="['chart-action-btn', { active: showCustomizer }]"
          title="Chart Settings"
          @click="showCustomizer = !showCustomizer"
        >
          <Settings :size="14" />
        </button>
        <button
          v-if="hasValidChart"
          class="chart-action-btn"
          title="Download as PNG"
          @click="downloadChart"
        >
          <Download :size="14" />
        </button>
        <button
          class="chart-action-btn"
          :title="isFullscreen ? 'Exit fullscreen' : 'Fullscreen'"
          @click="toggleFullscreen"
        >
          <Minimize2
            v-if="isFullscreen"
            :size="14"
          />
          <Maximize2
            v-else
            :size="14"
          />
        </button>
      </div>
    </div>

    <!-- Customizer Panel -->
    <Transition name="slide">
      <div
        v-if="showCustomizer"
        class="customizer-panel"
      >
        <ChartCustomizer
          :initial-settings="chartSettings"
          @update="updateChartSettings"
          @close="showCustomizer = false"
        />
      </div>
    </Transition>

    <!-- Loading State -->
    <div
      v-if="loading || mapLoading"
      class="chart-loading"
    >
      <Loader2
        class="spin"
        :size="32"
      />
      <p>{{ mapLoading ? 'Loading map data...' : 'Analyzing data...' }}</p>
    </div>

    <!-- Chart -->
    <v-chart
      v-else-if="hasValidChart && chartOption && !mapLoading"
      ref="chartRef"
      :key="themeKey"
      :option="chartOption"
      :theme="theme === 'dark' ? 'dark' : undefined"
      :autoresize="true"
      class="chart-container"
    />

    <!-- Empty/Non-chartable State -->
    <div
      v-else
      class="chart-empty"
    >
      <BarChart3
        class="empty-icon"
        :size="32"
      />
      <p v-if="!hasData">
        Execute a query to see visualization
      </p>
      <p v-else-if="!hasNumericData">
        No numeric columns found for visualization
      </p>
      <p v-else>
        Unable to generate chart for this data
      </p>
    </div>

    <!-- Alternative Charts (if available) -->
    <div
      v-if="alternativeCharts.length > 1"
      class="chart-alternatives"
    >
      <span class="alternatives-label">Try other charts:</span>
      <div class="alternatives-list">
        <button
          v-for="altChart in alternativeCharts"
          :key="altChart.type"
          :class="['alt-chart-btn', { active: selectedChartType === altChart.type }]"
          :title="altChart.reason"
          @click="selectChart(altChart)"
        >
          <component
            :is="getChartIcon(altChart.type)"
            :size="14"
          />
          <span class="alt-chart-label">{{ getChartLabel(altChart.type) }}</span>
        </button>
      </div>
    </div>

    <!-- Fullscreen Backdrop -->
    <div
      v-if="isFullscreen"
      class="fullscreen-backdrop"
      @click="toggleFullscreen"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import * as echarts from 'echarts/core'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import {
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  HeatmapChart,
  TreemapChart,
  RadarChart,
  FunnelChart,
  GaugeChart,
  MapChart
} from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent,
  DataZoomComponent,
  GeoComponent
} from 'echarts/components'

// Lazy-load map data - track both loading status and success (reactive for computed dependencies)
const mapLoadStatus = reactive({
  world: { loading: false, loaded: false },
  USA: { loading: false, loaded: false }
})

async function loadWorldMap() {
  // Skip if already loaded successfully
  if (mapLoadStatus.world.loaded) return true
  // Skip if already loading
  if (mapLoadStatus.world.loading) {
    // Wait for current load to complete
    while (mapLoadStatus.world.loading) {
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    return mapLoadStatus.world.loaded
  }

  mapLoadStatus.world.loading = true
  try {
    // Fetch GeoJSON data and register manually with echarts
    const response = await fetch('https://cdn.jsdelivr.net/npm/echarts@5/map/json/world.json')
    if (!response.ok) throw new Error('Failed to fetch world map')
    const worldGeoJson = await response.json()
    echarts.registerMap('world', worldGeoJson)
    mapLoadStatus.world.loaded = true
    return true
  } catch (e) {
    console.warn('Failed to load world map:', e)
    mapLoadStatus.world.loaded = false
    return false
  } finally {
    mapLoadStatus.world.loading = false
  }
}

async function loadUSAMap() {
  // Skip if already loaded successfully
  if (mapLoadStatus.USA.loaded) return true
  // Skip if already loading
  if (mapLoadStatus.USA.loading) {
    // Wait for current load to complete
    while (mapLoadStatus.USA.loading) {
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    return mapLoadStatus.USA.loaded
  }

  mapLoadStatus.USA.loading = true
  try {
    // Fetch GeoJSON data and register manually with echarts
    const response = await fetch('https://cdn.jsdelivr.net/npm/echarts@5/map/json/USA.json')
    if (!response.ok) throw new Error('Failed to fetch USA map')
    const usaGeoJson = await response.json()
    echarts.registerMap('USA', usaGeoJson)
    mapLoadStatus.USA.loaded = true
    return true
  } catch (e) {
    console.warn('Failed to load USA map:', e)
    mapLoadStatus.USA.loaded = false
    return false
  } finally {
    mapLoadStatus.USA.loading = false
  }
}
import VChart from 'vue-echarts'
import {
  BarChart3,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  ScatterChart as ScatterChartIcon,
  Loader2,
  TrendingUp,
  Grid3X3,
  LayoutGrid,
  Download,
  Maximize2,
  Minimize2,
  Gauge,
  Globe,
  Map,
  Settings
} from 'lucide-vue-next'
import ChartCustomizer from './ChartCustomizer.vue'

import {
  analyzeAndRecommend,
  getChartOptions,
  isChartable,
  ChartTypes,
  ChartLabels
} from '@/utils/chartAnalyzer'
import { addAnnotations } from '@/utils/chartAnnotations'

// Register ECharts components (tree-shaking)
use([
  CanvasRenderer,
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  HeatmapChart,
  TreemapChart,
  RadarChart,
  FunnelChart,
  GaugeChart,
  MapChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent,
  DataZoomComponent,
  GeoComponent
])

const props = defineProps({
  results: {
    type: Object,
    default: null
  },
  theme: {
    type: String,
    default: 'light'
  },
  // Backend-generated chart specification (optional)
  // When provided, uses the backend's chart type recommendation instead of re-analyzing
  chart: {
    type: Object,
    default: null
  }
})

const loading = ref(false)
const mapLoading = ref(false)
const chartRef = ref(null)
const analysisResult = ref(null)
const selectedChartType = ref(null)
const isFullscreen = ref(false)
const showCustomizer = ref(false)
const chartSettings = ref({
  colorScheme: 'default',
  legendPosition: 'bottom',
  showLabels: false,
  animation: true,
  showGrid: true,
  colors: ['#00739d', '#038898', '#1eb7df', '#26d1a0', '#ffc000', '#f15f5c']  // QueryfyAI palette
})

// Key for forcing chart re-render on theme change
const themeKey = computed(() => `chart-${props.theme}`)

// Check if we have data
const hasData = computed(() => {
  return props.results?.rows?.length > 0 && props.results?.columns?.length > 0
})

// Check if data has numeric columns
const hasNumericData = computed(() => {
  if (!hasData.value) return false
  return isChartable(props.results.columns, props.results.rows)
})

// Best chart recommendation
const bestChart = computed(() => {
  if (!analysisResult.value) return null
  if (selectedChartType.value) {
    return analysisResult.value.recommendations.find(r => r.type === selectedChartType.value) ||
           analysisResult.value.bestChart
  }
  return analysisResult.value.bestChart
})

// Data summary (e.g., "150 rows • 3 numeric, time series")
const dataSummary = computed(() => {
  return analysisResult.value?.dataSummary || null
})

// Check if we have a valid chart to display
const hasValidChart = computed(() => {
  return bestChart.value && bestChart.value.type !== ChartTypes.TABLE && bestChart.value.score > 0.3
})

// Alternative chart options
const alternativeCharts = computed(() => {
  if (!analysisResult.value) return []
  return analysisResult.value.recommendations
    .filter(r => r.type !== ChartTypes.TABLE && r.score > 0.5)
    .slice(0, 5)
})

// Minimum valid ECharts option: must have at least one series with data
// or be a pie/scatter with explicit data. Used as a structural gate to
// catch malformed backend/computed configs before they reach ECharts —
// without this, a missing `series` silently renders as a blank canvas.
function isValidEchartsOption(opt) {
  if (!opt || typeof opt !== 'object') return false
  // ECharts requires either a `series` array (bar/line/pie/etc.)
  // or a `geo`/`graphic` for map-only charts.
  const hasSeries = Array.isArray(opt.series) && opt.series.length > 0
  const hasGeo = !!opt.geo
  if (!hasSeries && !hasGeo) return false
  return true
}

// Chart options for ECharts.
// Day 4 fix (docs/architecture-audit-2026-04-16.md): this computed is
// wrapped in a try/catch so a malformed chart config produces the empty
// state ("Unable to generate chart") rather than throwing into Vue's
// reactivity system (which would leave the UI broken with no message).
const chartOption = computed(() => {
  try {
    if (!hasValidChart.value || !props.results) return null

    // For map charts, ensure the map is loaded before generating options
    const chart = bestChart.value
    const isMapChart = chart.type === ChartTypes.GEO_MAP || chart.type === ChartTypes.CHOROPLETH
    if (isMapChart) {
      const geoType = chart.config?.geoType || 'world'
      const isUSA = isUSAMap(geoType)
      const mapStatus = isUSA ? mapLoadStatus.USA : mapLoadStatus.world
      // Return null if map is not loaded yet - prevents ECharts 'regions' error
      if (!mapStatus.loaded) return null
    }

    const options = getChartOptions(
      bestChart.value,
      props.results.columns,
      props.results.rows
    )

    if (!options) return null

    const settings = chartSettings.value

    // Apply customizations
    const customizedOptions = {
      ...options,
      backgroundColor: 'transparent',
      textStyle: {
        color: props.theme === 'dark' ? '#FFFFFF' : '#0e191e'  // QueryfyAI text colors
      },
      animation: settings.animation,
      color: settings.colors
    }

    // Apply legend position
    if (options.legend) {
      if (settings.legendPosition === 'none') {
        customizedOptions.legend = { ...options.legend, show: false }
      } else {
        const legendConfig = {
          top: { top: 0, left: 'center' },
          bottom: { bottom: 0, left: 'center' },
          left: { left: 0, top: 'center', orient: 'vertical' },
          right: { right: 0, top: 'center', orient: 'vertical' }
        }
        customizedOptions.legend = {
          ...options.legend,
          show: true,
          ...legendConfig[settings.legendPosition]
        }
      }
    }

    // Apply data labels setting
    if (customizedOptions.series) {
      customizedOptions.series = customizedOptions.series.map(s => ({
        ...s,
        label: {
          ...s.label,
          show: settings.showLabels
        }
      }))
    }

    // Apply grid lines setting
    if (customizedOptions.xAxis) {
      customizedOptions.xAxis = {
        ...customizedOptions.xAxis,
        splitLine: { show: settings.showGrid }
      }
    }
    if (customizedOptions.yAxis) {
      customizedOptions.yAxis = {
        ...customizedOptions.yAxis,
        splitLine: { show: settings.showGrid }
      }
    }

    // Add intelligent annotations if present in backend chart spec.
    // Wrapped in its own try/catch so a malformed annotation does not
    // cost us the entire chart — we just skip annotations.
    let withAnnotations = customizedOptions
    if (props.chart?.annotations && props.chart.annotations.length > 0) {
      try {
        withAnnotations = addAnnotations(customizedOptions, props.chart.annotations)
      } catch (annotationError) {
        console.warn(
          '[ChartView] Failed to apply annotations, rendering without them:',
          annotationError
        )
        withAnnotations = customizedOptions
      }
    }

    // Final structural validation: the output must be renderable by ECharts.
    if (!isValidEchartsOption(withAnnotations)) {
      console.warn(
        '[ChartView] Computed chart option failed structural validation; ' +
        'falling back to empty state.',
        { chartType: bestChart.value?.type }
      )
      return null
    }

    return withAnnotations
  } catch (error) {
    // Never let a malformed chart break the surrounding UI. Fall back
    // to the empty-state template, which already renders a user-friendly
    // "Unable to generate chart for this data" message.
    console.error('[ChartView] chartOption computation failed:', error)
    return null
  }
})

// Analyze data when results change
watch(
  () => props.results,
  (newResults) => {
    if (newResults?.rows?.length > 0) {
      analyzeData()
    } else {
      analysisResult.value = null
      selectedChartType.value = null
    }
  },
  { immediate: true, deep: true }
)

// Helper to determine which map to load based on geoType
function isUSAMap(geoType) {
  if (!geoType) return false
  const normalized = String(geoType).toLowerCase()
  return normalized === 'us_state' || normalized === 'usa' || normalized.includes('state')
}

// Load map data when a map chart is selected
watch(
  bestChart,
  async (chart) => {
    if (!chart) return
    const isMapChart = chart.type === ChartTypes.GEO_MAP || chart.type === ChartTypes.CHOROPLETH
    if (isMapChart) {
      mapLoading.value = true
      try {
        const geoType = chart.config?.geoType || 'world'
        // Map column types to actual map names
        if (isUSAMap(geoType)) {
          await loadUSAMap()
        } else {
          // For COUNTRY, COUNTRY_CODE, 'world', or any other type, use world map
          await loadWorldMap()
        }
      } finally {
        mapLoading.value = false
      }
    }
  },
  { immediate: true }
)

function analyzeData() {
  if (!props.results?.columns || !props.results?.rows) {
    analysisResult.value = null
    return
  }

  loading.value = true

  // Use setTimeout to allow UI to update
  setTimeout(() => {
    try {
      analysisResult.value = analyzeAndRecommend(
        props.results.columns,
        props.results.rows
      )

      // If backend provided a chart spec, use its chart type as the initial selection
      // This ensures the backend's recommendation is respected while still allowing user to switch
      if (props.chart?.chart_type) {
        const backendChartType = props.chart.chart_type.toLowerCase()
        // Map backend chart type names to frontend ChartTypes
        const chartTypeMap = {
          'bar': ChartTypes.BAR,
          'line': ChartTypes.LINE,
          'pie': ChartTypes.PIE,
          'scatter': ChartTypes.SCATTER,
          'area': ChartTypes.AREA,
          'horizontal_bar': ChartTypes.HORIZONTAL_BAR,
          'stacked_bar': ChartTypes.STACKED_BAR,
          'donut': ChartTypes.DONUT,
          'heatmap': ChartTypes.HEATMAP,
          'treemap': ChartTypes.TREEMAP
        }
        const mappedType = chartTypeMap[backendChartType]
        if (mappedType) {
          selectedChartType.value = mappedType
        } else {
          selectedChartType.value = null // Use frontend's best recommendation
        }
      } else {
        selectedChartType.value = null // Reset to auto-selected chart
      }
    } catch (error) {
      console.error('Chart analysis error:', error)
      analysisResult.value = null
    } finally {
      loading.value = false
    }
  }, 50)
}

function selectChart(chart) {
  selectedChartType.value = chart.type
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  // Prevent body scroll when fullscreen
  document.body.style.overflow = isFullscreen.value ? 'hidden' : ''
}

function downloadChart() {
  if (!chartRef.value) return
  const chart = chartRef.value.chart
  if (!chart) return

  const url = chart.getDataURL({
    type: 'png',
    pixelRatio: 2,
    backgroundColor: props.theme === 'dark' ? '#162329' : '#FFFFFF'  // QueryfyAI bg-card
  })

  const link = document.createElement('a')
  link.download = `chart-${Date.now()}.png`
  link.href = url
  link.click()
}

function updateChartSettings(newSettings) {
  chartSettings.value = { ...chartSettings.value, ...newSettings }
}

function getChartLabel(type) {
  return ChartLabels[type] || type
}

function getChartIcon(type) {
  const iconMap = {
    [ChartTypes.BAR]: BarChart3,
    [ChartTypes.BAR_HORIZONTAL]: BarChart3,
    [ChartTypes.LINE]: LineChartIcon,
    [ChartTypes.AREA]: TrendingUp,
    [ChartTypes.PIE]: PieChartIcon,
    [ChartTypes.DONUT]: PieChartIcon,
    [ChartTypes.SCATTER]: ScatterChartIcon,
    [ChartTypes.BUBBLE]: ScatterChartIcon,
    [ChartTypes.MULTI_LINE]: LineChartIcon,
    [ChartTypes.STACKED_AREA]: TrendingUp,
    [ChartTypes.GROUPED_BAR]: BarChart3,
    [ChartTypes.STACKED_BAR]: BarChart3,
    [ChartTypes.HEATMAP]: Grid3X3,
    [ChartTypes.TREEMAP]: LayoutGrid,
    [ChartTypes.HISTOGRAM]: BarChart3,
    [ChartTypes.RADAR]: ScatterChartIcon,
    [ChartTypes.GAUGE]: Gauge,
    [ChartTypes.GEO_MAP]: Globe,
    [ChartTypes.CHOROPLETH]: Map,
    [ChartTypes.FUNNEL]: BarChart3
  }
  return iconMap[type] || BarChart3
}
</script>

<style scoped>
.chart-wrapper {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: var(--space-sm, 8px);
  background: var(--bg-card, #1E1B2E);
  border-radius: var(--radius-lg, 16px);
  border: 1px solid var(--border-subtle);
  overflow: hidden;
  position: relative;
}

.chart-wrapper.fullscreen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  border-radius: 0;
  padding: var(--space-lg, 24px);
  background: var(--bg-app, #13111C);
}

.fullscreen-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--bg-overlay);
  z-index: -1;
}

/* Chart Header */
.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm, 8px) var(--space-md, 16px);
  border-bottom: 1px solid var(--border-subtle);
  background: rgba(0, 0, 0, 0.15);
}

.chart-info {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}

.chart-actions {
  display: flex;
  align-items: center;
  gap: var(--space-xs, 4px);
}

.chart-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.chart-action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

.chart-action-btn.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

/* Customizer Panel */
.customizer-panel {
  position: absolute;
  top: 50px;
  right: var(--space-sm, 8px);
  z-index: 100;
}

/* Slide transition */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.chart-type-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-full, 9999px);
  font-size: var(--text-xs, 11px);
  font-weight: 600;
  background: var(--color-primary);
  color: white;
  box-shadow: var(--shadow-md);
}

.data-summary-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: var(--radius-full, 9999px);
  font-size: var(--text-xs, 11px);
  font-weight: 500;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.chart-reason {
  font-size: var(--text-xs, 11px);
  color: var(--text-muted);
  font-style: italic;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chart-container {
  flex: 1;
  min-height: 320px;
  margin: var(--space-sm, 8px);
  border-radius: var(--radius-md, 12px);
  background: transparent;
}

.chart-wrapper.fullscreen .chart-container {
  min-height: calc(100vh - 200px);
}

.chart-loading,
.chart-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 250px;
  color: var(--text-muted);
  gap: var(--space-sm, 8px);
  flex: 1;
}

.chart-loading .spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.empty-icon {
  opacity: 0.4;
}

/* Alternative Charts */
.chart-alternatives {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
  flex-wrap: wrap;
  padding: var(--space-sm, 8px) var(--space-md, 16px);
  border-top: 1px solid var(--border-subtle);
  background: rgba(0, 0, 0, 0.08);
}

.alternatives-label {
  font-size: var(--text-xs, 11px);
  color: var(--text-muted);
  font-weight: 500;
}

.alternatives-list {
  display: flex;
  gap: var(--space-xs, 4px);
  flex-wrap: wrap;
}

.alt-chart-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-full, 9999px);
  border: 1px solid var(--border-subtle);
  font-size: var(--text-xs, 11px);
  font-weight: 500;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.alt-chart-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  border-color: var(--color-primary);
  transform: translateY(-1px);
}

.alt-chart-btn.active {
  background: var(--color-primary);
  color: white;
  border-color: transparent;
  box-shadow: var(--shadow-md);
}

.alt-chart-label {
  display: inline;
}

@media (max-width: 768px) {
  .chart-container {
    min-height: 250px;
  }

  .chart-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-sm, 8px);
  }

  .chart-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .chart-info {
    width: 100%;
  }

  .chart-alternatives {
    flex-direction: column;
    align-items: flex-start;
  }

  .alt-chart-label {
    display: none;
  }

  .alt-chart-btn {
    padding: 8px;
  }
}
</style>

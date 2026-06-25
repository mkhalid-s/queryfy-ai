<template>
  <div class="chart-customizer">
    <div class="customizer-header">
      <Settings :size="14" />
      <span>Chart Settings</span>
      <button
        class="close-btn"
        aria-label="Close"
        @click="$emit('close')"
      >
        <X :size="14" />
      </button>
    </div>

    <div class="customizer-content">
      <!-- Color Scheme -->
      <div class="setting-group">
        <label class="setting-label">Color Scheme</label>
        <div class="color-schemes">
          <button
            v-for="scheme in colorSchemes"
            :key="scheme.id"
            :class="['color-scheme-btn', { active: settings.colorScheme === scheme.id }]"
            :title="scheme.name"
            @click="updateSetting('colorScheme', scheme.id)"
          >
            <div class="color-preview">
              <span
                v-for="(color, idx) in scheme.colors.slice(0, 4)"
                :key="idx"
                class="color-dot"
                :style="{ backgroundColor: color }"
              />
            </div>
            <span class="scheme-name">{{ scheme.name }}</span>
          </button>
        </div>
      </div>

      <!-- Legend Position -->
      <div class="setting-group">
        <label class="setting-label">Legend Position</label>
        <div class="position-grid">
          <button
            v-for="pos in legendPositions"
            :key="pos.id"
            :class="['position-btn', { active: settings.legendPosition === pos.id }]"
            :title="pos.name"
            @click="updateSetting('legendPosition', pos.id)"
          >
            <component
              :is="pos.icon"
              :size="14"
            />
          </button>
        </div>
      </div>

      <!-- Toggles -->
      <div class="setting-group toggles">
        <label class="toggle-item">
          <span class="toggle-label">Show Data Labels</span>
          <button
            :class="['toggle-btn', { active: settings.showLabels }]"
            @click="updateSetting('showLabels', !settings.showLabels)"
          >
            <span class="toggle-track">
              <span class="toggle-thumb" />
            </span>
          </button>
        </label>

        <label class="toggle-item">
          <span class="toggle-label">Enable Animation</span>
          <button
            :class="['toggle-btn', { active: settings.animation }]"
            @click="updateSetting('animation', !settings.animation)"
          >
            <span class="toggle-track">
              <span class="toggle-thumb" />
            </span>
          </button>
        </label>

        <label class="toggle-item">
          <span class="toggle-label">Show Grid Lines</span>
          <button
            :class="['toggle-btn', { active: settings.showGrid }]"
            @click="updateSetting('showGrid', !settings.showGrid)"
          >
            <span class="toggle-track">
              <span class="toggle-thumb" />
            </span>
          </button>
        </label>
      </div>

      <!-- Reset Button -->
      <button
        class="reset-btn"
        @click="resetSettings"
      >
        <RotateCcw :size="12" />
        Reset to Defaults
      </button>
    </div>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'
import {
  Settings,
  X,
  RotateCcw,
  AlignVerticalJustifyStart,
  AlignVerticalJustifyEnd,
  AlignHorizontalJustifyStart,
  AlignHorizontalJustifyEnd,
  EyeOff
} from 'lucide-vue-next'

const emit = defineEmits(['update', 'close'])

const props = defineProps({
  initialSettings: {
    type: Object,
    default: () => ({})
  }
})

// Color scheme presets - QueryfyAI Palette
const colorSchemes = [
  {
    id: 'default',
    name: 'QueryfyAI',
    colors: ['#00739d', '#038898', '#1eb7df', '#26d1a0', '#ffc000', '#f15f5c']  // QueryfyAI palette
  },
  {
    id: 'cool',
    name: 'Cool',
    colors: ['#00739d', '#038898', '#1eb7df', '#0a9bc7', '#26d1a0', '#1a9e7a']  // Blue/Teal variants
  },
  {
    id: 'warm',
    name: 'Warm',
    colors: ['#ffc000', '#d9a300', '#f15f5c', '#d94a47', '#f77f00', '#fcbf49']  // Gold/Coral variants
  },
  {
    id: 'pastel',
    name: 'Pastel',
    colors: ['#1eb7df', '#26d1a0', '#ffc000', '#00739d', '#038898', '#f15f5c']  // Lighter palette order
  },
  {
    id: 'monochrome',
    name: 'Mono',
    colors: ['#0e191e', '#333333', '#666666', '#999999', '#cccccc', '#e7f1f5']  // QueryfyAI grays
  },
  {
    id: 'accessible',
    name: 'Accessible',
    colors: ['#00739d', '#1a9e7a', '#d9a300', '#d94a47', '#038898', '#666666']  // High contrast
  }
]

// Legend position options
const legendPositions = [
  { id: 'top', name: 'Top', icon: AlignVerticalJustifyStart },
  { id: 'bottom', name: 'Bottom', icon: AlignVerticalJustifyEnd },
  { id: 'left', name: 'Left', icon: AlignHorizontalJustifyStart },
  { id: 'right', name: 'Right', icon: AlignHorizontalJustifyEnd },
  { id: 'none', name: 'Hidden', icon: EyeOff }
]

// Default settings
const defaultSettings = {
  colorScheme: 'default',
  legendPosition: 'bottom',
  showLabels: false,
  animation: true,
  showGrid: true
}

// Current settings
const settings = reactive({
  ...defaultSettings,
  ...props.initialSettings
})

// Update a setting
function updateSetting(key, value) {
  settings[key] = value
  emitUpdate()
}

// Reset to defaults
function resetSettings() {
  Object.assign(settings, defaultSettings)
  emitUpdate()
}

// Emit updated settings
function emitUpdate() {
  const colors = colorSchemes.find(s => s.id === settings.colorScheme)?.colors || colorSchemes[0].colors
  emit('update', {
    ...settings,
    colors
  })
}

// Watch for external changes
watch(
  () => props.initialSettings,
  (newSettings) => {
    if (newSettings) {
      Object.assign(settings, newSettings)
    }
  },
  { deep: true }
)
</script>

<style scoped>
.chart-customizer {
  background: var(--bg-card, #1e1b2e);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg, 16px);
  overflow: hidden;
  min-width: 280px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
}

.customizer-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
  padding: var(--space-sm, 8px) var(--space-md, 16px);
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--text-sm, 13px);
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

.customizer-content {
  padding: var(--space-md, 16px);
  display: flex;
  flex-direction: column;
  gap: var(--space-md, 16px);
}

.setting-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs, 4px);
}

.setting-label {
  font-size: var(--text-xs, 11px);
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Color Schemes */
.color-schemes {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-xs, 4px);
}

.color-scheme-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--space-xs, 4px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}

.color-scheme-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: var(--color-primary);
}

.color-scheme-btn.active {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
}

.color-preview {
  display: flex;
  gap: 2px;
}

.color-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.scheme-name {
  font-size: 9px;
  color: var(--text-muted);
}

.color-scheme-btn.active .scheme-name {
  color: var(--color-primary);
}

/* Legend Position */
.position-grid {
  display: flex;
  gap: var(--space-xs, 4px);
}

.position-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.position-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: var(--color-primary);
  color: var(--text-primary);
}

.position-btn.active {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* Toggles */
.toggles {
  gap: var(--space-sm, 8px);
}

.toggle-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}

.toggle-label {
  font-size: var(--text-sm, 13px);
  color: var(--text-secondary);
}

.toggle-btn {
  position: relative;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}

.toggle-track {
  display: block;
  width: 36px;
  height: 20px;
  border-radius: 10px;
  background: var(--border-subtle);
  transition: all 0.2s ease;
}

.toggle-btn.active .toggle-track {
  background: var(--color-primary);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: white;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.toggle-btn.active .toggle-thumb {
  left: 18px;
}

/* Reset Button */
.reset-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: var(--space-xs, 4px) var(--space-sm, 8px);
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs, 11px);
  cursor: pointer;
  transition: all 0.15s ease;
}

.reset-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
</style>

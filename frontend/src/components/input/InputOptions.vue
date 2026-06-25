<!--
============================================
InputOptions.vue
============================================
Mode toggle buttons displayed above the chat input:
- Standard Mode: Fast SQL generation
- Analyst Mode: AI Data Analyst with insights, charts, and key findings

Accessibility:
- Uses button role with aria-pressed for toggle state
- Keyboard accessible (Tab + Enter/Space)
- Clear visual feedback for active state
-->
<template>
  <div
    class="input-options"
    role="group"
    aria-label="Query generation options"
  >
    <!-- Standard Mode Toggle -->
    <button
      type="button"
      :class="['option-btn', { active: isStandardMode }]"
      :aria-pressed="isStandardMode"
      :title="isStandardMode ? 'Standard mode - fast SQL generation' : 'Switch to standard mode'"
      @click="setResponseMode(ResponseMode.STANDARD)"
    >
      <Zap :size="14" />
      <span>Standard</span>
    </button>

    <!-- Analyst Mode Toggle -->
    <button
      type="button"
      :class="['option-btn', 'analyst', { active: isAnalystMode }]"
      :aria-pressed="isAnalystMode"
      :title="isAnalystMode ? 'Analyst mode - insights with charts and key findings' : 'Switch to analyst mode'"
      @click="setResponseMode(ResponseMode.ANALYST)"
    >
      <BrainCircuit :size="14" />
      <span>Analyst</span>
      <span
        v-if="isAnalystMode"
        class="badge"
      >AI</span>
    </button>

    <!-- Mode Description -->
    <Transition name="fade">
      <span
        v-show="modeDescription"
        class="mode-description"
      >
        {{ modeDescription }}
      </span>
    </Transition>
  </div>
</template>

<script setup>
import { Zap, BrainCircuit } from 'lucide-vue-next'
import { useQueryOptions } from '../../composables/useQueryOptions'

const {
  isStandardMode,
  isAnalystMode,
  modeDescription,
  setResponseMode,
  ResponseMode
} = useQueryOptions()
</script>

<style scoped>
.input-options {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 0 var(--space-xs) 0;
}

.option-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}

.option-btn:hover:not(:disabled) {
  border-color: var(--border-focus);
  color: var(--text-primary);
}

.option-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--bg-app), 0 0 0 4px var(--color-primary);
}

.option-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Active state - Stream */
.option-btn.active {
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  border-color: var(--color-primary);
  color: white;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.option-btn.active:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--color-primary-hover), var(--color-primary));
  border-color: var(--color-primary-hover);
  box-shadow: 0 3px 12px rgba(0, 0, 0, 0.25);
}

/* Analyst mode styling - QueryfyAI Teal */
.option-btn.analyst.active {
  background: linear-gradient(135deg, var(--color-secondary), var(--color-secondary-hover));
  border-color: var(--color-secondary);
  color: white;
}

.option-btn.analyst.active:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--color-secondary-hover), var(--color-secondary));
  border-color: var(--color-secondary-hover);
}

/* Beta badge */
.badge {
  display: inline-block;
  padding: 1px 5px;
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.2);
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.option-btn:not(.active) .badge {
  background: var(--bg-input);
  color: var(--text-muted);
}

/* Mode description tooltip */
.mode-description {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}

/* Fade transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Mobile: hide description, make buttons more compact */
@media (max-width: 768px) {
  .input-options {
    padding: 0 0 var(--space-xs) 0;
  }

  .option-btn {
    padding: 3px 8px;
    font-size: 11px;
  }

  .mode-description {
    display: none;
  }
}
</style>

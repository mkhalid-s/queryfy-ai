<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="modal-overlay"
        @click.self="$emit('close')"
      >
        <div class="modal-container dml-modal">
          <!-- Header -->
          <div class="modal-header">
            <div class="modal-title">
              <component
                :is="operationIcon"
                :size="20"
              />
              <span>{{ operationTitle }} - Preview</span>
            </div>
            <button
              class="modal-close"
              @click="$emit('close')"
            >
              <X :size="20" />
            </button>
          </div>

          <!-- Body -->
          <div class="modal-body">
            <!-- Impact Summary -->
            <div class="impact-summary">
              <AlertCircle :size="16" />
              <span>
                This will affect <strong>{{ preview?.estimated_rows_affected || 0 }}</strong> row(s)
              </span>
            </div>

            <!-- Warnings -->
            <div
              v-if="preview?.warnings?.length"
              class="warnings-section"
            >
              <AlertTriangle :size="14" />
              <ul>
                <li
                  v-for="(warn, i) in preview.warnings"
                  :key="i"
                >
                  {{ warn }}
                </li>
              </ul>
            </div>

            <!-- SQL Preview -->
            <div class="sql-preview">
              <h4>SQL to Execute</h4>
              <pre><code>{{ sql }}</code></pre>
            </div>

            <!-- Sandbox Result -->
            <div
              v-if="sandboxResult"
              class="sandbox-result success"
            >
              <CheckCircle :size="14" />
              <span>
                Sandbox test successful: {{ sandboxResult.rows_affected }} rows affected
                (changes rolled back)
              </span>
            </div>
          </div>

          <!-- Footer Actions -->
          <div class="modal-footer">
            <button
              class="btn-secondary"
              @click="$emit('close')"
            >
              Cancel
            </button>
            <button
              v-if="mode === 'preview' && supportsSandbox"
              class="btn-warning"
              :disabled="loading"
              @click="$emit('test-sandbox')"
            >
              <Loader2
                v-if="loading"
                :size="14"
                class="spin"
              />
              <Play
                v-else
                :size="14"
              />
              Test in Sandbox
            </button>
            <button
              :class="['btn-danger', { loading }]"
              :disabled="loading"
              @click="$emit('confirm')"
            >
              <Loader2
                v-if="loading"
                :size="14"
                class="spin"
              />
              <Check
                v-else
                :size="14"
              />
              Execute
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { Plus, Edit, Trash2, X, AlertCircle, AlertTriangle,
         CheckCircle, Play, Check, Loader2 } from 'lucide-vue-next'

const props = defineProps({
  show: Boolean,
  operation: {
    type: String,
    default: null
  }, // 'insert', 'update', 'delete'
  sql: {
    type: String,
    default: null
  },
  preview: {
    type: Object,
    default: null
  },
  mode: {
    type: String,
    default: null
  },
  sandboxResult: {
    type: Object,
    default: null
  },
  loading: Boolean,
  supportsSandbox: Boolean
})

defineEmits(['close', 'confirm', 'test-sandbox'])

const operationIcon = computed(() => {
  switch (props.operation) {
    case 'insert': return Plus
    case 'update': return Edit
    case 'delete': return Trash2
    default: return Edit
  }
})

const operationTitle = computed(() => {
  return props.operation?.charAt(0).toUpperCase() + props.operation?.slice(1)
})
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-lg);
}

.modal-container {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dml-modal {
  max-width: 800px;
  width: 100%;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-lg);
  border-bottom: 1px solid var(--border-color);
}

.modal-title {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}

.modal-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  padding: var(--space-xs);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.modal-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.modal-body {
  padding: var(--space-lg);
  overflow-y: auto;
  flex: 1;
}

.impact-summary {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-md);
  background: var(--bg-info, #3b82f6);
  border-radius: var(--radius-md);
  color: white;
}

.warnings-section {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-md);
  background: var(--bg-warning, #f59e0b);
  border-radius: var(--radius-md);
  margin-top: var(--space-md);
  color: white;
}

.warnings-section ul {
  margin: 0;
  padding-left: var(--space-md);
}

.sql-preview {
  margin-top: var(--space-md);
}

.sql-preview h4 {
  margin-bottom: var(--space-sm);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: 600;
}

.sql-preview pre {
  background: var(--bg-code, var(--bg-input));
  padding: var(--space-md);
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-family: 'Courier New', monospace;
  font-size: var(--text-sm);
  border: 1px solid var(--border-color);
}

.sql-preview code {
  color: var(--text-primary);
}

.sandbox-result {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-md);
  background: var(--bg-success, #10b981);
  border-radius: var(--radius-md);
  margin-top: var(--space-md);
  color: white;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-sm);
  padding: var(--space-lg);
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary, var(--bg-card));
}

.modal-footer button {
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-md);
  border: none;
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  transition: all 0.2s;
}

.modal-footer button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-input);
  color: var(--text-primary);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--bg-hover);
}

.btn-warning {
  background: #f59e0b;
  color: white;
}

.btn-warning:hover:not(:disabled) {
  background: #d97706;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: #dc2626;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* Modal transitions */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.3s ease;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.9);
}
</style>

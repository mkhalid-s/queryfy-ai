<!--
============================================
ImportExportTab.vue
============================================
Bulk import/export functionality:
- File upload for CSV/JSON
- Import business terms and column descriptions
- Export to CSV/JSON
- Import history view
-->
<template>
  <div class="import-export">
    <!-- Import Section -->
    <section class="section">
      <h3 class="section-title">
        <Upload :size="16" />
        Import Data
      </h3>

      <!-- Import Type Selection -->
      <div class="import-options">
        <button
          :class="['option-btn', { active: importType === 'terms' }]"
          @click="importType = 'terms'"
        >
          <Tag :size="16" />
          <span>Business Terms</span>
        </button>
        <button
          :class="['option-btn', { active: importType === 'columns' }]"
          @click="importType = 'columns'"
        >
          <Columns :size="16" />
          <span>Column Descriptions</span>
        </button>
      </div>

      <!-- File Upload -->
      <div
        :class="['upload-zone', { dragging: isDragging }]"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="handleDrop"
        @click="triggerFileInput"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".csv,.json"
          hidden
          @change="handleFileSelect"
        >
        <div class="upload-content">
          <FileUp :size="32" />
          <p>Drop your CSV or JSON file here</p>
          <p class="hint">
            or click to browse
          </p>
        </div>
      </div>

      <!-- Selected File -->
      <div
        v-if="selectedFile"
        class="selected-file"
      >
        <File :size="16" />
        <span class="file-name">{{ selectedFile.name }}</span>
        <span class="file-size">{{ formatFileSize(selectedFile.size) }}</span>
        <button
          class="remove-btn"
          @click="clearFile"
        >
          <X :size="14" />
        </button>
      </div>

      <!-- Import Button -->
      <button
        v-if="selectedFile"
        :disabled="importing"
        class="btn btn-primary btn-full"
        @click="startImport"
      >
        <Loader2
          v-if="importing"
          :size="14"
          class="spin"
        />
        <Upload
          v-else
          :size="14"
        />
        Import {{ importType === 'terms' ? 'Business Terms' : 'Column Descriptions' }}
      </button>

      <!-- Import Result -->
      <div
        v-if="importResult"
        :class="['import-result', { error: importResult.failed > 0 }]"
      >
        <CheckCircle
          v-if="importResult.failed === 0"
          :size="16"
        />
        <AlertCircle
          v-else
          :size="16"
        />
        <div class="result-details">
          <span>Imported {{ importResult.created }} new, updated {{ importResult.updated }}</span>
          <span
            v-if="importResult.failed > 0"
            class="failed"
          >
            {{ importResult.failed }} failed
          </span>
        </div>
      </div>

      <!-- Format Help -->
      <div class="format-help">
        <button
          class="help-toggle"
          @click="showFormatHelp = !showFormatHelp"
        >
          <HelpCircle :size="14" />
          {{ importType === 'terms' ? 'Terms' : 'Columns' }} file format
          <ChevronDown
            :size="14"
            :class="{ rotated: showFormatHelp }"
          />
        </button>
        <div
          v-if="showFormatHelp"
          class="help-content"
        >
          <template v-if="importType === 'terms'">
            <p><strong>CSV columns:</strong></p>
            <code>term, definition, sql_expression, synonyms, examples, category</code>
            <p class="note">
              synonyms and examples are comma-separated lists
            </p>
          </template>
          <template v-else>
            <p><strong>CSV columns:</strong></p>
            <code>table_name, column_name, description, schema_name, business_name, data_type_hint, is_pii, is_sensitive</code>
            <p class="note">
              is_pii and is_sensitive are true/false
            </p>
          </template>
        </div>
      </div>
    </section>

    <!-- Export Section -->
    <section class="section">
      <h3 class="section-title">
        <Download :size="16" />
        Export Data
      </h3>

      <div class="export-options">
        <div class="export-card">
          <div class="export-info">
            <Tag :size="20" />
            <div>
              <span class="export-title">Business Terms</span>
              <span class="export-count">{{ stats.total_terms }} items</span>
            </div>
          </div>
          <div class="export-actions">
            <button
              :disabled="exporting"
              class="btn btn-secondary btn-sm"
              @click="exportData('terms', 'json')"
            >
              JSON
            </button>
            <button
              :disabled="exporting"
              class="btn btn-secondary btn-sm"
              @click="exportData('terms', 'csv')"
            >
              CSV
            </button>
          </div>
        </div>

        <div class="export-card">
          <div class="export-info">
            <Columns :size="20" />
            <div>
              <span class="export-title">Column Descriptions</span>
              <span class="export-count">{{ stats.total_columns }} items</span>
            </div>
          </div>
          <div class="export-actions">
            <button
              :disabled="exporting"
              class="btn btn-secondary btn-sm"
              @click="exportData('columns', 'json')"
            >
              JSON
            </button>
            <button
              :disabled="exporting"
              class="btn btn-secondary btn-sm"
              @click="exportData('columns', 'csv')"
            >
              CSV
            </button>
          </div>
        </div>
      </div>

      <!-- Export Result -->
      <div
        v-if="exportResult"
        :class="['export-result', { error: !exportResult.success }]"
      >
        <CheckCircle
          v-if="exportResult.success"
          :size="16"
        />
        <AlertCircle
          v-else
          :size="16"
        />
        <span>{{ exportResult.message }}</span>
      </div>
    </section>

    <!-- Import History -->
    <section class="section">
      <h3 class="section-title">
        <History :size="16" />
        Import History
      </h3>

      <div
        v-if="importHistoryLoading"
        class="loading-state small"
      >
        <Loader2
          :size="16"
          class="spin"
        />
        <span>Loading history...</span>
      </div>

      <div
        v-else-if="importHistory.length === 0"
        class="empty-state small"
      >
        <p>No imports yet</p>
      </div>

      <div
        v-else
        class="history-list"
      >
        <div
          v-for="item in importHistory"
          :key="item.id"
          class="history-item"
        >
          <div class="history-icon">
            <Tag
              v-if="item.import_type === 'terms'"
              :size="14"
            />
            <Columns
              v-else
              :size="14"
            />
          </div>
          <div class="history-info">
            <span class="history-file">{{ item.file_name || 'Manual import' }}</span>
            <span class="history-stats">
              {{ item.records_created }} created, {{ item.records_updated }} updated
              <span
                v-if="item.records_failed > 0"
                class="failed"
              >
                , {{ item.records_failed }} failed
              </span>
            </span>
          </div>
          <span class="history-time">{{ formatTime(item.imported_at) }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  Upload,
  Download,
  Tag,
  Columns,
  File,
  FileUp,
  X,
  CheckCircle,
  AlertCircle,
  HelpCircle,
  ChevronDown,
  History,
  Loader2
} from 'lucide-vue-next'
import { useDataDictionaryStore } from '@/stores/dataDictionary'
import { storeToRefs } from 'pinia'

const props = defineProps({
  sessionId: {
    type: String,
    required: true
  }
})

// Store
const store = useDataDictionaryStore()
const { stats, importHistory, importHistoryLoading } = storeToRefs(store)

// Local state
const importType = ref('terms')
const selectedFile = ref(null)
const isDragging = ref(false)
const importing = ref(false)
const exporting = ref(false)
const importResult = ref(null)
const exportResult = ref(null)
const showFormatHelp = ref(false)

// Refs
const fileInput = ref(null)

// Load history on mount
onMounted(async () => {
  try {
    await store.fetchImportHistory(props.sessionId)
  } catch (error) {
    console.warn('Failed to load import history:', error)
  }
})

// Methods
function triggerFileInput() {
  fileInput.value?.click()
}

function handleFileSelect(event) {
  const file = event.target.files?.[0]
  if (file) {
    selectFile(file)
  }
}

function handleDrop(event) {
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) {
    selectFile(file)
  }
}

function selectFile(file) {
  // Validate file type
  const validTypes = ['text/csv', 'application/json', 'text/plain']
  const validExtensions = ['.csv', '.json']

  const hasValidType = validTypes.includes(file.type)
  const hasValidExtension = validExtensions.some(ext => file.name.toLowerCase().endsWith(ext))

  if (!hasValidType && !hasValidExtension) {
    window.alert('Please select a CSV or JSON file')
    return
  }

  selectedFile.value = file
  importResult.value = null
}

function clearFile() {
  selectedFile.value = null
  importResult.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

async function startImport() {
  if (!selectedFile.value) return

  importing.value = true
  importResult.value = null

  try {
    let result
    if (importType.value === 'terms') {
      result = await store.importTerms(props.sessionId, selectedFile.value)
    } else {
      result = await store.importColumns(props.sessionId, selectedFile.value)
    }

    // Set import result immediately - don't let history fetch failure mask success
    importResult.value = result

    // Clear file on success
    if (result.failed === 0) {
      clearFile()
    }

    // Refresh history in background - don't fail import if this fails
    try {
      await store.fetchImportHistory(props.sessionId)
    } catch (historyError) {
      console.warn('Failed to refresh import history:', historyError)
    }
  } catch (error) {
    console.error('Import failed:', error)
    importResult.value = {
      created: 0,
      updated: 0,
      failed: 1,
      error: error.userMessage || error.message
    }
  } finally {
    importing.value = false
  }
}

async function exportData(type, format) {
  exporting.value = true
  exportResult.value = null

  try {
    if (type === 'terms') {
      await store.exportTerms(props.sessionId, format)
    } else {
      await store.exportColumns(props.sessionId, format)
    }
    // Show success message
    exportResult.value = {
      success: true,
      message: `${type === 'terms' ? 'Business terms' : 'Column descriptions'} exported as ${format.toUpperCase()}`
    }
    // Clear success message after 3 seconds
    setTimeout(() => {
      if (exportResult.value?.success) exportResult.value = null
    }, 3000)
  } catch (error) {
    console.error('Export failed:', error)
    exportResult.value = {
      success: false,
      message: error.userMessage || error.message || 'Export failed'
    }
  } finally {
    exporting.value = false
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}
</script>

<style scoped>
.import-export {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
}

/* Section */
.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.section-title {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Import Options */
.import-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-sm);
}

.option-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs);
  padding: var(--space-md);
  border: 2px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.option-btn:hover {
  border-color: var(--color-primary);
  color: var(--text-primary);
}

.option-btn.active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  color: var(--color-primary);
}

/* Upload Zone */
.upload-zone {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  padding: var(--space-lg);
  border: 2px dashed var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  cursor: pointer;
  transition: all 0.15s ease;
}

.upload-zone:hover,
.upload-zone.dragging {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.upload-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
  color: var(--text-muted);
  text-align: center;
}

.upload-content p {
  margin: 0;
  font-size: var(--text-sm);
}

.upload-content .hint {
  font-size: var(--text-xs);
}

/* Selected File */
.selected-file {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-input);
  border-radius: var(--radius-md);
}

.file-name {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.remove-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.remove-btn:hover {
  background: var(--bg-card);
  color: var(--text-primary);
}

/* Import Result */
.import-result,
.export-result {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-md);
  background: rgba(34, 197, 94, 0.1);
  color: var(--color-success);
  font-size: var(--text-sm);
}

.import-result.error,
.export-result.error {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

.result-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--text-sm);
}

.failed {
  color: var(--color-error);
}

/* Format Help */
.format-help {
  border-top: 1px solid var(--border-subtle);
  padding-top: var(--space-md);
}

.help-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-sm);
  cursor: pointer;
}

.help-toggle:hover {
  color: var(--text-primary);
}

.help-toggle svg:last-child {
  transition: transform 0.2s ease;
}

.help-toggle svg.rotated {
  transform: rotate(180deg);
}

.help-content {
  margin-top: var(--space-sm);
  padding: var(--space-sm);
  background: var(--bg-input);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}

.help-content p {
  margin: 0 0 var(--space-xs) 0;
  color: var(--text-secondary);
}

.help-content code {
  display: block;
  padding: var(--space-xs);
  background: var(--bg-app);
  border-radius: var(--radius-sm);
  font-family: monospace;
  font-size: var(--text-xs);
  color: var(--color-primary);
  overflow-x: auto;
}

.help-content .note {
  margin-top: var(--space-xs);
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* Export Options */
.export-options {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.export-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.export-info {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  color: var(--text-muted);
}

.export-info > div {
  display: flex;
  flex-direction: column;
}

.export-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
}

.export-count {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.export-actions {
  display: flex;
  gap: var(--space-xs);
}

/* History List */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm);
  background: var(--bg-card);
  border-radius: var(--radius-sm);
}

.history-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-muted);
}

.history-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.history-file {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.history-stats {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.history-time {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* States */
.loading-state,
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  padding: var(--space-lg);
  color: var(--text-muted);
}

.loading-state.small,
.empty-state.small {
  padding: var(--space-md);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Buttons */
.btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-sm {
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--text-xs);
}

.btn-full {
  width: 100%;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-input);
  color: var(--text-primary);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--border-subtle);
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

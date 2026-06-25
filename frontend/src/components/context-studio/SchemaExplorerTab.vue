<!--
============================================
SchemaExplorerTab.vue
============================================
Schema browser with column description management:
- Tree view of tables/collections and columns/fields
- Expandable table/collection rows
- Inline column description editing
- PII/Sensitive flags
- Column search/filter
- Supports SQL (tables/columns) and NoSQL (collections/fields)
-->
<template>
  <div class="schema-explorer">
    <!-- Search Bar -->
    <div class="search-bar">
      <Search
        :size="14"
        class="search-icon"
      />
      <input
        v-model="searchQuery"
        type="text"
        :placeholder="`Search ${entityLabel.plural} or ${fieldLabel.plural}...`"
        class="search-input"
      >
      <button
        v-if="searchQuery"
        class="clear-btn"
        @click="searchQuery = ''"
      >
        <X :size="14" />
      </button>
    </div>

    <!-- Stats Row -->
    <div class="stats-row">
      <span>{{ filteredTables.length }} {{ entityLabel.plural }}</span>
      <span class="separator">|</span>
      <span>{{ totalColumns }} {{ fieldLabel.plural }}</span>
      <span
        v-if="describedColumns > 0"
        class="described"
      >
        ({{ describedColumns }} described)
      </span>
    </div>

    <!-- Loading State -->
    <div
      v-if="enhancedSchemaLoading"
      class="loading-state"
    >
      <Loader2
        :size="20"
        class="spin"
      />
      <span>Loading schema...</span>
    </div>

    <!-- Empty State -->
    <div
      v-else-if="schemaTables.length === 0"
      class="empty-state"
    >
      <component
        :is="isMongoDB ? Layers : Database"
        :size="32"
      />
      <p>No {{ entityLabel.plural }} found</p>
      <button
        class="btn btn-secondary"
        @click="refreshSchema"
      >
        <RefreshCw :size="14" />
        Refresh Schema
      </button>
    </div>

    <!-- Table Tree -->
    <div
      v-else
      class="table-tree"
    >
      <div
        v-for="table in filteredTables"
        :key="table.name"
        class="table-node"
      >
        <!-- Table Header -->
        <div
          class="table-header"
          @click="toggleTable(table.name)"
        >
          <ChevronRight
            :size="16"
            :class="['chevron', { expanded: expandedTables.has(table.name) }]"
          />
          <component
            :is="isMongoDB ? Layers : Table"
            :size="16"
            class="table-icon"
          />
          <span class="table-name">
            {{ table.schema_name ? `${table.schema_name}.` : '' }}{{ table.name }}
          </span>
          <span class="column-count">{{ table.columns.length }} {{ fieldLabel.plural }}</span>
          <span
            v-if="getDescribedCount(table)"
            class="described-badge"
            :title="`${getDescribedCount(table)} ${fieldLabel.plural} have descriptions`"
          >
            {{ getDescribedCount(table) }}
          </span>
        </div>

        <!-- Columns List -->
        <transition name="expand">
          <div
            v-if="expandedTables.has(table.name)"
            class="columns-list"
          >
            <div
              v-for="column in filterColumns(table.columns)"
              :key="`${table.name}.${column.name}`"
              :class="['column-row', { editing: isEditing(table.name, column.name) }]"
            >
              <!-- Column Info -->
              <div class="column-info">
                <div class="column-main">
                  <Key
                    v-if="column.primary_key"
                    :size="12"
                    class="pk-icon"
                    title="Primary Key"
                  />
                  <Link
                    v-if="column.foreign_key"
                    :size="12"
                    class="fk-icon"
                    title="Foreign Key"
                  />
                  <span class="column-name">{{ column.name }}</span>
                  <span class="column-type">{{ column.type }}</span>
                </div>

                <!-- Description Display -->
                <div
                  v-if="column.description && !isEditing(table.name, column.name)"
                  class="column-description"
                >
                  <span class="description-text">{{ column.description }}</span>
                  <span
                    v-if="column.business_name"
                    class="business-name"
                  >
                    ({{ column.business_name }})
                  </span>
                  <div class="column-flags">
                    <span
                      v-if="column.is_pii"
                      class="flag pii"
                    >PII</span>
                    <span
                      v-if="column.is_sensitive"
                      class="flag sensitive"
                    >Sensitive</span>
                  </div>
                </div>

                <!-- No Description -->
                <div
                  v-else-if="!isEditing(table.name, column.name)"
                  class="no-description"
                >
                  <span>No description</span>
                </div>
              </div>

              <!-- Actions -->
              <div class="column-actions">
                <button
                  v-if="!isEditing(table.name, column.name)"
                  class="action-btn"
                  :title="column.description ? 'Edit description' : 'Add description'"
                  @click="startEdit(table, column)"
                >
                  <Edit3 :size="14" />
                </button>
                <button
                  v-if="column.description && !isEditing(table.name, column.name)"
                  class="action-btn delete"
                  title="Remove description"
                  @click="deleteDescription(table, column)"
                >
                  <Trash2 :size="14" />
                </button>
              </div>

              <!-- Edit Form -->
              <div
                v-if="isEditing(table.name, column.name)"
                class="edit-form"
              >
                <div class="form-row">
                  <input
                    ref="descriptionInput"
                    v-model="editForm.description"
                    type="text"
                    :placeholder="`${fieldLabel.singular.charAt(0).toUpperCase() + fieldLabel.singular.slice(1)} description...`"
                    class="form-input"
                    @keyup.enter="saveDescription"
                    @keyup.escape="cancelEdit"
                  >
                </div>
                <div class="form-row">
                  <input
                    v-model="editForm.business_name"
                    type="text"
                    placeholder="Business name (optional)"
                    class="form-input small"
                  >
                  <label class="checkbox-label">
                    <input
                      v-model="editForm.is_pii"
                      type="checkbox"
                    >
                    <span>PII</span>
                  </label>
                  <label class="checkbox-label">
                    <input
                      v-model="editForm.is_sensitive"
                      type="checkbox"
                    >
                    <span>Sensitive</span>
                  </label>
                </div>
                <div class="form-actions">
                  <button
                    class="btn btn-secondary btn-sm"
                    @click="cancelEdit"
                  >
                    Cancel
                  </button>
                  <button
                    class="btn btn-primary btn-sm"
                    :disabled="!editForm.description.trim()"
                    @click="saveDescription"
                  >
                    <Check :size="14" />
                    Save
                  </button>
                </div>
              </div>
            </div>
          </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import {
  Search,
  X,
  ChevronRight,
  Table,
  Database,
  Key,
  Link,
  Edit3,
  Trash2,
  Check,
  Loader2,
  RefreshCw,
  Layers
} from 'lucide-vue-next'
import { useDataDictionaryStore } from '@/stores/dataDictionary'
import { useToast } from '@/composables/useToast'
import { storeToRefs } from 'pinia'

const props = defineProps({
  sessionId: {
    type: String,
    required: true
  }
})

// Store
const store = useDataDictionaryStore()
const { schemaTables, enhancedSchemaLoading, enhancedSchema } = storeToRefs(store)
const toast = useToast()

// Database type detection
const dbType = computed(() => enhancedSchema.value?.db_type?.toLowerCase() || '')

// Check if MongoDB (uses different terminology and icon)
const isMongoDB = computed(() => dbType.value === 'mongodb')

// Dynamic labels based on specific database type
// Each NoSQL database has its own terminology
const entityLabel = computed(() => {
  switch (dbType.value) {
    case 'mongodb':
      return { singular: 'collection', plural: 'collections' }
    case 'dynamodb':
      return { singular: 'table', plural: 'tables' }  // DynamoDB uses "tables"
    case 'cassandra':
      return { singular: 'table', plural: 'tables' }  // Cassandra uses "tables" in keyspaces
    default:
      return { singular: 'table', plural: 'tables' }
  }
})

const fieldLabel = computed(() => {
  switch (dbType.value) {
    case 'mongodb':
      return { singular: 'field', plural: 'fields' }
    case 'dynamodb':
      return { singular: 'attribute', plural: 'attributes' }
    case 'cassandra':
      return { singular: 'column', plural: 'columns' }  // Cassandra uses standard column terminology
    default:
      return { singular: 'column', plural: 'cols' }
  }
})

// Local state
const searchQuery = ref('')
const expandedTables = ref(new Set())
const editingColumn = ref(null) // format: "table.column"
const editForm = ref({
  description: '',
  business_name: '',
  is_pii: false,
  is_sensitive: false
})

// Refs
const descriptionInput = ref(null)

// Computed
const filteredTables = computed(() => {
  if (!searchQuery.value.trim()) {
    return schemaTables.value
  }

  const query = searchQuery.value.toLowerCase()
  return schemaTables.value.filter(table => {
    // Match table name
    if (table.name.toLowerCase().includes(query)) return true
    // Match any column name
    return table.columns.some(col =>
      col.name.toLowerCase().includes(query) ||
      col.description?.toLowerCase().includes(query)
    )
  })
})

const totalColumns = computed(() => {
  return schemaTables.value.reduce((sum, t) => sum + t.columns.length, 0)
})

const describedColumns = computed(() => {
  return schemaTables.value.reduce((sum, t) => {
    return sum + t.columns.filter(c => c.description).length
  }, 0)
})

// Methods
function toggleTable(tableName) {
  if (expandedTables.value.has(tableName)) {
    expandedTables.value.delete(tableName)
  } else {
    expandedTables.value.add(tableName)
  }
  // Force reactivity
  expandedTables.value = new Set(expandedTables.value)
}

function getDescribedCount(table) {
  return table.columns.filter(c => c.description).length
}

function filterColumns(columns) {
  if (!searchQuery.value.trim()) return columns

  const query = searchQuery.value.toLowerCase()
  return columns.filter(col =>
    col.name.toLowerCase().includes(query) ||
    col.description?.toLowerCase().includes(query)
  )
}

function isEditing(tableName, columnName) {
  return editingColumn.value === `${tableName}.${columnName}`
}

function startEdit(table, column) {
  editingColumn.value = `${table.name}.${column.name}`
  editForm.value = {
    description: column.description || '',
    business_name: column.business_name || '',
    is_pii: column.is_pii || false,
    is_sensitive: column.is_sensitive || false,
    table_name: table.name,
    column_name: column.name,
    schema_name: table.schema_name || null,
    existing_id: column.id || null
  }

  // Focus input
  nextTick(() => {
    if (descriptionInput.value) {
      const input = Array.isArray(descriptionInput.value)
        ? descriptionInput.value[0]
        : descriptionInput.value
      input?.focus()
    }
  })
}

function cancelEdit() {
  editingColumn.value = null
  editForm.value = {
    description: '',
    business_name: '',
    is_pii: false,
    is_sensitive: false
  }
}

async function saveDescription() {
  if (!editForm.value.description.trim()) return

  try {
    const data = {
      table_name: editForm.value.table_name,
      column_name: editForm.value.column_name,
      description: editForm.value.description.trim(),
      schema_name: editForm.value.schema_name,
      business_name: editForm.value.business_name.trim() || null,
      is_pii: editForm.value.is_pii,
      is_sensitive: editForm.value.is_sensitive
    }

    await store.createColumnDescription(props.sessionId, data)

    // Refresh schema to get updated descriptions
    await store.fetchEnhancedSchema(props.sessionId)

    cancelEdit()
  } catch (error) {
    console.error('Failed to save description:', error)
    toast.error(error.userMessage || error.message || 'Failed to save description')
  }
}

async function deleteDescription(table, column) {
  if (!window.confirm(`Remove description for "${column.name}"?`)) return

  try {
    // Find the column description ID
    const colDescs = store.columnDescriptions
    const match = colDescs.find(
      c => c.table_name === table.name &&
           c.column_name === column.name &&
           c.schema_name === table.schema_name
    )

    if (match) {
      await store.deleteColumnDescription(match.id)
      await store.fetchEnhancedSchema(props.sessionId)
    }
  } catch (error) {
    console.error('Failed to delete description:', error)
    toast.error(error.userMessage || error.message || 'Failed to delete description')
  }
}

async function refreshSchema() {
  try {
    await store.fetchEnhancedSchema(props.sessionId)
  } catch (error) {
    console.error('Failed to refresh schema:', error)
    toast.error(error.userMessage || error.message || 'Failed to refresh schema')
  }
}
</script>

<style scoped>
.schema-explorer {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

/* Search Bar */
.search-bar {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-sm);
  outline: none;
}

.search-input::placeholder {
  color: var(--text-muted);
}

.clear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.clear-btn:hover {
  background: var(--bg-card);
  color: var(--text-primary);
}

/* Stats Row */
.stats-row {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.separator {
  color: var(--border-subtle);
}

.described {
  color: var(--color-success);
}

/* Loading/Empty States */
.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  padding: var(--space-xl);
  color: var(--text-muted);
  text-align: center;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Table Tree */
.table-tree {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.table-node {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.table-header {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-card);
  cursor: pointer;
  transition: background 0.15s ease;
}

.table-header:hover {
  background: var(--bg-input);
}

.chevron {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.chevron.expanded {
  transform: rotate(90deg);
}

.table-icon {
  color: var(--color-primary);
}

.table-name {
  font-weight: 500;
  color: var(--text-primary);
}

.column-count {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.described-badge {
  padding: 2px 6px;
  border-radius: var(--radius-full);
  background: var(--color-success);
  color: white;
  font-size: 10px;
  font-weight: 600;
}

/* Columns List */
.columns-list {
  border-top: 1px solid var(--border-subtle);
}

.column-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  padding-left: calc(var(--space-md) + 24px);
  border-bottom: 1px solid var(--border-subtle);
  transition: background 0.15s ease;
}

.column-row:last-child {
  border-bottom: none;
}

.column-row:hover {
  background: var(--bg-input);
}

.column-row.editing {
  background: var(--color-primary-light);
  flex-direction: column;
}

.column-info {
  flex: 1;
  min-width: 0;
}

.column-main {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.pk-icon {
  color: var(--color-warning);
}

.fk-icon {
  color: var(--color-info);
}

.column-name {
  font-weight: 500;
  color: var(--text-primary);
}

.column-type {
  font-size: var(--text-xs);
  color: var(--text-muted);
  padding: 1px 6px;
  background: var(--bg-input);
  border-radius: var(--radius-sm);
}

.column-description {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs);
  margin-top: 4px;
  font-size: var(--text-sm);
}

.description-text {
  color: var(--text-secondary);
}

.business-name {
  color: var(--color-primary);
  font-size: var(--text-xs);
}

.column-flags {
  display: flex;
  gap: 4px;
}

.flag {
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
}

.flag.pii {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

.flag.sensitive {
  background: rgba(245, 158, 11, 0.1);
  color: var(--color-warning);
}

.no-description {
  margin-top: 4px;
  font-size: var(--text-sm);
  color: var(--text-muted);
  font-style: italic;
}

/* Actions */
.column-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.column-row:hover .column-actions {
  opacity: 1;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-btn:hover {
  background: var(--border-subtle);
  color: var(--text-primary);
}

.action-btn.delete:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

/* Edit Form */
.edit-form {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin-top: var(--space-sm);
}

.form-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.form-input {
  flex: 1;
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg-app);
  color: var(--text-primary);
  font-size: var(--text-sm);
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.form-input.small {
  flex: 0 0 auto;
  width: 150px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
}

.checkbox-label input {
  cursor: pointer;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-xs);
}

/* Buttons */
.btn {
  display: flex;
  align-items: center;
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

.btn-secondary:hover {
  background: var(--border-subtle);
}

/* Transitions */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}
</style>

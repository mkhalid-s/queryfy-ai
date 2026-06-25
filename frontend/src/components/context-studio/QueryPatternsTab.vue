<!--
============================================
QueryPatternsTab.vue
============================================
Query patterns management for few-shot learning:
- List view with search/filter
- Create/Edit pattern form
- Curated flag for verified examples
- Rating system (thumbs up/down)
- Tags and complexity
-->
<template>
  <div class="query-patterns">
    <!-- Header -->
    <div class="tab-header">
      <div class="search-bar">
        <Search
          :size="14"
          class="search-icon"
        />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search patterns..."
          class="search-input"
          @input="debouncedSearch"
        >
        <select
          v-model="complexityFilter"
          class="filter-select"
        >
          <option value="">
            All Complexity
          </option>
          <option value="simple">
            Simple
          </option>
          <option value="medium">
            Medium
          </option>
          <option value="complex">
            Complex
          </option>
        </select>
        <label class="curated-toggle">
          <input
            v-model="curatedOnly"
            type="checkbox"
            @change="fetchPatterns"
          >
          <span>Curated only</span>
        </label>
      </div>
      <button
        class="btn btn-primary"
        @click="showCreateForm = true"
      >
        <Plus :size="14" />
        Add Pattern
      </button>
    </div>

    <!-- Create/Edit Form -->
    <div
      v-if="showCreateForm || editingPattern"
      class="form-card"
    >
      <div class="form-header">
        <h3>{{ editingPattern ? 'Edit Pattern' : 'New Query Pattern' }}</h3>
        <button
          class="close-btn"
          @click="closeForm"
        >
          <X :size="16" />
        </button>
      </div>

      <form
        class="pattern-form"
        @submit.prevent="savePattern"
      >
        <div class="form-group">
          <label>Natural Language Query *</label>
          <textarea
            v-model="form.natural_query"
            placeholder="e.g., Show me the total revenue by product category for last month"
            rows="2"
            required
          />
          <span class="hint">The question a user might ask</span>
        </div>

        <div class="form-group">
          <label>SQL Query *</label>
          <textarea
            v-model="form.sql"
            placeholder="SELECT category, SUM(revenue) FROM sales WHERE..."
            rows="4"
            class="code-input"
            required
          />
          <span class="hint">The correct SQL for this question</span>
        </div>

        <div class="form-group">
          <label>Description</label>
          <input
            v-model="form.description"
            type="text"
            placeholder="Optional description of what this pattern demonstrates"
          >
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>Complexity</label>
            <select v-model="form.complexity">
              <option value="">
                Not specified
              </option>
              <option value="simple">
                Simple
              </option>
              <option value="medium">
                Medium
              </option>
              <option value="complex">
                Complex
              </option>
            </select>
          </div>
          <div class="form-group">
            <label>Tags</label>
            <input
              v-model="tagsInput"
              type="text"
              placeholder="Comma-separated: aggregation, joins"
            >
          </div>
        </div>

        <label class="checkbox-label">
          <input
            v-model="form.is_curated"
            type="checkbox"
          >
          <span>Mark as curated (verified example)</span>
        </label>

        <div class="form-actions">
          <button
            type="button"
            class="btn btn-secondary"
            @click="closeForm"
          >
            Cancel
          </button>
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="!isFormValid || saving"
          >
            <Loader2
              v-if="saving"
              :size="14"
              class="spin"
            />
            <Check
              v-else
              :size="14"
            />
            {{ editingPattern ? 'Update' : 'Create' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Loading State -->
    <div
      v-if="queryPatternsLoading"
      class="loading-state"
    >
      <Loader2
        :size="20"
        class="spin"
      />
      <span>Loading patterns...</span>
    </div>

    <!-- Empty State -->
    <div
      v-else-if="queryPatterns.length === 0 && !showCreateForm"
      class="empty-state"
    >
      <FileCode :size="32" />
      <p>No query patterns defined</p>
      <p class="subtitle">
        Add example queries to improve SQL generation with few-shot learning
      </p>
      <button
        class="btn btn-primary"
        @click="showCreateForm = true"
      >
        <Plus :size="14" />
        Add First Pattern
      </button>
    </div>

    <!-- Patterns List -->
    <div
      v-else
      class="patterns-list"
    >
      <div
        v-for="pattern in queryPatterns"
        :key="pattern.id"
        :class="['pattern-card', { curated: pattern.is_curated }]"
      >
        <div class="pattern-header">
          <div class="pattern-badges">
            <span
              v-if="pattern.is_curated"
              class="badge curated"
              title="Curated example"
            >
              <Star :size="12" />
              Curated
            </span>
            <span
              v-if="pattern.complexity"
              :class="['badge', pattern.complexity]"
            >
              {{ pattern.complexity }}
            </span>
            <span
              v-for="tag in pattern.tags"
              :key="tag"
              class="badge tag"
            >
              {{ tag }}
            </span>
          </div>
          <div class="pattern-actions">
            <button
              class="action-btn"
              title="Edit"
              @click="startEdit(pattern)"
            >
              <Edit3 :size="14" />
            </button>
            <button
              class="action-btn delete"
              title="Delete"
              @click="deletePattern(pattern)"
            >
              <Trash2 :size="14" />
            </button>
          </div>
        </div>

        <div class="pattern-query">
          <MessageSquare
            :size="14"
            class="query-icon"
          />
          <span>{{ pattern.natural_query }}</span>
        </div>

        <div class="pattern-sql">
          <pre><code>{{ pattern.sql }}</code></pre>
        </div>

        <p
          v-if="pattern.description"
          class="pattern-description"
        >
          {{ pattern.description }}
        </p>

        <div class="pattern-footer">
          <div class="rating-controls">
            <button
              :class="['rate-btn', { active: pattern.rating > 0 }]"
              title="Helpful"
              @click="rate(pattern.id, 1)"
            >
              <ThumbsUp :size="14" />
            </button>
            <span class="rating-value">{{ pattern.rating || 0 }}</span>
            <button
              :class="['rate-btn', { active: pattern.rating < 0 }]"
              title="Not helpful"
              @click="rate(pattern.id, -1)"
            >
              <ThumbsDown :size="14" />
            </button>
          </div>

          <div class="pattern-stats">
            <span
              class="stat"
              title="Success count"
            >
              <CheckCircle :size="12" />
              {{ pattern.success_count || 0 }}
            </span>
            <span
              class="stat"
              title="Fail count"
            >
              <XCircle :size="12" />
              {{ pattern.fail_count || 0 }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div
      v-if="queryPatternsTotal > queryPatterns.length"
      class="pagination"
    >
      <button
        class="btn btn-secondary"
        @click="loadMore"
      >
        Load more ({{ queryPatternsTotal - queryPatterns.length }} remaining)
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import {
  Search,
  Plus,
  X,
  FileCode,
  Edit3,
  Trash2,
  Check,
  Loader2,
  Star,
  MessageSquare,
  ThumbsUp,
  ThumbsDown,
  CheckCircle,
  XCircle
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
const {
  queryPatterns,
  queryPatternsTotal,
  queryPatternsLoading
} = storeToRefs(store)
const toast = useToast()

// Local state
const searchQuery = ref('')
const complexityFilter = ref('')
const curatedOnly = ref(false)
const showCreateForm = ref(false)
const editingPattern = ref(null)
const saving = ref(false)

// Form state
const form = ref({
  natural_query: '',
  sql: '',
  description: '',
  complexity: '',
  is_curated: false
})
const tagsInput = ref('')

// Computed
const isFormValid = computed(() => {
  return form.value.natural_query.trim() && form.value.sql.trim()
})

// Debounced search
let searchTimeout = null
function debouncedSearch() {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    fetchPatterns()
  }, 300)
}

// Cleanup timeout on unmount
onUnmounted(() => {
  if (searchTimeout) clearTimeout(searchTimeout)
})

// Watch filters
watch(complexityFilter, () => {
  fetchPatterns()
})

// Methods
async function fetchPatterns() {
  await store.fetchQueryPatterns(props.sessionId, {
    search: searchQuery.value || undefined,
    complexity: complexityFilter.value || undefined,
    is_curated: curatedOnly.value || undefined,
    limit: 50
  })
}

async function loadMore() {
  await store.fetchQueryPatterns(props.sessionId, {
    search: searchQuery.value || undefined,
    complexity: complexityFilter.value || undefined,
    is_curated: curatedOnly.value || undefined,
    offset: queryPatterns.value.length,
    limit: 50
  })
}

function startEdit(pattern) {
  editingPattern.value = pattern
  form.value = {
    natural_query: pattern.natural_query,
    sql: pattern.sql,
    description: pattern.description || '',
    complexity: pattern.complexity || '',
    is_curated: pattern.is_curated
  }
  tagsInput.value = pattern.tags?.join(', ') || ''
}

function closeForm() {
  showCreateForm.value = false
  editingPattern.value = null
  form.value = {
    natural_query: '',
    sql: '',
    description: '',
    complexity: '',
    is_curated: false
  }
  tagsInput.value = ''
}

async function savePattern() {
  if (!isFormValid.value) return

  saving.value = true

  try {
    const data = {
      ...form.value,
      tags: tagsInput.value
        ? tagsInput.value.split(',').map(s => s.trim()).filter(Boolean)
        : []
    }

    // Remove empty complexity
    if (!data.complexity) delete data.complexity

    if (editingPattern.value) {
      await store.updateQueryPattern(editingPattern.value.id, data)
    } else {
      await store.createQueryPattern(props.sessionId, data)
    }

    closeForm()
  } catch (error) {
    console.error('Failed to save pattern:', error)
    toast.error(error.userMessage || error.message || 'Failed to save pattern')
  } finally {
    saving.value = false
  }
}

async function deletePattern(pattern) {
  if (!window.confirm('Delete this query pattern? This action cannot be undone.')) return

  try {
    await store.deleteQueryPattern(pattern.id)
  } catch (error) {
    console.error('Failed to delete pattern:', error)
    toast.error(error.userMessage || error.message || 'Failed to delete pattern')
  }
}

async function rate(patternId, rating) {
  try {
    await store.rateQueryPattern(patternId, rating)
  } catch (error) {
    console.error('Failed to rate pattern:', error)
    toast.error(error.userMessage || error.message || 'Failed to rate pattern')
  }
}
</script>

<style scoped>
.query-patterns {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

/* Header */
.tab-header {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}

.search-bar {
  flex: 1;
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

.filter-select {
  padding: var(--space-xs) var(--space-sm);
  border: none;
  border-left: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  outline: none;
  cursor: pointer;
}

.curated-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-left: var(--space-sm);
  border-left: 1px solid var(--border-subtle);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
}

/* Form Card */
.form-card {
  padding: var(--space-md);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.form-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-md);
}

.form-header h3 {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.close-btn:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

/* Form */
.pattern-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-md);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.form-group label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
}

.form-group input,
.form-group textarea,
.form-group select {
  padding: var(--space-sm);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg-app);
  color: var(--text-primary);
  font-size: var(--text-sm);
}

.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--color-primary);
}

.form-group textarea {
  resize: vertical;
  min-height: 60px;
}

textarea.code-input {
  font-family: monospace;
  font-size: var(--text-xs);
}

.hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  padding-top: var(--space-sm);
  border-top: 1px solid var(--border-subtle);
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

.empty-state .subtitle {
  font-size: var(--text-sm);
  margin: 0;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Patterns List */
.patterns-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.pattern-card {
  padding: var(--space-md);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  transition: border-color 0.15s ease;
}

.pattern-card:hover {
  border-color: var(--color-primary);
}

.pattern-card.curated {
  border-left: 3px solid var(--color-warning);
}

.pattern-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--space-sm);
}

.pattern-badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
}

.badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
}

.badge.curated {
  background: rgba(245, 158, 11, 0.1);
  color: var(--color-warning);
}

.badge.simple {
  background: rgba(34, 197, 94, 0.1);
  color: var(--color-success);
}

.badge.medium {
  background: rgba(59, 130, 246, 0.1);
  color: var(--color-info);
}

.badge.complex {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

.badge.tag {
  background: var(--bg-input);
  color: var(--text-secondary);
}

.pattern-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.pattern-card:hover .pattern-actions {
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
  background: var(--bg-input);
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

.pattern-query {
  display: flex;
  align-items: flex-start;
  gap: var(--space-xs);
  margin-bottom: var(--space-sm);
  font-size: var(--text-sm);
  color: var(--text-primary);
  line-height: 1.5;
}

.query-icon {
  color: var(--text-muted);
  flex-shrink: 0;
  margin-top: 2px;
}

.pattern-sql {
  padding: var(--space-sm);
  background: var(--bg-input);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-sm);
  overflow-x: auto;
}

.pattern-sql pre {
  margin: 0;
}

.pattern-sql code {
  font-family: monospace;
  font-size: var(--text-xs);
  color: var(--color-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.pattern-description {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.pattern-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: var(--space-sm);
  border-top: 1px solid var(--border-subtle);
}

.rating-controls {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.rate-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.rate-btn:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

.rate-btn.active {
  color: var(--color-primary);
}

.rating-value {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
  min-width: 24px;
  text-align: center;
}

.pattern-stats {
  display: flex;
  gap: var(--space-md);
}

.stat {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* Pagination */
.pagination {
  display: flex;
  justify-content: center;
  padding-top: var(--space-md);
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

/* Mobile */
@media (max-width: 640px) {
  .form-row {
    grid-template-columns: 1fr;
  }

  .tab-header {
    flex-direction: column;
    align-items: stretch;
  }

  .search-bar {
    flex-wrap: wrap;
  }

  .curated-toggle {
    border-left: none;
    padding-left: 0;
    padding-top: var(--space-xs);
  }
}
</style>

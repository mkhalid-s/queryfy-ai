<!--
============================================
BusinessTermsTab.vue
============================================
Business terms management:
- List view with search/filter
- Create/Edit term form
- Synonyms and examples
- Category management
- SQL expression preview
-->
<template>
  <div class="business-terms">
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
          placeholder="Search terms..."
          class="search-input"
          @input="debouncedSearch"
        >
        <select
          v-model="categoryFilter"
          class="category-select"
        >
          <option value="">
            All Categories
          </option>
          <option
            v-for="cat in termCategories"
            :key="cat"
            :value="cat"
          >
            {{ cat }}
          </option>
        </select>
      </div>
      <button
        class="btn btn-primary"
        @click="showCreateForm = true"
      >
        <Plus :size="14" />
        Add Term
      </button>
    </div>

    <!-- Create/Edit Form -->
    <div
      v-if="showCreateForm || editingTerm"
      class="form-card"
    >
      <div class="form-header">
        <h3>{{ editingTerm ? 'Edit Term' : 'New Business Term' }}</h3>
        <button
          class="close-btn"
          @click="closeForm"
        >
          <X :size="16" />
        </button>
      </div>

      <form
        class="term-form"
        @submit.prevent="saveTerm"
      >
        <div class="form-row">
          <div class="form-group">
            <label>Term *</label>
            <input
              v-model="form.term"
              type="text"
              placeholder="e.g., Revenue, Active User"
              required
            >
          </div>
          <div class="form-group">
            <label>Category</label>
            <input
              v-model="form.category"
              type="text"
              placeholder="e.g., Finance, Metrics"
              list="categories"
            >
            <datalist id="categories">
              <option
                v-for="cat in termCategories"
                :key="cat"
                :value="cat"
              />
            </datalist>
          </div>
        </div>

        <div class="form-group">
          <label>Definition *</label>
          <textarea
            v-model="form.definition"
            placeholder="Explain what this term means in business context..."
            rows="2"
            required
          />
        </div>

        <div class="form-group">
          <label>SQL Expression *</label>
          <textarea
            v-model="form.sql_expression"
            placeholder="e.g., SUM(sales_amount) - SUM(refund_amount)"
            rows="2"
            class="code-input"
            required
          />
          <span class="hint">The SQL expression that calculates this term</span>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>Synonyms</label>
            <input
              v-model="synonymsInput"
              type="text"
              placeholder="Comma-separated: income, earnings"
            >
            <span class="hint">Alternative names for this term</span>
          </div>
          <div class="form-group">
            <label>Examples</label>
            <input
              v-model="examplesInput"
              type="text"
              placeholder="Comma-separated example queries"
            >
            <span class="hint">Example usage in queries</span>
          </div>
        </div>

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
            {{ editingTerm ? 'Update' : 'Create' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Loading State -->
    <div
      v-if="businessTermsLoading"
      class="loading-state"
    >
      <Loader2
        :size="20"
        class="spin"
      />
      <span>Loading terms...</span>
    </div>

    <!-- Empty State -->
    <div
      v-else-if="businessTerms.length === 0 && !showCreateForm"
      class="empty-state"
    >
      <Tag :size="32" />
      <p>No business terms defined</p>
      <p class="subtitle">
        Define business vocabulary to improve SQL generation
      </p>
      <button
        class="btn btn-primary"
        @click="showCreateForm = true"
      >
        <Plus :size="14" />
        Add First Term
      </button>
    </div>

    <!-- Terms List -->
    <div
      v-else
      class="terms-list"
    >
      <div
        v-for="term in businessTerms"
        :key="term.id"
        class="term-card"
      >
        <div class="term-header">
          <div class="term-main">
            <span class="term-name">{{ term.term }}</span>
            <span
              v-if="term.category"
              class="term-category"
            >{{ term.category }}</span>
          </div>
          <div class="term-actions">
            <button
              class="action-btn"
              title="Edit"
              @click="startEdit(term)"
            >
              <Edit3 :size="14" />
            </button>
            <button
              class="action-btn delete"
              title="Delete"
              @click="deleteTerm(term)"
            >
              <Trash2 :size="14" />
            </button>
          </div>
        </div>

        <p class="term-definition">
          {{ term.definition }}
        </p>

        <div class="term-sql">
          <code>{{ term.sql_expression }}</code>
        </div>

        <div
          v-if="term.synonyms?.length || term.examples?.length"
          class="term-meta"
        >
          <div
            v-if="term.synonyms?.length"
            class="meta-item"
          >
            <span class="meta-label">Synonyms:</span>
            <span class="meta-value">{{ term.synonyms.join(', ') }}</span>
          </div>
          <div
            v-if="term.examples?.length"
            class="meta-item"
          >
            <span class="meta-label">Examples:</span>
            <span class="meta-value">{{ term.examples.join(', ') }}</span>
          </div>
        </div>

        <div class="term-footer">
          <span
            class="usage-count"
            title="Times used"
          >
            <Activity :size="12" />
            {{ term.usage_count || 0 }} uses
          </span>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div
      v-if="businessTermsTotal > businessTerms.length"
      class="pagination"
    >
      <button
        class="btn btn-secondary"
        @click="loadMore"
      >
        Load more ({{ businessTermsTotal - businessTerms.length }} remaining)
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
  Tag,
  Edit3,
  Trash2,
  Check,
  Loader2,
  Activity
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
  businessTerms,
  businessTermsTotal,
  businessTermsLoading,
  termCategories
} = storeToRefs(store)
const toast = useToast()

// Local state
const searchQuery = ref('')
const categoryFilter = ref('')
const showCreateForm = ref(false)
const editingTerm = ref(null)
const saving = ref(false)

// Form state
const form = ref({
  term: '',
  definition: '',
  sql_expression: '',
  category: '',
  scope_type: 'database'
})
const synonymsInput = ref('')
const examplesInput = ref('')

// Computed
const isFormValid = computed(() => {
  return form.value.term.trim() &&
         form.value.definition.trim() &&
         form.value.sql_expression.trim()
})

// Debounced search
let searchTimeout = null
function debouncedSearch() {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    fetchTerms()
  }, 300)
}

// Cleanup timeout on unmount
onUnmounted(() => {
  if (searchTimeout) clearTimeout(searchTimeout)
})

// Watch category filter
watch(categoryFilter, () => {
  fetchTerms()
})

// Methods
async function fetchTerms() {
  await store.fetchBusinessTerms(props.sessionId, {
    search: searchQuery.value || undefined,
    category: categoryFilter.value || undefined,
    limit: 50
  })
}

async function loadMore() {
  await store.fetchBusinessTerms(props.sessionId, {
    search: searchQuery.value || undefined,
    category: categoryFilter.value || undefined,
    offset: businessTerms.value.length,
    limit: 50
  })
}

function startEdit(term) {
  editingTerm.value = term
  form.value = {
    term: term.term,
    definition: term.definition,
    sql_expression: term.sql_expression,
    category: term.category || '',
    scope_type: term.scope_type || 'database'
  }
  synonymsInput.value = term.synonyms?.join(', ') || ''
  examplesInput.value = term.examples?.join(', ') || ''
}

function closeForm() {
  showCreateForm.value = false
  editingTerm.value = null
  form.value = {
    term: '',
    definition: '',
    sql_expression: '',
    category: '',
    scope_type: 'database'
  }
  synonymsInput.value = ''
  examplesInput.value = ''
}

async function saveTerm() {
  if (!isFormValid.value) return

  saving.value = true

  try {
    const data = {
      ...form.value,
      synonyms: synonymsInput.value
        ? synonymsInput.value.split(',').map(s => s.trim()).filter(Boolean)
        : [],
      examples: examplesInput.value
        ? examplesInput.value.split(',').map(s => s.trim()).filter(Boolean)
        : []
    }

    if (editingTerm.value) {
      await store.updateBusinessTerm(editingTerm.value.id, data)
    } else {
      await store.createBusinessTerm(props.sessionId, data)
    }

    closeForm()
  } catch (error) {
    console.error('Failed to save term:', error)
    toast.error(error.userMessage || error.message || 'Failed to save term')
  } finally {
    saving.value = false
  }
}

async function deleteTerm(term) {
  if (!window.confirm(`Delete "${term.term}"? This action cannot be undone.`)) return

  try {
    await store.deleteBusinessTerm(term.id)
  } catch (error) {
    console.error('Failed to delete term:', error)
    toast.error(error.userMessage || error.message || 'Failed to delete term')
  }
}
</script>

<style scoped>
.business-terms {
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

.category-select {
  padding: var(--space-xs) var(--space-sm);
  border: none;
  border-left: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  outline: none;
  cursor: pointer;
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
.term-form {
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
.form-group textarea {
  padding: var(--space-sm);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg-app);
  color: var(--text-primary);
  font-size: var(--text-sm);
}

.form-group input:focus,
.form-group textarea:focus {
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

/* Terms List */
.terms-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.term-card {
  padding: var(--space-md);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  transition: border-color 0.15s ease;
}

.term-card:hover {
  border-color: var(--color-primary);
}

.term-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--space-sm);
}

.term-main {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.term-name {
  font-weight: 600;
  color: var(--text-primary);
}

.term-category {
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: var(--text-xs);
  font-weight: 500;
}

.term-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.term-card:hover .term-actions {
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

.term-definition {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.5;
}

.term-sql {
  padding: var(--space-sm);
  background: var(--bg-input);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-sm);
}

.term-sql code {
  font-family: monospace;
  font-size: var(--text-xs);
  color: var(--color-primary);
}

.term-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: var(--space-sm);
}

.meta-item {
  display: flex;
  gap: var(--space-xs);
  font-size: var(--text-xs);
}

.meta-label {
  color: var(--text-muted);
}

.meta-value {
  color: var(--text-secondary);
}

.term-footer {
  display: flex;
  align-items: center;
  padding-top: var(--space-sm);
  border-top: 1px solid var(--border-subtle);
}

.usage-count {
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
}
</style>

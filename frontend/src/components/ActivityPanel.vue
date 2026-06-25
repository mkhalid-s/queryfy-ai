<!--
============================================
ActivityPanel.vue
============================================
Displays recent activity and query history with:
- Search/filter functionality
- Pinned queries with prominent cards
- Date-grouped recent queries
- Visual indicators for results
- Smooth animations
-->
<template>
  <div class="activity-panel">
    <!-- Search Bar -->
    <div class="search-bar">
      <Search
        :size="14"
        class="search-icon"
      />
      <input
        v-model="searchInput"
        type="text"
        placeholder="Search history..."
        class="search-input"
        @input="handleSearch"
      >
      <button
        v-if="searchInput"
        class="clear-btn"
        aria-label="Clear search"
        @click="clearSearch"
      >
        <X :size="14" />
      </button>
    </div>

    <!-- Pinned Section -->
    <div
      v-if="pinnedQueries.length > 0"
      class="section pinned-section"
    >
      <div class="section-header">
        <Star
          :size="12"
          class="header-icon pinned-icon"
        />
        <span>Pinned</span>
      </div>
      <div class="pinned-cards">
        <div
          v-for="(query, index) in pinnedQueries"
          :key="query.id"
          class="pinned-card"
          :style="{ '--index': index }"
          @click="$emit('select', query)"
        >
          <div class="pinned-card-content">
            <div class="pinned-query-text">
              {{ truncate(query.query, 60) }}
            </div>
            <div class="pinned-meta">
              <span
                v-if="query.rowCount"
                class="result-badge"
              >
                <Table2 :size="10" />
                {{ query.rowCount }} rows
              </span>
              <span
                v-if="query.hasChart"
                class="result-badge chart"
              >
                <BarChart3 :size="10" />
              </span>
            </div>
          </div>
          <button
            class="unpin-btn"
            title="Unpin"
            @click.stop="togglePin(query)"
          >
            <X :size="12" />
          </button>
        </div>
      </div>
    </div>

    <!-- Conversations Section with Date Groups -->
    <div class="section recent-section">
      <div
        v-if="!conversations || conversations.length === 0"
        class="empty-state"
      >
        <div class="empty-icon">
          <MessageSquare :size="32" />
        </div>
        <p
          v-if="searchQuery"
          class="empty-title"
        >
          No matches found
        </p>
        <p
          v-else
          class="empty-title"
        >
          No conversations yet
        </p>
        <p
          v-if="!searchQuery"
          class="empty-subtitle"
        >
          Start asking questions to build your history
        </p>
      </div>

      <template v-else>
        <!-- Date Groups -->
        <div
          v-for="group in groupedConversations"
          :key="group.label"
          class="date-group"
        >
          <div class="date-label">
            <span>{{ group.label }}</span>
            <span class="date-count">{{ group.conversations.length }}</span>
          </div>
          <div class="query-list">
            <div
              v-for="(conv, index) in group.conversations"
              :key="conv.sessionId"
              class="query-item conversation-item"
              :style="{ '--index': index }"
              :title="conv.title"
              @click="$emit('select', { type: 'conversation', sessionId: conv.sessionId, queries: conv.queries })"
            >
              <div class="query-icon">
                <MessagesSquare :size="14" />
              </div>
              <div class="query-content">
                <div class="query-text">
                  {{ truncate(conv.title, 45) }}
                </div>
                <div class="query-meta">
                  <span class="query-time">{{ formatTime(conv.latestTimestamp) }}</span>
                  <span class="meta-badge messages">
                    <MessageSquare :size="9" />
                    {{ conv.queryCount }}
                  </span>
                </div>
              </div>
              <div class="query-actions">
                <button
                  class="action-btn delete"
                  title="Remove conversation"
                  @click.stop="removeConversation(conv.sessionId)"
                >
                  <Trash2 :size="12" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Load More -->
        <button
          v-if="hasMore"
          class="load-more-btn"
          @click="loadMore"
        >
          <ChevronDown :size="14" />
          Show {{ Math.min(remaining, maxDisplay) }} more
        </button>
      </template>
    </div>

    <!-- Clear All -->
    <div
      v-if="recentCount > 0"
      class="footer-actions"
    >
      <button
        class="clear-all-btn"
        @click="confirmClear"
      >
        <Trash2 :size="12" />
        Clear history
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import {
  Search,
  X,
  Star,
  Trash2,
  MessageSquare,
  MessagesSquare,
  Table2,
  BarChart3,
  ChevronDown
} from 'lucide-vue-next'
import { useActivityStore } from '../stores/activity'

const props = defineProps({
  maxDisplay: {
    type: Number,
    default: 10
  }
})

defineEmits(['select'])

// Store - use storeToRefs for reactive state/getters, destructure actions directly
const store = useActivityStore()
const {
  pinnedQueries,
  searchQuery,
  recentCount,
  conversations
} = storeToRefs(store)

// Actions can be destructured directly
const {
  togglePin,
  removeQuery,
  clearRecent,
  setSearch,
  clearSearch: storeClearSearch
} = store

// Remove all queries for a conversation/session
function removeConversation(sessionId) {
  const convList = conversations.value || []
  const conv = convList.find(c => c.sessionId === sessionId)
  if (conv && conv.queries) {
    conv.queries.forEach(q => removeQuery(q.id))
  }
}

// Local state
const searchInput = ref('')
const displayCount = ref(props.maxDisplay)

// Group conversations by date
const groupedConversations = computed(() => {
  const convList = conversations.value || []
  const displayed = convList.slice(0, displayCount.value)
  const groups = []
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 86400000)
  const weekAgo = new Date(today.getTime() - 7 * 86400000)

  const todayItems = []
  const yesterdayItems = []
  const weekItems = []
  const olderItems = []

  displayed.forEach(conv => {
    const date = new Date(conv.latestTimestamp)
    if (date >= today) {
      todayItems.push(conv)
    } else if (date >= yesterday) {
      yesterdayItems.push(conv)
    } else if (date >= weekAgo) {
      weekItems.push(conv)
    } else {
      olderItems.push(conv)
    }
  })

  if (todayItems.length) groups.push({ label: 'Today', conversations: todayItems })
  if (yesterdayItems.length) groups.push({ label: 'Yesterday', conversations: yesterdayItems })
  if (weekItems.length) groups.push({ label: 'This Week', conversations: weekItems })
  if (olderItems.length) groups.push({ label: 'Older', conversations: olderItems })

  return groups
})

// Has more to show
const hasMore = computed(() => {
  return (conversations.value?.length || 0) > displayCount.value
})

// Remaining count
const remaining = computed(() => {
  return (conversations.value?.length || 0) - displayCount.value
})

// Debounced search
let searchTimeout = null
function handleSearch() {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    setSearch(searchInput.value)
    displayCount.value = props.maxDisplay // Reset pagination on search
  }, 200)
}

// Cleanup timeout on unmount
onUnmounted(() => {
  if (searchTimeout) clearTimeout(searchTimeout)
})

// Clear search
function clearSearch() {
  searchInput.value = ''
  storeClearSearch()
}

// Load more
function loadMore() {
  displayCount.value += props.maxDisplay
}

// Confirm clear all
function confirmClear() {
  if (window.confirm('Are you sure you want to clear all history?')) {
    clearRecent()
  }
}

// Helper: truncate text
function truncate(text, len) {
  if (!text) return ''
  return text.length > len ? text.slice(0, len) + '...' : text
}

// Helper: format relative time
function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m`
  if (diffHours < 24) return `${diffHours}h`
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Reset display count when search changes
watch(searchQuery, () => {
  displayCount.value = props.maxDisplay
})
</script>

<style scoped>
.activity-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* Search Bar */
.search-bar {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  margin: var(--space-sm);
  padding: 8px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  transition: all 0.2s ease;
}

.search-bar:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
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
  transition: all 0.15s ease;
}

.clear-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* Sections */
.section {
  display: flex;
  flex-direction: column;
}

.recent-section {
  flex: 1;
  overflow-y: auto;
  padding: 0 var(--space-sm);
}

/* Section Header */
.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.header-icon {
  opacity: 0.7;
}

.pinned-icon {
  color: #ffc000;
}

/* Pinned Cards */
.pinned-section {
  padding: 0 var(--space-sm);
  margin-bottom: var(--space-sm);
}

.pinned-cards {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pinned-card {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  padding: var(--space-sm);
  background: linear-gradient(135deg, var(--bg-card) 0%, var(--bg-input) 100%);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid #ffc000;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
  animation: slideIn 0.2s ease forwards;
  animation-delay: calc(var(--index) * 0.05s);
  opacity: 0;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(-8px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.pinned-card:hover {
  border-color: var(--color-primary-light);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  transform: translateX(2px);
}

.pinned-card-content {
  flex: 1;
  min-width: 0;
}

.pinned-query-text {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.4;
  margin-bottom: 4px;
}

.pinned-meta {
  display: flex;
  gap: 6px;
}

.result-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: 10px;
  font-weight: 500;
}

.result-badge.chart {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.unpin-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s ease;
}

.pinned-card:hover .unpin-btn {
  opacity: 1;
}

.unpin-btn:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

/* Date Groups */
.date-group {
  margin-bottom: var(--space-md);
}

.date-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-xs) 0;
  margin-bottom: var(--space-xs);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.date-count {
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--bg-input);
  font-size: 10px;
  font-weight: 500;
}

/* Query List */
.query-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.query-item {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: 8px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.15s ease;
  animation: fadeIn 0.2s ease forwards;
  animation-delay: calc(var(--index) * 0.03s);
  opacity: 0;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.query-item:hover {
  background: var(--bg-hover);
}

.query-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-muted);
  transition: all 0.15s ease;
}

.query-item:hover .query-icon {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.error-icon {
  color: var(--color-error);
}

.query-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.query-text {
  font-size: var(--text-sm);
  color: var(--text-primary);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.query-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.query-time {
  font-size: 11px;
  color: var(--text-muted);
}

.meta-badge {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 600;
}

.meta-badge.rows {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.meta-badge.chart {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.meta-badge.sql {
  background: var(--bg-input);
  color: var(--text-muted);
}

/* Query Actions */
.query-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.query-item:hover .query-actions {
  opacity: 1;
}

.action-btn {
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
  transition: all 0.15s ease;
}

.action-btn:hover {
  background: var(--bg-input);
  color: var(--color-primary);
}

.action-btn.delete:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-xl) var(--space-md);
  text-align: center;
}

.empty-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--bg-input);
  color: var(--text-muted);
  margin-bottom: var(--space-md);
}

.empty-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.empty-subtitle {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0;
}

/* Load More */
.load-more-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  margin-top: var(--space-sm);
  padding: 8px var(--space-sm);
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all 0.2s ease;
}

.load-more-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}

/* Footer Actions */
.footer-actions {
  margin-top: auto;
  padding: var(--space-sm);
  border-top: 1px solid var(--border-subtle);
}

.clear-all-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 8px var(--space-sm);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all 0.15s ease;
}

.clear-all-btn:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

/* Mobile */
@media (max-width: 768px) {
  .query-actions {
    opacity: 1;
  }

  .unpin-btn {
    opacity: 1;
  }
}
</style>

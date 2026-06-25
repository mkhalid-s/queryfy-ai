/**
 * Activity Store (Pinia)
 *
 * Manages recent activity and query history with:
 * - Recent queries list (last 50)
 * - Pinned/favorite queries (synced to backend)
 * - Search/filter functionality
 * - Persistence to localStorage + backend sync
 * - sql_hash storage for re-execution
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import api from '@/utils/api'

const STORAGE_KEY = 'queryfyai-activity'
const MAX_RECENT = 50

export const useActivityStore = defineStore('activity', () => {
  // ============================================
  // STATE
  // ============================================

  // Dual-tier history architecture
  const sessionQueries = ref([])         // Tier 1: Current session only
  const connectionQueries = ref([])      // Tier 2: All queries for this connection (cross-session)
  const pinnedQueries = ref([])
  const searchQuery = ref('')
  const currentSessionId = ref(null)
  const currentConnectionId = ref(null)  // Connection hash for filtering
  const currentDbType = ref(null)        // Database type for filtering
  const isSyncing = ref(false)
  const isLoadingConnection = ref(false) // Loading state for connection history

  // ============================================
  // COMPUTED
  // ============================================

  // TIER 1: Filter session queries (current session only)
  const filteredSession = computed(() => {
    let filtered = sessionQueries.value

    // Filter by current session ID
    if (currentSessionId.value) {
      filtered = filtered.filter(q => q.sessionId === currentSessionId.value)
    }

    // Filter by search query
    if (searchQuery.value.trim()) {
      const search = searchQuery.value.toLowerCase()
      filtered = filtered.filter(q =>
        q.query.toLowerCase().includes(search) ||
        q.sql?.toLowerCase().includes(search)
      )
    }

    // Filter out incomplete queries
    filtered = filtered.filter(q => q.sql != null && q.sql.trim() !== '')

    return filtered
  })

  // TIER 2: Filter connection queries (all sessions for this connection)
  const filteredConnection = computed(() => {
    let filtered = connectionQueries.value

    // Exclude queries already in session (prevent duplicates)
    const sessionIds = new Set(sessionQueries.value.map(q => q.id))
    filtered = filtered.filter(q => !sessionIds.has(q.id))

    // Filter by search query
    if (searchQuery.value.trim()) {
      const search = searchQuery.value.toLowerCase()
      filtered = filtered.filter(q =>
        q.query.toLowerCase().includes(search) ||
        q.sql?.toLowerCase().includes(search)
      )
    }

    return filtered
  })

  // Count of session queries
  const sessionCount = computed(() => sessionQueries.value.length)

  // Count of connection queries (excluding duplicates)
  const connectionCount = computed(() => filteredConnection.value.length)

  // Legacy: total count for backward compatibility
  const recentCount = computed(() => sessionCount.value + connectionCount.value)

  // Count of pinned queries
  const pinnedCount = computed(() => pinnedQueries.value.length)

  // Check if a query is pinned
  const isPinned = computed(() => (queryId) => {
    return pinnedQueries.value.some(q => q.id === queryId)
  })

  // Group session queries by sessionId as conversations (Tier 1)
  const sessionConversations = computed(() => {
    const sessionMap = new Map()

    // Group queries by sessionId
    for (const query of filteredSession.value) {
      const sessionId = query.sessionId || 'unknown'
      if (!sessionMap.has(sessionId)) {
        sessionMap.set(sessionId, {
          sessionId,
          queries: [],
          latestTimestamp: query.timestamp,
          firstQuery: query.query
        })
      }
      sessionMap.get(sessionId).queries.push(query)
      // Track latest timestamp for sorting
      if (query.timestamp > sessionMap.get(sessionId).latestTimestamp) {
        sessionMap.get(sessionId).latestTimestamp = query.timestamp
      }
    }

    // Convert to array and sort by latest timestamp (newest first)
    return Array.from(sessionMap.values())
      .map(session => ({
        ...session,
        queryCount: session.queries.length,
        title: session.queries.length > 0 ? session.queries[session.queries.length - 1].query : 'Conversation'
      }))
      .sort((a, b) => b.latestTimestamp - a.latestTimestamp)
  })

  // Group connection queries by sessionId as conversations (Tier 2)
  const connectionConversations = computed(() => {
    const sessionMap = new Map()

    // Group queries by sessionId
    for (const query of filteredConnection.value) {
      const sessionId = query.sessionId || 'unknown'
      if (!sessionMap.has(sessionId)) {
        sessionMap.set(sessionId, {
          sessionId,
          queries: [],
          latestTimestamp: query.timestamp,
          firstQuery: query.query
        })
      }
      sessionMap.get(sessionId).queries.push(query)
      if (query.timestamp > sessionMap.get(sessionId).latestTimestamp) {
        sessionMap.get(sessionId).latestTimestamp = query.timestamp
      }
    }

    // Convert to array and sort by latest timestamp (newest first)
    return Array.from(sessionMap.values())
      .map(session => ({
        ...session,
        queryCount: session.queries.length,
        title: session.queries.length > 0 ? session.queries[session.queries.length - 1].query : 'Conversation'
      }))
      .sort((a, b) => b.latestTimestamp - a.latestTimestamp)
  })

  // Legacy: combined conversations for backward compatibility
  const conversations = computed(() => sessionConversations.value)

  // ============================================
  // ACTIONS
  // ============================================

  /**
   * Load connection history from PostgreSQL (cross-session persistent queries)
   * @param {string} connectionHash - Connection hash
   * @param {string} dbType - Database type
   */
  async function loadConnectionHistory(connectionHash, dbType) {
    if (!connectionHash || !currentSessionId.value || isLoadingConnection.value) {
      return
    }

    isLoadingConnection.value = true
    try {
      const response = await api.searchHistory(currentSessionId.value, {
        connectionId: connectionHash,
        dbType: dbType,
        limit: 100,  // Load more for connection history
        offset: 0
      })

      if (response?.history) {
        connectionQueries.value = response.history.map(h => ({
          id: h.id,
          query: h.query,
          sql: h.sql,
          sqlHash: h.sql_hash,
          timestamp: new Date(h.timestamp).getTime(),
          sessionId: h.session_id,
          connectionHash: h.connection_id,
          success: h.success !== false,
          dbType: h.db_type,
          mode: h.mode,
          answer: h.answer,
          keyFindings: h.key_findings || [],
          confidence: h.confidence,
          chartSpec: h.chart_spec,
          rawResultSummary: h.raw_result_summary,
          toolsUsed: h.tools_used || [],
          agentSteps: h.agent_steps || [],
          isFollowUp: h.is_follow_up || false,
          conversationTurn: h.conversation_turn || null
        }))
      }
    } catch (error) {
      // 404 means session not found on backend (e.g. after backend restart) — expected, not an error
      if (error.response?.status !== 404) {
        console.warn('Failed to load connection history:', error.message || error)
      }
      connectionQueries.value = []
    } finally {
      isLoadingConnection.value = false
    }
  }

  /**
   * Set current session ID and connection info for backend sync
   * Triggers connection history load when connection changes
   * @param {string} sessionId - Session ID
   * @param {string} [connectionId] - Connection hash for filtering history
   * @param {string} [dbType] - Database type (mysql, postgresql, etc.)
   */
  function setSessionId(sessionId, connectionId = null, dbType = null) {
    const connectionChanged = connectionId && connectionId !== currentConnectionId.value

    currentSessionId.value = sessionId
    currentConnectionId.value = connectionId
    currentDbType.value = dbType

    // Load connection history when connection changes or on first load
    if (connectionChanged || (connectionId && connectionQueries.value.length === 0)) {
      loadConnectionHistory(connectionId, dbType)
    }
  }

  /**
   * Update connection info without changing session
   * Call this when user switches database within same session
   */
  function setConnectionInfo(connectionId, dbType) {
    currentConnectionId.value = connectionId
    currentDbType.value = dbType
  }

  /**
   * Add a query to recent history
   */
  function addQuery(queryData) {
    const entry = {
      id: queryData.id || `q-${Date.now()}`,
      query: queryData.query,
      sql: queryData.sql || null,
      sqlHash: queryData.sqlHash || null,  // Store sql_hash for re-execution
      timestamp: queryData.timestamp || Date.now(),
      sessionId: queryData.sessionId || null,
      success: queryData.success !== false,
      explanation: queryData.explanation || null,
      dbType: queryData.dbType || null,
      // Analyst mode fields for full conversation data
      mode: queryData.mode || 'standard',
      answer: queryData.answer || null,
      keyFindings: queryData.keyFindings || [],
      confidence: queryData.confidence || null,
      chartSpec: queryData.chartSpec || null,
      rawResultSummary: queryData.rawResultSummary || null,
      toolsUsed: queryData.toolsUsed || [],
      agentSteps: queryData.agentSteps || [],
      isFollowUp: queryData.isFollowUp || false,
      conversationTurn: queryData.conversationTurn || null
    }

    // Remove duplicate if exists (move to top)
    sessionQueries.value = sessionQueries.value.filter(q => q.id !== entry.id)

    // Add to beginning (session queries only - will appear in connection history next session)
    sessionQueries.value.unshift(entry)

    // Trim to max size
    if (sessionQueries.value.length > MAX_RECENT) {
      sessionQueries.value = sessionQueries.value.slice(0, MAX_RECENT)
    }
  }

  /**
   * Remove a query from recent history
   */
  function removeQuery(queryId) {
    sessionQueries.value = sessionQueries.value.filter(q => q.id !== queryId)
    // Note: Don't remove from connectionQueries (it's loaded from PostgreSQL)
  }

  /**
   * Pin a query for quick access (syncs with backend)
   */
  async function pinQuery(queryData) {
    // Don't duplicate
    if (pinnedQueries.value.some(q => q.id === queryData.id)) {
      return
    }

    const entry = {
      id: queryData.id,
      query: queryData.query,
      sql: queryData.sql || null,
      sqlHash: queryData.sqlHash || null,  // Store sql_hash for re-execution
      pinnedAt: Date.now(),
      explanation: queryData.explanation || null,
      dbType: queryData.dbType || null,
      // Analyst mode fields
      mode: queryData.mode || 'standard',
      answer: queryData.answer || null,
      keyFindings: queryData.keyFindings || [],
      confidence: queryData.confidence || null,
      chartSpec: queryData.chartSpec || null,
      rawResultSummary: queryData.rawResultSummary || null,
      toolsUsed: queryData.toolsUsed || [],
      agentSteps: queryData.agentSteps || []
    }

    pinnedQueries.value.unshift(entry)

    // Sync with backend if we have a session
    if (currentSessionId.value) {
      try {
        await api.togglePinQuery(currentSessionId.value, queryData.id, true)
      } catch (e) {
        console.warn('Failed to sync pin to backend:', e)
        // Keep local state - will sync later
      }
    }
  }

  /**
   * Unpin a query (syncs with backend)
   */
  async function unpinQuery(queryId) {
    pinnedQueries.value = pinnedQueries.value.filter(q => q.id !== queryId)

    // Sync with backend if we have a session
    if (currentSessionId.value) {
      try {
        await api.togglePinQuery(currentSessionId.value, queryId, false)
      } catch (e) {
        console.warn('Failed to sync unpin to backend:', e)
        // Keep local state - will sync later
      }
    }
  }

  /**
   * Toggle pin status (syncs with backend)
   */
  async function togglePin(queryData) {
    if (pinnedQueries.value.some(q => q.id === queryData.id)) {
      await unpinQuery(queryData.id)
    } else {
      await pinQuery(queryData)
    }
  }

  /**
   * Sync pinned queries from backend
   * Optionally filters by connection if currentConnectionId is set
   */
  async function syncPinnedFromBackend() {
    if (!currentSessionId.value || isSyncing.value) return

    isSyncing.value = true
    try {
      // Pass connection filter if available
      const options = {}
      if (currentConnectionId.value) {
        options.connectionId = currentConnectionId.value
      }
      if (currentDbType.value) {
        options.dbType = currentDbType.value
      }

      const response = await api.getPinnedQueries(currentSessionId.value, options)

      if (response?.history) {
        // Merge backend pinned with local pinned
        const backendPinned = response.history.map(h => ({
          id: h.id,
          query: h.query,
          sql: h.sql,
          sqlHash: h.sql_hash,
          pinnedAt: new Date(h.timestamp).getTime(),
          explanation: h.explanation,
          dbType: h.db_type,
          connectionId: h.connection_id
        }))

        // Merge: keep local pins not in backend, add backend pins not in local
        const localIds = new Set(pinnedQueries.value.map(q => q.id))

        // Add backend pins not in local
        const newFromBackend = backendPinned.filter(q => !localIds.has(q.id))

        // Keep local pins (they may not have synced yet)
        pinnedQueries.value = [...pinnedQueries.value, ...newFromBackend]
          .sort((a, b) => b.pinnedAt - a.pinnedAt)
      }
    } catch (e) {
      // 404 means session not found on backend (e.g. after backend restart) — expected, not an error
      if (e.response?.status !== 404) {
        console.warn('Failed to sync pinned queries from backend:', e.message || e)
      }
    } finally {
      isSyncing.value = false
    }
  }

  /**
   * Clear session queries only (preserve connection history)
   */
  function clearRecent() {
    sessionQueries.value = []
    // Don't clear connectionQueries (persistent history from PostgreSQL)
  }

  /**
   * Clear search filter
   */
  function clearSearch() {
    searchQuery.value = ''
  }

  /**
   * Set search query
   */
  function setSearch(query) {
    searchQuery.value = query
  }

  /**
   * Load history from backend response
   */
  function loadFromHistory(historyItems) {
    if (!Array.isArray(historyItems)) return

    // Convert backend history format to activity entries
    // Use currentSessionId since history is loaded per-session from backend
    const sessionIdToUse = currentSessionId.value || 'unknown'
    const entries = historyItems.map(item => ({
      id: item.id,
      query: item.query,
      sql: item.sql,
      sqlHash: item.sql_hash,  // Store sql_hash for re-execution
      timestamp: new Date(item.created_at || item.timestamp).getTime(),
      sessionId: item.session_id || sessionIdToUse,
      success: item.success !== false,
      explanation: item.explanation,
      dbType: item.db_type,
      // Analyst mode fields from backend
      mode: item.mode || 'standard',
      answer: item.answer || null,
      keyFindings: item.key_findings || [],
      confidence: item.confidence || null,
      chartSpec: item.chart_spec || null,
      rawResultSummary: item.raw_result_summary || null,
      toolsUsed: item.tools_used || [],
      agentSteps: item.agent_steps || [],
      isFollowUp: item.is_follow_up || false,
      conversationTurn: item.conversation_turn || null
    }))

    // Merge with existing session queries, avoiding duplicates
    const existingIds = new Set(sessionQueries.value.map(q => q.id))
    const newEntries = entries.filter(e => !existingIds.has(e.id))

    sessionQueries.value = [...newEntries, ...sessionQueries.value]
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, MAX_RECENT)

    // Also load pinned queries from backend history
    const pinnedEntries = historyItems.filter(item => item.pinned)
    if (pinnedEntries.length > 0) {
      const pinnedIds = new Set(pinnedQueries.value.map(q => q.id))
      const newPinned = pinnedEntries
        .filter(item => !pinnedIds.has(item.id))
        .map(item => ({
          id: item.id,
          query: item.query,
          sql: item.sql,
          sqlHash: item.sql_hash,
          pinnedAt: new Date(item.timestamp).getTime(),
          explanation: item.explanation,
          dbType: item.db_type,
          // Analyst mode fields
          mode: item.mode || 'standard',
          answer: item.answer || null,
          keyFindings: item.key_findings || [],
          confidence: item.confidence || null,
          chartSpec: item.chart_spec || null,
          rawResultSummary: item.raw_result_summary || null,
          toolsUsed: item.tools_used || [],
          agentSteps: item.agent_steps || []
        }))

      if (newPinned.length > 0) {
        pinnedQueries.value = [...pinnedQueries.value, ...newPinned]
          .sort((a, b) => b.pinnedAt - a.pinnedAt)
      }
    }
  }

  /**
   * Get the best re-execution strategy for a query
   *
   * Returns an object indicating how to re-execute:
   * - { method: 'reexecute', queryId } - Use reexecuteFromHistory (server-side lookup)
   *
   * Always uses server-side re-execution because:
   * - Backend SQL registry may expire or clear (server restart, session timeout)
   * - PostgreSQL fallback ensures cross-session re-execution works
   * - Connection verification happens server-side for security
   * - sqlHash in localStorage may outlive backend registry
   *
   * @param {string} queryId - Query ID from history
   * @returns {Object|null} Re-execution strategy or null if not possible
   */
  function getReexecutionStrategy(queryId) {
    // Find the query in recent or pinned
    const query = sessionQueries.value.find(q => q.id === queryId)
      || connectionQueries.value.find(q => q.id === queryId)
      || pinnedQueries.value.find(q => q.id === queryId)

    if (!query) {
      return null
    }

    // Always use server-side re-execution for reliability
    // Server will verify connection hash and fetch SQL from Redis or PostgreSQL
    return {
      method: 'reexecute',
      queryId: query.id
    }
  }

  /**
   * Get query info for display (doesn't execute)
   * @param {string} queryId - Query ID
   * @returns {Object|null} Query info or null if not found
   */
  function getQueryInfo(queryId) {
    return sessionQueries.value.find(q => q.id === queryId)
      || connectionQueries.value.find(q => q.id === queryId)
      || pinnedQueries.value.find(q => q.id === queryId)
      || null
  }

  // ============================================
  // PERSISTENCE
  // ============================================

  // Load from localStorage on init (with v1 → v2 migration)
  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (!stored) return

      const data = JSON.parse(stored)

      // v1 → v2 migration: 'recent' becomes 'session'
      if (data.recent && !data.session) {
        sessionQueries.value = data.recent || []
        pinnedQueries.value = data.pinned || []
        // Save in new format immediately
        saveToStorage()
      } else {
        // v2 format
        sessionQueries.value = data.session || []
        pinnedQueries.value = data.pinned || []
      }
    } catch (e) {
      console.warn('Failed to load activity from storage:', e)
      // Corrupt data - start fresh
      sessionQueries.value = []
      pinnedQueries.value = []
    }
  }

  // Save to localStorage on change (v2 format)
  function saveToStorage() {
    try {
      const data = {
        _version: 2,  // Version for future migrations
        session: sessionQueries.value.slice(0, MAX_RECENT),
        pinned: pinnedQueries.value
        // Note: connectionQueries NOT saved (loaded from backend on demand)
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
    } catch (e) {
      console.warn('Failed to save activity to storage:', e)
    }
  }

  // Watch for changes and persist (session queries + pinned only)
  watch([sessionQueries, pinnedQueries], saveToStorage, { deep: true })

  // Load on init
  loadFromStorage()

  // ============================================
  // RETURN
  // ============================================

  return {
    // State
    sessionQueries,           // NEW: Tier 1 queries
    connectionQueries,        // NEW: Tier 2 queries
    pinnedQueries,
    searchQuery,
    currentSessionId,
    currentConnectionId,
    currentDbType,
    isSyncing,
    isLoadingConnection,      // NEW: Loading state

    // Computed - Dual-tier
    filteredSession,          // NEW: Filtered session queries
    filteredConnection,       // NEW: Filtered connection queries
    sessionConversations,     // NEW: Grouped session conversations
    connectionConversations,  // NEW: Grouped connection conversations
    sessionCount,             // NEW: Session query count
    connectionCount,          // NEW: Connection query count

    // Computed - Legacy/shared
    recentCount,              // Total count (session + connection)
    pinnedCount,
    isPinned,
    conversations,            // Legacy: points to sessionConversations

    // Actions
    setSessionId,
    setConnectionInfo,
    loadConnectionHistory,    // NEW: Load connection history
    addQuery,
    removeQuery,
    pinQuery,
    unpinQuery,
    togglePin,
    clearRecent,
    clearSearch,
    setSearch,
    loadFromHistory,
    syncPinnedFromBackend,

    // Re-execution helpers
    getReexecutionStrategy,   // Returns best method for re-execution
    getQueryInfo              // Get query info without executing
  }
})

export default useActivityStore

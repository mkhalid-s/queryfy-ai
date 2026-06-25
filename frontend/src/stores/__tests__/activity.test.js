/**
 * Activity Store Tests
 *
 * Tests the activity store including:
 * - Query history management (session + connection tiers)
 * - Pinned queries with backend sync
 * - Search/filter functionality
 * - localStorage persistence
 * - Re-execution strategies
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import { useActivityStore } from '../activity'
import api from '@/utils/api'

/**
 * Wait for watch callbacks to complete.
 * Double nextTick is required because:
 * 1. First nextTick - Vue's reactive state updates
 * 2. Second nextTick - Watch callbacks execute
 */
async function flushWatchers() {
  await nextTick()
  await nextTick()
}

// Mock API
vi.mock('@/utils/api', () => ({
  default: {
    searchHistory: vi.fn(),
    getPinnedQueries: vi.fn(),
    togglePinQuery: vi.fn()
  }
}))

// Mock localStorage
const localStorageMock = (() => {
  let store = {}
  return {
    getItem: (key) => store[key] || null,
    setItem: (key, value) => { store[key] = value.toString() },
    removeItem: (key) => { delete store[key] },
    clear: () => { store = {} }
  }
})()

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock
})

describe('Activity Store', () => {
  let store

  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    setActivePinia(createPinia())
    store = useActivityStore()
  })

  afterEach(() => {
    localStorage.clear()
  })

  // ============================================
  // INITIALIZATION TESTS
  // ============================================

  describe('Initialization', () => {
    it('initializes with empty state', () => {
      expect(store.sessionQueries).toEqual([])
      expect(store.connectionQueries).toEqual([])
      expect(store.pinnedQueries).toEqual([])
      expect(store.searchQuery).toBe('')
      expect(store.currentSessionId).toBeNull()
      expect(store.currentConnectionId).toBeNull()
    })

    it('persists and loads queries', async () => {
      // Add a query
      store.addQuery({
        id: 'q1',
        query: 'SELECT * FROM users',
        sql: 'SELECT * FROM users',
        timestamp: Date.now()
      })

      // Wait for watch callbacks to save to localStorage
      await flushWatchers()

      // Verify it was saved
      const saved = localStorage.getItem('queryfyai-activity')
      expect(saved).toBeTruthy()

      const parsed = JSON.parse(saved)
      expect(parsed._version).toBe(2)
      expect(parsed.session.length).toBe(1)
      expect(parsed.session[0].query).toBe('SELECT * FROM users')
    })

    it('loads pinned queries from storage', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      // Pin a query
      await store.pinQuery({ id: 'p1', query: 'Pinned query', sql: 'SELECT 1' })

      // Wait for watch callbacks to save to localStorage
      await flushWatchers()

      // Verify saved
      const saved = localStorage.getItem('queryfyai-activity')
      const parsed = JSON.parse(saved)
      expect(parsed.pinned.length).toBe(1)
    })
  })

  // ============================================
  // QUERY MANAGEMENT TESTS
  // ============================================

  describe('Query Management', () => {
    it('adds a query to session history', () => {
      store.addQuery({
        id: 'q1',
        query: 'SELECT * FROM customers',
        sql: 'SELECT * FROM customers',
        sessionId: 'session1'
      })

      expect(store.sessionQueries.length).toBe(1)
      expect(store.sessionQueries[0].query).toBe('SELECT * FROM customers')
    })

    it('adds query with analyst mode fields', () => {
      store.addQuery({
        id: 'q1',
        query: 'Who are my top customers?',
        sql: 'SELECT * FROM customers ORDER BY revenue DESC LIMIT 10',
        sessionId: 'session1',
        mode: 'analyst',
        answer: 'Your top customer is ACME Corp',
        keyFindings: ['Total revenue: $5M'],
        confidence: 0.95,
        toolsUsed: ['search_tables', 'execute_and_analyze']
      })

      const query = store.sessionQueries[0]
      expect(query.mode).toBe('analyst')
      expect(query.answer).toBe('Your top customer is ACME Corp')
      expect(query.keyFindings).toEqual(['Total revenue: $5M'])
      expect(query.toolsUsed).toEqual(['search_tables', 'execute_and_analyze'])
    })

    it('removes duplicate query and moves it to top', () => {
      store.addQuery({ id: 'q1', query: 'test1', sql: 'SELECT 1', timestamp: 1000 })
      store.addQuery({ id: 'q2', query: 'test2', sql: 'SELECT 2', timestamp: 2000 })
      store.addQuery({ id: 'q1', query: 'test1', sql: 'SELECT 1', timestamp: 3000 })

      expect(store.sessionQueries.length).toBe(2)
      expect(store.sessionQueries[0].id).toBe('q1')
      expect(store.sessionQueries[0].timestamp).toBe(3000)
    })

    it('trims session queries to MAX_RECENT (50)', () => {
      for (let i = 0; i < 60; i++) {
        store.addQuery({
          id: `q${i}`,
          query: `Query ${i}`,
          sql: `SELECT ${i}`,
          timestamp: i
        })
      }

      expect(store.sessionQueries.length).toBe(50)
    })

    it('removes a query by ID', () => {
      store.addQuery({ id: 'q1', query: 'test1', sql: 'SELECT 1' })
      store.addQuery({ id: 'q2', query: 'test2', sql: 'SELECT 2' })

      store.removeQuery('q1')

      expect(store.sessionQueries.length).toBe(1)
      expect(store.sessionQueries[0].id).toBe('q2')
    })

    it('clears session queries', () => {
      store.addQuery({ id: 'q1', query: 'test1', sql: 'SELECT 1' })
      store.addQuery({ id: 'q2', query: 'test2', sql: 'SELECT 2' })

      store.clearRecent()

      expect(store.sessionQueries.length).toBe(0)
    })
  })

  // ============================================
  // SESSION/CONNECTION MANAGEMENT TESTS
  // ============================================

  describe('Session and Connection Management', () => {
    it('sets session ID and connection info', () => {
      store.setSessionId('session-123', 'conn-hash-abc', 'postgresql')

      expect(store.currentSessionId).toBe('session-123')
      expect(store.currentConnectionId).toBe('conn-hash-abc')
      expect(store.currentDbType).toBe('postgresql')
    })

    it('loads connection history when connection changes', async () => {
      api.searchHistory.mockResolvedValue({
        history: [
          {
            id: 'h1',
            query: 'Historical query',
            sql: 'SELECT * FROM history',
            sql_hash: 'hash123',
            timestamp: new Date('2024-01-01').toISOString(),
            session_id: 'old-session',
            success: true
          }
        ]
      })

      store.setSessionId('session-123', 'conn-hash-abc', 'postgresql')
      await vi.waitFor(() => expect(api.searchHistory).toHaveBeenCalled())

      expect(store.connectionQueries.length).toBe(1)
      expect(store.connectionQueries[0].query).toBe('Historical query')
    })

    it('does not reload connection history if unchanged', async () => {
      api.searchHistory.mockResolvedValue({
        history: [
          { id: 'h1', query: 'test', sql: 'SELECT 1', timestamp: new Date().toISOString(), session_id: 'old' }
        ]
      })

      store.setSessionId('session-123', 'conn-hash-abc', 'postgresql')
      await vi.waitFor(() => expect(api.searchHistory).toHaveBeenCalled())
      await vi.waitFor(() => expect(store.connectionQueries.length).toBe(1))

      vi.clearAllMocks()

      // Set session ID again with same connection (should not reload since connection unchanged)
      store.setSessionId('session-123', 'conn-hash-abc', 'postgresql')
      await nextTick()

      expect(api.searchHistory).not.toHaveBeenCalled()
    })
  })

  // ============================================
  // FILTERING TESTS
  // ============================================

  describe('Filtering and Search', () => {
    beforeEach(() => {
      store.setSessionId('session-123')
      store.addQuery({
        id: 'q1',
        query: 'SELECT * FROM customers',
        sql: 'SELECT * FROM customers',
        sessionId: 'session-123'
      })
      store.addQuery({
        id: 'q2',
        query: 'SELECT * FROM orders',
        sql: 'SELECT * FROM orders',
        sessionId: 'session-123'
      })
      store.addQuery({
        id: 'q3',
        query: 'SELECT * FROM products',
        sql: 'SELECT * FROM products',
        sessionId: 'session-456'
      })
    })

    it('filters session queries by current session ID', () => {
      expect(store.filteredSession.length).toBe(2)
      expect(store.filteredSession.every(q => q.sessionId === 'session-123')).toBe(true)
    })

    it('filters queries by search term', () => {
      store.setSearch('customers')

      expect(store.filteredSession.length).toBe(1)
      expect(store.filteredSession[0].query).toContain('customers')
    })

    it('filters queries by SQL search term', () => {
      store.setSearch('orders')

      expect(store.filteredSession.length).toBe(1)
      expect(store.filteredSession[0].sql).toContain('orders')
    })

    it('clears search filter', () => {
      store.setSearch('test')
      expect(store.searchQuery).toBe('test')

      store.clearSearch()
      expect(store.searchQuery).toBe('')
    })

    it('filters out queries without SQL', () => {
      store.addQuery({
        id: 'q4',
        query: 'Invalid query',
        sql: null,
        sessionId: 'session-123'
      })

      // Should not include query without SQL
      expect(store.filteredSession.every(q => q.sql)).toBe(true)
    })
  })

  // ============================================
  // PINNED QUERIES TESTS
  // ============================================

  describe('Pinned Queries', () => {
    it('pins a query', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      await store.pinQuery({
        id: 'q1',
        query: 'SELECT * FROM customers',
        sql: 'SELECT * FROM customers'
      })

      expect(store.pinnedQueries.length).toBe(1)
      expect(store.pinnedQueries[0].id).toBe('q1')
      expect(api.togglePinQuery).toHaveBeenCalledWith('session-123', 'q1', true)
    })

    it('unpins a query', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      await store.pinQuery({ id: 'q1', query: 'test', sql: 'SELECT 1' })
      await store.unpinQuery('q1')

      expect(store.pinnedQueries.length).toBe(0)
      expect(api.togglePinQuery).toHaveBeenCalledWith('session-123', 'q1', false)
    })

    it('toggles pin status', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      const queryData = { id: 'q1', query: 'test', sql: 'SELECT 1' }

      // Toggle on
      await store.togglePin(queryData)
      expect(store.pinnedQueries.length).toBe(1)

      // Toggle off
      await store.togglePin(queryData)
      expect(store.pinnedQueries.length).toBe(0)
    })

    it('checks if query is pinned', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      await store.pinQuery({ id: 'q1', query: 'test', sql: 'SELECT 1' })

      expect(store.isPinned('q1')).toBe(true)
      expect(store.isPinned('q2')).toBe(false)
    })

    it('syncs pinned queries from backend', async () => {
      api.getPinnedQueries.mockResolvedValue({
        history: [
          {
            id: 'h1',
            query: 'Backend pinned query',
            sql: 'SELECT * FROM pinned',
            sql_hash: 'hash123',
            timestamp: new Date().toISOString()
          }
        ]
      })

      store.setSessionId('session-123')
      await store.syncPinnedFromBackend()

      expect(store.pinnedQueries.length).toBe(1)
      expect(store.pinnedQueries[0].query).toBe('Backend pinned query')
    })

    it('prevents duplicate pins', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      const queryData = { id: 'q1', query: 'test', sql: 'SELECT 1' }

      await store.pinQuery(queryData)
      await store.pinQuery(queryData)

      expect(store.pinnedQueries.length).toBe(1)
    })
  })

  // ============================================
  // COMPUTED PROPERTIES TESTS
  // ============================================

  describe('Computed Properties', () => {
    beforeEach(() => {
      store.setSessionId('session-123')
      store.addQuery({ id: 'q1', query: 'test1', sql: 'SELECT 1', sessionId: 'session-123' })
      store.addQuery({ id: 'q2', query: 'test2', sql: 'SELECT 2', sessionId: 'session-123' })
    })

    it('computes session count correctly', () => {
      expect(store.sessionCount).toBe(2)
    })

    it('computes pinned count correctly', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      await store.pinQuery({ id: 'q1', query: 'test', sql: 'SELECT 1' })

      expect(store.pinnedCount).toBe(1)
    })

    it('computes total recent count (session + connection)', async () => {
      api.searchHistory.mockResolvedValue({
        history: [
          {
            id: 'h1',
            query: 'Historical',
            sql: 'SELECT * FROM history',
            timestamp: new Date().toISOString(),
            session_id: 'old-session'
          }
        ]
      })

      store.setSessionId('session-123', 'conn-123', 'postgresql')
      await vi.waitFor(() => expect(api.searchHistory).toHaveBeenCalled())

      // Should be 2 (session) + 1 (connection, excluding duplicates)
      expect(store.recentCount).toBe(3)
    })

    it('groups session queries into conversations', () => {
      store.addQuery({ id: 'q3', query: 'test3', sql: 'SELECT 3', sessionId: 'session-123' })

      const conversations = store.sessionConversations
      expect(conversations.length).toBe(1)
      expect(conversations[0].sessionId).toBe('session-123')
      expect(conversations[0].queries.length).toBe(3)
      expect(conversations[0].queryCount).toBe(3)
    })
  })

  // ============================================
  // PERSISTENCE TESTS
  // ============================================

  describe('localStorage Persistence', () => {
    it('saves to localStorage when queries change', async () => {
      store.addQuery({ id: 'q1', query: 'test', sql: 'SELECT 1' })

      // Wait for watch callbacks to save
      await flushWatchers()

      const stored = JSON.parse(localStorage.getItem('queryfyai-activity'))
      expect(stored._version).toBe(2)
      expect(stored.session.length).toBe(1)
      expect(stored.session[0].query).toBe('test')
    })

    it('saves to localStorage when pinned queries change', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      await store.pinQuery({ id: 'q1', query: 'test', sql: 'SELECT 1' })

      // Wait for watch callbacks to save
      await flushWatchers()

      const stored = JSON.parse(localStorage.getItem('queryfyai-activity'))
      expect(stored.pinned.length).toBe(1)
    })

    it('does not save connection queries to localStorage', async () => {
      // First add a session query to ensure localStorage has data
      store.addQuery({ id: 'q1', query: 'Session query', sql: 'SELECT 1' })
      await flushWatchers()

      // Load connection history
      api.searchHistory.mockResolvedValue({
        history: [{ id: 'h1', query: 'Historical', sql: 'SELECT 1', timestamp: new Date().toISOString(), session_id: 'old' }]
      })

      store.setSessionId('session-123', 'conn-123', 'postgresql')
      await vi.waitFor(() => expect(api.searchHistory).toHaveBeenCalled())
      await vi.waitFor(() => expect(store.connectionQueries.length).toBe(1))

      // Wait for any potential save
      await flushWatchers()

      const stored = JSON.parse(localStorage.getItem('queryfyai-activity'))
      expect(stored).toBeTruthy()
      expect(stored).not.toHaveProperty('connection')
      // Should only have session queries, not connection queries
      expect(stored.session).toBeDefined()
    })
  })

  // ============================================
  // RE-EXECUTION STRATEGY TESTS
  // ============================================

  describe('Re-execution Strategy', () => {
    beforeEach(() => {
      store.addQuery({
        id: 'q1',
        query: 'SELECT * FROM users',
        sql: 'SELECT * FROM users',
        sqlHash: 'hash123'
      })
    })

    it('returns re-execution strategy for existing query', () => {
      const strategy = store.getReexecutionStrategy('q1')

      expect(strategy).toBeTruthy()
      expect(strategy.method).toBe('reexecute')
      expect(strategy.queryId).toBe('q1')
    })

    it('returns null for non-existent query', () => {
      const strategy = store.getReexecutionStrategy('non-existent')

      expect(strategy).toBeNull()
    })

    it('finds query in pinned queries for re-execution', async () => {
      api.togglePinQuery.mockResolvedValue({ success: true })
      store.setSessionId('session-123')

      await store.pinQuery({
        id: 'p1',
        query: 'SELECT * FROM pinned',
        sql: 'SELECT * FROM pinned'
      })

      const strategy = store.getReexecutionStrategy('p1')
      expect(strategy).toBeTruthy()
      expect(strategy.queryId).toBe('p1')
    })

    it('gets query info without executing', () => {
      const info = store.getQueryInfo('q1')

      expect(info).toBeTruthy()
      expect(info.id).toBe('q1')
      expect(info.query).toBe('SELECT * FROM users')
      expect(info.sql).toBe('SELECT * FROM users')
    })
  })

  // ============================================
  // HISTORY LOADING TESTS
  // ============================================

  describe('History Loading', () => {
    it('loads history from backend format', () => {
      const historyItems = [
        {
          id: 'h1',
          query: 'Backend query 1',
          sql: 'SELECT 1',
          sql_hash: 'hash1',
          created_at: new Date('2024-01-01').toISOString(),
          session_id: 'session-123',
          success: true,
          mode: 'standard'
        },
        {
          id: 'h2',
          query: 'Backend query 2',
          sql: 'SELECT 2',
          sql_hash: 'hash2',
          created_at: new Date('2024-01-02').toISOString(),
          session_id: 'session-123',
          success: true,
          mode: 'analyst',
          answer: 'Analysis result',
          key_findings: ['Finding 1']
        }
      ]

      store.setSessionId('session-123')
      store.loadFromHistory(historyItems)

      expect(store.sessionQueries.length).toBe(2)
      expect(store.sessionQueries[0].mode).toBe('analyst')
      expect(store.sessionQueries[0].answer).toBe('Analysis result')
      expect(store.sessionQueries[0].keyFindings).toEqual(['Finding 1'])
    })

    it('loads pinned queries from history', () => {
      const historyItems = [
        {
          id: 'h1',
          query: 'Pinned query',
          sql: 'SELECT 1',
          sql_hash: 'hash1',
          timestamp: new Date().toISOString(),
          pinned: true
        }
      ]

      store.loadFromHistory(historyItems)

      expect(store.pinnedQueries.length).toBe(1)
      expect(store.pinnedQueries[0].query).toBe('Pinned query')
    })

    it('avoids duplicate queries when loading history', () => {
      store.addQuery({ id: 'q1', query: 'Existing', sql: 'SELECT 1' })

      const historyItems = [
        { id: 'q1', query: 'Existing', sql: 'SELECT 1', timestamp: new Date().toISOString() },
        { id: 'q2', query: 'New', sql: 'SELECT 2', timestamp: new Date().toISOString() }
      ]

      store.loadFromHistory(historyItems)

      expect(store.sessionQueries.length).toBe(2)
    })
  })
})

/**
 * Conversation Store Tests
 *
 * Tests the conversation store including:
 * - Message management (user, AI, system)
 * - Session-based conversations
 * - Multi-turn conversation support
 * - localStorage persistence
 * - Backend history loading
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import { useConversationStore, MessageType } from '../conversation'

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

// Create localStorage mock factory
function createLocalStorageMock() {
  let store = {}
  return {
    getItem: (key) => store[key] || null,
    setItem: (key, value) => { store[key] = value.toString() },
    removeItem: (key) => { delete store[key] },
    clear: () => { store = {} }
  }
}

describe('Conversation Store', () => {
  let store
  let localStorageMock

  beforeEach(() => {
    // Create and stub localStorage for each test
    localStorageMock = createLocalStorageMock()
    vi.stubGlobal('localStorage', localStorageMock)

    setActivePinia(createPinia())
    store = useConversationStore()
  })

  afterEach(() => {
    // Restore original localStorage
    vi.unstubAllGlobals()
  })

  // ============================================
  // INITIALIZATION TESTS
  // ============================================

  describe('Initialization', () => {
    it('initializes with empty state', () => {
      expect(store.messages).toEqual([])
      expect(store.currentSessionId).toBeNull()
      expect(store.hasMessages).toBe(false)
      expect(store.messageCount).toBe(0)
    })

    it('initializes with continueConversation enabled', () => {
      expect(store.continueConversation).toBe(true)
    })
  })

  // ============================================
  // MESSAGE ADDITION TESTS
  // ============================================

  describe('Message Addition', () => {
    it('adds a user message', () => {
      const id = store.addUserMessage('Show me all customers')

      expect(store.messages.length).toBe(1)
      expect(store.messages[0].type).toBe(MessageType.USER)
      expect(store.messages[0].content.text).toBe('Show me all customers')
      expect(store.messages[0].id).toBe(id)
    })

    it('adds an AI message with SQL', () => {
      const id = store.addAiMessage({
        sql: 'SELECT * FROM customers',
        isValid: true,
        queryType: 'SELECT'
      })

      expect(store.messages.length).toBe(1)
      expect(store.messages[0].type).toBe(MessageType.AI)
      expect(store.messages[0].content.sql).toBe('SELECT * FROM customers')
      expect(store.messages[0].id).toBe(id)
    })

    it('adds an AI message with analyst mode fields', () => {
      store.addAiMessage({
        sql: 'SELECT * FROM revenue ORDER BY amount DESC LIMIT 10',
        mode: 'analyst',
        answer: 'Your top revenue source is Product A',
        keyFindings: ['Total: $5M', 'Growth: 15%'],
        confidence: 0.95,
        toolsUsed: ['search_tables', 'execute_and_analyze']
      })

      const aiMsg = store.latestAiMessage
      expect(aiMsg.content.mode).toBe('analyst')
      expect(aiMsg.content.answer).toBe('Your top revenue source is Product A')
      expect(aiMsg.content.keyFindings).toEqual(['Total: $5M', 'Growth: 15%'])
      expect(aiMsg.content.confidence).toBe(0.95)
      expect(aiMsg.content.toolsUsed).toEqual(['search_tables', 'execute_and_analyze'])
    })

    it('adds a system message', () => {
      const id = store.addSystemMessage('Connection established', 'success')

      expect(store.messages.length).toBe(1)
      expect(store.messages[0].type).toBe(MessageType.SYSTEM)
      expect(store.messages[0].content.text).toBe('Connection established')
      expect(store.messages[0].variant).toBe('success')
      expect(store.messages[0].id).toBe(id)
    })

    it('adds messages in correct order', () => {
      store.addUserMessage('Query 1')
      store.addAiMessage({ sql: 'SELECT 1' })
      store.addUserMessage('Query 2')
      store.addAiMessage({ sql: 'SELECT 2' })

      expect(store.messages.length).toBe(4)
      expect(store.messages[0].type).toBe(MessageType.USER)
      expect(store.messages[1].type).toBe(MessageType.AI)
      expect(store.messages[2].type).toBe(MessageType.USER)
      expect(store.messages[3].type).toBe(MessageType.AI)
    })
  })

  // ============================================
  // MESSAGE UPDATE TESTS
  // ============================================

  describe('Message Updates', () => {
    it('updates a message by ID', () => {
      const id = store.addAiMessage({ sql: 'SELECT 1', isGenerating: true })

      store.updateMessage(id, { isGenerating: false, results: { rows: [] } })

      const msg = store.getMessage(id)
      expect(msg.content.isGenerating).toBe(false)
      expect(msg.content.results).toEqual({ rows: [] })
    })

    it('updates latest AI message with results', () => {
      store.addAiMessage({ sql: 'SELECT * FROM users' })

      const results = {
        columns: ['id', 'name'],
        rows: [[1, 'Alice'], [2, 'Bob']],
        row_count: 2
      }
      store.updateLatestWithResults(results)

      expect(store.latestAiMessage.content.results).toEqual(results)
    })

    it('updates latest AI message with explanation', () => {
      store.addAiMessage({ sql: 'SELECT * FROM users WHERE active = true' })

      store.updateLatestWithExplanation('This query filters for active users only')

      expect(store.latestAiMessage.content.explanation).toBe('This query filters for active users only')
    })

    it('does not update non-existent message', () => {
      store.addAiMessage({ sql: 'SELECT 1' })

      const initialCount = store.messages.length
      store.updateMessage('non-existent-id', { sql: 'SELECT 2' })

      expect(store.messages.length).toBe(initialCount)
    })
  })

  // ============================================
  // SESSION MANAGEMENT TESTS
  // ============================================

  describe('Session Management', () => {
    it('sets session ID', () => {
      store.setSessionId('session-123')

      expect(store.currentSessionId).toBe('session-123')
    })

    it('preserves messages when switching sessions', () => {
      store.setSessionId('session-1')
      store.addUserMessage('Query in session 1')
      store.addAiMessage({ sql: 'SELECT 1' })

      store.setSessionId('session-2')
      expect(store.messages.length).toBe(0)

      // Switch back to session 1
      store.setSessionId('session-1')
      expect(store.messages.length).toBe(2)
      expect(store.messages[0].content.text).toBe('Query in session 1')
    })

    it('starts with empty messages for new session', () => {
      store.setSessionId('session-1')
      store.addUserMessage('Message')

      store.setSessionId('session-2')
      expect(store.messages.length).toBe(0)
    })
  })

  // ============================================
  // COMPUTED PROPERTIES TESTS
  // ============================================

  describe('Computed Properties', () => {
    beforeEach(() => {
      store.addUserMessage('Query 1')
      store.addAiMessage({ sql: 'SELECT 1' })
      store.addUserMessage('Query 2')
      store.addAiMessage({ sql: 'SELECT 2' })
    })

    it('computes hasMessages correctly', () => {
      expect(store.hasMessages).toBe(true)

      store.clearConversation()
      expect(store.hasMessages).toBe(false)
    })

    it('computes messageCount correctly', () => {
      expect(store.messageCount).toBe(4)
    })

    it('returns latest message', () => {
      expect(store.latestMessage.type).toBe(MessageType.AI)
      expect(store.latestMessage.content.sql).toBe('SELECT 2')
    })

    it('returns latest AI message', () => {
      store.addUserMessage('Query 3')

      expect(store.latestAiMessage.type).toBe(MessageType.AI)
      expect(store.latestAiMessage.content.sql).toBe('SELECT 2')
    })

    it('returns latest SQL', () => {
      expect(store.latestSql).toBe('SELECT 2')
    })

    it('returns null for latest SQL when no AI messages', () => {
      store.clearConversation()
      expect(store.latestSql).toBeNull()
    })

    it('computes follow-up count correctly', () => {
      store.addAiMessage({ sql: 'SELECT 3', isFollowUp: true, conversationTurn: 2 })
      store.addAiMessage({ sql: 'SELECT 4', isFollowUp: true, conversationTurn: 3 })

      expect(store.followUpCount).toBe(2)
    })

    it('computes current conversation turn', () => {
      expect(store.currentConversationTurn).toBeGreaterThan(0)
    })
  })

  // ============================================
  // MESSAGE REMOVAL TESTS
  // ============================================

  describe('Message Removal', () => {
    it('removes a message by ID', () => {
      const id = store.addUserMessage('Query to remove')
      expect(store.messages.length).toBe(1)

      store.removeMessage(id)
      expect(store.messages.length).toBe(0)
    })

    it('clears entire conversation', () => {
      store.setSessionId('session-123')
      store.addUserMessage('Query 1')
      store.addAiMessage({ sql: 'SELECT 1' })

      store.clearConversation()

      expect(store.messages.length).toBe(0)
      expect(store.hasMessages).toBe(false)
    })

    it('does not affect other sessions when clearing', () => {
      store.setSessionId('session-1')
      store.addUserMessage('Query in session 1')

      store.setSessionId('session-2')
      store.addUserMessage('Query in session 2')
      store.clearConversation()

      store.setSessionId('session-1')
      expect(store.messages.length).toBe(1)
    })
  })

  // ============================================
  // BACKEND HISTORY LOADING TESTS
  // ============================================

  describe('Backend History Loading', () => {
    it('loads conversation from backend history', () => {
      const historyEntries = [
        {
          id: 'h1',
          query: 'SELECT * FROM users',
          sql: 'SELECT * FROM users',
          sql_hash: 'hash1',
          timestamp: new Date('2024-01-01T10:00:00Z').toISOString(),
          success: true,
          mode: 'standard'
        },
        {
          id: 'h2',
          query: 'What is the revenue?',
          sql: 'SELECT SUM(revenue) FROM orders',
          sql_hash: 'hash2',
          timestamp: new Date('2024-01-01T10:05:00Z').toISOString(),
          success: true,
          mode: 'analyst',
          answer: 'Total revenue is $5M',
          key_findings: ['Growth: 15%'],
          confidence: 0.95
        }
      ]

      store.loadFromBackendHistory(historyEntries)

      // Should create 4 messages: 2 user + 2 AI
      expect(store.messages.length).toBe(4)
      expect(store.messages[0].type).toBe(MessageType.USER)
      expect(store.messages[1].type).toBe(MessageType.AI)
      expect(store.messages[1].content.mode).toBe('standard')
      expect(store.messages[3].content.mode).toBe('analyst')
      expect(store.messages[3].content.answer).toBe('Total revenue is $5M')
    })

    it('sorts messages by timestamp when loading', () => {
      const historyEntries = [
        {
          id: 'h2',
          query: 'Query 2',
          sql: 'SELECT 2',
          timestamp: new Date('2024-01-01T10:05:00Z').toISOString()
        },
        {
          id: 'h1',
          query: 'Query 1',
          sql: 'SELECT 1',
          timestamp: new Date('2024-01-01T10:00:00Z').toISOString()
        }
      ]

      store.loadFromBackendHistory(historyEntries)

      // First message should be from h1 (earlier timestamp)
      expect(store.messages[0].id).toContain('h1')
    })

    it('avoids duplicate messages when loading history', () => {
      store.addUserMessage('Existing query')
      const existingAiId = store.addAiMessage({ sql: 'SELECT 1' })

      const historyEntries = [
        {
          id: existingAiId,
          query: 'Existing query',
          sql: 'SELECT 1',
          timestamp: new Date().toISOString()
        }
      ]

      store.loadFromBackendHistory(historyEntries)

      // Should not create duplicates
      const aiMessages = store.messages.filter(m => m.type === MessageType.AI)
      expect(aiMessages.length).toBe(1)
    })
  })

  // ============================================
  // QUERY ID LOOKUP TESTS
  // ============================================

  describe('Query ID Lookup', () => {
    it('finds message by query ID', () => {
      store.addAiMessage({ sql: 'SELECT 1', queryId: 'q123' })
      store.addAiMessage({ sql: 'SELECT 2', queryId: 'q456' })

      const msg = store.findMessageByQueryId('q123')
      expect(msg).toBeTruthy()
      expect(msg.content.sql).toBe('SELECT 1')
    })

    it('gets SQL hash for query', () => {
      store.addAiMessage({
        sql: 'SELECT * FROM users',
        queryId: 'q789',
        sqlHash: 'hash-abc-123'
      })

      const hash = store.getSqlHashForQuery('q789')
      expect(hash).toBe('hash-abc-123')
    })

    it('returns null for non-existent query ID', () => {
      const msg = store.findMessageByQueryId('non-existent')
      expect(msg).toBeUndefined()

      const hash = store.getSqlHashForQuery('non-existent')
      expect(hash).toBeNull()
    })
  })

  // ============================================
  // CONVERSATION CONTROL TESTS
  // ============================================

  describe('Conversation Control', () => {
    it('sets continue conversation flag', () => {
      store.setContinueConversation(false)
      expect(store.continueConversation).toBe(false)

      store.setContinueConversation(true)
      expect(store.continueConversation).toBe(true)
    })

    it('resets conversation context', () => {
      store.addUserMessage('Query 1')
      store.addAiMessage({ sql: 'SELECT 1' })

      store.resetConversationContext()

      expect(store.messages.length).toBe(0)
    })
  })

  // ============================================
  // EXPORT TESTS
  // ============================================

  describe('Export', () => {
    it('exports conversation', () => {
      store.addUserMessage('Test query')
      store.addAiMessage({ sql: 'SELECT 1' })

      const exported = store.exportConversation()

      expect(Array.isArray(exported)).toBe(true)
      expect(exported.length).toBe(2)
      expect(exported[0].type).toBe(MessageType.USER)
    })

    it('exports a deep copy', () => {
      store.addUserMessage('Test')
      const exported = store.exportConversation()

      // Modify exported data
      exported[0].content.text = 'Modified'

      // Original should be unchanged
      expect(store.messages[0].content.text).toBe('Test')
    })
  })

  // ============================================
  // PERSISTENCE TESTS
  // ============================================

  describe('localStorage Persistence', () => {
    it('saves conversation to localStorage', async () => {
      store.setSessionId('session-123')
      store.addUserMessage('Test query')

      // Wait for watch callbacks to save
      await flushWatchers()

      const stored = localStorage.getItem('queryfyai-conversations')
      expect(stored).toBeTruthy()

      const parsed = JSON.parse(stored)
      expect(parsed.conversations['session-123']).toBeDefined()
      expect(parsed.conversations['session-123'].length).toBe(1)
    })

    it('limits messages per session to MAX (100)', async () => {
      store.setSessionId('session-123')

      // Add 120 messages
      for (let i = 0; i < 120; i++) {
        store.addUserMessage(`Message ${i}`)
      }

      // Wait for watch callbacks to save
      await flushWatchers()

      const stored = JSON.parse(localStorage.getItem('queryfyai-conversations'))
      const sessionMessages = stored.conversations['session-123']

      expect(sessionMessages.length).toBeLessThanOrEqual(100)
    })

    it('cleans up old sessions (keeps last 10)', async () => {
      // Create 12 sessions
      for (let i = 1; i <= 12; i++) {
        store.setSessionId(`session-${i}`)
        store.addUserMessage(`Message in session ${i}`)
        await flushWatchers()
      }

      // Wait for final save
      await flushWatchers()

      const stored = JSON.parse(localStorage.getItem('queryfyai-conversations'))
      const sessionCount = Object.keys(stored.conversations).length

      expect(sessionCount).toBeLessThanOrEqual(10)
    })
  })
})

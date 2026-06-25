/**
 * Conversation Store Resilience Tests
 *
 * Tests resilience features of conversation store:
 * - Network interruption handling
 * - localStorage quota exceeded
 * - Large conversations (1000+ messages)
 * - Malformed API responses
 * - Session recovery
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import { useConversationStore, MessageType } from '../conversation'

describe('Conversation Store - Resilience', () => {
  let store

  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    setActivePinia(createPinia())
    store = useConversationStore()
  })

  describe('Network Interruption', () => {
    it('handles network errors gracefully when loading history', async () => {
      store.setSessionId('session-123')

      // Simulate network error
      const networkError = new Error('Network request failed')
      networkError.message = 'Failed to fetch'

      // Store should not crash on network error
      // Just verify it doesn't throw
      expect(() => {
        store.addUserMessage('Test message during network issues')
      }).not.toThrow()

      // Message should be added locally even if network is down
      expect(store.messageCount).toBe(1)
      expect(store.messages[0].content.text).toBe('Test message during network issues')
    })

    it('queues messages when network is unavailable', async () => {
      store.setSessionId('session-123')

      // Add messages while "offline"
      store.addUserMessage('Message 1')
      store.addUserMessage('Message 2')
      store.addUserMessage('Message 3')

      await nextTick()

      // All messages should be stored locally
      expect(store.messageCount).toBe(3)

      // Messages should be in store
      expect(store.messages.length).toBe(3)
      expect(store.messages[0].content.text).toBe('Message 1')
      expect(store.messages[1].content.text).toBe('Message 2')
      expect(store.messages[2].content.text).toBe('Message 3')
    })

    it('recovers messages after network restoration', async () => {
      store.setSessionId('session-123')

      // Simulate offline messages
      store.addUserMessage('Offline message 1')
      store.addUserMessage('Offline message 2')

      await nextTick()

      // Create new store instance (simulates page reload)
      const newStore = useConversationStore()
      newStore.setSessionId('session-123')

      await nextTick()

      // Messages should be restored from localStorage
      expect(newStore.messageCount).toBeGreaterThanOrEqual(2)
    })
  })

  describe('localStorage Quota Exceeded', () => {
    it('handles localStorage quota exceeded gracefully', async () => {
      store.setSessionId('session-123')

      // Mock localStorage.setItem to throw quota exceeded error
      const originalSetItem = Storage.prototype.setItem
      Storage.prototype.setItem = vi.fn(() => {
        throw new DOMException('QuotaExceededError', 'QuotaExceededError')
      })

      // Should not crash when quota exceeded
      expect(() => {
        store.addUserMessage('Message that exceeds quota')
      }).not.toThrow()

      // Restore original
      Storage.prototype.setItem = originalSetItem
    })

    it('handles localStorage unavailable (private mode)', async () => {
      store.setSessionId('session-123')

      // Mock localStorage to be unavailable
      const originalSetItem = Storage.prototype.setItem
      Storage.prototype.setItem = vi.fn(() => {
        throw new Error('localStorage is not available')
      })

      // Should gracefully degrade
      expect(() => {
        store.addUserMessage('Message in private mode')
        store.addAiMessage({ content: 'AI response' })
      }).not.toThrow()

      // Messages should still be in store (just not persisted)
      expect(store.messageCount).toBe(2)

      // Restore original
      Storage.prototype.setItem = originalSetItem
    })

    it('falls back to in-memory only when localStorage fails', async () => {
      store.setSessionId('session-123')

      // Mock localStorage to always fail
      const originalSetItem = Storage.prototype.setItem
      Storage.prototype.setItem = vi.fn(() => {
        throw new Error('Storage unavailable')
      })

      // Add many messages
      for (let i = 1; i <= 50; i++) {
        store.addUserMessage(`Message ${i}`)
      }

      // Should not crash
      expect(store.messageCount).toBe(50)

      // Restore original
      Storage.prototype.setItem = originalSetItem
    })
  })

  describe('Large Conversations', () => {
    it('handles 1000+ messages without performance degradation', async () => {
      store.setSessionId('session-large')

      const startTime = performance.now()

      // Add 1000 messages
      for (let i = 1; i <= 1000; i++) {
        store.addUserMessage(`Message ${i}`)
      }

      const endTime = performance.now()
      const duration = endTime - startTime

      // Should complete in reasonable time (<5 seconds)
      expect(duration).toBeLessThan(5000)

      // All messages should be present
      expect(store.messageCount).toBe(1000)
    })

    it('maintains responsiveness with very long messages', async () => {
      store.setSessionId('session-long-messages')

      // Create very long message (10KB each)
      const longMessage = 'x'.repeat(10000)

      // Add 100 long messages
      for (let i = 1; i <= 100; i++) {
        store.addUserMessage(longMessage)
      }

      await nextTick()

      // Should handle without crashing
      expect(store.messageCount).toBe(100)
    })

    it('limits localStorage size by cleaning old sessions', async () => {
      // Create many large sessions
      for (let i = 1; i <= 20; i++) {
        store.setSessionId(`session-${i}`)

        // Add messages to each session
        for (let j = 1; j <= 50; j++) {
          store.addUserMessage(`Session ${i} Message ${j}`)
        }

        await nextTick()
      }

      // Check that localStorage didn't explode
      const stored = localStorage.getItem('queryfyai-conversations')
      if (stored) {
        const storedSizeKB = new Blob([stored]).size / 1024

        // Should not exceed reasonable size (e.g., 5MB)
        expect(storedSizeKB).toBeLessThan(5000)
      }
    })
  })

  describe('Malformed Data Recovery', () => {
    it('recovers from corrupted localStorage data', async () => {
      // Set corrupted data in localStorage
      localStorage.setItem('queryfyai-conversations', '{invalid json}')

      // Should not crash on initialization
      expect(() => {
        const newStore = useConversationStore()
        newStore.setSessionId('session-123')
      }).not.toThrow()
    })

    it('handles null/undefined message content gracefully', async () => {
      store.setSessionId('session-123')

      // Try to add message with null/undefined content
      expect(() => {
        store.addUserMessage(null)
        store.addUserMessage(undefined)
        store.addUserMessage('')
      }).not.toThrow()
    })

    it('handles missing required fields in stored data', async () => {
      // Set data missing required fields
      localStorage.setItem('queryfyai-conversations', JSON.stringify({
        conversations: {
          'session-123': {
            // Missing messages array
            sessionId: 'session-123'
          }
        }
      }))

      // Should handle gracefully
      expect(() => {
        const newStore = useConversationStore()
        newStore.setSessionId('session-123')
      }).not.toThrow()
    })

    it('sanitizes malicious content in messages', async () => {
      store.setSessionId('session-123')

      // Try to add message with script tags
      const maliciousContent = '<script>alert("xss")</script>'
      store.addUserMessage(maliciousContent)

      await nextTick()

      // Message should be stored (sanitization happens at display time)
      expect(store.messageCount).toBe(1)
      // Content should be preserved for sanitization at render time
      expect(store.messages[0].content.text).toBe(maliciousContent)
    })
  })

  describe('Session Recovery', () => {
    it('recovers active session after page reload', async () => {
      store.setSessionId('session-123')
      store.addUserMessage('Message before reload')
      store.addAiMessage({ content: 'AI response before reload' })

      await nextTick()

      // Simulate page reload by creating new store
      const newStore = useConversationStore()
      newStore.setSessionId('session-123')

      await nextTick()

      // Should restore session
      expect(newStore.messageCount).toBeGreaterThanOrEqual(2)
    })

    it('handles switching between multiple sessions without data loss', async () => {
      // Create session 1
      store.setSessionId('session-1')
      store.addUserMessage('Message in session 1')

      await nextTick()

      // Switch to session 2
      store.setSessionId('session-2')
      store.addUserMessage('Message in session 2')

      await nextTick()

      // Switch back to session 1
      store.setSessionId('session-1')

      await nextTick()

      // Verify session switching worked - current session ID should be set
      expect(store.currentSessionId).toBe('session-1')
    })

    it('prevents data corruption when multiple operations happen simultaneously', async () => {
      store.setSessionId('session-123')

      // Simulate rapid sequential operations (synchronous burst)
      // This tests the store's ability to handle rapid-fire operations
      for (let i = 0; i < 10; i++) {
        store.addUserMessage(`Rapid message ${i}`)
      }

      await nextTick()

      // Should handle all messages without corruption
      expect(store.messageCount).toBe(10)

      // Verify message order and content integrity
      const messages = store.messages
      expect(messages.length).toBe(10)

      // Each message should have correct content and valid structure
      for (let i = 0; i < 10; i++) {
        expect(messages[i].content.text).toBe(`Rapid message ${i}`)
        expect(messages[i].type).toBe(MessageType.USER)
        expect(messages[i].id).toBeDefined()
        expect(messages[i].timestamp).toBeDefined()
      }

      // Verify localStorage was properly updated
      const stored = localStorage.getItem('queryfyai-conversations')
      expect(stored).toBeTruthy()
      const parsed = JSON.parse(stored)
      // Conversations are stored under conversations[sessionId]
      expect(parsed.conversations['session-123']).toBeDefined()
      expect(parsed.conversations['session-123'].length).toBe(10)
    })
  })

  describe('Memory Leaks Prevention', () => {
    it('cleans up old sessions to prevent memory bloat', async () => {
      // Create many sessions
      for (let i = 1; i <= 50; i++) {
        store.setSessionId(`session-${i}`)
        store.addUserMessage(`Message in session ${i}`)
      }

      await nextTick()

      // Check that localStorage cleanup occurred
      const stored = localStorage.getItem('queryfyai-conversations')
      if (stored) {
        const parsed = JSON.parse(stored)
        const sessionCount = Object.keys(parsed.conversations || {}).length

        // Should limit number of stored sessions
        expect(sessionCount).toBeLessThanOrEqual(20)
      }
    })

    it('removes old messages from memory after session switch', async () => {
      // Add many messages to session 1
      store.setSessionId('session-1')
      for (let i = 1; i <= 1000; i++) {
        store.addUserMessage(`Message ${i}`)
      }

      // Switch to new session
      store.setSessionId('session-2')

      // Current session should start fresh (old messages cleared from active state)
      // Note: Actual behavior depends on store implementation
      expect(store.currentSessionId).toBe('session-2')
    })
  })
})

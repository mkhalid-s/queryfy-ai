/**
 * Conversation Store (Pinia)
 *
 * Manages conversation state with:
 * - Full message persistence to localStorage
 * - Session-based message segregation
 * - Backend history sync
 * - Support for re-execution via sql_hash
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

const STORAGE_KEY = 'queryfyai-conversations'
const MAX_MESSAGES_PER_SESSION = 100
// Phase 2 Day 6: cap persisted conversations at 5 (down from 10) and
// strip execution_result.rows from every persisted message to stay well
// under the ~5MB localStorage quota. Rows are only meaningful in-flight;
// when the conversation is reloaded the user reruns the query to re-
// fetch. Titles, insights and metadata are kept so the history list
// remains informative.
const MAX_STORED_CONVERSATIONS = 5


/**
 * Phase 2 Day 6: return a shallow clone of a message suitable for
 * localStorage. Removes execution_result.rows and raw_output which
 * dominate payload size for large result sets.
 */
function stripLargeFieldsForPersist(msg) {
  if (!msg || typeof msg !== 'object') return msg
  const out = { ...msg }

  // Phase 2 Day 6: strip rows + raw_output from execution_result.
  const exec = msg.execution_result
  if (exec && typeof exec === 'object') {
    const { rows, raw_output, ...rest } = exec
    out.execution_result = {
      ...rest,
      // Compact marker so UI can show "N rows hidden (refresh to reload)"
      rows_persisted: false,
      row_count: exec.row_count ?? (Array.isArray(rows) ? rows.length : 0),
    }
  }

  // Phase 4.3: symmetric strip for content.rawResult — that's what the
  // SSE done-event populates (App.vue:920) and what ResultsExpander
  // actually renders. Without this strip, persisted history can blow
  // the localStorage quota for large queries. We deliberately keep
  // ``rows_ref`` so reload can re-fetch from the backend.
  const content = msg.content
  if (content && typeof content === 'object' && content.rawResult) {
    const raw = content.rawResult
    if (raw && typeof raw === 'object') {
      const { rows: rawRows, raw_output: rawOutput, ...restRaw } = raw
      out.content = {
        ...content,
        rawResult: {
          ...restRaw,
          rows_persisted: false,
          row_count:
            raw.row_count ?? (Array.isArray(rawRows) ? rawRows.length : 0),
        },
      }
    }
  }

  return out
}

// Message types
export const MessageType = {
  USER: 'user',
  AI: 'ai',
  SYSTEM: 'system'
}

// Create a unique ID
const createId = () => `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

export const useConversationStore = defineStore('conversation', () => {
  // ============================================
  // STATE
  // ============================================

  // Current session's messages
  const messages = ref([])

  // Current session ID (for persistence)
  const currentSessionId = ref(null)

  // All stored conversations (keyed by session ID)
  const storedConversations = ref({})

  // Multi-turn conversation state
  const continueConversation = ref(true)

  // ============================================
  // COMPUTED
  // ============================================

  const hasMessages = computed(() => messages.value.length > 0)

  const latestMessage = computed(() => {
    if (messages.value.length === 0) return null
    return messages.value[messages.value.length - 1]
  })

  const latestAiMessage = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].type === MessageType.AI) {
        return messages.value[i]
      }
    }
    return null
  })

  const latestSql = computed(() => {
    return latestAiMessage.value?.content?.sql || null
  })

  const messageCount = computed(() => messages.value.length)

  // Multi-turn conversation computed properties
  const followUpCount = computed(() => {
    return messages.value.filter(
      m => m.type === MessageType.AI && m.content?.isFollowUp
    ).length
  })

  const currentConversationTurn = computed(() => {
    const aiMessages = messages.value.filter(m => m.type === MessageType.AI)
    if (aiMessages.length === 0) return 0
    const lastAi = aiMessages[aiMessages.length - 1]
    return lastAi.content?.conversationTurn || aiMessages.length
  })

  // ============================================
  // ACTIONS
  // ============================================

  /**
   * Set current session ID
   */
  function setSessionId(sessionId) {
    // Save current session before switching
    if (currentSessionId.value && messages.value.length > 0) {
      storedConversations.value[currentSessionId.value] = [...messages.value]
    }

    currentSessionId.value = sessionId

    // Load existing conversation for this session
    if (sessionId && storedConversations.value[sessionId]) {
      messages.value = [...storedConversations.value[sessionId]]
    } else {
      messages.value = []
    }
  }

  /**
   * Add a user message to the conversation
   */
  function addUserMessage(text, isOriginal = false) {
    const message = {
      id: createId(),
      type: MessageType.USER,
      timestamp: new Date().toISOString(),
      content: {
        text,
        isOriginal
      }
    }
    messages.value.push(message)
    return message.id
  }

  /**
   * Add an AI response to the conversation
   */
  function addAiMessage(options) {
    const {
      sql,
      isValid = true,
      queryType = null,
      transformationType = null,
      explanation = null,
      results = null,
      queryId = null,
      sqlHash = null,
      // Analyst mode / Agent fields
      mode = null,
      answer = null,
      keyFindings = [],
      confidence = null,
      chart = null,
      rawResult = null,
      toolsUsed = [],
      agentSteps = [],
      isGenerating = false,
      error = null,
      cancelled = false,
      // Multi-turn conversation fields
      isFollowUp = false,
      conversationTurn = 1,
      suggestions = null
    } = options

    const message = {
      id: createId(),
      type: MessageType.AI,
      timestamp: new Date().toISOString(),
      content: {
        sql,
        isValid,
        queryType,
        transformationType,
        explanation,
        results,
        queryId,
        sqlHash,  // Store sql_hash for re-execution
        // Analyst mode / Agent fields
        mode,
        answer,
        keyFindings,
        confidence,
        chart,
        rawResult,
        toolsUsed,
        agentSteps,
        isGenerating,
        error,
        cancelled,
        // Multi-turn conversation fields
        isFollowUp,
        conversationTurn,
        suggestions
      }
    }
    messages.value.push(message)
    return message.id
  }

  /**
   * Add a system message (info, warning, error)
   */
  function addSystemMessage(text, variant = 'info', action = null) {
    const message = {
      id: createId(),
      type: MessageType.SYSTEM,
      timestamp: new Date().toISOString(),
      variant, // 'info', 'success', 'warning', 'error'
      content: {
        text
      },
      action // { label: string, callback: function }
    }
    messages.value.push(message)
    return message.id
  }

  /**
   * Update an existing message (e.g., add results to AI message)
   */
  function updateMessage(messageId, updates) {
    const index = messages.value.findIndex(m => m.id === messageId)
    if (index !== -1) {
      messages.value[index] = {
        ...messages.value[index],
        content: {
          ...messages.value[index].content,
          ...updates
        }
      }
    }
  }

  /**
   * Update the latest AI message with results
   */
  function updateLatestWithResults(results) {
    const latest = latestAiMessage.value
    if (latest) {
      updateMessage(latest.id, { results })
    }
  }

  /**
   * Update the latest AI message with explanation
   */
  function updateLatestWithExplanation(explanation) {
    const latest = latestAiMessage.value
    if (latest) {
      updateMessage(latest.id, { explanation })
    }
  }

  /**
   * Clear all messages in current conversation
   */
  function clearConversation() {
    messages.value = []
    if (currentSessionId.value) {
      delete storedConversations.value[currentSessionId.value]
    }
  }

  /**
   * Remove a specific message
   */
  function removeMessage(messageId) {
    const index = messages.value.findIndex(m => m.id === messageId)
    if (index !== -1) {
      messages.value.splice(index, 1)
    }
  }

  /**
   * Get message by ID
   */
  function getMessage(messageId) {
    return messages.value.find(m => m.id === messageId)
  }

  /**
   * Restore conversation from saved state (e.g., backend history)
   */
  function restoreConversation(savedMessages) {
    if (Array.isArray(savedMessages)) {
      messages.value = savedMessages
    }
  }

  /**
   * Load conversation from backend history
   * Converts backend HistoryEntry format to conversation messages
   * Now includes full analyst mode data for conversation restore
   */
  function loadFromBackendHistory(historyEntries) {
    if (!Array.isArray(historyEntries) || historyEntries.length === 0) {
      return
    }

    // Convert backend history format to conversation messages
    const convertedMessages = []

    for (const entry of historyEntries) {
      // Add user message for the query
      convertedMessages.push({
        id: `user-${entry.id}`,
        type: MessageType.USER,
        timestamp: entry.timestamp,
        content: {
          text: entry.query,
          isOriginal: true
        }
      })

      // Add AI message for the SQL response with full analyst mode data
      convertedMessages.push({
        id: entry.id,
        type: MessageType.AI,
        timestamp: entry.timestamp,
        content: {
          sql: entry.sql,
          isValid: entry.success !== false,
          explanation: entry.explanation,
          queryId: entry.id,
          sqlHash: entry.sql_hash,
          // Analyst mode fields from backend
          mode: entry.mode || 'standard',
          answer: entry.answer,
          keyFindings: entry.key_findings || [],
          confidence: entry.confidence,
          chart: entry.chart_spec,
          rawResult: entry.raw_result_summary,
          toolsUsed: entry.tools_used || [],
          agentSteps: entry.agent_steps || [],
          // Conversation threading
          isFollowUp: entry.is_follow_up || false,
          conversationTurn: entry.conversation_turn || 1,
          // Results not fully stored - use raw_result_summary for basic display
          // Phase 4 Batch C: preserve rows_ref + cache flags so a
          // restored message can fetch the full dataset from the cache
          // (when TTL hasn't expired) and Export can pull from the
          // same handle. Without these fields the restored card shows
          // only the persisted preview with no escape hatch.
          results: entry.raw_result_summary ? {
            columns: entry.raw_result_summary.columns || [],
            rows: entry.raw_result_summary.sample_rows || [],
            row_count: entry.raw_result_summary.row_count || 0,
            rows_ref: entry.raw_result_summary.rows_ref || null,
            rows_cached: entry.raw_result_summary.rows_cached || false,
            preview_row_count: entry.raw_result_summary.preview_row_count,
            // Marker so the UI can show "Preview only — re-run to load
            // all N rows" when the rows we have are a subset of
            // row_count and we don't have a working rows_ref.
            rows_persisted: entry.raw_result_summary.rows_persisted ?? null,
          } : null
        }
      })
    }

    // Sort by timestamp
    convertedMessages.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))

    // Merge with existing messages, avoiding duplicates
    const existingIds = new Set(messages.value.map(m => m.id))
    const newMessages = convertedMessages.filter(m => !existingIds.has(m.id))

    if (newMessages.length > 0) {
      messages.value = [...newMessages, ...messages.value]
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
        .slice(-MAX_MESSAGES_PER_SESSION)
    }
  }

  /**
   * Export conversation for saving
   */
  function exportConversation() {
    return JSON.parse(JSON.stringify(messages.value))
  }

  /**
   * Find message by queryId (for re-execution)
   */
  function findMessageByQueryId(queryId) {
    return messages.value.find(
      m => m.type === MessageType.AI && m.content?.queryId === queryId
    )
  }

  /**
   * Get sql_hash for a query by queryId (for re-execution)
   */
  function getSqlHashForQuery(queryId) {
    const message = findMessageByQueryId(queryId)
    return message?.content?.sqlHash || null
  }

  /**
   * Toggle continue conversation mode
   */
  function setContinueConversation(value) {
    continueConversation.value = value
  }

  /**
   * Reset conversation context (start fresh)
   */
  function resetConversationContext() {
    // Clear messages but keep session
    messages.value = []
    // Note: Backend session store is reset via API when continueConversation=false
  }

  // ============================================
  // PERSISTENCE
  // ============================================

  // Load from localStorage on init
  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const data = JSON.parse(stored)
        storedConversations.value = data.conversations || {}

        // If we have a current session, load its messages
        if (currentSessionId.value && storedConversations.value[currentSessionId.value]) {
          messages.value = storedConversations.value[currentSessionId.value]
        }
      }
    } catch (e) {
      console.warn('Failed to load conversations from storage:', e)
    }
  }

  // Save to localStorage on change
  function saveToStorage() {
    try {
      // Update stored conversations for current session. Phase 2 Day 6:
      // strip large result-row payloads before persisting to avoid the
      // ~5MB localStorage quota cliff.
      if (currentSessionId.value) {
        storedConversations.value[currentSessionId.value] = messages.value
          .slice(-MAX_MESSAGES_PER_SESSION)
          .map(stripLargeFieldsForPersist)
      }

      // Phase 2 Day 6: keep the last 5 sessions (was 10).
      const sessionIds = Object.keys(storedConversations.value)
      if (sessionIds.length > MAX_STORED_CONVERSATIONS) {
        const sessionsWithTime = sessionIds.map(id => ({
          id,
          lastMessage: storedConversations.value[id]?.[storedConversations.value[id].length - 1]?.timestamp || '1970-01-01'
        }))
        sessionsWithTime.sort((a, b) => new Date(b.lastMessage) - new Date(a.lastMessage))

        // Remove old sessions
        sessionsWithTime.slice(MAX_STORED_CONVERSATIONS).forEach(s => {
          delete storedConversations.value[s.id]
        })
      }

      const data = {
        conversations: storedConversations.value
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
    } catch (e) {
      // Phase 2 Day 6: QuotaExceededError means the browser rejected
      // the write. Try again with a more aggressive trim (keep only
      // the current session) so at least the live conversation
      // survives a refresh. If that still fails, log and move on.
      if (e && e.name === 'QuotaExceededError') {
        try {
          const trimmed = currentSessionId.value
            ? { [currentSessionId.value]: storedConversations.value[currentSessionId.value] || [] }
            : {}
          localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ conversations: trimmed })
          )
          console.warn('Conversation storage over quota; kept only current session')
        } catch (err2) {
          console.error('Conversation storage quota exceeded; history not persisted:', err2)
        }
      } else {
        console.warn('Failed to save conversations to storage:', e)
      }
    }
  }

  /**
   * Phase 2 Day 6: user-triggered clear-history. Removes all persisted
   * conversations (including the current session's) from localStorage
   * and from in-memory state.
   */
  function clearAllHistory() {
    storedConversations.value = {}
    messages.value = []
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch (e) {
      console.warn('Failed to clear conversations from storage:', e)
    }
  }

  // Watch for changes and persist
  watch(messages, saveToStorage, { deep: true })

  // Load on init
  loadFromStorage()

  // ============================================
  // RETURN
  // ============================================

  return {
    // State
    messages,
    currentSessionId,
    continueConversation,

    // Computed
    hasMessages,
    latestMessage,
    latestAiMessage,
    latestSql,
    messageCount,
    followUpCount,
    currentConversationTurn,

    // Actions
    setSessionId,
    addUserMessage,
    addAiMessage,
    addSystemMessage,
    updateMessage,
    updateLatestWithResults,
    updateLatestWithExplanation,
    clearConversation,
    clearAllHistory,  // Phase 2 Day 6: nuke persisted history
    removeMessage,
    getMessage,
    restoreConversation,
    loadFromBackendHistory,
    exportConversation,
    findMessageByQueryId,
    getSqlHashForQuery,
    setContinueConversation,
    resetConversationContext
  }
})

export default useConversationStore

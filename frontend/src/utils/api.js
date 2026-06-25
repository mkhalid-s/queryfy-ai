// ============================================
// FILE: frontend/src/utils/api.js
// ============================================
import axios from 'axios'
import { categorizeError } from './errorCategories'

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1'

// Timeout configuration (milliseconds)
const DEFAULT_TIMEOUT = parseInt(import.meta.env.VITE_REQUEST_TIMEOUT) || 120000  // 2 min
const ANALYST_TIMEOUT = parseInt(import.meta.env.VITE_ANALYST_TIMEOUT) || 180000  // 3 min
const TIMEOUT_BUFFER = 5000  // 5s buffer to avoid racing with backend

// Retry configuration
const MAX_RETRIES = 3
const RETRY_DELAY = 1000  // 1 second base
const BACKOFF_MULTIPLIER = 2
const MAX_RETRY_DELAY = 10000  // 10 seconds cap

const client = axios.create({
  baseURL: API_BASE,
  timeout: DEFAULT_TIMEOUT,
  headers: { 'Content-Type': 'application/json' }
})

// SECURITY: CSRF token management
let csrfToken = null

const setCsrfToken = (token) => {
  csrfToken = token
}

const getCsrfToken = () => csrfToken

// Add CSRF token to requests
client.interceptors.request.use((config) => {
  if (csrfToken && ['post', 'put', 'delete', 'patch'].includes(config.method)) {
    config.headers['X-CSRF-Token'] = csrfToken
  }
  return config
})

// ============================================
// RESPONSE INTERCEPTOR: Centralized Error Handling
// ============================================
client.interceptors.response.use(
  // Success: pass through
  (response) => response,

  // Error: centralized handling with retry logic
  async (error) => {
    const config = error.config
    const status = error.response?.status
    const url = config?.url

    // Initialize retry count
    config._retryCount = config._retryCount || 0

    // Check if error is retryable
    const shouldRetry = (
      // Network errors (no response received)
      (!error.response) ||
      // Retryable HTTP status codes
      [408, 502, 503, 504].includes(status)
    )

    // Retry if applicable and under max retries
    if (shouldRetry && config._retryCount < MAX_RETRIES) {
      config._retryCount++

      // Calculate exponential backoff with jitter
      const baseDelay = RETRY_DELAY * Math.pow(BACKOFF_MULTIPLIER, config._retryCount - 1)
      const cappedDelay = Math.min(baseDelay, MAX_RETRY_DELAY)
      const jitter = cappedDelay * 0.1 * (Math.random() * 2 - 1)
      const finalDelay = cappedDelay + jitter

      if (import.meta.env.DEV) {
        console.warn(
          `Retrying request (${config._retryCount}/${MAX_RETRIES}) after ${Math.round(finalDelay)}ms`,
          url
        )
      }

      // Wait and retry
      await new Promise(resolve => setTimeout(resolve, finalDelay))
      return client(config)
    }

    // Not retryable or max retries exceeded - categorize and handle error
    const errorInfo = categorizeError(error)

    // Attach categorized info to error object
    error.category = errorInfo.category
    error.userMessage = errorInfo.userMessage
    error.actionable = errorInfo.actionable

    // Add retry information to message if retries were attempted
    if (config._retryCount > 0) {
      error.userMessage += ` (after ${config._retryCount} ${config._retryCount === 1 ? 'retry' : 'retries'})`
    }

    // Handle session expiration (401)
    if (status === 401) {
      import('../stores/session.js').then(({ useSessionStore }) => {
        const sessionStore = useSessionStore()
        sessionStore.emitSessionExpired()
      })
    }

    // Log in development with categorization
    if (import.meta.env.DEV) {
      console.error('[API Error]', {
        category: error.category,
        status,
        message: error.userMessage,
        retries: config._retryCount,
        url
      })
    }

    // Re-throw for component-level handling
    return Promise.reject(error)
  }
)

export default {
  // CSRF token methods
  setCsrfToken,
  getCsrfToken,

  // Health check (mounted at root, not under /api/v1)
  async healthCheck() {
    const { data } = await axios.get('/health', { timeout: DEFAULT_TIMEOUT })
    return data
  },

  // Frontend configuration (mounted at root, not under /api/v1)
  async getFrontendConfig() {
    const { data } = await axios.get('/config/frontend', { timeout: DEFAULT_TIMEOUT })
    return data
  },

  // Sessions
  async createSession(llmConfig, dbConfig) {
    const { data } = await client.post('/sessions', { llm_config: llmConfig, db_config: dbConfig })
    return data
  },
  
  async getSession(sessionId) {
    const { data } = await client.get(`/sessions/${sessionId}`)
    return data
  },
  
  async deleteSession(sessionId) {
    await client.delete(`/sessions/${sessionId}`)
  },

  // Schema
  async refreshSchema(sessionId) {
    const { data } = await client.post(`/schema/refresh?session_id=${sessionId}`)
    return data
  },
  
  async getSchema(sessionId) {
    const { data } = await client.get(`/schema/${sessionId}`)
    return data
  },
  
  // Queries
  // Note: generateSQL() and generateSQLStream() have been removed.
  // Use chatStream() or chat() instead.

  // ============================================
  // Unified Chat Endpoint
  // ============================================

  /**
   * Send a chat message for SQL generation or analysis.
   * @param {string} sessionId - Session ID
   * @param {string} message - Natural language query
   * @param {Object} options - Chat options
   * @param {string} [options.mode='standard'] - 'standard' (SQL only) or 'analyst' (insights + SQL)
   * @param {boolean} [options.stream=false] - Stream response via SSE
   * @param {boolean} [options.includeReasoning=false] - Include reasoning trace (analyst mode)
   * @param {boolean} [options.includeChart=true] - Auto-generate charts (analyst mode)
   * @param {boolean} [options.continueConversation=true] - Continue from previous conversation context
   * @returns {Object} ChatResponse with is_follow_up and conversation_turn metadata
   */
  async chat(sessionId, message, { mode = 'standard', stream = false, includeReasoning = false, includeChart = true, continueConversation = true } = {}) {
    const { data } = await client.post('/chat', {
      session_id: sessionId,
      message,
      mode,
      stream,
      include_reasoning: includeReasoning,
      include_chart: includeChart,
      continue_conversation: continueConversation
    })
    return data
  },

  /**
   * Stream chat response via Server-Sent Events.
   * @param {string} sessionId - Session ID
   * @param {string} message - Natural language query
   * @param {Object} options - Chat options
   * @param {string} [options.mode='standard'] - 'standard' or 'analyst'
   * @param {boolean} [options.includeReasoning=false] - Include reasoning (analyst mode)
   * @param {boolean} [options.includeChart=true] - Auto-generate charts (analyst mode)
   * @param {boolean} [options.continueConversation=true] - Continue from previous conversation context
   * @param {AbortSignal} [options.signal] - AbortSignal for cancellation
   * @param {Function} onEvent - Callback for each SSE event { event, content, data, progress, tool_name }
   * @returns {Promise<Object>} Final response data from 'done' event with is_follow_up and conversation_turn
   */
  async chatStream(sessionId, message, { mode = 'standard', includeReasoning = false, includeChart = true, continueConversation = true, signal } = {}, onEvent) {
    // Day 4 fix: auto-reconnect on stream-level disconnects (heartbeat
    // timeout, premature end, transient network errors). Backend-reported
    // errors (event.error) are NOT retried — they are real failures.
    //
    // Retry policy: up to 3 additional attempts, exponential backoff
    // (1s, 2s, 4s). A synthetic 'reconnecting' event is emitted to the
    // callback so the UI can show appropriate feedback.
    //
    // Known limitation: a retried request starts the backend flow from
    // scratch — any work the previous attempt triggered may run twice
    // (LLM calls, SQL execution). This is acceptable for transient
    // network issues; true session resumption is Phase 3 work.
    const SSE_MAX_RECONNECTS = 3
    const SSE_BACKOFF_MS = [1000, 2000, 4000]

    // One-shot stream attempt. Extracted so the retry wrapper below can
    // simply call this in a loop. Closes over the outer function args.
    const runOnce = async () => {
      const baseTimeout = mode === 'analyst' ? ANALYST_TIMEOUT : DEFAULT_TIMEOUT
      const timeout = baseTimeout + TIMEOUT_BUFFER

      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), timeout)

      // Link external signal to internal controller for cancellation.
      // Registered per-attempt so external aborts still work after a retry.
      const abortHandler = () => controller.abort()
      if (signal) signal.addEventListener('abort', abortHandler)

      try {
        const response = await fetch(`${API_BASE}/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(csrfToken && { 'X-CSRF-Token': csrfToken })
          },
          body: JSON.stringify({
            session_id: sessionId,
            message,
            mode,
            stream: true,
            include_reasoning: includeReasoning,
            include_chart: includeChart,
            continue_conversation: continueConversation
          }),
          signal: controller.signal
        })

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}))
          // HTTP errors are not retry-worthy — they indicate a real problem
          // (auth failure, bad request, server error). Don't mark as
          // isStreamDisconnect so the retry wrapper rethrows immediately.
          throw new Error(errorData.detail || `HTTP error ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let finalResult = null

        const HEARTBEAT_TIMEOUT = 60000 // 60 seconds

        const readWithTimeout = () => Promise.race([
          reader.read(),
          new Promise((_, reject) =>
            setTimeout(() => reject(Object.assign(
              new Error('Stream heartbeat timeout - no events received for 60 seconds'),
              { isStreamDisconnect: true }
            )), HEARTBEAT_TIMEOUT)
          )
        ])

        try {
          while (true) {
            const { done, value } = await readWithTimeout()
            if (done) break

            buffer += decoder.decode(value, { stream: true })

            // Process complete SSE messages (ending with \n\n)
            const lines = buffer.split('\n\n')
            buffer = lines.pop() || ''

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue

              const jsonStr = line.slice(6).trim()
              if (!jsonStr) continue

              try {
                const event = JSON.parse(jsonStr)

                // Phase 3a Day 2 / Phase 4 Batch D: heartbeat events
                // are backend keepalives every 15s during quiet
                // periods. Forward to onEvent so the consumer can
                // render a "Running 0m 15s..." badge in the thinking
                // indicator. Chat stores that don't recognize the
                // event type can safely ignore it.
                if (event.event === 'heartbeat') {
                  if (onEvent) {
                    onEvent(event)
                  }
                  continue
                }

                // Phase 3b.2: query_progress events carry driver-side
                // metrics (bytes_scanned, rows_read, percent, elapsed_ms)
                // during long-running async queries (BigQuery, Snowflake).
                // Forward via onEvent so consumers can render a "Running
                // 2m 15s — 1.2 GB scanned" status badge. Chat stores that
                // don't recognise the event type can safely ignore it.
                if (event.event === 'query_progress') {
                  if (onEvent) {
                    onEvent(event)
                  }
                  continue
                }

                // Call event callback
                if (onEvent) {
                  onEvent(event)
                }

                // Capture final result from 'done' event
                if (event.event === 'done') {
                  finalResult = event.data || { content: event.content }
                }

                // Handle error event (backend-reported, not retry-worthy)
                if (event.event === 'error') {
                  throw new Error(event.error || event.content || 'Stream error')
                }
              } catch (parseError) {
                if (parseError.message !== 'Stream error') {
                  console.error('Failed to parse SSE event:', parseError, jsonStr)
                } else {
                  throw parseError
                }
              }
            }
          }
        } finally {
          reader.releaseLock()
        }

        // Detect premature stream termination (stream ended without 'done' event).
        // Mark as isStreamDisconnect so the retry wrapper can reconnect.
        if (!finalResult) {
          const err = new Error('Stream disconnected before completion. The query may still be running on the server.')
          err.isStreamDisconnect = true
          throw err
        }

        return finalResult
      } catch (error) {
        if (error.name === 'AbortError') {
          // External abort (user cancellation or outer timeout) — do not retry.
          throw new Error('Chat request timed out')
        }
        // Re-classify network-level fetch failures as retry-worthy.
        // (TypeError with 'Failed to fetch' is the Chrome/Firefox signal
        // for a lost connection mid-stream.)
        if (error.name === 'TypeError' && /fetch/i.test(error.message || '')) {
          error.isStreamDisconnect = true
        }
        throw error
      } finally {
        clearTimeout(timeoutId)
        if (signal) signal.removeEventListener('abort', abortHandler)
      }
    }

    // Retry wrapper: only retries when the failure is stream-level.
    let lastError = null
    for (let attempt = 0; attempt <= SSE_MAX_RECONNECTS; attempt++) {
      try {
        if (attempt > 0) {
          const delay = SSE_BACKOFF_MS[attempt - 1] ?? SSE_BACKOFF_MS[SSE_BACKOFF_MS.length - 1]
          if (onEvent) {
            onEvent({
              event: 'reconnecting',
              attempt,
              max_attempts: SSE_MAX_RECONNECTS,
              delay_ms: delay,
              content: `Connection lost — reconnecting (attempt ${attempt}/${SSE_MAX_RECONNECTS})…`,
            })
          }
          await new Promise((resolve) => setTimeout(resolve, delay))
          // If the caller aborted during backoff, bail out immediately.
          if (signal && signal.aborted) {
            throw new Error('Chat request aborted during reconnect')
          }
        }
        return await runOnce()
      } catch (error) {
        lastError = error
        // Retry only transient stream failures; rethrow anything else.
        if (!error.isStreamDisconnect || attempt >= SSE_MAX_RECONNECTS) {
          throw error
        }
        console.warn(
          `[SSE] stream disconnected (${error.message || 'unknown'}); ` +
          `retry ${attempt + 1}/${SSE_MAX_RECONNECTS}`
        )
      }
    }
    // Unreachable under normal control flow, but keeps the type clean.
    throw lastError
  },

  async explainSQL(sessionId, sql) {
    const { data } = await client.post('/query/explain', {
      session_id: sessionId,
      sql_query: sql
    })
    return data
  },

  /**
   * Stream SQL explanation via Server-Sent Events
   * @param {string} sessionId
   * @param {string} sql
   * @param {Function} onChunk - Callback receiving each text chunk
   * @returns {Promise<void>} - Resolves when stream completes
   */
  async explainSQLStream(sessionId, sql, onChunk) {
    const response = await fetch(`${API_BASE}/query/explain`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(csrfToken && { 'X-CSRF-Token': csrfToken })
      },
      body: JSON.stringify({
        session_id: sessionId,
        sql_query: sql,
        stream: true
      })
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(errorData.detail || `HTTP error ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete SSE messages (ending with \n\n)
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || '' // Keep incomplete message in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue

          const data = line.slice(6) // Remove 'data: ' prefix

          if (data === '[DONE]') {
            return // Stream complete
          }

          if (data.startsWith('[ERROR]')) {
            throw new Error(data.slice(8)) // Remove '[ERROR] ' prefix
          }

          // Unescape newlines that were escaped for SSE
          const unescaped = data.replace(/\\n/g, '\n').replace(/\\r/g, '\r')
          onChunk(unescaped)
        }
      }
    } finally {
      reader.releaseLock()
    }
  },
  
  async executeQuery(sessionId, sql, limit = 100, queryId = null, sqlHash = null) {
    const { data } = await client.post('/query/execute', {
      session_id: sessionId,
      sql_query: sql,
      limit,
      query_id: queryId,
      sql_hash: sqlHash
    })
    return data
  },
  
  async exportToExcel(
    sessionId,
    sql,
    limit = 10000,
    queryId = null,
    sqlHash = null,
    rowsRef = null,
  ) {
    // Phase 4.3: pass ``rows_ref`` so the backend can source from the
    // ResultCache (matching exactly what was analysed) instead of
    // re-running the SQL. Falls back to SQL on cache miss / TTL.
    const response = await client.post('/query/export',
      {
        session_id: sessionId,
        sql_query: sql,
        limit,
        query_id: queryId,
        sql_hash: sqlHash,
        rows_ref: rowsRef,
      },
      { responseType: 'blob' }
    )

    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `query_results_${Date.now()}.xlsx`)
    document.body.appendChild(link)
    link.click()
    link.remove()

    // Phase 4.3 Batch B: surface the source so the caller can toast
    // "exported from fresh query (cache expired)" when the cached
    // dataset wasn't available — the user otherwise can't tell that
    // the exported file may not match what the analysis described.
    return {
      source: response.headers?.['x-export-source'] || 'sql',
    }
  },

  /**
   * Phase 4.3: paginated fetch of a cached query result.
   *
   * The backend's ``/api/v1/results/{rows_ref}`` endpoint pages the
   * cached rows so the UI never needs the full set in the SSE payload.
   * Returns ``{rows, columns, total_row_count, has_more, offset, limit}``.
   * Throws on 404 (cache expired); the caller can fall back to
   * re-running the SQL via ``/query/execute``.
   */
  async getCachedResult(rowsRef, { offset = 0, limit = 1000 } = {}) {
    const { data } = await client.get(
      `/results/${encodeURIComponent(rowsRef)}`,
      { params: { offset, limit } },
    )
    return data
  },
  
  // History & Feedback
  async getHistory(sessionId) {
    const { data } = await client.get(`/history/${sessionId}`)
    return data
  },
  
  async submitFeedback(sessionId, queryId, rating, comment = '') {
    const { data } = await client.post('/feedback', {
      session_id: sessionId,
      query_id: queryId,
      rating,
      comment
    })
    return data
  },
  
  // Test connections
  async testDBConnection(config) {
    const { data } = await client.post('/test-connection', config)
    return data
  },
  
  async testLLMConnection(config) {
    const { data } = await client.post('/test-llm', config)
    return data
  },
  
  // DB Types
  async getDBTypes() {
    const { data } = await client.get('/db-types')
    return data
  },

  // LLM Providers
  async getLLMProviders() {
    const { data } = await client.get('/llm-providers')
    return data
  },

  // Default Configuration
  async getDefaultConfig() {
    const { data } = await client.get('/config/defaults')
    return data
  },

  // ============================================
  // Consolidated Endpoints (reduced API calls)
  // ============================================

  /**
   * Initialize app with all necessary data in one call.
   * Combines: GET /config/defaults + GET /sessions/{id} + GET /history/{id}
   * @param {string|null} previousSessionId - Optional session ID to restore
   * @returns {Object} { has_defaults, llm_config, db_config, session, history, csrf_token, token_info }
   */
  async initialize(previousSessionId = null) {
    const { data } = await client.post('/init', {
      previous_session_id: previousSessionId
    })
    // Auto-set CSRF token if returned
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token)
    }
    return data
  },

  /**
   * Generate SQL with extended response including history and optional auto-execute.
   * Combines: POST /query/generate + GET /history/{id} + optional POST /query/execute
   * @param {string} sessionId
   * @param {string} naturalLanguage
   * @param {boolean} autoExecute - If true, also executes the generated SQL
   * @param {number} executeLimit - Row limit for auto-execution
   * @returns {Object} { sql, query_id, sql_hash, history, executed, execution_result, ... }
   */
  async generateSQLExtended(sessionId, naturalLanguage, autoExecute = false, executeLimit = 100) {
    const { data } = await client.post('/query/generate-extended', {
      session_id: sessionId,
      natural_language: naturalLanguage,
      auto_execute: autoExecute,
      execute_limit: executeLimit
    })
    return data
  },

  /**
   * Execute multiple query actions in one request.
   * Combines: POST /query/explain + POST /feedback
   * @param {string} sessionId
   * @param {string} sqlQuery
   * @param {Array} actions - Array of {type: 'explain'|'feedback', params: {...}}
   * @param {string|null} queryId
   * @param {string|null} sqlHash
   * @returns {Object} { results: [{type, success, data, error}, ...] }
   */
  async batchActions(sessionId, sqlQuery, actions, queryId = null, sqlHash = null) {
    const { data } = await client.post('/query/actions', {
      session_id: sessionId,
      sql_query: sqlQuery,
      actions,
      query_id: queryId,
      sql_hash: sqlHash
    })
    return data
  },

  /**
   * Restore session with all necessary data in one call.
   * Alternative to using initialize() with previousSessionId.
   * @param {string} sessionId
   * @returns {Object} { session, history, csrf_token, token_info }
   */
  async restoreSession(sessionId) {
    const { data } = await client.post(`/sessions/${sessionId}/restore`)
    // Auto-set CSRF token if returned
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token)
    }
    return data
  },

  // ============================================
  // Data Dictionary API
  // ============================================

  // --- Business Terms ---

  /**
   * Create a new business term
   * @param {string} sessionId
   * @param {Object} term - { term, definition, sql_expression, scope_type?, synonyms?, examples?, category? }
   */
  async createBusinessTerm(sessionId, term) {
    const { data } = await client.post(`/data-dictionary/terms?session_id=${sessionId}`, term)
    return data
  },

  /**
   * List business terms with filtering
   * @param {string} sessionId
   * @param {Object} params - { scope_type?, category?, include_global?, search?, limit?, offset? }
   */
  async listBusinessTerms(sessionId, params = {}) {
    const { data } = await client.get('/data-dictionary/terms', {
      params: { session_id: sessionId, ...params }
    })
    return data
  },

  /**
   * Get a business term by ID
   */
  async getBusinessTerm(termId) {
    const { data } = await client.get(`/data-dictionary/terms/${termId}`)
    return data
  },

  /**
   * Update a business term
   * @param {string} termId
   * @param {Object} updates - { term?, definition?, sql_expression?, synonyms?, examples?, category?, is_active? }
   */
  async updateBusinessTerm(termId, updates) {
    const { data } = await client.put(`/data-dictionary/terms/${termId}`, updates)
    return data
  },

  /**
   * Delete a business term
   * @param {string} termId
   * @param {boolean} hardDelete - If true, permanently deletes the term
   */
  async deleteBusinessTerm(termId, hardDelete = false) {
    const { data } = await client.delete(`/data-dictionary/terms/${termId}`, {
      params: { hard_delete: hardDelete }
    })
    return data
  },

  /**
   * Search for relevant business terms for a query
   * @param {string} sessionId
   * @param {string} query - Natural language query
   * @param {number} limit
   */
  async searchRelevantTerms(sessionId, query, limit = 5) {
    const { data } = await client.get('/data-dictionary/terms/search/relevant', {
      params: { session_id: sessionId, query, limit }
    })
    return data
  },

  // --- Query Patterns ---

  /**
   * Create a new query pattern
   * @param {string} sessionId
   * @param {Object} pattern - { natural_query, sql, description?, tags?, complexity?, is_curated? }
   */
  async createQueryPattern(sessionId, pattern) {
    const { data } = await client.post(`/data-dictionary/patterns?session_id=${sessionId}`, pattern)
    return data
  },

  /**
   * List query patterns with filtering
   * @param {string} sessionId
   * @param {Object} params - { is_curated?, complexity?, min_rating?, search?, limit?, offset? }
   */
  async listQueryPatterns(sessionId, params = {}) {
    const { data } = await client.get('/data-dictionary/patterns', {
      params: { session_id: sessionId, ...params }
    })
    return data
  },

  /**
   * Get a query pattern by ID
   */
  async getQueryPattern(patternId) {
    const { data } = await client.get(`/data-dictionary/patterns/${patternId}`)
    return data
  },

  /**
   * Update a query pattern
   */
  async updateQueryPattern(patternId, updates) {
    const { data } = await client.put(`/data-dictionary/patterns/${patternId}`, updates)
    return data
  },

  /**
   * Delete a query pattern
   */
  async deleteQueryPattern(patternId, hardDelete = false) {
    const { data } = await client.delete(`/data-dictionary/patterns/${patternId}`, {
      params: { hard_delete: hardDelete }
    })
    return data
  },

  /**
   * Rate a query pattern
   * @param {string} patternId
   * @param {number} rating - -1 to 5
   */
  async rateQueryPattern(patternId, rating) {
    const { data } = await client.post(`/data-dictionary/patterns/${patternId}/rate`, null, {
      params: { rating }
    })
    return data
  },

  /**
   * Search for similar query patterns (few-shot learning)
   */
  async searchSimilarPatterns(sessionId, query, limit = 3) {
    const { data } = await client.get('/data-dictionary/patterns/search/similar', {
      params: { session_id: sessionId, query, limit }
    })
    return data
  },

  // --- Column Descriptions ---

  /**
   * Create a column description
   * @param {string} sessionId
   * @param {Object} column - { table_name, column_name, description, schema_name?, business_name?, ... }
   */
  async createColumnDescription(sessionId, column) {
    const { data } = await client.post(`/data-dictionary/columns?session_id=${sessionId}`, column)
    return data
  },

  /**
   * List column descriptions
   * @param {string} sessionId
   * @param {Object} params - { table_name?, schema_name?, search?, limit?, offset? }
   */
  async listColumnDescriptions(sessionId, params = {}) {
    const { data } = await client.get('/data-dictionary/columns', {
      params: { session_id: sessionId, ...params }
    })
    return data
  },

  /**
   * Get a column description by ID
   */
  async getColumnDescription(columnId) {
    const { data } = await client.get(`/data-dictionary/columns/${columnId}`)
    return data
  },

  /**
   * Update a column description
   */
  async updateColumnDescription(columnId, updates) {
    const { data } = await client.put(`/data-dictionary/columns/${columnId}`, updates)
    return data
  },

  /**
   * Delete a column description
   */
  async deleteColumnDescription(columnId, hardDelete = false) {
    const { data } = await client.delete(`/data-dictionary/columns/${columnId}`, {
      params: { hard_delete: hardDelete }
    })
    return data
  },

  // --- Enhanced Schema ---

  /**
   * Get schema with merged data dictionary descriptions
   * @param {string} sessionId
   * @returns {Object} { db_type, tables: [{ name, columns: [{ name, type, description, ... }] }], connection_hash }
   */
  async getEnhancedSchema(sessionId) {
    const { data } = await client.get(`/data-dictionary/schema/enhanced/${sessionId}`)
    return data
  },

  // --- Bulk Import ---

  /**
   * Import business terms from file
   * @param {string} sessionId
   * @param {File} file - CSV or JSON file
   */
  async importBusinessTerms(sessionId, file) {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await client.post(`/data-dictionary/import/terms?session_id=${sessionId}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return data
  },

  /**
   * Import column descriptions from file
   * @param {string} sessionId
   * @param {File} file - CSV or JSON file
   */
  async importColumnDescriptions(sessionId, file) {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await client.post(`/data-dictionary/import/columns?session_id=${sessionId}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return data
  },

  /**
   * Get import history
   * @param {string} sessionId
   * @param {number} limit
   */
  async getImportHistory(sessionId, limit = 20) {
    const { data } = await client.get('/data-dictionary/import/history', {
      params: { session_id: sessionId, limit }
    })
    return data
  },

  // --- Export ---

  /**
   * Export business terms
   * @param {string} sessionId
   * @param {string} format - 'json' or 'csv'
   */
  async exportBusinessTerms(sessionId, format = 'json') {
    const { data } = await client.get('/data-dictionary/export/terms', {
      params: { session_id: sessionId, format }
    })
    return data
  },

  /**
   * Export column descriptions
   * @param {string} sessionId
   * @param {string} format - 'json' or 'csv'
   */
  async exportColumnDescriptions(sessionId, format = 'json') {
    const { data } = await client.get('/data-dictionary/export/columns', {
      params: { session_id: sessionId, format }
    })
    return data
  },

  // --- Statistics ---

  /**
   * Get data dictionary statistics
   * @param {string} sessionId
   * @returns {Object} { total_terms, total_patterns, total_columns, curated_patterns }
   */
  async getDataDictionaryStats(sessionId) {
    const { data } = await client.get('/data-dictionary/stats', {
      params: { session_id: sessionId }
    })
    return data
  },

  // ============================================
  // History Management Endpoints
  // ============================================

  /**
   * Search through query history with optional filters
   * @param {string} sessionId - Session ID
   * @param {Object} options - Search options
   * @param {string} [options.searchTerm] - Search term
   * @param {boolean} [options.pinnedOnly] - Only return pinned queries
   * @param {string} [options.connectionId] - Filter by connection hash
   * @param {string} [options.dbType] - Filter by database type
   * @param {number} [options.limit] - Max results (default 50)
   * @param {number} [options.offset] - Offset for pagination
   * @returns {Object} { history: HistoryEntry[] }
   */
  async searchHistory(sessionId, { searchTerm, pinnedOnly = false, connectionId, dbType, limit = 50, offset = 0 } = {}) {
    const params = { session_id: sessionId, pinned_only: pinnedOnly, limit, offset }
    if (searchTerm) params.search_term = searchTerm
    if (connectionId) params.connection_id = connectionId
    if (dbType) params.db_type = dbType
    const { data } = await client.get('/history/search', { params })
    return data
  },

  /**
   * Get all pinned queries for the session
   * @param {string} sessionId - Session ID
   * @param {Object} options - Filter options
   * @param {string} [options.connectionId] - Filter by connection hash
   * @param {string} [options.dbType] - Filter by database type
   * @returns {Object} { history: HistoryEntry[] }
   */
  async getPinnedQueries(sessionId, { connectionId, dbType } = {}) {
    const params = { session_id: sessionId }
    if (connectionId) params.connection_id = connectionId
    if (dbType) params.db_type = dbType
    const { data } = await client.get('/history/pinned', { params })
    return data
  },

  /**
   * Pin or unpin a query in history
   * @param {string} sessionId - Session ID
   * @param {string} queryId - Query ID to pin/unpin
   * @param {boolean} pinned - Whether to pin or unpin
   * @returns {Object} { success: boolean, query_id: string, pinned: boolean }
   */
  async togglePinQuery(sessionId, queryId, pinned) {
    const { data } = await client.post('/history/pin', {
      query_id: queryId,
      pinned
    }, {
      params: { session_id: sessionId }
    })
    return data
  },

  /**
   * Get a specific history entry by ID
   * Used for re-executing past queries using sql_hash
   * @param {string} sessionId - Session ID
   * @param {string} queryId - Query ID
   * @returns {Object} HistoryEntry with sql_hash for re-execution
   */
  async getHistoryEntry(sessionId, queryId) {
    const { data } = await client.get(`/history/${queryId}`, {
      params: { session_id: sessionId }
    })
    return data
  },

  // ============================================
  // Cross-Session Re-execution
  // ============================================

  /**
   * Re-execute a query from history without requiring sql_hash.
   *
   * SECURITY: This endpoint does NOT send SQL to the server.
   * The server fetches SQL from its own history using query_id.
   * This enables cross-session re-execution (after logout/login).
   *
   * Use this instead of executeQuery() when:
   * - Re-executing from history after session change
   * - Re-executing queries from a previous login
   * - Re-executing pinned queries from any session
   *
   * @param {string} sessionId - Current session ID
   * @param {string} queryId - ID of the query to re-execute (from history)
   * @param {number} [limit=500] - Row limit for results
   * @param {boolean} [forceRefresh=false] - Bypass cache
   * @returns {Object} ExecuteQueryResponse with query results
   */
  async reexecuteFromHistory(sessionId, queryId, limit = 500, forceRefresh = false) {
    const { data } = await client.post('/query/reexecute', {
      session_id: sessionId,
      query_id: queryId,
      limit,
      force_refresh: forceRefresh
    })
    return data
  },

  // ============================================
  // DML Operations API
  // ============================================

  /**
   * Get DML capabilities for a database type
   */
  async getDmlCapabilities(dbType) {
    const { data } = await client.get(`/dml/capabilities/${dbType}`)
    return data
  },

  /**
   * Preview DML operation impact
   */
  async dmlPreview(sessionId, sql, mode = 'preview') {
    const { data } = await client.post('/dml/preview', {
      session_id: sessionId,
      sql,
      mode
    })
    return data
  },

  /**
   * Execute DML operation
   */
  async dmlExecute(sessionId, sql, mode, confirmationToken = null) {
    const payload = {
      session_id: sessionId,
      sql,
      mode
    }
    if (confirmationToken) {
      payload.confirmation_token = confirmationToken
    }
    const { data } = await client.post('/dml/execute', payload)
    return data
  },

  /**
   * Request confirmation token for DML execution
   */
  async dmlRequestConfirmation(sessionId, sql) {
    const { data } = await client.post('/dml/request-confirmation', {
      session_id: sessionId,
      sql
    })
    return data
  }
}
<template>
  <!-- Network status banner -->
  <NetworkBanner />

  <AppShell
    :session="session"
    :conversation="conversationMessages"
    :history="history"
    :suggestions="suggestions"
    :llm-config="llmConfig"
    :db-config="dbConfig"
    :token-info="tokenInfo"
    :is-dark="isDark"
    :is-generating="isGenerating"
    :is-executing="isExecuting"
    :is-explaining="isExplaining"
    :explaining-message-id="explainingMessageId"
    :show-setup="showSetupWizard"
    :sidebar-open="sidebarOpen"
    :query-count="queryCount"
    :session-start-time="sessionStartTime"
    @toggle-theme="cycleTheme"
    @update-llm="llmConfig = { ...llmConfig, ...$event }"
    @update-db="dbConfig = { ...dbConfig, ...$event }"
    @start-session="startSession"
    @reset-session="resetSession"
    @generate="handleGenerate"
    @stop="stopGeneration"
    @run-query="handleRunQuery"
    @explain="handleExplain"
    @copy="handleCopy"
    @export="handleExport"
    @feedback="handleFeedback"
    @load-history="loadFromHistory"
    @toggle-sidebar="sidebarOpen = !sidebarOpen"
    @update:sidebar-open="sidebarOpen = $event"
  />

  <LoadingOverlay
    :show="isLoading"
    :message="loadingMessage"
  />

  <!-- Toast notifications (renders via Teleport to body) -->
  <ToastContainer />
</template>

<script setup>
import { ref, computed, watch, provide, onMounted } from 'vue'
import AppShell from './components/layout/AppShell.vue'
import ToastContainer from './components/ToastContainer.vue'
import LoadingOverlay from './components/LoadingOverlay.vue'
import NetworkBanner from './components/layout/NetworkBanner.vue'
import { storeToRefs } from 'pinia'
import { useConversationStore } from './stores/conversation'
import { useSessionStore } from './stores/session'
import { useToast } from './composables/useToast'
import { useQueryOptions } from './composables/useQueryOptions'
import { useActivityStore } from './stores/activity'
import api from './utils/api'

// ========================================
// THEME STATE
// ========================================
const THEMES = [
  { id: 'queryfy-dark', name: 'QueryfyAI Dark', class: '', isDark: true },
  { id: 'queryfy-light', name: 'QueryfyAI Light', class: 'queryfy-light-theme', isDark: false }
]

const getStoredTheme = () => {
  const stored = localStorage.getItem('queryfyai-theme')
  // Migrate old mocha themes to queryfy
  if (stored === 'mocha-dark') return 'queryfy-dark'
  if (stored === 'mocha-light') return 'queryfy-light'
  if (stored && THEMES.find(t => t.id === stored)) {
    return stored
  }
  // Default to queryfy-dark, migrate old settings
  const oldDarkMode = localStorage.getItem('queryfyai-dark-mode')
  return oldDarkMode === 'false' ? 'queryfy-light' : 'queryfy-dark'
}

const currentTheme = ref(getStoredTheme())

// Computed for backward compatibility
const isDark = computed(() => {
  const theme = THEMES.find(t => t.id === currentTheme.value)
  return theme ? theme.isDark : true
})

// Provide theme to all child components
provide('isDark', isDark)

// Toggle between dark and light theme
const cycleTheme = () => {
  const currentIndex = THEMES.findIndex(t => t.id === currentTheme.value)
  const nextIndex = (currentIndex + 1) % THEMES.length
  currentTheme.value = THEMES[nextIndex].id
}

// Persist theme preference and apply to document
watch(currentTheme, (newTheme) => {
  localStorage.setItem('queryfyai-theme', newTheme)
  // Remove all theme classes first (including legacy mocha classes)
  document.documentElement.classList.remove('queryfy-light-theme', 'mocha-light-theme')
  // Apply the new theme class
  const theme = THEMES.find(t => t.id === newTheme)
  if (theme && theme.class) {
    document.documentElement.classList.add(theme.class)
  }
}, { immediate: true })

// ========================================
// SESSION STATE
// ========================================
const session = ref(null)
const tokenInfo = ref(null)
const showSetupWizard = ref(false)
const sessionStartTime = ref(null)
const queryCount = ref(0)

// Save session to localStorage (includes config for restore)
watch(session, (newSession) => {
  try {
    if (newSession) {
      // Save session with config so we can restore it properly
      // Note: client_secret and api_key intentionally excluded for security
      const sessionData = {
        ...newSession,
        dbConfig: dbConfig.value,
        llmConfig: {
          provider: llmConfig.value.provider,
          model: llmConfig.value.model,
          base_url: llmConfig.value.base_url,
          token_url: llmConfig.value.token_url,
          client_id: llmConfig.value.client_id,
          auth_scope: llmConfig.value.auth_scope,
          auth_type: llmConfig.value.auth_type,
          tenant: llmConfig.value.tenant,
          star: llmConfig.value.star,
          chat_endpoint: llmConfig.value.chat_endpoint
        },
        sessionStartTime: sessionStartTime.value,
        queryCount: queryCount.value
      }
      localStorage.setItem('queryfyai-session', JSON.stringify(sessionData))
    } else {
      localStorage.removeItem('queryfyai-session')
    }
  } catch (error) {
    console.warn('Failed to persist session to localStorage:', error.message)
  }
}, { deep: true })

// ========================================
// CONFIGURATION STATE
// ========================================
const llmConfig = ref({
  provider: 'oauth_gateway',
  base_url: '',
  token_url: '',
  client_id: '',
  client_secret: '',
  auth_scope: '',
  auth_type: 'client_credentials',
  tenant: '',
  star: '',
  chat_endpoint: '',
  api_key: '',
  model: 'gpt-4'
})

const dbConfig = ref({
  db_type: 'postgresql',
  connection_url: '',
  name: ''
})

// ========================================
// CONVERSATION STATE
// ========================================
const conversationStore = useConversationStore()
const { continueConversation } = storeToRefs(conversationStore)
const history = ref([])
const schema = ref(null)
const suggestions = computed(() => generateSchemaSuggestions(schema.value))

// Computed wrapper for conversation messages to ensure proper reactivity
const conversationMessages = computed(() => conversationStore.messages)

// Backward compatible alias for conversation methods
const conversation = {
  messages: computed(() => conversationStore.messages),
  messageCount: computed(() => conversationStore.messageCount),
  addUserMessage: (...args) => conversationStore.addUserMessage(...args),
  addAiMessage: (...args) => conversationStore.addAiMessage(...args),
  addSystemMessage: (...args) => conversationStore.addSystemMessage(...args),
  updateMessage: (...args) => conversationStore.updateMessage(...args),
  clearConversation: () => conversationStore.clearConversation()
}

// Security tokens
const currentQueryId = ref(null)
const currentSqlHash = ref(null)

// ========================================
// UI STATE
// ========================================
const isLoading = ref(false)
const loadingMessage = ref('Processing...')
const isGenerating = ref(false)
const isExecuting = ref(false)
const isExplaining = ref(false)
const explainingMessageId = ref(null)
const sidebarOpen = ref(false)

// Abort controller for cancelling streaming requests
const abortController = ref(null)

// Toast notifications (using new composable)
const toast = useToast()

// Query options (streaming/agentic modes)
const queryOptions = useQueryOptions()

// Activity store for sidebar history
const activityStore = useActivityStore()

// Session store for session expiration handling
const sessionStore = useSessionStore()

const startLoading = (message = 'Processing...') => {
  loadingMessage.value = message
  isLoading.value = true
}

const stopLoading = () => {
  isLoading.value = false
}

// Stop/cancel the current generation request
const stopGeneration = () => {
  if (abortController.value) {
    abortController.value.abort()
    abortController.value = null
  }
  isGenerating.value = false
  showToast('Generation cancelled', 'info')
}

// Backward-compatible showToast function (now uses composable)
const showToast = (message, type = 'info', options = {}) => {
  toast.add(message, type, options)
}

// ========================================
// SCHEMA-BASED SUGGESTIONS
// ========================================
const MAX_SUGGESTIONS = 6

/**
 * Parse schema_text format into structured tables array
 * Format: "Table: users\n  - id (integer)\n  - name (varchar)\nTable: orders..."
 */
const parseSchemaText = (schemaText) => {
  if (!schemaText || typeof schemaText !== 'string') return []

  try {
    const tables = []
    const tableBlocks = schemaText.split(/(?=Table:\s)/i)

    for (const block of tableBlocks) {
      if (!block.trim()) continue

      const tableMatch = block.match(/Table:\s*([^\n]+)/i)
      if (!tableMatch) continue

      const tableName = tableMatch[1].trim()
      if (!tableName) continue

      const columns = []

      // Extract columns: "  - column_name (type)" or "  - column_name: type"
      const columnMatches = block.matchAll(/^\s*-\s*([^\s(:]+)\s*[:(]\s*([^)\n]+)/gim)
      for (const match of columnMatches) {
        columns.push({ name: match[1].trim(), type: match[2].trim() })
      }

      tables.push({ name: tableName, columns })
    }

    return tables
  } catch (error) {
    console.error('Error parsing schema text:', error)
    return []
  }
}

/**
 * Generate context-aware query suggestions based on database schema
 */
const generateSchemaSuggestions = (schemaData) => {
  // Default suggestions when no schema available
  const defaultSuggestions = [
    { text: 'Show all tables in the database', label: 'List tables', icon: 'Database' },
    { text: 'Describe the database schema', label: 'Schema info', icon: 'FileText' }
  ]

  try {
    if (!schemaData) {
      return defaultSuggestions
    }

    // Handle both structured tables and schema_text formats
    let tables = Array.isArray(schemaData.tables) ? schemaData.tables : []

    // If no structured tables but we have schema_text, parse it
    if (!tables.length && schemaData.schema_text) {
      tables = parseSchemaText(schemaData.schema_text)
    }

    if (!tables.length) {
      return defaultSuggestions
    }

    const suggestions = []
    const seen = new Set() // Track seen suggestions to avoid duplicates

    // Helper to add unique suggestion
    const addSuggestion = (suggestion) => {
      if (suggestions.length >= MAX_SUGGESTIONS) return false
      if (seen.has(suggestion.text)) return false
      seen.add(suggestion.text)
      suggestions.push(suggestion)
      return true
    }

    // Common table name patterns for smarter suggestions
    const patterns = {
      orders: { match: /^(orders?|sales|transactions?|purchases?)$/i, icon: 'TrendingUp' },
      users: { match: /^(users?|customers?|clients?|members?|accounts?)$/i, icon: 'Users' },
      products: { match: /^(products?|items?|inventory|stock)$/i, icon: 'Package' },
    }

    // Build a set of table names for FK detection
    const tableNames = new Set(tables.map(t => t?.name?.trim()?.toLowerCase()).filter(Boolean))

    // Process tables to generate suggestions
    for (const table of tables) {
      if (suggestions.length >= MAX_SUGGESTIONS) break

      const tableName = table?.name?.trim()
      if (!tableName) continue

      const columns = Array.isArray(table.columns) ? table.columns : []
      const lowerName = tableName.toLowerCase()

      // Find interesting columns for smarter suggestions
      const numericCols = columns.filter(c => {
        if (!c?.name || !c?.type || typeof c.type !== 'string') return false
        return /int|decimal|numeric|float|double|money|number|real|bigint|smallint/i.test(c.type)
      })
      const dateCols = columns.filter(c => {
        if (!c?.name || !c?.type || typeof c.type !== 'string') return false
        return /date|time|timestamp/i.test(c.type)
      })

      // Detect FK-like columns that reference other tables
      const fkCols = columns.filter(c => {
        if (!c?.name) return false
        const match = c.name.match(/^(.+)_id$/i)
        if (!match) return false
        // Check if referenced table exists (singular or plural)
        const ref = match[1].toLowerCase()
        return tableNames.has(ref) || tableNames.has(ref + 's') || tableNames.has(ref + 'es')
      })

      // Pattern-based suggestions for well-known table types
      if (patterns.orders.match.test(lowerName) && dateCols.length > 0) {
        addSuggestion({
          text: `Show monthly ${tableName} trends over the last year`,
          label: `${tableName} trends`,
          icon: patterns.orders.icon
        })
      } else if (patterns.users.match.test(lowerName)) {
        addSuggestion({
          text: `How many ${tableName} are there? Show a summary breakdown`,
          label: `${tableName} summary`,
          icon: patterns.users.icon
        })
      } else if (patterns.products.match.test(lowerName) && numericCols.length > 0) {
        const priceCol = numericCols.find(c => /price|cost|amount/i.test(c.name)) || numericCols[0]
        addSuggestion({
          text: `Show top 10 ${tableName} by ${priceCol.name}`,
          label: `Top ${tableName}`,
          icon: patterns.products.icon
        })
      }

      // FK-based join suggestions
      if (fkCols.length > 0 && suggestions.length < MAX_SUGGESTIONS) {
        const fk = fkCols[0]
        const refName = fk.name.replace(/_id$/i, '')
        addSuggestion({
          text: `Show ${tableName} with their ${refName} details`,
          label: `${tableName} + ${refName}`,
          icon: 'Table'
        })
      }

      // Aggregation suggestions for tables with numeric columns
      if (numericCols.length > 0 && suggestions.length < MAX_SUGGESTIONS) {
        const numCol = numericCols[0].name
        if (dateCols.length > 0) {
          addSuggestion({
            text: `Show average ${numCol} from ${tableName} by month`,
            label: `${tableName} analysis`,
            icon: 'Calculator'
          })
        } else {
          addSuggestion({
            text: `Show summary statistics for ${numCol} in ${tableName}`,
            label: `${tableName} stats`,
            icon: 'Calculator'
          })
        }
      }

      // Time-based suggestion as fallback
      if (dateCols.length > 0 && suggestions.length < MAX_SUGGESTIONS) {
        addSuggestion({
          text: `Show ${tableName} from the last 30 days`,
          label: `Recent ${tableName}`,
          icon: 'Calendar'
        })
      }
    }

    return suggestions.length > 0 ? suggestions : defaultSuggestions
  } catch (error) {
    console.error('Error generating suggestions:', error)
    return defaultSuggestions
  }
}

// Fetch schema for a session
const fetchSchema = async (sessionId) => {
  try {
    const response = await api.getSchema(sessionId)
    schema.value = response
  } catch (error) {
    console.warn('Failed to fetch schema:', error)
    schema.value = null
  }
}

// ========================================
// INITIALIZATION
// ========================================
const loadDefaultConfig = async () => {
  try {
    const response = await api.getDefaultConfig()

    llmConfig.value = {
      provider: response.llm_config.provider || 'oauth_gateway',
      base_url: response.llm_config.base_url || '',
      token_url: response.llm_config.token_url || '',
      client_id: response.llm_config.client_id || '',
      client_secret: '',
      auth_scope: response.llm_config.auth_scope || '',
      auth_type: response.llm_config.auth_type || 'client_credentials',
      tenant: response.llm_config.tenant || '',
      star: response.llm_config.star || '',
      chat_endpoint: response.llm_config.chat_endpoint || '',
      api_key: '',
      model: response.llm_config.model || 'gpt-4'
    }

    dbConfig.value = {
      db_type: response.db_config.db_type || 'postgresql',
      connection_url: response.db_config.connection_url || '',
      name: response.db_config.name || ''
    }
  } catch (error) {
    console.warn('Could not load default config:', error.message)
  }
}

const restoreSession = async () => {
  const stored = localStorage.getItem('queryfyai-session')
  if (!stored) {
    showSetupWizard.value = true
    return false
  }

  // Silent restore - no loading overlay needed
  // Connection status indicator shows session state
  try {
    const storedSession = JSON.parse(stored)

    // Use the consolidated restore endpoint which returns CSRF token
    const response = await api.restoreSession(storedSession.id)

    if (response && response.session) {
      // IMPORTANT: Restore config BEFORE setting session to avoid
      // race condition where watcher saves default config to localStorage
      if (storedSession.dbConfig) {
        dbConfig.value = { ...dbConfig.value, ...storedSession.dbConfig }
      }
      if (storedSession.llmConfig) {
        llmConfig.value = { ...llmConfig.value, ...storedSession.llmConfig }
      }

      // Restore session stats
      sessionStartTime.value = storedSession.sessionStartTime || new Date().toISOString()
      queryCount.value = storedSession.queryCount || 0

      // Now set session - watcher will save correct config
      session.value = { id: storedSession.id, locked: response.session.locked || false }
      tokenInfo.value = response.token_info

      // CSRF token is automatically set by api.restoreSession()

      // Set session ID on stores for proper persistence and sync
      conversationStore.setSessionId(storedSession.id)
      activityStore.setSessionId(
        storedSession.id,
        response.session?.connection_hash,
        response.session?.db_type
      )

      // Restore history from consolidated response
      if (response.history && response.history.length > 0) {
        history.value = response.history.reverse()
        activityStore.loadFromHistory(response.history)

        // Load conversation from backend - now includes full analyst mode data
        // Backend stores: answer, key_findings, chart_spec, raw_result_summary, tools_used, etc.
        // The store's loadFromBackendHistory merges with localStorage and deduplicates
        conversationStore.loadFromBackendHistory(response.history)

        // Sync pinned queries from backend
        activityStore.syncPinnedFromBackend()
      }

      // Fetch schema for intelligent suggestions
      await fetchSchema(storedSession.id)

      return true
    }
  } catch (error) {
    // Session expired or server restarted - clear stale data and start fresh
    const status = error.response?.status
    const detail = error.response?.data?.detail || error.message
    console.warn(`Session restore failed: [${status || 'network'}] ${detail}`)
    localStorage.removeItem('queryfyai-session')
    showSetupWizard.value = true
    // Don't show error toast - just silently redirect to setup
  }
  return false
}

onMounted(async () => {
  await loadDefaultConfig()
  await restoreSession()
  // Silent restore - connection status indicator shows session state
  // Only show toasts for errors, not successful restore

  // Session expiration handler
  sessionStore.onSessionExpired(() => {
    // Backup current conversation
    const backup = {
      messages: conversationStore.messages,
      dbConfig: dbConfig.value,
      llmConfig: llmConfig.value,
      timestamp: Date.now()
    }

    localStorage.setItem('queryfyai-session-backup', JSON.stringify(backup))

    // Show persistent toast with action
    showToast(
      'Session expired. Your conversation has been saved.',
      'warning'
    )

    // Auto-trigger reconnect flow
    handleReconnect()
  })
})

// Handle session reconnection after expiration
async function handleReconnect() {
  // Clear expired session
  session.value = null
  conversationStore.clearConversation()

  // Attempt to restore from backup (if < 1 hour old)
  const backup = localStorage.getItem('queryfyai-session-backup')
  if (backup) {
    try {
      const data = JSON.parse(backup)
      if (Date.now() - data.timestamp < 3600000) { // 1 hour
        dbConfig.value = data.dbConfig
        llmConfig.value = data.llmConfig

        // Recreate session
        await startSession()

        // Restore messages (mark as restored)
        conversationStore.messages = data.messages
        showToast('Conversation restored', 'success')

        // Clear backup
        localStorage.removeItem('queryfyai-session-backup')
        return
      }
    } catch (e) {
      console.error('Failed to restore conversation from backup:', e)
    }
  }

  // No backup or expired - show setup wizard
  showSetupWizard.value = true
  showToast('Please reconnect to continue', 'info')
}

// ========================================
// ERROR HANDLING
// ========================================
const getErrorMessage = (error, fallback = 'An error occurred') => {
  const data = error.response?.data

  if (data?.detail && Array.isArray(data.detail)) {
    const messages = data.detail.map(err => {
      const field = err.loc?.slice(-1)[0] || 'field'
      return `${field}: ${err.msg}`
    })
    return messages.join(', ')
  }

  if (typeof data?.detail === 'string') return data.detail
  if (data?.message) return data.message

  return error.message || fallback
}

// ========================================
// SESSION ACTIONS
// ========================================
// Phase 4 Batch D (H10): poll the session endpoint for schema_ready.
// The backend creates the session immediately and indexes schema in
// a background task; without this poll a user who types a query in
// the first few seconds hits the agent before it has any schema
// context, the agent wanders, and produces "I don't have enough
// information." Polling caps at 60 attempts (~30s with 500ms spacing
// + jitter) so a stuck indexer surfaces a clean failure rather than
// looping forever.
const pollSchemaReady = async (sessionId, attempt = 0) => {
  if (!session.value || session.value.id !== sessionId) return  // stale
  try {
    const data = await api.getSession(sessionId)
    if (data?.schema_ready) {
      session.value = { ...session.value, schema_ready: true }
      return
    }
    if (data?.schema_error) {
      session.value = {
        ...session.value,
        schema_ready: false,
        schema_error: data.schema_error,
      }
      return
    }
  } catch {
    // Transient — keep trying.
  }
  if (attempt >= 60) {
    session.value = {
      ...session.value,
      schema_error: 'Schema indexing did not complete within 30s. Try refreshing.',
    }
    return
  }
  setTimeout(() => pollSchemaReady(sessionId, attempt + 1), 500)
}

const startSession = async () => {
  startLoading('Connecting to database & validating LLM...')
  try {
    const response = await api.createSession(llmConfig.value, dbConfig.value)
    session.value = {
      id: response.session_id,
      locked: false,
      // Phase 4 Batch D (H10): backend creates the session immediately
      // and starts schema extraction in the background. Track readiness
      // so the input/Run buttons can wait for it. Begins as false;
      // pollSchemaReady flips it once /sessions/{id} reports ready.
      schema_ready: false,
    }
    sessionStartTime.value = new Date().toISOString()
    queryCount.value = 0

    if (response.csrf_token) {
      api.setCsrfToken(response.csrf_token)
    }

    // Set session ID on stores for proper persistence and sync
    conversationStore.setSessionId(response.session_id)
    activityStore.setSessionId(
      response.session_id,
      response.connection_hash,
      response.db_type
    )

    // Fetch schema for intelligent suggestions
    await fetchSchema(response.session_id)
    // Kick off background polling — non-blocking, updates session.schema_ready
    pollSchemaReady(response.session_id)

    // Fetch DML capabilities
    try {
      const dmlCaps = await api.getDmlCapabilities(dbConfig.value.db_type)
      session.value.dml_capabilities = dmlCaps
    } catch (e) {
      console.warn('DML capabilities not available:', e.message)
    }

    showSetupWizard.value = false
    showToast(response.message || 'Session started!', 'success')
  } catch (error) {
    showToast(getErrorMessage(error, 'Failed to start session'), 'error')
  } finally {
    stopLoading()
  }
}

const resetSession = (confirmed = false) => {
  // If not confirmed, this will be handled by SettingsDrawer confirmation
  if (!confirmed) return

  if (session.value) {
    // Fire-and-forget: session cleanup on server is best-effort
    api.deleteSession(session.value.id).catch(() => {
      // Silently ignore - session will be cleaned up by server TTL
    })
  }

  session.value = null
  tokenInfo.value = null
  sessionStartTime.value = null
  queryCount.value = 0
  history.value = []
  currentQueryId.value = null
  currentSqlHash.value = null
  conversation.clearConversation()
  api.setCsrfToken(null)

  // Show setup wizard for new session
  showSetupWizard.value = true
  showToast('Session ended. Configure a new connection to continue.', 'info')
}

// ========================================
// QUERY ACTIONS
// ========================================
const handleGenerate = async (query) => {
  if (!session.value || !query.trim()) return

  // Add user message
  const isOriginal = conversation.messageCount.value === 0
  conversation.addUserMessage(query, isOriginal)

  isGenerating.value = true

  // Get current mode options
  const useStreaming = queryOptions.streamMode.value
  const responseMode = queryOptions.responseMode.value // 'standard' or 'analyst'
  const isAnalystMode = responseMode === 'analyst'

  if (useStreaming) {
    // Don't create AI message until first SSE event - show loading dots only
    let messageId = null
    let streamedSql = ''
    let toolsUsed = []
    let agentSteps = []  // Track detailed agent activity

    // Create abort controller for this request
    abortController.value = new AbortController()

    // Helper to lazily create the AI message on first content
    const ensureMessage = () => {
      if (messageId === null) {
        messageId = conversation.addAiMessage({
          sql: '',
          isValid: true,
          isGenerating: true,
          // Always track toolsUsed and agentSteps for real-time display
          toolsUsed: [],
          agentSteps: [],
          ...(isAnalystMode && {
            mode: 'analyst',
            answer: null,
            keyFindings: [],
            chart: null
          })
        })
      }
      return messageId
    }

    try {
      const finalResult = await api.chatStream(
        session.value.id,
        query,
        {
          mode: responseMode,
          includeReasoning: false,
          signal: abortController.value.signal,
          includeChart: true,
          continueConversation: continueConversation.value
        },
        // Event handler - create message on first meaningful event
        (event) => {
          switch (event.event) {
            case 'thinking':
              // Create message and track thinking step
              ensureMessage()
              if (event.content) {
                agentSteps.push({
                  type: 'thinking',
                  content: event.content,
                  timestamp: Date.now()
                })
                conversation.updateMessage(messageId, { agentSteps: [...agentSteps] })
              }
              break

            case 'sql_chunk':
              // Progressive SQL display (standard mode)
              ensureMessage()
              streamedSql += event.content
              conversation.updateMessage(messageId, { sql: streamedSql })
              break

            case 'sql_complete':
            case 'sql':
            case 'sql_generated':
              // Final validated SQL
              ensureMessage()
              conversation.updateMessage(messageId, { sql: event.sql || event.content })
              // Track query generation as a step for agent activity (both modes)
              agentSteps.push({
                type: 'sql_generated',
                content: 'Query generated',  // Generic for SQL/NoSQL
                timestamp: Date.now()
              })
              conversation.updateMessage(messageId, { agentSteps: [...agentSteps] })
              break

            case 'executed':
              // Query execution completed
              ensureMessage()
              // Track execution as a step
              agentSteps.push({
                type: 'executed',
                content: event.content || `Query returned ${event.row_count || 0} rows`,
                row_count: event.row_count,
                timestamp: Date.now()
              })
              conversation.updateMessage(messageId, { agentSteps: [...agentSteps] })
              break

            case 'tool_call':
              // Track tool call with CLI-style details
              ensureMessage()
              if (event.tool_name) {
                if (!toolsUsed.includes(event.tool_name)) {
                  toolsUsed.push(event.tool_name)
                }
                // Backend sends step data at top level, not in event.data
                agentSteps.push({
                  type: 'tool_call',
                  tool_name: event.tool_name,
                  tool_args: event.tool_args || {},
                  step_number: event.step_number || agentSteps.length + 1,
                  description: event.description || event.tool_name,
                  timestamp: Date.now()
                })
                conversation.updateMessage(messageId, {
                  toolsUsed: [...toolsUsed],
                  agentSteps: [...agentSteps]
                })
              }
              break

            case 'tool_result':
              // Track tool result with CLI-style summary
              ensureMessage()
              if (event.tool_name) {
                if (!toolsUsed.includes(event.tool_name)) {
                  toolsUsed.push(event.tool_name)
                }
                // Backend sends summary at top level, not in event.data
                agentSteps.push({
                  type: 'tool_result',
                  tool_name: event.tool_name,
                  summary: event.summary || '',
                  content: event.content || '',
                  timestamp: Date.now()
                })
                conversation.updateMessage(messageId, {
                  toolsUsed: [...toolsUsed],
                  agentSteps: [...agentSteps]
                })
              }
              break

            case 'executing':
              // SQL execution status
              ensureMessage()
              agentSteps.push({
                type: 'executing',
                content: event.content || 'Executing SQL...',
                timestamp: Date.now()
              })
              conversation.updateMessage(messageId, { agentSteps: [...agentSteps] })
              break

            case 'analyzing':
              // Analysis status
              ensureMessage()
              break

            case 'heartbeat':
              // Phase 4 Batch D (M8): backend keepalive every 15s during
              // quiet periods (long DB queries, multi-second analysis).
              // Surface elapsed_ms so the AIResponseCard's thinking
              // indicator can render "Running 1m 23s..." instead of a
              // silent spinner.
              ensureMessage()
              if (typeof event.elapsed_ms === 'number') {
                conversation.updateMessage(messageId, {
                  elapsedMs: event.elapsed_ms,
                })
              }
              break

            case 'query_progress':
              // Phase 3b.2: optional driver-side metrics during long
              // queries (BigQuery bytes_scanned etc.). Forward to
              // store; AIResponseCard can render a status badge.
              ensureMessage()
              conversation.updateMessage(messageId, {
                queryProgress: {
                  elapsed_ms: event.elapsed_ms,
                  bytes_scanned: event.bytes_scanned,
                  rows_read: event.rows_read,
                  percent: event.percent,
                },
              })
              break

            case 'error':
              // Error is already thrown in api.js, this case is handled by the outer catch block
              // Just ensure message exists so it can be marked with error state
              ensureMessage()
              break
          }
        }
      )

      // Finalize with complete data from 'done' event
      if (finalResult) {
        // Ensure message exists (in case no intermediate events were received)
        ensureMessage()

        const updates = {
          sql: finalResult.sql,
          isGenerating: false,
          queryId: finalResult.query_id,
          sqlHash: finalResult.sql_hash,
          // Multi-turn conversation metadata
          isFollowUp: finalResult.is_follow_up || false,
          conversationTurn: finalResult.conversation_turn || 1
        }

        // Add analyst mode fields if present
        if (finalResult.mode === 'analyst') {
          updates.mode = 'analyst'
          updates.answer = finalResult.answer
          updates.keyFindings = finalResult.key_findings || []
          // Mission-critical: the STRUCTURED insights list (LLM
          // business_insight + detector findings) the backend now
          // emits. Without this assignment, AIResponseCard's
          // InsightCard renderer stays empty even when the backend
          // generates rich narrative.
          updates.insights = finalResult.insights || []
          updates.confidence = finalResult.confidence
          updates.chart = finalResult.chart
          // Include db_type for NoSQL document view detection
          updates.rawResult = finalResult.raw_result ? {
            ...finalResult.raw_result,
            db_type: finalResult.raw_result.db_type || session.value.db_type
          } : null
          updates.toolsUsed = finalResult.tools_used || toolsUsed
          updates.suggestions = finalResult.suggestions || []
        }

        conversation.updateMessage(messageId, updates)

        // Auto-restore continue mode after fresh start
        if (!continueConversation.value) {
          conversationStore.setContinueConversation(true)
        }

        currentQueryId.value = finalResult.query_id
        currentSqlHash.value = finalResult.sql_hash
        session.value.locked = true

        // Optimistic history update (avoid full reload for better UX)
        const newHistoryEntry = {
          id: finalResult.query_id,
          query: query,
          sql: finalResult.sql,
          sql_hash: finalResult.sql_hash,
          session_id: session.value.id,
          timestamp: new Date().toISOString(),
          success: true
        }
        history.value = [newHistoryEntry, ...history.value]
        activityStore.addQuery({
          id: finalResult.query_id,
          query: query,
          sql: finalResult.sql,
          sqlHash: finalResult.sql_hash,
          sessionId: session.value.id,
          timestamp: Date.now(),
          success: true,
          dbType: activityStore.currentDbType,
          mode: finalResult.mode || 'standard',
          answer: finalResult.answer,
          keyFindings: finalResult.key_findings,
          chartSpec: finalResult.chart
        })
      }

      queryCount.value++
      showToast(isAnalystMode ? 'Analysis complete!' : 'SQL generated!', 'success')
    } catch (error) {
      // Check if this was a user-initiated cancellation
      const wasCancelled = error.name === 'AbortError' || error.message?.includes('cancelled')
      const wasDisconnect = error.isStreamDisconnect === true

      // Update message to show appropriate state
      if (messageId !== null) {
        conversation.updateMessage(messageId, {
          sql: streamedSql || null,
          isGenerating: false,
          ...(wasCancelled
            ? { cancelled: true }
            : { error: wasDisconnect
                ? 'Connection lost during analysis. Your query may still be processing.'
                : getErrorMessage(error, 'Generation failed') })
        })
      } else if (!wasCancelled) {
        // No message created yet - show error as system message (but not for cancellation)
        const errorMsg = wasDisconnect
          ? 'Connection lost during analysis. Your query may still be processing.'
          : getErrorMessage(error, 'Generation failed')
        conversation.addSystemMessage(errorMsg, 'error')
      }

      if (wasDisconnect) {
        showToast('Connection lost during analysis. Your query may still be processing. Please wait a moment and try again.', 'warning')
      } else if (!wasCancelled) {
        showToast(getErrorMessage(error, 'Generation failed'), 'error')
      }
    } finally {
      isGenerating.value = false
      abortController.value = null
    }
  } else {
    // Non-streaming fallback using unified /chat endpoint
    try {
      const response = await api.chat(session.value.id, query, {
        mode: responseMode,
        includeReasoning: false,
        includeChart: true,
        continueConversation: continueConversation.value
      })

      if (!response.success || response.error) {
        conversation.addSystemMessage(response.error || 'Generation failed', 'error')
        showToast(response.error || 'Generation failed', 'error')
        return
      }

      // Build message content
      const messageContent = {
        sql: response.sql,
        isValid: response.is_valid !== false,
        queryType: response.query_type || null,
        queryId: response.query_id,
        sqlHash: response.sql_hash,
        // Multi-turn conversation metadata
        isFollowUp: response.is_follow_up || false,
        conversationTurn: response.conversation_turn || 1
      }

      // Add analyst mode fields if present
      if (response.mode === 'analyst') {
        messageContent.mode = 'analyst'
        messageContent.answer = response.answer
        messageContent.keyFindings = response.key_findings || []
        // Mission-critical: structured insights for InsightCard.
        messageContent.insights = response.insights || []
        messageContent.confidence = response.confidence
        messageContent.chart = response.chart
        // Include db_type for NoSQL document view detection
        messageContent.rawResult = response.raw_result ? {
          ...response.raw_result,
          db_type: response.raw_result.db_type || session.value.db_type
        } : null
        messageContent.toolsUsed = response.tools_used || []
        messageContent.suggestions = response.suggestions || []
      }

      conversation.addAiMessage(messageContent)

      // Auto-restore continue mode after fresh start
      if (!continueConversation.value) {
        conversationStore.setContinueConversation(true)
      }

      currentQueryId.value = response.query_id
      currentSqlHash.value = response.sql_hash
      session.value.locked = true

      // Optimistic history update (avoid full reload for better UX)
      const newHistoryEntry = {
        id: response.query_id,
        query: query,
        sql: response.sql,
        sql_hash: response.sql_hash,
        session_id: session.value.id,
        timestamp: new Date().toISOString(),
        success: true
      }
      history.value = [newHistoryEntry, ...history.value]
      activityStore.addQuery({
        id: response.query_id,
        query: query,
        sql: response.sql,
        sqlHash: response.sql_hash,
        sessionId: session.value.id,
        timestamp: Date.now(),
        success: true,
        dbType: activityStore.currentDbType
      })

      queryCount.value++
      showToast(isAnalystMode ? 'Analysis complete!' : 'SQL generated!', 'success')
    } catch (error) {
      conversation.addSystemMessage(getErrorMessage(error, 'Generation failed'), 'error')
      showToast(getErrorMessage(error, 'Generation failed'), 'error')
    } finally {
      isGenerating.value = false
    }
  }
}

const handleRunQuery = async (message) => {
  if (!session.value || !message?.content?.sql) return

  const queryId = message.content.queryId || currentQueryId.value

  isExecuting.value = true

  try {
    // Always use reexecuteFromHistory for reliability
    // This uses PostgreSQL fallback when Redis registry clears (server restart, expiry)
    const response = queryId
      ? await api.reexecuteFromHistory(session.value.id, queryId, 500)
      : await api.executeQuery(session.value.id, message.content.sql, 500)

    // Update the AI message with results (use rawResult to match AIResponseCard expectations)
    // Also update sqlHash if returned (important for export after re-execution)
    // Include db_type for NoSQL document view detection
    const updates = {
      rawResult: {
        ...response,
        db_type: response.db_type || session.value.db_type
      }
    }
    if (response.sql_hash) {
      updates.sqlHash = response.sql_hash
      currentSqlHash.value = response.sql_hash
    }
    conversation.updateMessage(message.id, updates)

    const moreMsg = response.has_more ? ' (more available)' : ''
    showToast(`Returned ${response.row_count} rows${moreMsg}`, 'success')
  } catch (error) {
    showToast(getErrorMessage(error, 'Query execution failed'), 'error')
  } finally {
    isExecuting.value = false
  }
}

const handleExplain = async (message) => {
  if (!session.value || !message?.content?.sql) return
  if (isExplaining.value) return // Prevent multiple simultaneous explains

  isExplaining.value = true
  explainingMessageId.value = message.id

  try {
    // Initialize with empty explanation to show streaming has started
    conversation.updateMessage(message.id, { explanation: '' })

    // Use streaming API for progressive updates
    await api.explainSQLStream(
      session.value.id,
      message.content.sql,
      (chunk) => {
        // Progressive update - append each chunk
        const currentMsg = conversation.messages.value.find(m => m.id === message.id)
        const currentExplanation = currentMsg?.content?.explanation || ''
        conversation.updateMessage(message.id, { explanation: currentExplanation + chunk })
      }
    )
  } catch (error) {
    // Clear partial explanation on error
    conversation.updateMessage(message.id, { explanation: null })
    showToast(getErrorMessage(error, 'SQL explanation failed'), 'error')
  } finally {
    isExplaining.value = false
    explainingMessageId.value = null
  }
}

const handleCopy = () => {
  showToast('SQL copied to clipboard', 'success')
}

const handleExport = async (message) => {
  if (!session.value || !message?.content?.sql) return

  const sql = message.content.sql
  const queryId = message.content.queryId || currentQueryId.value
  const sqlHash = message.content.sqlHash || currentSqlHash.value
  // Phase 4.3: prefer the cached rows_ref so the export matches the
  // exact dataset the analysis ran on. Backend falls back to SQL re-
  // execution on cache miss / TTL expiry.
  const rowsRef = message?.content?.rawResult?.rows_ref || null

  try {
    const result = await api.exportToExcel(
      session.value.id,
      sql,
      1000000,
      queryId,
      sqlHash,
      rowsRef,
    )
    // Phase 4.3 Batch B: tell the user when we fell back to a fresh
    // query — the exported rows may not match the analysed dataset
    // exactly (e.g. underlying data changed, or cache TTL expired).
    if (rowsRef && result?.source === 'sql') {
      showToast(
        'Exported from a fresh query (cache expired) — rows may differ from the analysis above.',
        'warning',
      )
    } else {
      showToast('Excel file downloaded!', 'success')
    }
  } catch (error) {
    showToast(getErrorMessage(error, 'Export failed'), 'error')
  }
}

const handleFeedback = async ({ message, rating }) => {
  if (!session.value) return

  const queryId = message?.content?.queryId || (history.value[0]?.id)
  if (!queryId) return

  try {
    await api.submitFeedback(session.value.id, queryId, rating)
    showToast('Thanks for feedback!', 'success')
  } catch (error) {
    console.error(error)
  }
}

const loadFromHistory = (item) => {
  // Handle full conversation loading
  if (item.type === 'conversation' && item.queries?.length > 0) {
    // Clear current conversation and load all queries from history
    conversation.clearConversation()

    // Sort queries by timestamp (oldest first)
    const sortedQueries = [...item.queries].sort((a, b) => a.timestamp - b.timestamp)

    // Add each query as user message + AI response
    for (const query of sortedQueries) {
      conversation.addUserMessage(query.query, false)
      conversation.addAiMessage({
        sql: query.sql,
        isValid: query.success !== false,
        queryId: query.id,
        sqlHash: query.sql_hash || query.sqlHash,
        explanation: query.explanation,
        // Add analyst mode fields if available
        mode: query.mode,
        answer: query.answer,
        keyFindings: query.keyFindings || query.key_findings || [],
        confidence: query.confidence,
        chart: query.chartSpec || query.chart,
        rawResult: query.rawResultSummary || query.raw_result_summary,
        toolsUsed: query.toolsUsed || query.tools_used || []
      })
    }

    // Set current query to the latest one
    const lastQuery = sortedQueries[sortedQueries.length - 1]
    currentQueryId.value = lastQuery.id
    currentSqlHash.value = lastQuery.sql_hash || lastQuery.sqlHash || null
    return
  }

  // Legacy: single query loading
  conversation.addUserMessage(item.query, false)
  conversation.addAiMessage({
    sql: item.sql,
    isValid: true,
    queryId: item.id,
    sqlHash: item.sql_hash || item.sqlHash,  // Support both backend and frontend formats
    explanation: item.explanation
  })

  currentQueryId.value = item.id
  // Use stored sql_hash for re-execution (no need to regenerate)
  currentSqlHash.value = item.sql_hash || item.sqlHash || null
}
</script>

<style>
/* Import design tokens */
@import './styles/design-tokens.css';

/* App container */
.app-shell {
  min-height: 100vh;
  min-height: 100dvh;
}

/* Loading overlay styles */
.loading-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal);
}

/* Toast styles */
.toast-container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: var(--z-toast);
}
</style>

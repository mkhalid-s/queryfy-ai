/**
 * E2E Query Flow Tests
 *
 * Tests complete end-to-end flows:
 * 1. Standard SQL generation flow
 * 2. Analyst mode with enriched responses
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConversationStore } from '@/stores/conversation'
import { useActivityStore } from '@/stores/activity'
import api from '@/utils/api'

// Mock API
vi.mock('@/utils/api', () => ({
  default: {
    createSession: vi.fn(),
    chat: vi.fn(),
    reexecuteFromHistory: vi.fn()
  }
}))

describe('E2E Query Flows', () => {
  let conversationStore
  let activityStore

  beforeEach(() => {
    setActivePinia(createPinia())
    conversationStore = useConversationStore()
    activityStore = useActivityStore()
    vi.clearAllMocks()
  })

  // ============================================
  // STANDARD SQL GENERATION FLOW
  // ============================================

  it('completes standard SQL generation flow', async () => {
    /*
     * E2E Flow:
     * 1. User submits natural language query
     * 2. API generates SQL
     * 3. Conversation store adds user and AI messages
     * 4. Activity store records the query
     * 5. User can re-execute the query
     */

    // Setup: Session exists
    const sessionId = 'test-session-123'
    conversationStore.setSessionId(sessionId)
    activityStore.setSessionId(sessionId)

    // Step 1: Mock API response for SQL generation
    api.chat.mockResolvedValue({
      success: true,
      mode: 'standard',
      sql: 'SELECT * FROM customers LIMIT 10',
      is_valid: true,
      query_type: 'SELECT',
      query_id: 'q-123',
      sql_hash: 'hash-abc-123',
      execution_time_ms: 250,
      usage: {
        prompt_tokens: 100,
        completion_tokens: 50,
        total_tokens: 150
      }
    })

    // Step 2: User submits query
    const userQuery = 'Show me the top 10 customers'
    conversationStore.addUserMessage(userQuery)

    expect(conversationStore.messages.length).toBe(1)
    expect(conversationStore.messages[0].content.text).toBe(userQuery)

    // Step 3: Call API (simulating frontend chat logic)
    const response = await api.chat({
      session_id: sessionId,
      message: userQuery,
      mode: 'standard'
    })

    // Step 4: Add AI response to conversation
    const aiMessageId = conversationStore.addAiMessage({
      sql: response.sql,
      isValid: response.is_valid,
      queryType: response.query_type,
      queryId: response.query_id,
      sqlHash: response.sql_hash,
      mode: response.mode
    })

    expect(conversationStore.messages.length).toBe(2)
    expect(conversationStore.latestAiMessage.content.sql).toBe('SELECT * FROM customers LIMIT 10')
    expect(conversationStore.latestSql).toBe('SELECT * FROM customers LIMIT 10')

    // Step 5: Record in activity store
    activityStore.addQuery({
      id: response.query_id,
      query: userQuery,
      sql: response.sql,
      sqlHash: response.sql_hash,
      sessionId: sessionId,
      mode: response.mode
    })

    expect(activityStore.sessionQueries.length).toBe(1)
    expect(activityStore.sessionQueries[0].sql).toBe('SELECT * FROM customers LIMIT 10')

    // Step 6: Verify re-execution strategy
    const reexecStrategy = activityStore.getReexecutionStrategy(response.query_id)
    expect(reexecStrategy).toBeTruthy()
    expect(reexecStrategy.method).toBe('reexecute')
    expect(reexecStrategy.queryId).toBe('q-123')

    // Step 7: User re-executes query
    api.reexecuteFromHistory.mockResolvedValue({
      success: true,
      sql: 'SELECT * FROM customers LIMIT 10',
      results: {
        columns: ['id', 'name', 'email'],
        rows: [
          [1, 'Alice', 'alice@example.com'],
          [2, 'Bob', 'bob@example.com']
        ],
        row_count: 2
      }
    })

    const reexecResult = await api.reexecuteFromHistory(sessionId, response.query_id)

    expect(reexecResult.success).toBe(true)
    expect(reexecResult.results.row_count).toBe(2)

    // Step 8: Update message with results
    conversationStore.updateMessage(aiMessageId, {
      results: reexecResult.results
    })

    const updatedMessage = conversationStore.getMessage(aiMessageId)
    expect(updatedMessage.content.results.row_count).toBe(2)

    // Verify complete flow
    expect(conversationStore.hasMessages).toBe(true)
    expect(conversationStore.messageCount).toBe(2)
    expect(activityStore.sessionCount).toBe(1)
  })

  // ============================================
  // ANALYST MODE WITH ENRICHED RESPONSES
  // ============================================

  it('completes analyst mode flow with enriched responses', async () => {
    /*
     * E2E Flow:
     * 1. User submits analytical question
     * 2. API processes with ReAct agent
     * 3. Returns enriched response (answer, findings, chart, insights)
     * 4. Stores full analyst data in conversation and activity
     * 5. User can view all enriched features
     */

    // Setup
    const sessionId = 'test-session-456'
    conversationStore.setSessionId(sessionId)
    activityStore.setSessionId(sessionId)

    // Step 1: Mock API response for analyst mode
    api.chat.mockResolvedValue({
      success: true,
      mode: 'analyst',
      sql: 'SELECT region, SUM(revenue) as total_revenue FROM orders GROUP BY region ORDER BY total_revenue DESC',
      is_valid: true,
      query_type: 'SELECT',
      query_id: 'q-456',
      sql_hash: 'hash-xyz-456',
      // Analyst-specific fields
      answer: 'Your top revenue region is North America with $3.2M in total sales.',
      key_findings: [
        'North America leads with $3.2M (45% of total)',
        'Europe follows with $2.1M (30% of total)',
        'Asia Pacific: $1.5M (21% of total)',
        'Growth: North America +15% YoY'
      ],
      confidence: 0.95,
      chart: {
        chart_type: 'bar',
        title: 'Revenue by Region',
        x_axis: 'region',
        y_axis: 'total_revenue',
        data: [
          { region: 'North America', total_revenue: 3200000 },
          { region: 'Europe', total_revenue: 2100000 },
          { region: 'Asia Pacific', total_revenue: 1500000 }
        ]
      },
      raw_result: {
        columns: ['region', 'total_revenue'],
        rows: [
          ['North America', 3200000],
          ['Europe', 2100000],
          ['Asia Pacific', 1500000]
        ],
        row_count: 3
      },
      data_quality: {
        overall_score: 92,
        completeness: 95,
        issues: []
      },
      insights: [
        {
          type: 'trend',
          severity: 'info',
          message: 'North America showing strong growth trend'
        }
      ],
      suggestions: [
        { question: 'What are the top products in North America?' },
        { question: 'Show me month-over-month revenue trends' }
      ],
      tools_used: ['search_tables', 'get_table_schema', 'execute_and_analyze'],
      tool_calls_count: 3,
      execution_time_ms: 1250
    })

    // Step 2: User submits analytical question
    const userQuery = 'What are my top revenue regions?'
    conversationStore.addUserMessage(userQuery)

    // Step 3: Call API in analyst mode
    const response = await api.chat({
      session_id: sessionId,
      message: userQuery,
      mode: 'analyst',
      include_chart: true
    })

    // Step 4: Add enriched AI response
    conversationStore.addAiMessage({
      sql: response.sql,
      isValid: response.is_valid,
      queryType: response.query_type,
      queryId: response.query_id,
      sqlHash: response.sql_hash,
      mode: response.mode,
      answer: response.answer,
      keyFindings: response.key_findings,
      confidence: response.confidence,
      chart: response.chart,
      rawResult: response.raw_result,
      toolsUsed: response.tools_used,
      isGenerating: false
    })

    // Step 5: Verify conversation has enriched data
    const latestAi = conversationStore.latestAiMessage
    expect(latestAi.content.mode).toBe('analyst')
    expect(latestAi.content.answer).toContain('North America')
    expect(latestAi.content.keyFindings.length).toBe(4)
    expect(latestAi.content.confidence).toBe(0.95)
    expect(latestAi.content.chart).toBeTruthy()
    expect(latestAi.content.chart.chart_type).toBe('bar')
    expect(latestAi.content.chart.data.length).toBe(3)
    expect(latestAi.content.toolsUsed).toContain('execute_and_analyze')

    // Step 6: Record full analyst data in activity
    activityStore.addQuery({
      id: response.query_id,
      query: userQuery,
      sql: response.sql,
      sqlHash: response.sql_hash,
      sessionId: sessionId,
      mode: response.mode,
      answer: response.answer,
      keyFindings: response.key_findings,
      confidence: response.confidence,
      chartSpec: response.chart,
      rawResultSummary: response.raw_result,
      toolsUsed: response.tools_used
    })

    const savedQuery = activityStore.sessionQueries[0]
    expect(savedQuery.mode).toBe('analyst')
    expect(savedQuery.answer).toBe(response.answer)
    expect(savedQuery.keyFindings).toEqual(response.key_findings)
    expect(savedQuery.chartSpec.chart_type).toBe('bar')

    // Step 7: Verify follow-up suggestions
    expect(response.suggestions).toBeTruthy()
    expect(response.suggestions.length).toBe(2)

    // Step 8: User asks follow-up question
    const followUpQuery = 'What about by product?'
    conversationStore.addUserMessage(followUpQuery)

    api.chat.mockResolvedValue({
      success: true,
      mode: 'analyst',
      sql: 'SELECT product_name, SUM(revenue) as revenue FROM orders GROUP BY product_name ORDER BY revenue DESC LIMIT 10',
      query_id: 'q-457',
      sql_hash: 'hash-follow-up',
      answer: 'Your top product is Product A with $1.2M',
      key_findings: ['Product A: $1.2M', 'Product B: $950K'],
      confidence: 0.93,
      isFollowUp: true,
      conversationTurn: 2
    })

    const followUpResponse = await api.chat({
      session_id: sessionId,
      message: followUpQuery,
      mode: 'analyst',
      continue_conversation: true
    })

    conversationStore.addAiMessage({
      sql: followUpResponse.sql,
      queryId: followUpResponse.query_id,
      sqlHash: followUpResponse.sql_hash,
      mode: followUpResponse.mode,
      answer: followUpResponse.answer,
      keyFindings: followUpResponse.key_findings,
      confidence: followUpResponse.confidence,
      isFollowUp: followUpResponse.isFollowUp,
      conversationTurn: followUpResponse.conversationTurn
    })

    // Verify follow-up tracking
    expect(conversationStore.followUpCount).toBe(1)
    expect(conversationStore.currentConversationTurn).toBe(2)

    // Verify complete analyst flow
    expect(conversationStore.messageCount).toBe(4) // 2 user + 2 AI
    expect(activityStore.sessionCount).toBe(2)
    expect(conversationStore.hasMessages).toBe(true)
  })
})

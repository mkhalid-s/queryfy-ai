/**
 * Mock Service Worker (MSW) handlers for API mocking
 * Use in tests that need to mock HTTP requests
 */

import { http, HttpResponse } from 'msw'

const API_BASE_URL = 'http://test/api/v1'

/**
 * Default MSW handlers for common API endpoints
 */
export const handlers = [
  // Create session
  http.post(`${API_BASE_URL}/sessions`, () => {
    return HttpResponse.json({
      sessionId: 'test-session-123',
      csrfToken: 'test-csrf-token'
    })
  }),

  // Chat endpoint (standard mode)
  http.post(`${API_BASE_URL}/chat`, async ({ request }) => {
    const body = await request.json()

    if (body.mode === 'analyst') {
      return HttpResponse.json({
        sql: 'SELECT * FROM customers ORDER BY revenue DESC LIMIT 10',
        is_valid: true,
        query_type: 'SELECT',
        answer: 'Here are your top 10 customers by revenue',
        key_findings: ['Customer A leads with $500K', 'Top 3 account for 60% of revenue'],
        raw_result: {
          columns: ['id', 'name', 'revenue'],
          rows: [[1, 'Customer A', 500000], [2, 'Customer B', 350000]],
          row_count: 2
        },
        confidence: 0.92,
        tools_used: ['search_tables', 'execute_and_analyze']
      })
    }

    return HttpResponse.json({
      sql: 'SELECT * FROM customers LIMIT 10',
      is_valid: true,
      query_type: 'SELECT'
    })
  }),

  // Get schema
  http.get(`${API_BASE_URL}/schema/:sessionId`, () => {
    return HttpResponse.json({
      tables: {
        customers: {
          columns: [
            { name: 'id', type: 'integer', nullable: false },
            { name: 'name', type: 'varchar', nullable: false },
            { name: 'email', type: 'varchar', nullable: true }
          ]
        }
      }
    })
  }),

  // Refresh schema
  http.post(`${API_BASE_URL}/schema/:sessionId/refresh`, () => {
    return HttpResponse.json({ status: 'refreshing' }, { status: 202 })
  }),

  // Pin/unpin query
  http.post(`${API_BASE_URL}/activity/pin`, () => {
    return HttpResponse.json({ success: true })
  }),

  http.delete(`${API_BASE_URL}/activity/pin/:queryId`, () => {
    return HttpResponse.json({ success: true })
  }),

  // Get config defaults
  http.get(`${API_BASE_URL}/config/defaults`, () => {
    return HttpResponse.json({
      llmProviders: ['openai', 'anthropic'],
      dbTypes: ['postgresql', 'mysql', 'mongodb']
    })
  }),
]

/**
 * Create error response handler for testing error scenarios
 * @param {string} endpoint - API endpoint path
 * @param {number} status - HTTP status code
 * @param {string} message - Error message
 */
export function createErrorHandler(endpoint, status = 500, message = 'Server error') {
  return http.post(`${API_BASE_URL}${endpoint}`, () => {
    return HttpResponse.json(
      { error: message },
      { status }
    )
  })
}

/**
 * Create timeout handler for testing timeout scenarios
 * @param {string} endpoint - API endpoint path
 * @param {number} delay - Delay in ms
 */
export function createTimeoutHandler(endpoint, delay = 5000) {
  return http.post(`${API_BASE_URL}${endpoint}`, async () => {
    await new Promise(resolve => setTimeout(resolve, delay))
    return HttpResponse.json({ timeout: true }, { status: 504 })
  })
}

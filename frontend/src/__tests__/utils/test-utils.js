/**
 * Test utilities for Vue component testing
 * Provides helpers for mounting components with stores, routers, etc.
 */
/* global setImmediate */

import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { vi } from 'vitest'

/**
 * Create a fresh Pinia instance for testing
 * @returns {Pinia} New Pinia instance
 */
export function createTestingPinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return pinia
}

/**
 * Mount a Vue component with testing defaults
 * @param {Component} component - Vue component to mount
 * @param {Object} options - Mount options
 * @returns {VueWrapper}
 */
export function mountWithDefaults(component, options = {}) {
  const pinia = createTestingPinia()

  return mount(component, {
    global: {
      plugins: [pinia],
      stubs: {
        teleport: true,
        ...options.stubs
      },
    },
    ...options
  })
}

/**
 * Create mock API client for testing
 * @returns {Object} Mock API client
 */
export function createMockApi() {
  return {
    createSession: vi.fn().mockResolvedValue({
      sessionId: 'test-session-id',
      csrfToken: 'test-csrf-token'
    }),
    chat: vi.fn().mockResolvedValue({
      sql: 'SELECT * FROM customers LIMIT 10',
      is_valid: true,
      query_type: 'SELECT',
      raw_result: {
        columns: ['id', 'name', 'email'],
        rows: [
          [1, 'John Doe', 'john@example.com'],
          [2, 'Jane Smith', 'jane@example.com']
        ],
        row_count: 2
      }
    }),
    getCsrfToken: vi.fn().mockResolvedValue('test-csrf-token'),
    refreshSchema: vi.fn().mockResolvedValue({ success: true }),
    getSchema: vi.fn().mockResolvedValue({
      tables: {
        customers: {
          columns: [
            { name: 'id', type: 'integer' },
            { name: 'name', type: 'varchar' },
            { name: 'email', type: 'varchar' }
          ]
        }
      }
    }),
    pinQuery: vi.fn().mockResolvedValue({ success: true }),
    unpinQuery: vi.fn().mockResolvedValue({ success: true }),
    deleteQuery: vi.fn().mockResolvedValue({ success: true }),
  }
}

/**
 * Create mock SSE EventSource for testing
 * @param {Function} _onMessage - Callback for messages
 * @returns {Object} Mock EventSource
 */
export function createMockEventSource(_onMessage) {
  const listeners = {
    message: [],
    error: [],
    open: []
  }

  return {
    addEventListener: vi.fn((event, callback) => {
      listeners[event]?.push(callback)
    }),
    removeEventListener: vi.fn((event, callback) => {
      const index = listeners[event]?.indexOf(callback)
      if (index > -1) {
        listeners[event].splice(index, 1)
      }
    }),
    close: vi.fn(),
    _emit: (event, data) => {
      listeners[event]?.forEach(callback => callback(data))
    },
    readyState: 1, // OPEN
    url: 'http://test/api/v1/chat',
    withCredentials: false
  }
}

/**
 * Wait for next tick and promises to resolve
 * @returns {Promise}
 */
export async function flushPromises() {
  return new Promise(resolve => setImmediate(resolve))
}

/**
 * Create sample query response for testing
 * @param {Object} overrides - Override default values
 * @returns {Object}
 */
export function createSampleQueryResponse(overrides = {}) {
  return {
    sql: 'SELECT * FROM customers',
    is_valid: true,
    query_type: 'SELECT',
    intent: 'data_retrieval',
    raw_result: {
      columns: ['id', 'name'],
      rows: [[1, 'John'], [2, 'Jane']],
      row_count: 2
    },
    confidence: 0.95,
    tools_used: ['search_tables', 'execute_sql'],
    ...overrides
  }
}

/**
 * Create sample analyst response for testing
 * @param {Object} overrides - Override default values
 * @returns {Object}
 */
export function createSampleAnalystResponse(overrides = {}) {
  return {
    ...createSampleQueryResponse(),
    answer: 'Here are the top customers by revenue.',
    key_findings: [
      'Total revenue across all customers is $1.2M',
      'Top customer accounts for 25% of revenue'
    ],
    insights: [
      {
        type: 'trend',
        severity: 'info',
        message: 'Revenue is growing 15% month-over-month'
      }
    ],
    chart: {
      type: 'bar',
      title: 'Top Customers by Revenue',
      x: 'customer_name',
      y: 'total_revenue'
    },
    data_quality: {
      score: 0.92,
      completeness: 0.95,
      issues: []
    },
    ...overrides
  }
}

/**
 * Create sample SSE event for testing
 * @param {string} type - Event type
 * @param {Object} data - Event data
 * @returns {Object}
 */
export function createSSEEvent(type, data = {}) {
  return {
    type,
    data,
    timestamp: new Date().toISOString()
  }
}

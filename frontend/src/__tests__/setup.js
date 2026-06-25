/**
 * Vitest global setup file
 * Configures test environment and utilities
 */
/* global setImmediate */

import { vi } from 'vitest'

// Mock window.matchMedia for components that use media queries
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return []
  }
  unobserve() {}
}

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  unobserve() {}
}

// Suppress console warnings in tests (optional - can be removed if you want to see warnings)
global.console = {
  ...console,
  warn: vi.fn(),
  error: vi.fn(),
}

// Global test utilities available in all tests
global.flushPromises = () => new Promise(resolve => setImmediate(resolve))

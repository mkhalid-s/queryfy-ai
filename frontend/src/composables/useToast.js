/**
 * useToast Composable
 *
 * Centralized toast notification management with:
 * - Singleton state (shared across all components)
 * - Queue management (max 5 toasts)
 * - Auto-dismiss with WCAG-compliant timing
 * - Pause/resume on hover
 * - Action button support
 * - Persistent toast option
 */

import { ref, readonly } from 'vue'

// ============================================
// SINGLETON STATE (shared across all instances)
// ============================================
const toasts = ref([])
const timeouts = new Map()
let toastId = 0

// Configuration
const CONFIG = {
  DEFAULT_DURATION: 5000,    // 5 seconds minimum (WCAG)
  MS_PER_WORD: 400,          // Additional time per word
  MAX_DURATION: 12000,       // Cap at 12 seconds
  MAX_TOASTS: 5              // Maximum visible toasts
}

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * Calculate appropriate duration based on message length
 * Based on WCAG guidelines: ~400-500ms per word, minimum 5 seconds
 */
function calculateDuration(message, options = {}) {
  if (options.persistent) return 0
  if (options.action) return 0  // Persist if has action button
  if (options.duration !== undefined) return options.duration

  const wordCount = message.split(/\s+/).length
  const calculated = CONFIG.DEFAULT_DURATION + (wordCount * CONFIG.MS_PER_WORD)
  return Math.min(calculated, CONFIG.MAX_DURATION)
}

/**
 * Schedule auto-removal of a toast
 */
function scheduleRemoval(id, delay) {
  if (delay <= 0) return

  const timeoutId = setTimeout(() => {
    removeToast(id)
  }, delay)

  timeouts.set(id, {
    timeoutId,
    scheduledAt: Date.now(),
    delay
  })
}

/**
 * Remove a toast by ID
 */
function removeToast(id) {
  const index = toasts.value.findIndex(t => t.id === id)
  if (index > -1) {
    toasts.value.splice(index, 1)
  }

  // Clear any pending timeout
  const timeout = timeouts.get(id)
  if (timeout) {
    clearTimeout(timeout.timeoutId)
    timeouts.delete(id)
  }
}

// ============================================
// COMPOSABLE EXPORT
// ============================================

export function useToast() {
  /**
   * Add a toast notification
   * @param {string} message - Message to display
   * @param {'success'|'error'|'warning'|'info'} type - Toast type
   * @param {Object} options - Options: duration, persistent, action
   * @returns {number} Toast ID for manual removal
   */
  function add(message, type = 'info', options = {}) {
    const id = ++toastId

    const toast = {
      id,
      message,
      type,
      duration: calculateDuration(message, options),
      action: options.action || null,
      persistent: options.persistent || false,
      createdAt: Date.now(),
      pausedAt: null,
      remainingTime: null
    }

    // Limit max toasts (remove oldest if exceeding)
    if (toasts.value.length >= CONFIG.MAX_TOASTS) {
      const oldest = toasts.value[0]
      removeToast(oldest.id)
    }

    toasts.value.push(toast)

    // Schedule auto-dismiss
    if (!toast.persistent && toast.duration > 0) {
      scheduleRemoval(id, toast.duration)
    }

    return id
  }

  /**
   * Remove a toast by ID
   */
  function remove(id) {
    removeToast(id)
  }

  /**
   * Pause auto-dismiss (e.g., on hover/focus)
   */
  function pause(id) {
    const toast = toasts.value.find(t => t.id === id)
    const timeout = timeouts.get(id)

    if (toast && timeout) {
      clearTimeout(timeout.timeoutId)
      const elapsed = Date.now() - timeout.scheduledAt
      toast.remainingTime = Math.max(timeout.delay - elapsed, 1000)
      toast.pausedAt = Date.now()
      timeouts.delete(id)
    }
  }

  /**
   * Resume auto-dismiss (e.g., on mouse leave/blur)
   */
  function resume(id) {
    const toast = toasts.value.find(t => t.id === id)

    if (toast && toast.remainingTime && !toast.persistent) {
      scheduleRemoval(id, toast.remainingTime)
      toast.pausedAt = null
      toast.remainingTime = null
    }
  }

  /**
   * Clear all toasts
   */
  function clear() {
    timeouts.forEach(({ timeoutId }) => clearTimeout(timeoutId))
    timeouts.clear()
    toasts.value = []
  }

  // Convenience methods
  const success = (msg, opts) => add(msg, 'success', opts)
  const error = (msg, opts) => add(msg, 'error', opts)
  const warning = (msg, opts) => add(msg, 'warning', opts)
  const info = (msg, opts) => add(msg, 'info', opts)

  return {
    // Reactive state (readonly to prevent external mutation)
    toasts: readonly(toasts),

    // Core methods
    add,
    remove,
    pause,
    resume,
    clear,

    // Convenience methods
    success,
    error,
    warning,
    info
  }
}

/**
 * Get toast instance for non-component contexts (api.js, main.js)
 * Returns the same singleton instance
 */
let globalInstance = null
export function getToastInstance() {
  if (!globalInstance) {
    globalInstance = useToast()
  }
  return globalInstance
}

export default useToast

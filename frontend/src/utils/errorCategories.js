// ============================================
// FILE: frontend/src/utils/errorCategories.js
// Error categorization for better user messages
// ============================================

export const ErrorCategory = {
  NETWORK: 'network',
  AUTH: 'auth',
  PERMISSION: 'permission',
  VALIDATION: 'validation',
  BUSINESS: 'business',
  SERVER: 'server',
  TIMEOUT: 'timeout'
}

export function categorizeError(error) {
  const status = error.response?.status
  const data = error.response?.data
  const message = error.message?.toLowerCase() || ''

  // Network errors
  if (!error.response) {
    return {
      category: ErrorCategory.NETWORK,
      userMessage: error.code === 'ECONNABORTED' || message.includes('timeout')
        ? 'Request timed out. Please try again.'
        : 'Network error. Please check your connection.',
      actionable: 'Check your network connection and retry.'
    }
  }

  // Auth errors
  if (status === 401) {
    return {
      category: ErrorCategory.AUTH,
      userMessage: 'Session expired. Please reconnect.',
      actionable: 'Click the Reconnect button to start a new session.'
    }
  }

  // Permission errors (403)
  if (status === 403) {
    // Distinguish SQL integrity failures
    if (data?.detail?.includes('SQL integrity') || data?.detail?.includes('tampering')) {
      return {
        category: ErrorCategory.BUSINESS,
        userMessage: `Cannot execute query: ${data.detail}`,
        actionable: 'SQL verification failed. Please regenerate the query.'
      }
    }

    // CSRF failures
    if (data?.detail?.includes('CSRF') || data?.detail?.includes('token')) {
      return {
        category: ErrorCategory.AUTH,
        userMessage: 'Security token expired. Please refresh the page.',
        actionable: 'Refresh your browser to get a new security token.'
      }
    }

    // Generic permission denied
    return {
      category: ErrorCategory.PERMISSION,
      userMessage: data?.detail || 'Access denied',
      actionable: 'Contact your administrator if you should have access.'
    }
  }

  // Validation errors (422)
  if (status === 422) {
    let fieldErrors = []
    if (Array.isArray(data?.detail)) {
      fieldErrors = data.detail.map(err => {
        const field = err.loc?.slice(-1)[0] || 'field'
        return `${field}: ${err.msg}`
      })
    }

    return {
      category: ErrorCategory.VALIDATION,
      userMessage: fieldErrors.length
        ? fieldErrors.join(', ')
        : data?.detail || 'Invalid request data',
      actionable: 'Check your input and try again.'
    }
  }

  // Rate limiting
  if (status === 429) {
    return {
      category: ErrorCategory.BUSINESS,
      userMessage: 'Too many requests. Please wait a moment.',
      actionable: 'Wait 60 seconds before trying again.'
    }
  }

  // Server errors
  if (status >= 500) {
    return {
      category: ErrorCategory.SERVER,
      userMessage: data?.detail || 'Server error. Please try again later.',
      actionable: 'The server encountered an error. Try again in a few moments.'
    }
  }

  // Default
  return {
    category: ErrorCategory.BUSINESS,
    userMessage: data?.detail || data?.message || error.message || 'An error occurred',
    actionable: 'Please try again or contact support if the issue persists.'
  }
}

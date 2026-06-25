// ============================================
// FILE: frontend/src/main.js
// ============================================
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { getToastInstance } from './composables/useToast'
import { configService } from './utils/configService'
// Note: design-tokens.css is imported in App.vue

// Initialize app asynchronously to load config first
async function initializeApp() {
  // Load configuration from backend
  await configService.init()

  const app = createApp(App)
  app.use(createPinia())

  // ============================================
  // GLOBAL ERROR HANDLERS
  // ============================================

  // Get toast instance for error notifications
  const toast = getToastInstance()

  /**
   * Vue Error Handler
   * Catches errors in Vue components (render functions, watchers, lifecycle hooks)
   */
  app.config.errorHandler = (err, instance, info) => {
    if (import.meta.env.DEV) {
      console.error('[Vue Error]', err)
      console.error('Component:', instance?.$options?.name || 'Anonymous')
      console.error('Info:', info)
    }

    // Don't show toast for network errors (handled by axios interceptor)
    if (err.name === 'AxiosError' || err.message?.includes('Network Error')) {
      return
    }

    // Show user-friendly error toast
    const message = err.message || 'An unexpected error occurred'
    toast.error(message.length > 100 ? message.slice(0, 100) + '...' : message)
  }

  /**
   * Vue Warning Handler (development only)
   */
  if (import.meta.env.DEV) {
    app.config.warnHandler = (msg, instance, trace) => {
      console.warn('[Vue Warning]', msg)
      if (trace) console.warn('Trace:', trace)
    }
  }

  /**
   * Global uncaught JavaScript errors
   */
  window.onerror = (message, source, lineno, colno, error) => {
    if (import.meta.env.DEV) {
      console.error('[Global Error]', { message, source, lineno, colno, error })
    }

    // Avoid duplicate notifications for errors already handled by Vue
    if (error?.handled) return true

    // Don't show toast for script loading errors (usually third-party)
    if (message?.includes('Script error')) return true

    toast.error('An unexpected error occurred. Please try again.')
    return true // Prevents default browser error handling
  }

  /**
   * Unhandled Promise rejections
   */
  window.addEventListener('unhandledrejection', (event) => {
    if (import.meta.env.DEV) {
      console.error('[Unhandled Promise Rejection]', event.reason)
    }

    // Prevent default console error
    event.preventDefault()

    // Don't show toast for network errors (handled by axios interceptor)
    const reason = event.reason
    if (reason?.name === 'AxiosError' || reason?.message?.includes('Network Error')) {
      return
    }

    // Show user-friendly error
    const message = reason?.message || 'An operation failed unexpectedly'
    toast.error(message.length > 100 ? message.slice(0, 100) + '...' : message)
  })

  app.mount('#app')
}

// Start the application
initializeApp().catch((error) => {
  console.error('[Initialization Error]', error)
  // Show basic error if app fails to initialize
  document.body.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: center; height: 100vh; font-family: sans-serif; color: #ef4444;">
      <div style="text-align: center;">
        <h1>Failed to Initialize Application</h1>
        <p>Please refresh the page or contact support if the issue persists.</p>
        <pre style="color: #666; font-size: 12px; margin-top: 20px;">${error.message}</pre>
      </div>
    </div>
  `
})




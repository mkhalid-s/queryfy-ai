// ============================================
// FILE: frontend/src/utils/configService.js
// Configuration service - fetches config from backend
// ============================================

import api from './api'

class ConfigService {
  constructor() {
    this.config = null
  }

  async init() {
    try {
      // Fetch configuration from backend
      const backendConfig = await api.getFrontendConfig()

      // Merge with environment variables (env takes precedence)
      this.config = {
        timeouts: {
          default: parseInt(import.meta.env.VITE_REQUEST_TIMEOUT) || backendConfig.timeouts.default,
          analyst: parseInt(import.meta.env.VITE_ANALYST_TIMEOUT) || backendConfig.timeouts.analyst,
          streaming: backendConfig.timeouts.streaming,
        },
        limits: backendConfig.limits,
        features: backendConfig.features,
        app: backendConfig.app
      }

      // Configuration loaded successfully
    } catch (e) {
      console.warn('[ConfigService] Failed to load backend config, using defaults:', e.message)

      // Fallback to environment or hardcoded defaults
      this.config = {
        timeouts: {
          default: parseInt(import.meta.env.VITE_REQUEST_TIMEOUT) || 120000,
          analyst: parseInt(import.meta.env.VITE_ANALYST_TIMEOUT) || 180000,
          streaming: 120000,
        },
        limits: {
          max_query_length: 5000,
          max_export_rows: 1000000
        },
        features: {
          dml_enabled: true,
          followup_enabled: true,
          retry_enabled: true,
        },
        app: {
          name: 'QueryfyAI',
          version: 'unknown'
        }
      }
    }
  }

  getTimeout(type = 'default') {
    return this.config?.timeouts[type] || 120000
  }

  getLimit(key) {
    return this.config?.limits[key]
  }

  isFeatureEnabled(feature) {
    return this.config?.features[feature] !== false
  }

  getAppInfo() {
    return this.config?.app || {}
  }

  getConfig() {
    return this.config
  }
}

export const configService = new ConfigService()

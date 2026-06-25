// ============================================
// FILE: frontend/src/utils/networkStatus.js
// Network status detection and monitoring
// ============================================

import { ref } from 'vue'

class NetworkStatus {
  constructor() {
    this.online = ref(navigator.onLine)
    this.listeners = []

    // Listen to browser online/offline events
    window.addEventListener('online', () => this.handleOnline())
    window.addEventListener('offline', () => this.handleOffline())
  }

  isOnline() {
    return this.online.value
  }

  onChange(callback) {
    this.listeners.push(callback)
    return () => {
      const idx = this.listeners.indexOf(callback)
      if (idx > -1) this.listeners.splice(idx, 1)
    }
  }

  handleOnline() {
    this.online.value = true
    // Back online
    this.listeners.forEach(cb => cb(true))
  }

  handleOffline() {
    this.online.value = false
    console.warn('[Network] Offline')
    this.listeners.forEach(cb => cb(false))
  }
}

export const networkStatus = new NetworkStatus()

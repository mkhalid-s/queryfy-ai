// ============================================
// FILE: frontend/src/stores/session.js
// ============================================
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import mitt from 'mitt'

// Event emitter for session state changes
const sessionEvents = mitt()

export const useSessionStore = defineStore('session', () => {
  const session = ref(null)
  const isLoading = ref(false)
  
  const isActive = computed(() => !!session.value)
  const isLocked = computed(() => session.value?.locked || false)
  
  function setSession(data) {
    session.value = data
  }
  
  function clearSession() {
    session.value = null
  }
  
  function lockSession() {
    if (session.value) {
      session.value.locked = true
    }
  }

  function onSessionExpired(callback) {
    sessionEvents.on('session-expired', callback)
  }

  function emitSessionExpired() {
    sessionEvents.emit('session-expired')
    console.warn('Session expired event emitted')
  }

  return {
    session,
    isLoading,
    isActive,
    isLocked,
    setSession,
    clearSession,
    lockSession,
    onSessionExpired,
    emitSessionExpired
  }
})

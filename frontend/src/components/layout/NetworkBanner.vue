<template>
  <Transition name="slide-down">
    <div
      v-if="!isOnline"
      class="network-banner"
    >
      <WifiOff :size="16" />
      <span>You're offline. Some features are unavailable.</span>
      <button
        class="retry-btn"
        :disabled="retrying"
        @click="retry"
      >
        <Loader2
          v-if="retrying"
          :size="14"
          class="spin"
        />
        <RefreshCw
          v-else
          :size="14"
        />
        Retry Connection
      </button>
    </div>
  </Transition>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { WifiOff, RefreshCw, Loader2 } from 'lucide-vue-next'
import { networkStatus } from '@/utils/networkStatus'
import api from '@/utils/api'

const isOnline = ref(networkStatus.isOnline())
const retrying = ref(false)

let cleanupFn = null

onMounted(() => {
  // Listen to network status changes
  cleanupFn = networkStatus.onChange((online) => {
    isOnline.value = online
  })
})

onUnmounted(() => {
  if (cleanupFn) cleanupFn()
})

async function retry() {
  retrying.value = true

  try {
    // Test connectivity with health check
    await api.healthCheck()

    // If we reach here, connection is working
    if (!navigator.onLine) {
      // Manually trigger online event if browser didn't detect it
      networkStatus.handleOnline()
    }
    isOnline.value = true
  } catch {
    console.error('[Network] Still offline or server unreachable')
  } finally {
    retrying.value = false
  }
}
</script>

<style scoped>
.network-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  padding: var(--space-md);
  background: #f59e0b;
  color: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  font-size: var(--text-sm);
  font-weight: 500;
}

.retry-btn {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: var(--radius-sm);
  color: white;
  cursor: pointer;
  font-size: var(--text-sm);
  transition: all 0.2s;
}

.retry-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.3);
}

.retry-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* Slide down transition */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: transform 0.3s ease, opacity 0.3s ease;
}

.slide-down-enter-from {
  transform: translateY(-100%);
  opacity: 0;
}

.slide-down-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}
</style>

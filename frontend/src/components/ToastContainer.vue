<!--
============================================
ToastContainer.vue
============================================
Renders toast notifications with:
- Teleport to body (independent of DOM hierarchy)
- ARIA accessibility (role="status", aria-live)
- Pause on hover/focus
- Keyboard dismiss (Escape)
- Reduced motion support
- Action button support
-->
<template>
  <Teleport to="body">
    <div
      v-if="toasts.length > 0"
      class="toast-container"
      role="region"
      aria-label="Notifications"
    >
      <TransitionGroup
        name="toast-slide"
        tag="div"
        class="toast-stack"
      >
        <div
          v-for="toast in toasts"
          :key="toast.id"
          :class="['toast-item', `toast-${toast.type}`]"
          role="status"
          aria-live="polite"
          aria-atomic="true"
          tabindex="0"
          @mouseenter="handlePause(toast.id)"
          @mouseleave="handleResume(toast.id)"
          @focus="handlePause(toast.id)"
          @blur="handleResume(toast.id)"
        >
          <!-- Icon -->
          <span
            class="toast-icon"
            aria-hidden="true"
          >
            <CheckCircle2
              v-if="toast.type === 'success'"
              :size="18"
            />
            <XCircle
              v-else-if="toast.type === 'error'"
              :size="18"
            />
            <AlertTriangle
              v-else-if="toast.type === 'warning'"
              :size="18"
            />
            <Info
              v-else
              :size="18"
            />
          </span>

          <!-- Message -->
          <span class="toast-message">{{ toast.message }}</span>

          <!-- Action Button (optional) -->
          <button
            v-if="toast.action"
            class="toast-action"
            @click="handleAction(toast)"
          >
            {{ toast.action.label }}
          </button>

          <!-- Close Button -->
          <button
            class="toast-close"
            aria-label="Dismiss notification"
            @click="handleDismiss(toast.id)"
          >
            <X :size="16" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useToast } from '../composables/useToast'
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  X
} from 'lucide-vue-next'

const { toasts, remove, pause, resume } = useToast()

function handleDismiss(id) {
  remove(id)
}

function handlePause(id) {
  pause(id)
}

function handleResume(id) {
  resume(id)
}

function handleAction(toast) {
  if (toast.action?.onClick) {
    toast.action.onClick()
  }
  remove(toast.id)
}

// Keyboard support: Escape dismisses most recent toast
function handleKeydown(e) {
  if (e.key === 'Escape' && toasts.value.length > 0) {
    const lastToast = toasts.value[toasts.value.length - 1]
    remove(lastToast.id)
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.toast-container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 10000;
  max-width: 380px;
  width: calc(100vw - 40px);
  pointer-events: none;
}

.toast-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  color: white;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
  pointer-events: auto;
  backdrop-filter: blur(8px);
}

/* Toast type colors - QueryfyAI Palette */
.toast-success {
  background: linear-gradient(135deg, var(--color-success), var(--color-success-hover));
}

.toast-error {
  background: linear-gradient(135deg, var(--color-error), var(--color-error-hover));
}

.toast-warning {
  background: linear-gradient(135deg, var(--color-warning), var(--color-warning-hover));
}

.toast-info {
  background: linear-gradient(135deg, var(--color-info), var(--color-info-hover));
}

.toast-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.toast-message {
  flex: 1;
  min-width: 0;
  word-wrap: break-word;
}

.toast-action {
  flex-shrink: 0;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.toast-action:hover {
  background: rgba(255, 255, 255, 0.3);
}

.toast-close {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  transition: all 0.15s ease;
}

.toast-close:hover {
  background: rgba(255, 255, 255, 0.2);
  color: white;
}

/* Slide animations */
.toast-slide-enter-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.toast-slide-leave-active {
  transition: all 0.2s cubic-bezier(0.4, 0, 1, 1);
}

.toast-slide-enter-from {
  transform: translateX(100%);
  opacity: 0;
}

.toast-slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

.toast-slide-move {
  transition: transform 0.3s ease;
}

/* Reduced motion support (WCAG) */
@media (prefers-reduced-motion: reduce) {
  .toast-slide-enter-active,
  .toast-slide-leave-active,
  .toast-slide-move {
    transition: opacity 0.15s ease;
  }

  .toast-slide-enter-from,
  .toast-slide-leave-to {
    transform: none;
  }
}

/* Mobile responsiveness */
@media (max-width: 480px) {
  .toast-container {
    left: 12px;
    right: 12px;
    bottom: 12px;
    max-width: none;
    width: auto;
  }

  .toast-item {
    padding: 10px 12px;
    font-size: 13px;
  }
}
</style>

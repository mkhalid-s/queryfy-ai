<template>
  <div :class="['system-message', message.variant || 'info']">
    <div class="message-icon">
      <AlertCircle
        v-if="message.variant === 'error'"
        :size="16"
      />
      <AlertTriangle
        v-else-if="message.variant === 'warning'"
        :size="16"
      />
      <CheckCircle
        v-else-if="message.variant === 'success'"
        :size="16"
      />
      <Info
        v-else
        :size="16"
      />
    </div>
    <div class="message-content">
      <span class="message-text">{{ message.content?.text || message.text }}</span>
      <button
        v-if="message.action"
        class="action-link"
        @click="$emit('action', message.action)"
      >
        {{ message.action.label }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { Info, AlertCircle, AlertTriangle, CheckCircle } from 'lucide-vue-next'

defineProps({
  message: {
    type: Object,
    required: true
  }
})

defineEmits(['action'])
</script>

<style scoped>
.system-message {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  font-size: var(--text-sm);
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.system-message.info {
  background: var(--color-info-light);
  border-color: rgba(30, 183, 223, 0.2);
  color: var(--color-info);
}

.system-message.success {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.2);
  color: var(--color-success);
}

.system-message.warning {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.2);
  color: var(--color-warning);
}

.system-message.error {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.2);
  color: var(--color-error);
}

.message-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.message-content {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  align-items: center;
}

.message-text {
  line-height: 1.5;
}

.action-link {
  border: none;
  background: transparent;
  color: inherit;
  font-size: inherit;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
}

.action-link:hover {
  opacity: 0.8;
}
</style>

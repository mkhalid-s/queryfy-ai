<template>
  <div class="user-message">
    <div class="message-avatar">
      <User :size="16" />
    </div>
    <div class="message-content">
      <div class="message-header">
        <span class="sender-name">You</span>
        <span
          v-if="!message.content?.isOriginal"
          class="followup-badge"
        >
          follow-up
        </span>
        <span class="message-time">{{ formatTime(message.timestamp) }}</span>
      </div>
      <div class="message-text">
        {{ message.content?.text || message.text }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { User } from 'lucide-vue-next'

defineProps({
  message: {
    type: Object,
    required: true
  }
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.user-message {
  display: flex;
  gap: var(--space-sm);
  animation: slideIn 0.3s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--bg-input);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: 4px;
}

.sender-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.followup-badge {
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: 500;
}

.message-time {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-left: auto;
}

.message-text {
  padding: var(--space-sm) var(--space-md);
  background: var(--color-primary-light);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  border-top-left-radius: 4px;
  color: var(--text-primary);
  font-size: var(--text-base);
  line-height: 1.5;
  word-break: break-word;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .message-avatar {
    width: 28px;
    height: 28px;
  }

  .message-text {
    padding: var(--space-xs) var(--space-sm);
    font-size: var(--text-sm);
  }

  .message-time {
    display: none;
  }
}
</style>

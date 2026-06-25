<template>
  <header class="app-header">
    <!-- Left: Sidebar Toggle + Logo + Brand -->
    <div class="header-left">
      <!-- Sidebar Toggle Button -->
      <button
        class="icon-btn sidebar-toggle"
        title="Toggle History"
        @click="$emit('toggle-sidebar')"
      >
        <Menu :size="20" />
      </button>

      <div class="header-brand">
        <div class="logo">
          <svg
            viewBox="0 0 32 32"
            fill="none"
            width="44"
            height="44"
          >
            <defs>
              <linearGradient
                id="logoGradNew"
                x1="0%"
                y1="0%"
                x2="100%"
                y2="100%"
              >
                <stop
                  offset="0%"
                  style="stop-color:var(--color-primary)"
                />
                <stop
                  offset="100%"
                  style="stop-color:var(--color-primary-hover)"
                />
              </linearGradient>
            </defs>
            <circle
              cx="16"
              cy="16"
              r="15"
              fill="url(#logoGradNew)"
            />
            <path
              d="M8 10C8 8.9 8.9 8 10 8H18C19.1 8 20 8.9 20 10V14C20 15.1 19.1 16 18 16H12L9 19V16H10C8.9 16 8 15.1 8 14V10Z"
              fill="white"
              fill-opacity="0.95"
            />
            <path
              d="M22 13L24 16L22 19"
              stroke="white"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <ellipse
              cx="20"
              cy="22"
              rx="4"
              ry="1.5"
              fill="white"
              fill-opacity="0.9"
            />
            <path
              d="M16 22V25C16 25.8 17.8 26.5 20 26.5C22.2 26.5 24 25.8 24 25V22"
              stroke="white"
              stroke-width="1.5"
              fill="none"
            />
            <circle
              cx="11"
              cy="11"
              r="0.8"
              fill="#ffc000"
            />
            <circle
              cx="17"
              cy="12"
              r="0.5"
              fill="#ffc000"
            />
          </svg>
        </div>
        <span class="brand-name">QueryfyAI</span>
      </div>
    </div>

    <!-- Right: Actions -->
    <div class="header-actions">
      <!-- Connection Status Indicator -->
      <div
        v-if="hasSession"
        class="status-indicator connected"
      >
        <span class="status-dot" />
        <span class="status-text">Connected</span>
      </div>
      <div
        v-else
        class="status-indicator disconnected"
      >
        <span class="status-dot" />
        <span class="status-text">Not connected</span>
      </div>

      <!-- Theme Toggle -->
      <button
        class="icon-btn"
        :title="isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'"
        @click="$emit('toggle-theme')"
      >
        <Sun
          v-if="isDark"
          :size="18"
        />
        <Moon
          v-else
          :size="18"
        />
      </button>

      <!-- Context Studio -->
      <button
        v-if="hasSession"
        class="icon-btn"
        title="Context Studio"
        @click="$emit('open-context-studio')"
      >
        <Database :size="18" />
      </button>

      <!-- Settings -->
      <button
        class="icon-btn"
        title="Settings"
        @click="$emit('open-settings')"
      >
        <Settings :size="18" />
      </button>
    </div>
  </header>
</template>

<script setup>
import { Sun, Moon, Settings, Menu, Database } from 'lucide-vue-next'

defineProps({
  isDark: Boolean,
  hasSession: Boolean
})

defineEmits(['toggle-theme', 'open-settings', 'open-context-studio', 'toggle-sidebar'])
</script>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
  z-index: 100;
  box-shadow: var(--shadow-sm);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.sidebar-toggle {
  color: var(--text-muted);
  transition: all var(--transition-smooth);
}

.sidebar-toggle:hover {
  color: var(--color-primary);
  background: var(--color-primary-light);
  transform: translateY(-1px);
  box-shadow: var(--shadow-card);
}

.header-brand {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.logo {
  flex-shrink: 0;
}

.brand-name {
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
  box-shadow: var(--shadow-sm);
  transition: all var(--transition-smooth);
}

.status-indicator.connected {
  background: rgba(16, 185, 129, 0.1);
  color: var(--color-success);
}

.status-indicator.disconnected {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.status-indicator.connected .status-dot {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-smooth);
  position: relative;
}

.icon-btn:hover {
  background: var(--bg-input);
  color: var(--text-primary);
  transform: translateY(-1px);
  box-shadow: var(--shadow-card);
}

.icon-btn:active {
  transform: translateY(0) scale(0.98);
  box-shadow: var(--shadow-sm);
}

/* Mobile responsive */
@media (max-width: 480px) {
  .app-header {
    padding: var(--space-xs) var(--space-sm);
  }

  .logo svg {
    width: 36px;
    height: 36px;
  }

  .brand-name {
    font-size: var(--text-base);
  }

  .status-text {
    display: none;
  }

  .status-indicator {
    padding: 6px;
    min-width: auto;
  }

  .icon-btn {
    width: 32px;
    height: 32px;
  }
}
</style>

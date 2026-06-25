<!--
============================================
HistorySidebar.vue
============================================
Collapsible left sidebar for session history.
Shows recent and pinned queries with search functionality.
-->
<template>
  <!-- Backdrop for mobile overlay -->
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="isOpen && isMobile"
        class="sidebar-backdrop"
        @click="close"
      />
    </Transition>
  </Teleport>

  <!-- Sidebar -->
  <aside :class="['history-sidebar', { open: isOpen }]">
    <!-- Collapsed state: toggle button -->
    <button
      v-if="!isOpen"
      class="expand-btn"
      title="Open History"
      @click="openSidebar"
    >
      <PanelLeftOpen :size="20" />
    </button>

    <!-- Expanded state -->
    <template v-else>
      <div class="sidebar-header">
        <div class="header-title">
          <History :size="16" />
          <span>History</span>
        </div>
        <button
          class="collapse-btn"
          title="Close History"
          @click="close"
        >
          <PanelLeftClose :size="18" />
        </button>
      </div>

      <div class="sidebar-content">
        <ActivityPanel
          :max-display="15"
          @select="handleSelect"
        />
      </div>
    </template>
  </aside>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { History, PanelLeftOpen, PanelLeftClose } from 'lucide-vue-next'
import ActivityPanel from '../ActivityPanel.vue'

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:open', 'select'])

// Local state
const isOpen = computed({
  get: () => props.open,
  set: (value) => emit('update:open', value)
})

// Mobile detection
const isMobile = ref(false)

function checkMobile() {
  isMobile.value = window.innerWidth < 768
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})

// Actions
function openSidebar() {
  isOpen.value = true
}

function close() {
  isOpen.value = false
}

function handleSelect(query) {
  emit('select', query)
  // Close on mobile after selection
  if (isMobile.value) {
    close()
  }
}

// Keyboard shortcut: Escape to close
function handleKeydown(e) {
  if (e.key === 'Escape' && isOpen.value) {
    close()
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
.history-sidebar {
  position: fixed;
  top: var(--header-height, 56px);
  left: 0;
  bottom: 0;
  width: 0;
  background: var(--bg-card);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  z-index: 50;
  transition: width var(--transition-spring);
  overflow: hidden;
}

.history-sidebar.open {
  width: var(--sidebar-width, 300px);
  box-shadow: var(--shadow-elevated);
}

/* Expand button (collapsed state) - floating button */
.expand-btn {
  position: fixed;
  top: calc(var(--header-height, 56px) + 12px);
  left: 12px;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--transition-smooth);
  box-shadow: var(--shadow-card);
  z-index: 51;
}

.expand-btn:hover {
  background: var(--color-primary-light);
  color: var(--color-primary);
  border-color: var(--color-primary);
  box-shadow: var(--shadow-elevated);
  transform: translateY(-2px) scale(1.05);
}

.expand-btn:active {
  transform: translateY(0) scale(1);
  box-shadow: var(--shadow-card);
}

/* Header (expanded state) */
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-input);
  flex-shrink: 0;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.header-title svg {
  color: var(--color-primary);
}

.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--transition-smooth);
}

.collapse-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  transform: scale(1.1);
}

.collapse-btn:active {
  transform: scale(0.95);
}

/* Content area */
.sidebar-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* Override ActivityPanel styles for sidebar context */
.sidebar-content :deep(.activity-panel) {
  height: 100%;
  border: none;
  border-radius: 0;
  background: transparent;
}

/* Backdrop */
.sidebar-backdrop {
  position: fixed;
  inset: 0;
  top: var(--header-height, 56px);
  background: rgba(0, 0, 0, 0.4);
  z-index: 49;
  backdrop-filter: blur(2px);
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--transition-smooth);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Mobile adjustments */
@media (max-width: 767px) {
  .history-sidebar {
    width: 0;
  }

  .history-sidebar.open {
    width: min(var(--sidebar-width, 300px), 85vw);
  }

  .expand-btn {
    display: none;
  }
}
</style>

<template>
  <div
    ref="containerRef"
    class="chat-container"
  >
    <!-- Empty State -->
    <div
      v-if="conversation.length === 0"
      class="empty-state"
    >
      <div class="hero-icon-container">
        <!-- Ambient Glow -->
        <div class="ambient-glow" />

        <!-- Floating Data Points -->
        <div class="floating-particles">
          <span
            v-for="i in 12"
            :key="i"
            class="float-particle"
            :style="getFloatStyle(i)"
          />
        </div>

        <!-- Main Icon with Breathing Effect -->
        <div class="main-icon">
          <Database
            :size="32"
            class="icon-db"
          />
          <transition
            name="icon-swap"
            mode="out-in"
          >
            <component
              :is="codeIcons[currentCodeIcon]"
              :key="currentCodeIcon"
              :size="28"
              class="icon-code"
            />
          </transition>
        </div>

        <!-- Soft Pulse Ring -->
        <div class="pulse-ring" />
      </div>
      <h3>What would you like to know?</h3>
      <p class="tagline">
        <transition
          name="tagline-fade"
          mode="out-in"
        >
          <span :key="currentTagline">{{ taglines[currentTagline] }}</span>
        </transition>
      </p>
      <div class="example-queries">
        <span class="example-label">
          <Lightbulb :size="14" />
          Try one of these
        </span>
        <div class="example-chips">
          <button
            class="example-chip"
            @click="$emit('example-select', 'Show all tables in the database')"
          >
            <Database :size="14" />
            List tables
          </button>
          <button
            class="example-chip"
            @click="$emit('example-select', 'Describe the database schema')"
          >
            <FileText :size="14" />
            Schema info
          </button>
          <button
            class="example-chip"
            @click="$emit('example-select', 'What data is available?')"
          >
            <Search :size="14" />
            Explore data
          </button>
        </div>
      </div>
    </div>

    <!-- Conversation Messages -->
    <div
      v-else
      class="messages-list"
    >
      <template
        v-for="(message, index) in conversation"
        :key="message.id"
      >
        <!-- User Message -->
        <UserMessage
          v-if="message.type === 'user'"
          :message="message"
        />

        <!-- AI Response -->
        <AIResponseCard
          v-else-if="message.type === 'ai'"
          :message="message"
          :is-latest="index === conversation.length - 1"
          :is-executing="isExecuting && index === conversation.length - 1"
          :is-explaining="isExplaining && explainingMessageId === message.id"
          :session-id="sessionId"
          :dml-capabilities="dmlCapabilities"
          @run-query="$emit('run-query', message)"
          @explain="$emit('explain', message)"
          @copy="$emit('copy', message)"
          @export="$emit('export', message)"
          @feedback="(rating) => $emit('feedback', { message, rating })"
          @toggle-results="$emit('toggle-results', message)"
          @toggle-chart="$emit('toggle-chart', message)"
          @stop="$emit('stop', message)"
          @ask-question="(question) => $emit('ask-follow-up', question)"
        />

        <!-- System Message -->
        <SystemMessage
          v-else-if="message.type === 'system'"
          :message="message"
        />
      </template>

      <!-- Loading Indicator - only show before AI card is created -->
      <div
        v-if="isGenerating && !hasGeneratingAIMessage"
        class="loading-message"
      >
        <div class="loading-avatar">
          <Bot :size="16" />
        </div>
        <div class="loading-content">
          <div class="loading-dots">
            <span />
            <span />
            <span />
          </div>
          <span class="loading-text">Thinking...</span>
        </div>
      </div>
    </div>

    <!-- Scroll to bottom button -->
    <transition name="fade">
      <button
        v-if="showScrollButton"
        class="scroll-bottom-btn"
        @click="scrollToBottom"
      >
        <ChevronDown :size="16" />
      </button>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Bot, ChevronDown, Database, Braces, Code, Code2, FileCode, Terminal, FileJson, Hash, Binary, SquareCode, SquareTerminal, BrainCircuit, Sparkles, Lightbulb, FileText, Search } from 'lucide-vue-next'
import UserMessage from './UserMessage.vue'
import AIResponseCard from './AIResponseCard.vue'
import SystemMessage from './SystemMessage.vue'

const props = defineProps({
  conversation: {
    type: Array,
    required: true
  },
  isGenerating: Boolean,
  isExecuting: Boolean,
  isExplaining: Boolean,
  explainingMessageId: {
    type: String,
    default: null
  },
  sessionId: {
    type: String,
    default: null
  },
  dmlCapabilities: {
    type: Object,
    default: null
  }
})

defineEmits([
  'run-query',
  'explain',
  'copy',
  'export',
  'feedback',
  'toggle-results',
  'toggle-chart',
  'example-select',
  'stop',
  'ask-follow-up'
])

const containerRef = ref(null)
const showScrollButton = ref(false)

// Check if there's an AI message currently generating (to avoid double loading indicators)
const hasGeneratingAIMessage = computed(() => {
  if (!props.conversation.length) return false
  const lastMsg = props.conversation[props.conversation.length - 1]
  return lastMsg.type === 'ai' && lastMsg.content?.isGenerating === true
})

// Dynamic taglines
const taglines = [
  'Just ask. AI analyzes your data.',
  'From questions to insights in seconds.',
  'Your AI-powered data analyst.',
  'Chat with your database naturally.',
  'No code needed. Just curiosity.',
  'Turn plain English into answers.',
  'SQL or NoSQL — we speak both.',
  'One interface for all your databases.'
]
const currentTagline = ref(0)
let taglineInterval = null

// Cycling code icons
const codeIcons = [Braces, Code, Code2, FileCode, Terminal, FileJson, Hash, Binary, SquareCode, SquareTerminal, BrainCircuit, Sparkles]
const currentCodeIcon = ref(0)
let codeIconInterval = null

// Floating particle styles - random positions and timing
const getFloatStyle = (index) => {
  const positions = [
    { x: -50, delay: 0 },
    { x: -30, delay: 1.5 },
    { x: -10, delay: 0.8 },
    { x: 10, delay: 2.2 },
    { x: 30, delay: 0.3 },
    { x: 50, delay: 1.8 },
    { x: -40, delay: 2.5 },
    { x: 20, delay: 0.5 },
    { x: -20, delay: 1.2 },
    { x: 40, delay: 2.8 },
    { x: 0, delay: 1.0 },
    { x: -45, delay: 2.0 }
  ]
  const pos = positions[index - 1] || { x: 0, delay: 0 }
  const size = 3 + (index % 3) * 2
  const duration = 4 + (index % 4)

  return {
    '--float-x': `${pos.x}px`,
    '--float-delay': `${pos.delay}s`,
    '--float-duration': `${duration}s`,
    '--float-size': `${size}px`
  }
}

// Check if user has scrolled up
const handleScroll = () => {
  if (!containerRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = containerRef.value
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight
  showScrollButton.value = distanceFromBottom > 100
}

// Scroll to bottom with smooth animation
const scrollToBottom = () => {
  if (!containerRef.value) return
  containerRef.value.scrollTo({
    top: containerRef.value.scrollHeight,
    behavior: 'smooth'
  })
}

// Setup scroll listener and rotations
onMounted(() => {
  containerRef.value?.addEventListener('scroll', handleScroll)
  // Start tagline rotation
  taglineInterval = setInterval(() => {
    currentTagline.value = (currentTagline.value + 1) % taglines.length
  }, 3500)
  // Start code icon rotation
  codeIconInterval = setInterval(() => {
    currentCodeIcon.value = (currentCodeIcon.value + 1) % codeIcons.length
  }, 20000)
})

onUnmounted(() => {
  containerRef.value?.removeEventListener('scroll', handleScroll)
  if (taglineInterval) {
    clearInterval(taglineInterval)
  }
  if (codeIconInterval) {
    clearInterval(codeIconInterval)
  }
})

// Expose methods for parent
defineExpose({
  scrollToBottom: async () => {
    await nextTick()
    scrollToBottom()
  }
})
</script>

<style scoped>
.chat-container {
  flex: 1;
  min-height: 0;
  padding: var(--space-md) 0;
  position: relative;
  /* No internal scroll - parent handles scrolling (Gemini-like layout) */
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: var(--space-xl);
  color: var(--text-secondary);
  animation: fadeIn 0.5s ease;
}

/* Hero Icon Container */
.hero-icon-container {
  position: relative;
  width: 140px;
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-lg);
}

/* Ambient Glow */
.ambient-glow {
  position: absolute;
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--color-primary) 0%, transparent 70%);
  opacity: 0.12;
  animation: ambient-breathe 4s ease-in-out infinite;
}

@keyframes ambient-breathe {
  0%, 100% {
    transform: scale(1);
    opacity: 0.1;
  }
  50% {
    transform: scale(1.2);
    opacity: 0.18;
  }
}

/* Floating Data Points */
.floating-particles {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.float-particle {
  position: absolute;
  bottom: -10px;
  left: calc(50% + var(--float-x));
  width: var(--float-size);
  height: var(--float-size);
  border-radius: 50%;
  background: var(--color-primary);
  opacity: 0;
  animation: float-up var(--float-duration) ease-in-out infinite;
  animation-delay: var(--float-delay);
}

.float-particle:nth-child(odd) {
  background: #ffc000;
}

@keyframes float-up {
  0% {
    transform: translateY(0) scale(0);
    opacity: 0;
  }
  10% {
    opacity: 0.6;
    transform: translateY(-10px) scale(1);
  }
  90% {
    opacity: 0.4;
  }
  100% {
    transform: translateY(-140px) scale(0.5);
    opacity: 0;
  }
}

/* Main Icon with Breathing Effect */
.main-icon {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  z-index: 1;
  animation: icon-breathe 4s ease-in-out infinite;
}

@keyframes icon-breathe {
  0%, 100% {
    transform: scale(1);
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  }
  50% {
    transform: scale(1.05);
    box-shadow: 0 8px 32px rgba(0, 115, 157, 0.15);
  }
}

.icon-db {
  color: var(--color-primary);
}

.icon-code {
  position: absolute;
  bottom: -4px;
  right: 0px;
  color: #8b5cf6;
  animation: code-pulse 3s ease-in-out infinite;
  filter: drop-shadow(0 2px 4px rgba(139, 92, 246, 0.3));
}

@keyframes code-pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 0.85;
    filter: drop-shadow(0 2px 4px rgba(139, 92, 246, 0.3));
  }
  50% {
    transform: scale(1.15);
    opacity: 1;
    filter: drop-shadow(0 4px 12px rgba(139, 92, 246, 0.5));
  }
}

/* Icon swap transition */
.icon-swap-enter-active,
.icon-swap-leave-active {
  transition: all 0.3s ease;
}

.icon-swap-enter-from {
  opacity: 0;
  transform: scale(0.5) rotate(-15deg);
}

.icon-swap-leave-to {
  opacity: 0;
  transform: scale(0.5) rotate(15deg);
}

/* Soft Pulse Ring */
.pulse-ring {
  position: absolute;
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 1px solid var(--color-primary);
  opacity: 0;
  animation: pulse-expand 3s ease-out infinite;
}

@keyframes pulse-expand {
  0% {
    transform: scale(1);
    opacity: 0.5;
  }
  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}

.empty-state h3 {
  font-size: var(--text-2xl);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-sm) 0;
}

.empty-state .tagline {
  font-size: var(--text-lg);
  margin: 0 0 var(--space-xl) 0;
  max-width: 400px;
  color: var(--text-secondary);
  min-height: 1.5em;
}

/* Tagline fade transition */
.tagline-fade-enter-active,
.tagline-fade-leave-active {
  transition: all 0.4s ease;
}

.tagline-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.tagline-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.example-queries {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-md);
}

.example-label {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--text-sm);
  color: var(--text-muted);
  font-weight: 500;
}

.example-label svg {
  color: var(--color-primary);
}

.example-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-sm);
}

.example-chip {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: 10px 18px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-subtle);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all 0.2s ease;
}

.example-chip svg {
  color: var(--text-muted);
  transition: color 0.2s ease;
}

.example-chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 115, 157, 0.15);
}

.example-chip:hover svg {
  color: var(--color-primary);
}

/* Messages List */
.messages-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  padding-bottom: 60px; /* Space for scroll button */
}

/* Loading State */
.loading-message {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-md);
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.loading-avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.loading-content {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.loading-dots {
  display: flex;
  gap: 4px;
}

.loading-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
  animation: bounce 1.4s ease-in-out infinite;
}

.loading-dots span:nth-child(1) { animation-delay: 0s; }
.loading-dots span:nth-child(2) { animation-delay: 0.2s; }
.loading-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
  40% { transform: translateY(-6px); opacity: 1; }
}

.loading-text {
  font-size: var(--text-sm);
  color: var(--text-muted);
}

/* Scroll to Bottom Button */
.scroll-bottom-btn {
  position: absolute;
  bottom: 20px;
  right: 20px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--border-subtle);
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  transition: all 0.15s ease;
}

.scroll-bottom-btn:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

/* Fade transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .chat-container {
    padding: var(--space-sm) 0;
  }

  .empty-state {
    padding: var(--space-lg);
  }

  .empty-icon {
    width: 64px;
    height: 64px;
  }

  .example-chips {
    flex-direction: column;
    width: 100%;
  }

  .example-chip {
    width: 100%;
    text-align: center;
  }
}
</style>

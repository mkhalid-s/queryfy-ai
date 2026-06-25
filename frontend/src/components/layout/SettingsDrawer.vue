<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <transition name="fade">
      <div
        v-if="open"
        class="drawer-backdrop"
        @click="$emit('close')"
      />
    </transition>

    <!-- Drawer -->
    <transition name="slide">
      <div
        v-if="open"
        :class="['settings-drawer', { 'light-theme': !isDark }]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-drawer-title"
      >
        <!-- Header -->
        <div class="drawer-header">
          <h2 id="settings-drawer-title">
            Settings
          </h2>
          <button
            class="close-btn"
            @click="$emit('close')"
          >
            <X :size="20" />
          </button>
        </div>

        <!-- Content -->
        <div class="drawer-content">
          <!-- Connection Status -->
          <section class="settings-section">
            <h3 class="section-title">
              Connection Status
            </h3>
            <div class="status-card">
              <div class="status-row">
                <span class="status-label">Session</span>
                <span :class="['status-value', session ? 'connected' : 'disconnected']">
                  {{ session ? 'Active' : 'Not Connected' }}
                </span>
              </div>
              <template v-if="session">
                <div class="status-row">
                  <span class="status-label">Database</span>
                  <span class="status-value with-icon">
                    <Icon
                      :icon="getDBIcon(dbConfig.db_type)"
                      width="16"
                      height="16"
                    />
                    {{ getDBDisplayName(dbConfig.db_type) }}
                  </span>
                </div>
                <div
                  v-if="dbConfig.connection_url"
                  class="status-row"
                >
                  <span class="status-label">Host</span>
                  <span class="status-value muted">{{ getMaskedUrl(dbConfig.connection_url) }}</span>
                </div>
                <div
                  v-if="dbConfig.name"
                  class="status-row"
                >
                  <span class="status-label">Connection</span>
                  <span class="status-value">{{ dbConfig.name }}</span>
                </div>
                <div class="status-row">
                  <span class="status-label">LLM Provider</span>
                  <span class="status-value with-icon">
                    <Icon
                      :icon="getProviderIcon(llmConfig.provider)"
                      width="16"
                      height="16"
                    />
                    {{ getProviderDisplayName(llmConfig.provider) }}
                  </span>
                </div>
                <div
                  v-if="llmConfig.model"
                  class="status-row"
                >
                  <span class="status-label">Model</span>
                  <span class="status-value">{{ llmConfig.model }}</span>
                </div>
                <div
                  v-if="sessionDuration"
                  class="status-row"
                >
                  <span class="status-label">Duration</span>
                  <span class="status-value muted">{{ sessionDuration }}</span>
                </div>
                <div
                  v-if="queryCount > 0"
                  class="status-row"
                >
                  <span class="status-label">Queries</span>
                  <span class="status-value muted">{{ queryCount }} generated</span>
                </div>
                <div
                  v-if="tokenInfo"
                  class="status-row"
                >
                  <span class="status-label">Token Status</span>
                  <span class="status-value connected">Auto-managed</span>
                </div>
              </template>
            </div>
          </section>

          <!-- Database Configuration (only show when no session) -->
          <section
            v-if="!session"
            class="settings-section"
          >
            <h3 class="section-title">
              <Database :size="16" />
              Database
            </h3>

            <div class="form-group">
              <label>Database Type</label>
              <div
                class="custom-select"
                @click="toggleDbDropdown"
              >
                <div class="select-display">
                  <Icon
                    :icon="getDBIcon(dbConfig.db_type)"
                    width="18"
                    height="18"
                  />
                  <span>{{ getDBDisplayName(dbConfig.db_type) || 'Select database...' }}</span>
                  <ChevronDown
                    :size="16"
                    :class="['chevron', { open: dbDropdownOpen }]"
                  />
                </div>
                <transition name="dropdown">
                  <div
                    v-if="dbDropdownOpen"
                    class="select-dropdown"
                  >
                    <button
                      v-for="db in dbTypes"
                      :key="db.id"
                      :class="['select-option', { active: dbConfig.db_type === db.id }]"
                      @click.stop="selectDB(db.id)"
                    >
                      <Icon
                        :icon="db.icon"
                        width="18"
                        height="18"
                      />
                      <span class="option-label">{{ db.name }}</span>
                      <Check
                        v-if="dbConfig.db_type === db.id"
                        :size="14"
                        class="check-icon"
                      />
                    </button>
                  </div>
                </transition>
              </div>
            </div>

            <div class="form-group">
              <label>Connection URL</label>
              <input
                :value="dbConfig.connection_url"
                :placeholder="getDBExample"
                type="text"
                @input="updateDB('connection_url', $event.target.value)"
              >
            </div>

            <div class="form-group">
              <label>Connection Name (optional)</label>
              <input
                :value="dbConfig.name"
                placeholder="My Database"
                type="text"
                @input="updateDB('name', $event.target.value)"
              >
            </div>
          </section>

          <!-- LLM Configuration (only show when no session) -->
          <section
            v-if="!session"
            class="settings-section"
          >
            <h3 class="section-title">
              <Bot :size="16" />
              LLM Provider
            </h3>

            <div class="form-group">
              <label>Provider</label>
              <div
                class="custom-select"
                @click="toggleLlmDropdown"
              >
                <div class="select-display">
                  <Icon
                    :icon="getProviderIcon(llmConfig.provider)"
                    width="18"
                    height="18"
                  />
                  <span>{{ getProviderDisplayName(llmConfig.provider) || 'Select provider...' }}</span>
                  <ChevronDown
                    :size="16"
                    :class="['chevron', { open: llmDropdownOpen }]"
                  />
                </div>
                <transition name="dropdown">
                  <div
                    v-if="llmDropdownOpen"
                    class="select-dropdown select-dropdown-grouped"
                  >
                    <template
                      v-for="category in providerCategories"
                      :key="category"
                    >
                      <div class="dropdown-category">
                        {{ category }}
                      </div>
                      <button
                        v-for="provider in getProvidersByCategory(category)"
                        :key="provider.id"
                        :class="['select-option', { active: llmConfig.provider === provider.id }]"
                        @click.stop="selectLLM(provider.id)"
                      >
                        <Icon
                          :icon="provider.icon || 'mdi:robot'"
                          width="18"
                          height="18"
                        />
                        <span class="option-label">{{ provider.name }}</span>
                        <Check
                          v-if="llmConfig.provider === provider.id"
                          :size="14"
                          class="check-icon"
                        />
                      </button>
                    </template>
                  </div>
                </transition>
              </div>
            </div>

            <!-- OAuth Gateway Fields -->
            <template v-if="llmConfig.provider === 'oauth_gateway'">
              <div class="form-group">
                <label>Base URL</label>
                <input
                  :value="llmConfig.base_url"
                  placeholder="https://llm-gateway.company.com"
                  @input="updateLLM('base_url', $event.target.value)"
                >
              </div>
              <div class="form-group">
                <label>Token URL</label>
                <input
                  :value="llmConfig.token_url"
                  placeholder="https://auth.company.com/oauth/token"
                  @input="updateLLM('token_url', $event.target.value)"
                >
              </div>
              <div class="form-group">
                <label>Client ID</label>
                <input
                  :value="llmConfig.client_id"
                  @input="updateLLM('client_id', $event.target.value)"
                >
              </div>
              <div class="form-group">
                <label>Client Secret</label>
                <input
                  type="password"
                  :value="llmConfig.client_secret"
                  @input="updateLLM('client_secret', $event.target.value)"
                >
              </div>
              <div class="form-group">
                <label>Chat Endpoint</label>
                <input
                  :value="llmConfig.chat_endpoint"
                  placeholder="/v1/chat/completions"
                  @input="updateLLM('chat_endpoint', $event.target.value)"
                >
              </div>
            </template>

            <!-- Base URL (for providers that need it, except OAuth) -->
            <template v-if="currentProviderConfig.requiresBaseUrl && llmConfig.provider !== 'oauth_gateway'">
              <div class="form-group">
                <label>{{ getBaseUrlLabel }}</label>
                <input
                  :value="llmConfig.base_url"
                  :placeholder="getBaseUrlPlaceholder"
                  @input="updateLLM('base_url', $event.target.value)"
                >
              </div>
            </template>

            <!-- API Key (for providers that need it) -->
            <template v-if="currentProviderConfig.requiresApiKey">
              <div class="form-group">
                <label>API Key</label>
                <input
                  type="password"
                  :value="llmConfig.api_key"
                  @input="updateLLM('api_key', $event.target.value)"
                >
              </div>
            </template>

            <div class="form-group">
              <label>Model</label>
              <input
                :value="llmConfig.model"
                :placeholder="currentProviderConfig.defaultModel || 'gpt-4'"
                @input="updateLLM('model', $event.target.value)"
              >
            </div>
          </section>
        </div>

        <!-- Footer Actions -->
        <div class="drawer-footer">
          <button
            v-if="!session"
            class="btn btn-primary btn-full"
            @click="$emit('start-session')"
          >
            <Rocket :size="16" />
            Start Session
          </button>
          <template v-else>
            <button
              v-if="!showResetConfirm"
              class="btn btn-danger btn-full"
              @click="showResetConfirm = true"
            >
              <RotateCcw :size="16" />
              Reset Session
            </button>
            <div
              v-else
              class="reset-confirm"
            >
              <p class="confirm-text">
                End this session and start fresh?
              </p>
              <div class="confirm-actions">
                <button
                  class="btn btn-secondary"
                  @click="showResetConfirm = false"
                >
                  Cancel
                </button>
                <button
                  class="btn btn-danger"
                  @click="confirmReset"
                >
                  <RotateCcw :size="14" />
                  Yes, Reset
                </button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Icon } from '@iconify/vue'
import {
  X,
  Database,
  Bot,
  Rocket,
  RotateCcw,
  ChevronDown,
  Check
} from 'lucide-vue-next'
import api from '../../utils/api'
import {
  DB_TYPES_FALLBACK,
  LLM_PROVIDERS_FALLBACK,
  getProviderRequirements
} from '../../constants/config'

const props = defineProps({
  open: Boolean,
  session: {
    type: Object,
    default: null
  },
  llmConfig: {
    type: Object,
    default: null
  },
  dbConfig: {
    type: Object,
    default: null
  },
  tokenInfo: {
    type: Object,
    default: null
  },
  isDark: Boolean,
  queryCount: { type: Number, default: 0 },
  sessionStartTime: { type: [Date, String, Number], default: null }
})

const emit = defineEmits([
  'close',
  'update-llm',
  'update-db',
  'start-session',
  'reset-session'
])

// Reset confirmation state
const showResetConfirm = ref(false)

// Dropdown states
const dbDropdownOpen = ref(false)
const llmDropdownOpen = ref(false)

// Timer for live duration updates
const currentTime = ref(new Date())
let durationTimer = null

// Reset confirmation state when drawer closes
watch(() => props.open, (isOpen) => {
  if (!isOpen) {
    showResetConfirm.value = false
    dbDropdownOpen.value = false
    llmDropdownOpen.value = false
  }
})

// Confirm reset and emit with confirmed flag
const confirmReset = () => {
  showResetConfirm.value = false
  emit('reset-session', true)
  emit('close')
}

// Dropdown toggle functions
const toggleDbDropdown = () => {
  dbDropdownOpen.value = !dbDropdownOpen.value
  llmDropdownOpen.value = false
}

const toggleLlmDropdown = () => {
  llmDropdownOpen.value = !llmDropdownOpen.value
  dbDropdownOpen.value = false
}

const selectDB = (dbId) => {
  updateDB('db_type', dbId)
  dbDropdownOpen.value = false
}

const selectLLM = (providerId) => {
  updateLLM('provider', providerId)
  llmDropdownOpen.value = false
}

// Dynamic data from API with fallbacks
const dbTypes = ref(DB_TYPES_FALLBACK)
const llmProviders = ref(LLM_PROVIDERS_FALLBACK)

// Fetch data from API on mount
onMounted(async () => {
  // Start duration timer (update every second for live display)
  durationTimer = setInterval(() => {
    currentTime.value = new Date()
  }, 1000)

  try {
    const [dbResponse, llmResponse] = await Promise.all([
      api.getDBTypes().catch(() => null),
      api.getLLMProviders().catch(() => null)
    ])
    if (dbResponse?.db_types) {
      dbTypes.value = dbResponse.db_types
    }
    if (llmResponse?.providers) {
      llmProviders.value = llmResponse.providers
    }
  } catch (e) {
    console.warn('Using fallback config data:', e.message)
  }
})

// Cleanup timer on unmount
onUnmounted(() => {
  if (durationTimer) {
    clearInterval(durationTimer)
    durationTimer = null
  }
})

// Get provider requirements for current selection
const currentProviderConfig = computed(() => {
  return getProviderRequirements(props.llmConfig?.provider, llmProviders.value)
})

// Provider categories for grouped select
const providerCategories = computed(() => {
  const categories = [...new Set(llmProviders.value.map(p => p.category))]
  const order = ['Enterprise', 'Cloud', 'Fast', 'Local', 'OpenSource', 'Custom']
  return categories.sort((a, b) => order.indexOf(a) - order.indexOf(b))
})

const getProvidersByCategory = (category) => {
  return llmProviders.value.filter(p => p.category === category)
}

// Dynamic labels for base_url field based on provider
const getBaseUrlLabel = computed(() => {
  const labels = {
    azure: 'Azure Endpoint',
    ollama: 'Ollama Server URL',
    custom: 'Custom Endpoint URL',
    vertex_ai: 'GCP Project ID'
  }
  return labels[props.llmConfig?.provider] || 'Base URL'
})

const getBaseUrlPlaceholder = computed(() => {
  const placeholders = {
    azure: 'https://your-resource.openai.azure.com',
    ollama: 'http://localhost:11434',
    custom: 'https://your-api-endpoint.com',
    vertex_ai: 'your-gcp-project-id'
  }
  return placeholders[props.llmConfig?.provider] || 'https://api.example.com'
})

const getDBExample = computed(() => {
  const examples = {
    postgresql: 'postgresql://user:pass@host:5432/db',
    mysql: 'mysql://user:pass@host:3306/db',
    mongodb: 'mongodb://user:pass@host:27017/db',
    sqlserver: 'mssql://user:pass@host:1433/db',
    oracle: 'oracle://user:pass@host:1521/db',
    snowflake: 'snowflake://user:pass@account/db',
    bigquery: 'bigquery://project/dataset'
  }
  return examples[props.dbConfig?.db_type] || 'Enter connection URL'
})

const updateLLM = (key, value) => emit('update-llm', { [key]: value })
const updateDB = (key, value) => emit('update-db', { [key]: value })

// Get display name for database type
const getDBDisplayName = (dbType) => {
  const db = dbTypes.value.find(d => d.id === dbType)
  return db?.name || dbType || 'Unknown'
}

// Get icon for database type
const getDBIcon = (dbType) => {
  const db = dbTypes.value.find(d => d.id === dbType)
  return db?.icon || 'mdi:database'
}

// Get display name for LLM provider
const getProviderDisplayName = (providerId) => {
  const provider = llmProviders.value.find(p => p.id === providerId)
  return provider?.name || providerId || 'Unknown'
}

// Get icon for LLM provider
const getProviderIcon = (providerId) => {
  const provider = llmProviders.value.find(p => p.id === providerId)
  return provider?.icon || 'mdi:robot'
}

// Mask connection URL (hide password, show host/db)
const getMaskedUrl = (url) => {
  if (!url) return ''
  try {
    // Handle special cases like :memory:
    if (url.includes(':memory:')) return ':memory:'

    const parsed = new URL(url)
    const host = parsed.hostname || 'localhost'
    const port = parsed.port ? `:${parsed.port}` : ''
    const db = parsed.pathname?.replace(/^\//, '') || ''
    return `${host}${port}${db ? '/' + db : ''}`
  } catch {
    // If URL parsing fails, try to extract host manually
    const match = url.match(/@([^:/]+)(:\d+)?/)
    if (match) {
      return match[1] + (match[2] || '')
    }
    return url.substring(0, 30) + (url.length > 30 ? '...' : '')
  }
}

// Session duration computed (uses reactive currentTime for live updates)
const sessionDuration = computed(() => {
  if (!props.sessionStartTime) return null

  const start = new Date(props.sessionStartTime)
  if (isNaN(start.getTime())) return null

  const diffMs = currentTime.value - start

  const hours = Math.floor(diffMs / (1000 * 60 * 60))
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))
  const seconds = Math.floor((diffMs % (1000 * 60)) / 1000)

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`
  } else if (minutes > 0) {
    return `${minutes}m ${seconds}s`
  } else {
    return `${seconds}s`
  }
})
</script>

<style scoped>
/* Backdrop */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  z-index: 999;
}

/* Drawer */
.settings-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  max-width: 400px;
  background: var(--bg-app);
  border-left: 1px solid var(--border-subtle);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Header */
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.drawer-header h2 {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.close-btn {
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
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: var(--bg-input);
  color: var(--text-primary);
}

/* Content */
.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-md);
}

/* Sections */
.settings-section {
  margin-bottom: var(--space-lg);
}

.section-title {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-md) 0;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Status Card */
.status-card {
  padding: var(--space-md);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-xs) 0;
}

.status-row + .status-row {
  border-top: 1px solid var(--border-subtle);
  margin-top: var(--space-xs);
  padding-top: var(--space-sm);
}

.status-label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.status-value {
  font-size: var(--text-sm);
  font-weight: 500;
}

.status-value.connected {
  color: var(--color-success);
}

.status-value.disconnected {
  color: var(--text-muted);
}

.status-value.with-icon {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
}

.status-value.muted {
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-family: var(--font-mono, monospace);
}

/* Form Groups */
.form-group {
  margin-bottom: var(--space-md);
}

.form-group label {
  display: block;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: var(--space-xs);
}

.form-group input,
.form-group select {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: var(--text-base);
  transition: all 0.15s ease;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-group input:disabled,
.form-group select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-group input::placeholder {
  color: var(--text-muted);
}

/* Custom Select Dropdown */
.custom-select {
  position: relative;
  width: 100%;
}

.select-display {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: var(--text-base);
  cursor: pointer;
  transition: all 0.15s ease;
}

.select-display:hover {
  border-color: var(--border-focus);
}

.select-display span {
  flex: 1;
}

.select-display .chevron {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.select-display .chevron.open {
  transform: rotate(180deg);
}

.select-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 280px;
  overflow-y: auto;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  z-index: 100;
}

.select-dropdown-grouped {
  max-height: 320px;
}

.dropdown-category {
  padding: var(--space-xs) var(--space-md);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--bg-input);
  position: sticky;
  top: 0;
}

.select-option {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}

.select-option:hover {
  background: var(--bg-hover);
}

.select-option.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.select-option .option-label {
  flex: 1;
}

.select-option .check-icon {
  color: var(--color-primary);
}

/* Dropdown transition */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.2s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* Footer */
.drawer-footer {
  padding: var(--space-md);
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
}

.btn-primary:hover {
  background: var(--color-primary-hover);
}

.btn-danger {
  background: var(--color-error);
  color: white;
}

.btn-danger:hover {
  background: var(--color-error-hover);
}

.btn-secondary {
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
}

.btn-secondary:hover {
  background: var(--bg-hover);
  border-color: var(--border-focus);
}

.btn-full {
  width: 100%;
}

/* Reset Confirmation */
.reset-confirm {
  text-align: center;
}

.confirm-text {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin: 0 0 var(--space-md) 0;
}

.confirm-actions {
  display: flex;
  gap: var(--space-sm);
}

.confirm-actions .btn {
  flex: 1;
  padding: var(--space-sm) var(--space-md);
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}

/* Mobile */
@media (max-width: 480px) {
  .settings-drawer {
    max-width: 100%;
  }

  .select-dropdown {
    max-height: 240px;
  }
}
</style>

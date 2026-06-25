<template>
  <Teleport to="body">
    <div :class="['wizard-overlay', { 'light-theme': !isDark }]">
      <div class="wizard-modal">
        <!-- Header -->
        <div class="wizard-header">
          <h2>Welcome to QueryfyAI</h2>
          <p>Let's set up your connection to get started</p>
        </div>

        <!-- Progress -->
        <div class="wizard-progress">
          <div
            v-for="(step, index) in steps"
            :key="step.id"
            :class="['progress-step', {
              active: currentStep === index,
              completed: currentStep > index
            }]"
          >
            <div class="step-dot">
              <Check
                v-if="currentStep > index"
                :size="12"
              />
              <span v-else>{{ index + 1 }}</span>
            </div>
            <span class="step-label">{{ step.label }}</span>
          </div>
        </div>

        <!-- Step Content -->
        <div class="wizard-content">
          <!-- Step 1: Database -->
          <div
            v-if="currentStep === 0"
            class="step-content"
          >
            <h3>Select your database</h3>
            <div class="db-grid">
              <button
                v-for="db in dbTypes"
                :key="db.id"
                :class="['db-card', { selected: dbConfig.db_type === db.id }]"
                @click="selectDB(db.id)"
              >
                <Icon
                  :icon="db.icon"
                  width="32"
                  height="32"
                />
                <span>{{ db.name }}</span>
              </button>
            </div>
          </div>

          <!-- Step 2: Connection -->
          <div
            v-if="currentStep === 1"
            class="step-content"
          >
            <h3>Enter connection details</h3>
            <div class="form-group">
              <label>Connection URL</label>
              <input
                v-model="connectionUrl"
                :placeholder="getDBExample"
                @keydown.enter="nextStep"
              >
              <span class="form-hint">{{ getDBHint }}</span>
            </div>
            <div class="form-group">
              <label>Connection Name (optional)</label>
              <input
                v-model="connectionName"
                placeholder="My Production Database"
              >
            </div>
          </div>

          <!-- Step 3: LLM -->
          <div
            v-if="currentStep === 2"
            class="step-content"
          >
            <h3>Configure AI provider</h3>
            <div class="form-group">
              <label>Provider</label>
              <div
                class="custom-select"
                @click="toggleLlmDropdown"
              >
                <div class="select-display">
                  <Icon
                    :icon="getProviderIcon(provider)"
                    width="18"
                    height="18"
                  />
                  <span>{{ getProviderDisplayName(provider) }}</span>
                  <ChevronDown
                    :size="16"
                    :class="['chevron', { open: llmDropdownOpen }]"
                  />
                </div>
                <transition name="dropdown">
                  <div
                    v-if="llmDropdownOpen"
                    class="select-dropdown"
                    @click.stop
                  >
                    <template
                      v-for="category in providerCategories"
                      :key="category"
                    >
                      <div class="dropdown-category">
                        {{ category }}
                      </div>
                      <button
                        v-for="p in getProvidersByCategory(category)"
                        :key="p.id"
                        :class="['select-option', { active: provider === p.id }]"
                        @click="selectProvider(p.id)"
                      >
                        <Icon
                          :icon="p.icon || 'mdi:robot'"
                          width="18"
                          height="18"
                        />
                        <span class="option-label">{{ p.name }}</span>
                        <Check
                          v-if="provider === p.id"
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
            <template v-if="provider === 'oauth_gateway'">
              <div class="form-group">
                <label>Base URL</label>
                <input
                  v-model="oauthBaseUrl"
                  placeholder="https://llm-gateway.company.com"
                >
                <span class="form-hint">Your AI gateway endpoint URL</span>
              </div>
              <div class="form-group">
                <label>Chat Endpoint</label>
                <input
                  v-model="oauthChatEndpoint"
                  placeholder="/v1/chat/completions"
                >
                <span class="form-hint">Path for chat completions API (default: /v1/chat/completions)</span>
              </div>
              <div class="form-group">
                <label>Token URL</label>
                <input
                  v-model="oauthTokenUrl"
                  placeholder="https://auth.company.com/oauth/token"
                >
                <span class="form-hint">OAuth2 token endpoint</span>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Client ID</label>
                  <input v-model="oauthClientId">
                </div>
                <div class="form-group">
                  <label>Client Secret</label>
                  <input
                    v-model="oauthClientSecret"
                    type="password"
                  >
                </div>
              </div>
              <div class="form-group">
                <label>Scope</label>
                <input
                  v-model="oauthScope"
                  placeholder="api://your-scope/.default"
                >
                <span class="form-hint">OAuth scope for access token (e.g., api://app-id/.default)</span>
              </div>
            </template>

            <!-- Base URL (for providers that need it, except OAuth) -->
            <template v-else-if="currentProviderConfig.requiresBaseUrl">
              <div class="form-group">
                <label>{{ getBaseUrlLabel }}</label>
                <input
                  v-model="baseUrl"
                  :placeholder="getBaseUrlPlaceholder"
                >
              </div>
            </template>

            <!-- API Key (for providers that need it) -->
            <template v-if="currentProviderConfig.requiresApiKey && provider !== 'oauth_gateway'">
              <div class="form-group">
                <label>API Key</label>
                <input
                  v-model="apiKey"
                  type="password"
                  placeholder="sk-..."
                >
              </div>
            </template>

            <div class="form-group">
              <label>Model</label>
              <input
                v-model="model"
                :placeholder="currentProviderConfig.defaultModel || 'gpt-4'"
              >
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="wizard-footer">
          <button
            v-if="currentStep > 0"
            class="btn btn-secondary"
            @click="prevStep"
          >
            <ChevronLeft :size="16" />
            Back
          </button>
          <button
            class="btn btn-ghost"
            @click="$emit('skip')"
          >
            Skip for now
          </button>
          <button
            v-if="currentStep < steps.length - 1"
            :disabled="!canProceed"
            class="btn btn-primary"
            @click="nextStep"
          >
            Next
            <ChevronRight :size="16" />
          </button>
          <button
            v-else
            :disabled="!canComplete"
            class="btn btn-primary"
            @click="complete"
          >
            <Rocket :size="16" />
            Start
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { Icon } from '@iconify/vue'
import { Check, ChevronLeft, ChevronRight, ChevronDown, Rocket } from 'lucide-vue-next'
import api from '../../utils/api'
import {
  DB_TYPES_FALLBACK,
  LLM_PROVIDERS_FALLBACK,
  getProviderRequirements
} from '../../constants/config'

const props = defineProps({
  dbConfig: {
    type: Object,
    default: null
  },
  llmConfig: {
    type: Object,
    default: null
  },
  isDark: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['update-llm', 'update-db', 'complete', 'skip'])

// Steps
const steps = [
  { id: 'database', label: 'Database' },
  { id: 'connection', label: 'Connection' },
  { id: 'llm', label: 'AI Provider' }
]

const currentStep = ref(0)

// Dynamic data from API with fallbacks
const dbTypes = ref(DB_TYPES_FALLBACK)
const llmProviders = ref(LLM_PROVIDERS_FALLBACK)

// Fetch data from API on mount
onMounted(async () => {
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

// Get provider requirements for current selection
const currentProviderConfig = computed(() => {
  return getProviderRequirements(provider.value, llmProviders.value)
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

// Get provider display name
const getProviderDisplayName = (providerId) => {
  const p = llmProviders.value.find(p => p.id === providerId)
  return p?.name || providerId || 'Select provider...'
}

// Get provider icon
const getProviderIcon = (providerId) => {
  const p = llmProviders.value.find(p => p.id === providerId)
  return p?.icon || 'mdi:robot'
}

// Dropdown state
const llmDropdownOpen = ref(false)

const toggleLlmDropdown = () => {
  llmDropdownOpen.value = !llmDropdownOpen.value
}

const selectProvider = (providerId) => {
  provider.value = providerId
  llmDropdownOpen.value = false
}

// Form state
const connectionUrl = ref(props.dbConfig?.connection_url || '')
const connectionName = ref(props.dbConfig?.name || '')
const provider = ref(props.llmConfig?.provider || 'openai')
const apiKey = ref(props.llmConfig?.api_key || '')
const model = ref(props.llmConfig?.model || '')
const baseUrl = ref(props.llmConfig?.base_url || '')  // For non-OAuth providers needing base_url
const oauthBaseUrl = ref(props.llmConfig?.base_url || '')
const oauthChatEndpoint = ref(props.llmConfig?.chat_endpoint || '/v1/chat/completions')
const oauthTokenUrl = ref(props.llmConfig?.token_url || '')
const oauthClientId = ref(props.llmConfig?.client_id || '')
const oauthClientSecret = ref(props.llmConfig?.client_secret || '')
const oauthScope = ref(props.llmConfig?.auth_scope || '')

// Dynamic labels for base_url field based on provider
const getBaseUrlLabel = computed(() => {
  const labels = {
    azure: 'Azure Endpoint',
    ollama: 'Ollama Server URL',
    custom: 'Custom Endpoint URL',
    vertex_ai: 'GCP Project ID'
  }
  return labels[provider.value] || 'Base URL'
})

const getBaseUrlPlaceholder = computed(() => {
  const placeholders = {
    azure: 'https://your-resource.openai.azure.com',
    ollama: 'http://localhost:11434',
    custom: 'https://your-api-endpoint.com',
    vertex_ai: 'your-gcp-project-id'
  }
  return placeholders[provider.value] || 'https://api.example.com'
})

// Computed
const getDBExample = computed(() => {
  const examples = {
    postgresql: 'postgresql://user:password@localhost:5432/database',
    mysql: 'mysql://user:password@localhost:3306/database',
    mongodb: 'mongodb://user:password@localhost:27017/database',
    sqlserver: 'mssql://user:password@localhost:1433/database',
    oracle: 'oracle://user:password@localhost:1521/database',
    snowflake: 'snowflake://user:password@account/database/schema?warehouse=WH',
    bigquery: 'bigquery://project-id/dataset',
    redshift: 'redshift://user:password@cluster.region.redshift.amazonaws.com:5439/database',
    databricks: 'databricks://token@host?http_path=/sql/1.0/warehouses/abc',
    clickhouse: 'clickhouse://user:password@localhost:8123/database',
    athena: 'athena://region/database?s3_staging_dir=s3://bucket/path',
    trino: 'trino://user:password@localhost:8080/catalog/schema',
    presto: 'presto://user:password@localhost:8080/catalog/schema',
    hive: 'hive://user:password@localhost:10000/database',
    spark: 'spark://localhost:10001/database'
  }
  return examples[props.dbConfig?.db_type] || 'Enter connection URL'
})

const getDBHint = computed(() => {
  const hints = {
    postgresql: 'Format: postgresql://user:pass@host:port/database',
    mysql: 'Format: mysql://user:pass@host:port/database',
    mongodb: 'Format: mongodb://user:pass@host:port/database',
    sqlserver: 'Format: mssql://user:pass@host:port/database',
    oracle: 'Format: oracle://user:pass@host:port/sid',
    snowflake: 'Format: snowflake://user:pass@account/database/schema?warehouse=WH',
    bigquery: 'Format: bigquery://project-id/dataset',
    redshift: 'Format: redshift://user:pass@cluster.region.redshift.amazonaws.com:5439/database',
    databricks: 'Format: databricks://token@host?http_path=/sql/warehouses/id',
    clickhouse: 'Format: clickhouse://user:pass@host:8123/database',
    athena: 'Format: athena://region/database?s3_staging_dir=s3://bucket/path',
    trino: 'Format: trino://user:pass@host:8080/catalog/schema',
    presto: 'Format: presto://user:pass@host:8080/catalog/schema',
    hive: 'Format: hive://user:pass@host:10000/database',
    spark: 'Format: spark://host:10001/database'
  }
  return hints[props.dbConfig?.db_type] || ''
})

const canProceed = computed(() => {
  if (currentStep.value === 0) {
    return !!props.dbConfig?.db_type
  }
  if (currentStep.value === 1) {
    return !!connectionUrl.value
  }
  return true
})

const canComplete = computed(() => {
  if (provider.value === 'oauth_gateway') {
    return oauthBaseUrl.value && oauthTokenUrl.value && oauthClientId.value && oauthClientSecret.value
  }
  // Check requirements for the selected provider
  const reqs = currentProviderConfig.value
  if (reqs.requiresApiKey && !apiKey.value) return false
  if (reqs.requiresBaseUrl && !baseUrl.value) return false
  return true
})

// Methods
const selectDB = (dbType) => {
  emit('update-db', { db_type: dbType })
}

const nextStep = () => {
  if (currentStep.value === 1) {
    emit('update-db', {
      connection_url: connectionUrl.value,
      name: connectionName.value
    })
  }
  if (currentStep.value < steps.length - 1) {
    currentStep.value++
  }
}

const prevStep = () => {
  if (currentStep.value > 0) {
    currentStep.value--
  }
}

const complete = () => {
  // Emit final LLM config
  const llmUpdate = {
    provider: provider.value,
    model: model.value || currentProviderConfig.value.defaultModel || 'gpt-4'
  }

  if (provider.value === 'oauth_gateway') {
    llmUpdate.base_url = oauthBaseUrl.value
    llmUpdate.chat_endpoint = oauthChatEndpoint.value || '/v1/chat/completions'
    llmUpdate.token_url = oauthTokenUrl.value
    llmUpdate.client_id = oauthClientId.value
    llmUpdate.client_secret = oauthClientSecret.value
    llmUpdate.auth_scope = oauthScope.value
  } else {
    // Handle API key and base_url based on provider requirements
    const reqs = currentProviderConfig.value
    if (reqs.requiresApiKey) {
      llmUpdate.api_key = apiKey.value
    }
    if (reqs.requiresBaseUrl) {
      llmUpdate.base_url = baseUrl.value
    }
  }

  emit('update-llm', llmUpdate)
  emit('complete')
}

// Sync with props
watch(() => props.dbConfig, (config) => {
  if (config?.connection_url) connectionUrl.value = config.connection_url
  if (config?.name) connectionName.value = config.name
}, { deep: true })
</script>

<style scoped>
.wizard-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: var(--space-md);
}

.wizard-modal {
  width: 100%;
  max-width: 600px;
  max-height: 90vh;
  background: var(--bg-app);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* Header */
.wizard-header {
  padding: var(--space-lg);
  text-align: center;
  border-bottom: 1px solid var(--border-subtle);
}

.wizard-header h2 {
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-xs) 0;
}

.wizard-header p {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin: 0;
}

/* Progress */
.wizard-progress {
  display: flex;
  justify-content: center;
  gap: var(--space-lg);
  padding: var(--space-md);
  background: var(--bg-card);
}

.progress-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
}

.step-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  background: var(--bg-app);
  transition: all 0.2s ease;
}

.progress-step.active .step-dot {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.progress-step.completed .step-dot {
  border-color: var(--color-success);
  background: var(--color-success);
  color: white;
}

.step-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.progress-step.active .step-label {
  color: var(--text-primary);
}

/* Content */
.wizard-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-lg);
}

.step-content h3 {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-md) 0;
}

/* Database Grid */
.db-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-sm);
}

.db-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-xs);
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.db-card:hover {
  color: var(--text-primary);
  background: var(--bg-card);
  transform: translateY(-4px);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.15), 0 4px 8px rgba(0, 0, 0, 0.1);
}

.db-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  color: var(--color-primary);
  box-shadow: 0 4px 12px rgba(0, 115, 157, 0.25);
}

/* Database icon styling */
.db-card :deep(svg) {
  width: 32px;
  height: 32px;
  color: var(--text-muted);
  transition: all 0.2s ease;
}

.db-card:hover :deep(svg) {
  color: var(--color-primary);
  transform: scale(1.08);
}

.db-card.selected :deep(svg) {
  color: var(--color-primary);
}

.db-card span {
  font-size: 11px;
  font-weight: 500;
  text-align: center;
  line-height: 1.2;
}

/* Form */
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
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-hint {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-top: var(--space-xs);
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
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.2);
  z-index: 100;
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

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-md);
}

/* Footer */
.wizard-footer {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-md) var(--space-lg);
  border-top: 1px solid var(--border-subtle);
}

.btn {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
  margin-left: auto;
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-input);
  color: var(--text-secondary);
}

.btn-secondary:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.btn-ghost {
  background: transparent;
  color: var(--text-muted);
}

.btn-ghost:hover {
  color: var(--text-secondary);
}

/* Tablet */
@media (max-width: 600px) {
  .db-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

/* Mobile */
@media (max-width: 480px) {
  .wizard-modal {
    max-height: 100vh;
    border-radius: 0;
  }

  .db-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .form-row {
    grid-template-columns: 1fr;
  }

  .wizard-progress {
    gap: var(--space-sm);
  }

  .step-label {
    display: none;
  }
}

/* Light theme adjustments */
.wizard-overlay.light-theme .db-card {
  background: white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04);
}

.wizard-overlay.light-theme .db-card:hover {
  background: white;
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.1), 0 4px 8px rgba(0, 0, 0, 0.06);
}

.wizard-overlay.light-theme .db-card.selected {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  box-shadow: 0 4px 12px rgba(0, 115, 157, 0.2);
}
</style>

/**
 * Shared configuration constants for QueryfyAI
 *
 * These serve as fallbacks when API is unavailable.
 * Primary data should be fetched from:
 * - /api/db-types
 * - /api/llm-providers
 */

// ============================================
// Database Types - Fallback Data
// ============================================
export const DB_TYPES_FALLBACK = [
  // SQL Databases
  { id: 'postgresql', name: 'PostgreSQL', icon: 'simple-icons:postgresql', category: 'SQL' },
  { id: 'mysql', name: 'MySQL', icon: 'simple-icons:mysql', category: 'SQL' },
  { id: 'sqlserver', name: 'SQL Server', icon: 'simple-icons:microsoftsqlserver', category: 'SQL' },
  { id: 'oracle', name: 'Oracle', icon: 'simple-icons:oracle', category: 'SQL' },
  // Cloud Data Warehouses
  { id: 'snowflake', name: 'Snowflake', icon: 'simple-icons:snowflake', category: 'Cloud' },
  { id: 'bigquery', name: 'BigQuery', icon: 'simple-icons:googlebigquery', category: 'Cloud' },
  { id: 'redshift', name: 'Redshift', icon: 'simple-icons:amazonredshift', category: 'Cloud' },
  { id: 'databricks', name: 'Databricks', icon: 'simple-icons:databricks', category: 'Cloud' },
  // Analytics Engines
  { id: 'clickhouse', name: 'ClickHouse', icon: 'simple-icons:clickhouse', category: 'Analytics' },
  { id: 'athena', name: 'Athena', icon: 'simple-icons:amazonaws', category: 'Analytics' },
  { id: 'trino', name: 'Trino', icon: 'simple-icons:trino', category: 'Analytics' },
  { id: 'presto', name: 'Presto', icon: 'simple-icons:presto', category: 'Analytics' },
  { id: 'hive', name: 'Hive', icon: 'simple-icons:apachehive', category: 'Analytics' },
  { id: 'spark', name: 'Spark SQL', icon: 'simple-icons:apachespark', category: 'Analytics' },
  // NoSQL
  { id: 'mongodb', name: 'MongoDB', icon: 'simple-icons:mongodb', category: 'NoSQL' },
  { id: 'cassandra', name: 'Cassandra', icon: 'simple-icons:apachecassandra', category: 'NoSQL' },
  { id: 'dynamodb', name: 'DynamoDB', icon: 'simple-icons:amazondynamodb', category: 'NoSQL' },
  // Embedded
  { id: 'duckdb', name: 'DuckDB', icon: 'simple-icons:duckdb', category: 'Embedded' },
  { id: 'sqlite', name: 'SQLite', icon: 'simple-icons:sqlite', category: 'Embedded' }
]

// ============================================
// LLM Providers - Fallback Data
// ============================================
export const LLM_PROVIDERS_FALLBACK = [
  // Enterprise
  {
    id: 'oauth_gateway',
    name: 'OAuth Gateway (Enterprise)',
    icon: 'mdi:shield-key',
    category: 'Enterprise',
    requiresApiKey: false,
    requiresBaseUrl: true,
    requiresOAuth: true,
    defaultModel: 'gpt-4'
  },
  // Cloud Providers
  {
    id: 'openai',
    name: 'OpenAI',
    icon: 'simple-icons:openai',
    category: 'Cloud',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'gpt-4'
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    icon: 'simple-icons:anthropic',
    category: 'Cloud',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'claude-sonnet-4-20250514'
  },
  {
    id: 'azure',
    name: 'Azure OpenAI',
    icon: 'simple-icons:microsoftazure',
    category: 'Cloud',
    requiresApiKey: true,
    requiresBaseUrl: true,
    requiresOAuth: false,
    defaultModel: 'gpt-4'
  },
  {
    id: 'bedrock',
    name: 'AWS Bedrock',
    icon: 'simple-icons:amazonaws',
    category: 'Cloud',
    requiresApiKey: false,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'anthropic.claude-3-sonnet-20240229-v1:0'
  },
  {
    id: 'vertex_ai',
    name: 'Google Vertex AI',
    icon: 'simple-icons:googlecloud',
    category: 'Cloud',
    requiresApiKey: false,
    requiresBaseUrl: true,
    requiresOAuth: false,
    defaultModel: 'gemini-1.5-pro'
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    icon: 'simple-icons:google',
    category: 'Cloud',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'gemini-1.5-pro'
  },
  // Fast Inference
  {
    id: 'groq',
    name: 'Groq',
    icon: 'mdi:lightning-bolt',
    category: 'Fast',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'llama-3.1-70b-versatile'
  },
  // Local
  {
    id: 'ollama',
    name: 'Ollama (Local)',
    icon: 'mdi:server',
    category: 'Local',
    requiresApiKey: false,
    requiresBaseUrl: true,
    requiresOAuth: false,
    defaultModel: 'llama3'
  },
  // Open Source
  {
    id: 'together',
    name: 'Together AI',
    icon: 'mdi:account-group',
    category: 'OpenSource',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'meta-llama/Llama-3-70b-chat-hf'
  },
  {
    id: 'mistral',
    name: 'Mistral AI',
    icon: 'simple-icons:mistral',
    category: 'OpenSource',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'mistral-large-latest'
  },
  {
    id: 'cohere',
    name: 'Cohere',
    icon: 'mdi:alpha-c-circle',
    category: 'OpenSource',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'command-r-plus'
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    icon: 'mdi:magnify-scan',
    category: 'OpenSource',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'deepseek-chat'
  },
  {
    id: 'replicate',
    name: 'Replicate',
    icon: 'mdi:cloud-sync',
    category: 'OpenSource',
    requiresApiKey: true,
    requiresBaseUrl: false,
    requiresOAuth: false,
    defaultModel: 'meta/llama-2-70b-chat'
  },
  // Custom
  {
    id: 'custom',
    name: 'Custom Endpoint',
    icon: 'mdi:api',
    category: 'Custom',
    requiresApiKey: true,
    requiresBaseUrl: true,
    requiresOAuth: false,
    defaultModel: 'gpt-4'
  }
]

// ============================================
// Icon Fallbacks (for unknown types)
// ============================================
export const DEFAULT_DB_ICON = 'mdi:database'
export const DEFAULT_LLM_ICON = 'mdi:brain'

// ============================================
// Helper Functions
// ============================================

/**
 * Get icon for a database type (with fallback)
 */
export function getDbIcon(dbTypeId, dbTypes = []) {
  const dbType = dbTypes.find(d => d.id === dbTypeId)
  if (dbType?.icon) return dbType.icon

  // Check fallback
  const fallback = DB_TYPES_FALLBACK.find(d => d.id === dbTypeId)
  return fallback?.icon || DEFAULT_DB_ICON
}

/**
 * Get icon for an LLM provider (with fallback)
 */
export function getLlmIcon(providerId, providers = []) {
  const provider = providers.find(p => p.id === providerId)
  if (provider?.icon) return provider.icon

  // Check fallback
  const fallback = LLM_PROVIDERS_FALLBACK.find(p => p.id === providerId)
  return fallback?.icon || DEFAULT_LLM_ICON
}

/**
 * Get provider config requirements
 */
export function getProviderRequirements(providerId, providers = []) {
  const provider = providers.find(p => p.id === providerId) ||
                   LLM_PROVIDERS_FALLBACK.find(p => p.id === providerId)

  return {
    requiresApiKey: provider?.requiresApiKey ?? true,
    requiresBaseUrl: provider?.requiresBaseUrl ?? false,
    requiresOAuth: provider?.requiresOAuth ?? false,
    defaultModel: provider?.defaultModel ?? 'gpt-4'
  }
}

"""
QueryfyAI - Pydantic Models
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field, field_validator

# ============== LLM Configuration ==============
# Supported LLM providers - all through LiteLLM unified interface
LlmProviders = Literal[
    # Enterprise & Corporate
    "oauth_gateway",  # Custom OAuth2 gateway (corporate environments)
    # Major Cloud Providers
    "openai",  # OpenAI API (GPT-4, GPT-4o, etc.)
    "anthropic",  # Anthropic API (Claude)
    "azure",  # Azure OpenAI Service
    "bedrock",  # AWS Bedrock (Claude, Llama, Titan)
    "vertex_ai",  # Google Cloud Vertex AI (Gemini)
    "gemini",  # Google Gemini API (direct)
    # Fast Inference
    "groq",  # Groq (ultra-fast inference)
    # Local & Self-hosted
    "ollama",  # Ollama (local LLM)
    # Open Source Model Providers
    "together",  # Together AI (open source models)
    "mistral",  # Mistral AI
    "cohere",  # Cohere (Command-R)
    "replicate",  # Replicate
    "deepseek",  # DeepSeek
    # Fallback
    "custom",  # Custom OpenAI-compatible endpoint
]


class LLMConfig(BaseModel):
    provider: LlmProviders

    # OAuth Gateway Fields
    base_url: Optional[str] = None
    token_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    auth_scope: Optional[str] = None
    auth_type: Optional[str] = "client_credentials"
    tenant: Optional[str] = None
    star: Optional[str] = None
    chat_endpoint: Optional[str] = None

    # Direct API Fields
    api_key: Optional[str] = None
    model: str = "gpt-4"

    # Complexity Routing: Use faster/cheaper model for simple queries
    fast_model: Optional[str] = None  # e.g., "gpt-4o-mini", "claude-3-haiku"
    enable_complexity_routing: bool = False  # Enable automatic model selection

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v):
        valid = [
            "oauth_gateway",
            "openai",
            "anthropic",
            "azure",
            "custom",
            "bedrock",
            "vertex_ai",
            "gemini",
            "groq",
            "ollama",
            "together",
            "mistral",
            "cohere",
            "replicate",
            "deepseek",
        ]
        if v not in valid:
            raise ValueError(f"Provider must be one of: {valid}")
        return v


# ============== Database Configuration ==============
# Supported database types
SupportedDbTypes = Literal[
    # Async (native connection pooling)
    "postgresql",
    "mysql",
    "mongodb",
    # Cloud Data Warehouses
    "snowflake",
    "bigquery",
    "databricks",
    "redshift",
    # Enterprise RDBMS
    "sqlserver",
    "oracle",
    # Data Lakes & Analytics
    "athena",
    "trino",
    "presto",
    "clickhouse",
    "hive",
    "spark",
    # Embedded/Local
    "duckdb",
    "sqlite",
    # NoSQL
    "cassandra",
    "dynamodb",
]


class DatabaseConfig(BaseModel):
    db_type: SupportedDbTypes
    connection_url: str
    name: Optional[str] = None

    @field_validator("connection_url")
    @classmethod
    def validate_url(cls, v):
        if not v or len(v) < 10:
            raise ValueError("Invalid connection URL")
        return v


# ============== Session Models ==============
class SessionCreateRequest(BaseModel):
    llm_config: LLMConfig
    db_config: DatabaseConfig


class SessionResponse(BaseModel):
    session_id: str
    message: str
    locked: bool = False
    csrf_token: Optional[str] = None  # Security: CSRF protection token
    schema_ready: bool = True  # Indicates if schema extraction is complete
    connection_hash: Optional[str] = (
        None  # For history filtering by database connection
    )
    db_type: Optional[str] = None  # Database type for history filtering


class SessionInfo(BaseModel):
    id: str
    created_at: str
    updated_at: str
    locked: bool
    history_count: int
    db_type: str
    llm_provider: str


# ============== Query Models ==============
class QueryRequest(BaseModel):
    session_id: str
    natural_language: str = Field(..., min_length=3, max_length=5000)


class QueryResponse(BaseModel):
    sql: Optional[str] = None
    query_id: Optional[str] = None
    sql_hash: Optional[str] = None  # Security: Hash for SQL integrity verification
    warnings: Optional[List[str]] = None
    error: Optional[str] = None
    message: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None  # LLM token usage and cost data


class ExplainRequest(BaseModel):
    session_id: str
    sql_query: str
    stream: bool = False  # If True, returns SSE stream instead of JSON


class ExplainResponse(BaseModel):
    explanation: str
    usage: Optional[Dict[str, Any]] = None  # LLM token usage and cost data


class ExecuteQueryRequest(BaseModel):
    session_id: str
    sql_query: str
    limit: int = Field(default=500, ge=1, le=1000000)
    query_id: Optional[str] = None  # Security: ID of the generated query
    sql_hash: Optional[str] = None  # Security: Hash for integrity verification
    force_refresh: bool = False  # Bypass cache and get fresh data
    # Phase 4.3: when present, the export endpoint will source rows from
    # the ResultCache instead of re-executing the SQL. Eliminates the
    # "summary says 200 / export gives 9000" drift by guaranteeing the
    # exported data matches the analysed data exactly. Falls back to
    # SQL re-execution on a cache miss / TTL expiry.
    rows_ref: Optional[str] = None


class ReexecuteFromHistoryRequest(BaseModel):
    """
    Request to re-execute a query from history.

    SECURITY: This endpoint does NOT accept SQL from the client.
    The SQL is fetched server-side from history using query_id.
    This allows cross-session re-execution without sql_hash verification.

    Connection verification ensures queries are only re-executed on
    the same database they were originally run on.
    """

    session_id: str
    query_id: str  # Lookup key for history entry
    limit: int = Field(default=500, ge=1, le=1000000)
    force_refresh: bool = False  # Bypass cache and get fresh data


class ExecuteQueryResponse(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    execution_time: float = 0
    has_more: bool = False  # Indicates if more rows exist beyond the limit
    warnings: Optional[List[str]] = None  # Security: Size limit warnings
    from_cache: bool = False  # Indicates if result came from cache
    db_type: Optional[str] = None  # Database type (postgresql, mongodb, etc.)


# ============== Feedback Models ==============
class FeedbackRequest(BaseModel):
    session_id: str
    query_id: str
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


# ============== History Models ==============
class HistoryEntry(BaseModel):
    """
    Extended history entry with full context for re-execution and conversation restore.

    Stores sql_hash to allow re-executing past queries without regeneration,
    and full analyst mode data for cross-session conversation persistence.
    """

    id: str
    query: str  # Natural language query
    sql: str  # Generated SQL
    timestamp: str
    feedback_rating: Optional[int] = None

    # New fields for improved history functionality
    sql_hash: Optional[str] = None  # For re-execution without regeneration
    explanation: Optional[str] = None  # AI-generated explanation
    pinned: bool = False  # User-pinned queries
    connection_id: Optional[str] = None  # Which database connection was used
    db_type: Optional[str] = None  # Database type (mysql, postgresql, etc.)
    success: Optional[bool] = None  # Whether execution succeeded
    error_message: Optional[str] = None  # Error message if execution failed

    # Analyst mode fields for full conversation restore
    mode: Optional[str] = None  # 'standard' or 'analyst'
    answer: Optional[str] = None  # Analyst mode synthesized answer
    key_findings: Optional[List[str]] = None  # Array of insights
    confidence: Optional[float] = None  # 0-1 confidence score
    chart_spec: Optional[Dict[str, Any]] = None  # Chart configuration with data
    raw_result_summary: Optional[Dict[str, Any]] = None  # {columns, row_count, sample_rows}
    tools_used: Optional[List[str]] = None  # Array of tool names
    agent_steps: Optional[List[Dict[str, Any]]] = None  # Array of step objects

    # Conversation threading
    is_follow_up: Optional[bool] = None  # Whether this is a follow-up query
    conversation_turn: Optional[int] = None  # Turn number in conversation
    session_id: Optional[str] = None  # Session that created this entry (for grouping)


class HistoryResponse(BaseModel):
    history: List[HistoryEntry]


class PinnedQueryRequest(BaseModel):
    """Request to pin/unpin a query"""

    query_id: str
    pinned: bool


class HistorySearchRequest(BaseModel):
    """Request to search history"""

    search_term: Optional[str] = None
    pinned_only: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


# ============== Token Models ==============
class TokenInfo(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    expires_at: datetime
    obtained_at: datetime
    scope: Optional[str] = None


# ============== Database Types ==============
class DBTypeInfo(BaseModel):
    id: str
    name: str
    port: Optional[int]
    example: str
    icon: Optional[str] = None  # Iconify icon name (e.g., 'simple-icons:postgresql')
    category: Optional[str] = (
        None  # Category for grouping (e.g., 'SQL', 'Cloud', 'Embedded')
    )


# ============== LLM Provider Types ==============
class LLMProviderInfo(BaseModel):
    id: str
    name: str
    icon: Optional[str] = None  # Iconify icon name
    category: Optional[str] = None  # Category (e.g., 'Cloud', 'Local', 'Enterprise')
    requiresApiKey: bool = True
    requiresBaseUrl: bool = False
    requiresOAuth: bool = False
    defaultModel: Optional[str] = None
    description: Optional[str] = None


class LLMProvidersResponse(BaseModel):
    providers: List[LLMProviderInfo]


class DBTypesResponse(BaseModel):
    db_types: List[DBTypeInfo]


# ============== Test Connection ==============
class TestConnectionResponse(BaseModel):
    success: bool
    message: str


class TestLLMResponse(BaseModel):
    success: bool
    message: str
    response_preview: Optional[str] = None


# ============== Default Configuration ==============


def mask_connection_url(url: str) -> str:
    """Mask password in database connection URL for safe exposure to frontend.

    Uses urllib.parse for reliable URL parsing. Replaces the password
    portion with '****' while preserving all other URL components.
    """
    if not url:
        return url
    try:
        parsed = urlparse(url)
        if parsed.password:
            # Reconstruct netloc to reliably mask password, regardless of URL encoding
            userinfo = parsed.username or ""
            masked_netloc = f"{userinfo}:****@"
            hostname = parsed.hostname or ""
            if parsed.port is not None:
                masked_netloc += f"{hostname}:{parsed.port}"
            else:
                masked_netloc += hostname
            return urlunparse(parsed._replace(netloc=masked_netloc))
        return url
    except Exception:
        return url  # Return as-is if parsing fails


class DefaultLLMConfig(BaseModel):
    """
    Default LLM configuration exposed to frontend.

    SECURITY: Sensitive fields (api_key, client_secret) are NOT included.
    Instead, boolean indicators (*_set fields) show whether values are configured.
    All string fields contain actual values or empty strings, never masked placeholders.
    """

    provider: str  # LLM provider name (actual value)
    base_url: str  # OAuth gateway base URL (actual value or empty)
    token_url: str  # OAuth token endpoint URL (actual value or empty)
    client_id: str  # OAuth client ID (actual value or empty)
    client_secret_set: bool  # True if client_secret is configured (value NOT exposed)
    auth_scope: str  # OAuth scope (actual value or empty)
    auth_type: str  # Authentication type (actual value or empty)
    tenant: str  # Tenant identifier (actual value or empty)
    star: str  # Star identifier (actual value or empty)
    chat_endpoint: str  # Chat API endpoint (actual value or empty)
    api_key_set: bool  # True if API key is configured (value NOT exposed)
    model: str  # Model name/identifier (actual value)


class DefaultDBConfig(BaseModel):
    """
    Default database configuration exposed to frontend.

    SECURITY: The connection_url is masked to hide passwords.
    The connection_url_set boolean indicates whether a URL is configured.
    """

    db_type: str
    connection_url: str  # Masked URL (password replaced with ****)
    connection_url_set: bool  # True if connection_url is configured (for frontend logic)
    name: str


class DefaultConfigResponse(BaseModel):
    """Response containing default configuration"""

    has_defaults: bool
    llm_config: DefaultLLMConfig
    db_config: DefaultDBConfig


# ============== Health Response Models ==============


class HealthCheckResponse(BaseModel):
    """Response for /health endpoint"""

    status: str
    timestamp: str
    app: str
    version: str
    redis_connected: bool


class LivenessResponse(BaseModel):
    """Response for /health/live endpoint"""

    status: str
    timestamp: str


class ReadinessResponse(BaseModel):
    """Response for /health/ready endpoint"""

    ready: bool
    timestamp: str
    checks: Dict[str, Any]  # Contains booleans for status and floats for latency_ms


class ServiceHealthDetail(BaseModel):
    """Health details for a single service"""

    healthy: bool
    type: Optional[str] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None
    collections: Optional[int] = None
    persist_dir: Optional[str] = None
    active_pools: Optional[int] = None
    pools: Optional[Dict[str, Any]] = None
    backend: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    active_sessions: Optional[int] = None


class DetailedHealthResponse(BaseModel):
    """Response for /health/detailed endpoint"""

    healthy: bool
    timestamp: str
    check_duration_ms: float
    app: str
    version: str
    checks: Dict[str, Any]


class DiagnosticResponse(BaseModel):
    """
    Response for /health/diagnostic endpoint.

    Exposes Phase 1 reliability fix effectiveness so operators can verify
    that the fixes are actually catching bugs in production. Each counter
    represents one instance where the corresponding fix prevented a
    silently-masked failure. See docs/architecture-audit-2026-04-16.md.
    """

    timestamp: str
    fix_flags: Dict[str, bool]    # which Phase 1 fixes are enabled
    fix_events: Dict[str, int]    # count of bugs each enabled fix caught


# ============== Session Response Models ==============


class SessionDetailResponse(BaseModel):
    """Response for GET /sessions/{session_id}"""

    id: str
    created_at: str
    updated_at: str
    locked: bool
    history_count: int
    db_type: str
    llm_provider: str
    token_info: Optional[Dict[str, Any]] = None
    schema_ready: bool = False
    schema_table_count: int = 0
    schema_error: Optional[str] = None


class SchemaStatusResponse(BaseModel):
    """Response for GET /sessions/{session_id}/schema-status"""

    session_id: str
    schema_ready: bool
    table_count: int
    error: Optional[str] = None
    message: str


class SessionListResponse(BaseModel):
    """Response for GET /sessions"""

    sessions: List[SessionInfo]


class TokenRefreshResponse(BaseModel):
    """Response for POST /sessions/{session_id}/refresh-token"""

    success: bool
    token_info: Optional[Dict[str, Any]] = None


class CSRFTokenResponse(BaseModel):
    """Response for GET /sessions/{session_id}/csrf-token"""

    csrf_token: str


# ============== Generic Response Models ==============


class MessageResponse(BaseModel):
    """Generic message response"""

    message: str


class FeedbackResponse(BaseModel):
    """Response for POST /feedback"""

    message: str
    rating: int


# ============== Schema Response Models ==============


class RefreshSchemaResponse(BaseModel):
    """Response for POST /schema/refresh"""

    message: str
    status: str


class LoadedSchemaInfo(BaseModel):
    """Info about a loaded schema in vector DB"""

    connection_hash: str
    table_count: int
    tables: List[str]
    truncated: bool = False


class VectorDBStatsResponse(BaseModel):
    """Response for GET /schema/vector-db/stats"""

    db_type: str
    embedding_enabled: bool
    collections: Dict[str, int]
    loaded_schemas: List[LoadedSchemaInfo] = []
    error: Optional[str] = None


class EmbeddingTestResponse(BaseModel):
    """Response for GET /schema/test-embedding"""

    embedding_enabled: bool
    test_query: str
    embedding_generated: bool
    embedding_dimension: Optional[int] = None
    error: Optional[str] = None


class VectorDBSearchResponse(BaseModel):
    """Response for GET /schema/vector-db/search"""

    query: str
    connection_url_provided: bool
    matches: List[Any] = []
    connection_hash: Optional[str] = None
    schema_text: Optional[str] = None
    schema_found: Optional[bool] = None
    message: Optional[str] = None
    error: Optional[str] = None


class DebugSchemaResponse(BaseModel):
    """Response for GET /schema/debug/{session_id}"""

    session_id: str
    db_type: str
    connection_hash_for_lookup: str
    schema_ready_in_session: bool
    schema_error_in_session: Optional[str] = None
    vector_db_type: str
    embedding_enabled: bool
    stored_hashes: List[str] = []
    hash_match_found: bool
    warning: Optional[str] = None
    schema_preview: Optional[str] = None
    schema_found: bool = False
    error: Optional[str] = None


class SchemaResponse(BaseModel):
    """Response for GET /schema/{session_id}"""

    schema_text: Optional[str] = None
    # When returning full schema dict, these fields are populated
    db_type: Optional[str] = None
    tables: Optional[List[Dict[str, Any]]] = None
    views: Optional[List[Dict[str, Any]]] = None
    collections: Optional[List[Dict[str, Any]]] = None
    extracted_at: Optional[str] = None


# ============== LLM Usage Response Model ==============


class LLMUsage(BaseModel):
    """Token usage and cost data from LLM call"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0
    cached: bool = False


# ============== Metrics Response Models ==============


class RequestMetrics(BaseModel):
    """Request-related metrics"""

    total: int
    success: int
    errors: int
    success_rate: float


class LLMMetrics(BaseModel):
    """LLM-related metrics"""

    total_requests: int
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    errors: int
    avg_latency_ms: float
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    estimated_cost_usd: float = 0.0


class DatabaseMetrics(BaseModel):
    """Database-related metrics"""

    queries_executed: int
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    pool_stats: Dict[str, Any] = {}


class AgentMetrics(BaseModel):
    """SQL Agent metrics"""

    total_runs: int
    total_retries: int
    successes: int
    failures: int
    success_rate: float
    avg_attempts: float


class SessionMetrics(BaseModel):
    """Session-related metrics"""

    active: int
    queries_generated: int


class DetailedMetricsResponse(BaseModel):
    """Response for GET /metrics/detailed"""

    timestamp: str
    uptime_seconds: float
    requests: RequestMetrics
    llm: LLMMetrics
    database: DatabaseMetrics
    agent: AgentMetrics
    sessions: SessionMetrics


# ============== Error Response Models ==============


class ErrorDetail(BaseModel):
    """Detailed error information"""

    field: Optional[str] = None
    message: str
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    """
    Standardized error response for all API errors.

    Used for 4xx and 5xx HTTP responses across all endpoints.
    """

    error: str = Field(..., description="Error type or category")
    message: str = Field(..., description="Human-readable error message")
    status_code: int = Field(..., description="HTTP status code")
    request_id: Optional[str] = Field(
        None, description="Correlation ID for request tracing"
    )
    details: Optional[List[ErrorDetail]] = Field(
        None, description="Additional error details"
    )
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp of error")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "error": "ValidationError",
                    "message": "Invalid request parameters",
                    "status_code": 400,
                    "request_id": "req_abc123",
                    "details": [
                        {"field": "session_id", "message": "Session not found"}
                    ],
                    "timestamp": "2025-01-15T10:30:00Z",
                },
                {
                    "error": "NotFound",
                    "message": "Session not found",
                    "status_code": 404,
                    "request_id": "req_def456",
                    "timestamp": "2025-01-15T10:30:00Z",
                },
            ]
        }
    }


# ============== Negative Examples (Failed Queries) ==============


class NegativeExample(BaseModel):
    """A failed query stored for learning to avoid repeating mistakes."""

    question: str = Field(..., description="The natural language question")
    failed_sql: str = Field(..., description="The SQL that failed")
    error_message: str = Field(..., description="The error message from the database")
    error_type: str = Field(
        ..., description="Classified error type (syntax, semantic, timeout, etc.)"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now, description="When the failure occurred"
    )


# ============== DML (Data Modification Language) ==============


class DMLMode(str, Enum):
    """DML execution mode - controls how INSERT/UPDATE/DELETE are handled."""

    DISABLED = "disabled"  # No DML allowed (current default behavior)
    PREVIEW = "preview"  # Show what would change, don't execute
    SANDBOX = "sandbox"  # Execute in transaction, auto-rollback
    CONFIRM = "confirm"  # Execute with explicit user confirmation


class DMLPreviewResult(BaseModel):
    """Result of DML preview analysis - shows what would happen without executing."""

    operation: str = Field(
        ..., description="DML operation type: INSERT, UPDATE, or DELETE"
    )
    table: str = Field(..., description="Target table name")
    estimated_rows_affected: int = Field(
        ..., description="Estimated number of rows affected"
    )
    sample_changes: List[Dict[str, Any]] = Field(
        default=[], description="Sample of rows that would be affected"
    )
    warnings: List[str] = Field(
        default=[], description="Safety warnings about the operation"
    )
    sql: str = Field(..., description="The DML SQL statement")


class DMLExecuteRequest(BaseModel):
    """Request to execute a DML statement."""

    session_id: str = Field(..., description="Session ID")
    sql: str = Field(..., description="DML SQL statement to execute")
    mode: DMLMode = Field(..., description="Execution mode")
    confirmation_token: Optional[str] = Field(
        None, description="Required for CONFIRM mode"
    )


class DMLExecuteResponse(BaseModel):
    """Response from DML execution."""

    success: bool = Field(..., description="Whether execution succeeded")
    rows_affected: int = Field(default=0, description="Number of rows affected")
    message: str = Field(..., description="Human-readable result message")
    rollback_performed: bool = Field(
        default=False, description="True if changes were rolled back (SANDBOX mode)"
    )
    execution_time: float = Field(default=0.0, description="Execution time in seconds")


class DMLConfirmationRequest(BaseModel):
    """Request a confirmation token for DML execution."""

    session_id: str = Field(..., description="Session ID")
    sql: str = Field(..., description="DML SQL statement to confirm")


class DMLConfirmationResponse(BaseModel):
    """Response with confirmation token for DML execution."""

    confirmation_token: str = Field(
        ..., description="Token to use for confirmed execution"
    )
    expires_in_seconds: int = Field(default=300, description="Token expiry time")
    message: str = Field(default="Token generated. Use this to confirm DML execution.")


# ============== Common Error Responses for OpenAPI ==============
# Use these in endpoint `responses` parameter for consistent documentation

ERROR_RESPONSES = {
    400: {
        "model": ErrorResponse,
        "description": "Bad Request - Invalid input parameters or configuration",
    },
    403: {
        "model": ErrorResponse,
        "description": "Forbidden - Security check failed or access denied",
    },
    404: {
        "model": ErrorResponse,
        "description": "Not Found - Session or resource does not exist",
    },
    422: {
        "model": ErrorResponse,
        "description": "Validation Error - Request body failed validation",
    },
    429: {
        "model": ErrorResponse,
        "description": "Too Many Requests - Rate limit exceeded",
    },
    500: {
        "model": ErrorResponse,
        "description": "Internal Server Error - Unexpected server error",
    },
}

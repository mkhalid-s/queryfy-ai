"""
QueryfyAI - Configuration
"""

import logging
from pathlib import Path
from typing import Any, List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Calculate backend directory path for .env file lookup
_BACKEND_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "QueryfyAI"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" for production, "text" for development

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Vector Database
    VECTOR_DB_TYPE: str = "chromadb"  # chromadb, qdrant
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    QDRANT_URL: Optional[str] = None  # e.g., "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None

    # Embeddings
    EMBEDDING_PROVIDER: str = "local"  # local, openai, none
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"  # for local
    OPENAI_API_KEY: Optional[str] = None  # for openai embeddings

    # Session
    SESSION_EXPIRY_HOURS: int = 24
    TOKEN_REFRESH_BUFFER_SECONDS: int = 300
    MAX_CONTEXT_WINDOW: int = 20
    MAX_HISTORY_ITEMS: int = 100

    # Query History Persistence (PostgreSQL)
    QUERY_HISTORY_RETENTION_DAYS: int = 30  # Days to keep queries in long-term storage

    # Security
    MAX_QUERY_LENGTH: int = 5000
    MAX_SCHEMA_TOKENS: int = 8000
    SESSION_SIGNING_SECRET: Optional[str] = (
        None  # Set this to preserve sessions across restarts
    )

    # Query Execution Limits
    QUERY_TIMEOUT_SECONDS: int = 300  # 5 minutes default for large exports
    MAX_EXPORT_ROWS: int = 1000000  # 1 million rows max for export
    MAX_RESULT_BYTES: int = 500 * 1024 * 1024  # 500MB max result size

    # ============== Caching Configuration ==============
    CACHE_TYPE: str = "auto"  # auto (Redis if available), redis, memory
    CACHE_TTL_LLM: int = 3600  # 1 hour for LLM responses
    CACHE_TTL_QUERY: int = 300  # 5 minutes for query results
    CACHE_TTL_SCHEMA: int = 3600  # 1 hour for schema

    # ============== MCP Server Endpoint (A8 — carve-out gate) ==============
    # A8 ships the MCP JSON-RPC endpoint at /api/v1/mcp behind this gate.
    # Default off so the first main-merge soaks in staging without
    # exposing a fresh public RPC endpoint to production traffic. Flip
    # to True per-environment to enable; flip the default in a separate
    # PR after ≥1 week clean soak.
    #
    # The MCP router is mounted unconditionally as of Tier A.5 — the
    # gate is enforced at the handler with a 503 response. This makes
    # the env var a runtime kill-switch: ops can flip it via SIGHUP
    # without redeploying. (Pre-Tier-A.5 the check fired at import
    # time, so toggling required a worker restart.)
    MCP_ENDPOINT_ENABLED: bool = False

    # Curated allowlist for tools exposed via MCP. Defaults to the 5
    # tools the audit explicitly named as the A8 public surface
    # (search_tables, get_table_schema, execute_and_analyze,
    # inspect_cached_result, lookup_business_term). Set to ``None`` or
    # an empty value to expose every tool the ToolRegistry knows about
    # — this is "opt-in to the wider surface" rather than "opt-in to
    # the curated narrow surface," matching the Architect's P1 from
    # the Pass 2 + Pass 3 reviews.
    #
    # The default is intentionally conservative: an operator who flips
    # `MCP_ENDPOINT_ENABLED=true` without thinking about the catalog
    # gets the 5-tool external contract, not all 18 internal tools.
    # When set to a list (CSV or JSON), `tools/list` and `tools/call`
    # are filtered to that set; entries not in the registry are dropped
    # with a WARN log.
    MCP_EXPOSED_TOOLS: Optional[List[str]] = [
        "search_tables",
        "get_table_schema",
        "execute_and_analyze",
        "inspect_cached_result",
        "lookup_business_term",
    ]

    # Per-route rate limit for the MCP endpoint. Applied to all MCP
    # methods including ``tools/call`` (which can drive
    # ``execute_and_analyze`` and burn LLM tokens at the global
    # 100/min IP default without this guard).
    RATE_LIMIT_MCP: str = "30/minute"

    # ============== Tier B retrieval — query-aware column context ==============
    # When True, ``data_dictionary.get_column_context()`` uses semantic
    # search against the column-descriptions vector collection to rank
    # columns by relevance to the query, and returns only the top
    # ``MAX_COLUMNS_IN_CONTEXT`` descriptions. When False (default),
    # falls back to the pre-Tier-B behaviour of dumping every column
    # description for the table-scoped or connection-scoped set.
    #
    # Default off — flip to True per-environment AFTER a Tier B PR
    # records before/after recall@k numbers measured via the harness
    # at `python -m benchmarks.retrieval.harness`. See F45 in the
    # tracker for the procedural gate.
    FIX_QUERY_AWARE_COLUMN_CONTEXT: bool = False
    MAX_COLUMNS_IN_CONTEXT: int = 20

    # ============== Rate Limiting Configuration ==============
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_LLM: str = "30/minute"  # LLM calls (expensive)
    RATE_LIMIT_QUERY: str = "60/minute"  # Query execution
    RATE_LIMIT_EXPORT: str = "10/minute"  # Export operations

    # ============== SQL Agent Configuration ==============
    AGENT_MAX_RETRIES: int = 3  # Self-healing retry attempts
    AGENT_USE_POSTGRES_STATE: bool = True  # PostgreSQL state for horizontal scaling
    AGENT_TIMEOUT_SECONDS: int = 120  # Agent execution timeout
    ANALYST_TIMEOUT_SECONDS: int = 180  # Analyst mode timeout (0 = use standard timeout)
    # Wall-clock budget on the ReAct agent's iteration loop.
    # Without this, a slow query × 10 iterations could push the
    # agent to ~50 min worst case. 600 s sits well above any single-
    # tool timeout (data lake = 5 min) and well below the unguarded
    # worst case. Set to 0 to disable.
    AGENT_WALL_CLOCK_BUDGET_SECONDS: int = 600

    # Auto-refresh schema for MongoDB on column-not-found events.
    # MongoDB schema is inferred via document sampling — there is no
    # live-metadata API equivalent to Cassandra's system_schema or
    # DynamoDB's DescribeTable. So a per-column-not-found refresh
    # for Mongo would just re-sample documents (same cost as the
    # manual /schema/refresh endpoint). Default OFF; manual endpoint
    # still works. Operators opt in.
    SCHEMA_AUTO_REFRESH_MONGO: bool = False
    # Auto-trigger a single-table schema refresh in the background
    # when the agent classifies a tool error as COLUMN_NOT_FOUND.
    # Best-effort — extracts the table name from the failing SQL via
    # regex; on parse failure or refresh failure the agent's recovery
    # hint still fires (just no fresh schema for the next iteration).
    # Default ON; flip to False to disable.
    SCHEMA_AUTO_REFRESH_ON_COLUMN_NOT_FOUND: bool = True

    @property
    def effective_analyst_timeout(self) -> int:
        """Get effective analyst timeout (falls back to AGENT_TIMEOUT_SECONDS if 0)"""
        return self.ANALYST_TIMEOUT_SECONDS if self.ANALYST_TIMEOUT_SECONDS > 0 else self.AGENT_TIMEOUT_SECONDS

    # ============== Agent Query & Analysis Limits ==============
    # PROGRESSIVE ROLLOUT STRATEGY:
    #   Phase 1 (Weeks 1-2): 1000/10000 - Conservative start, monitor OOM/latency
    #   Phase 2 (Weeks 3-4): 2500/10000 - Increase if P95 < 8s and OOM = 0
    #   Phase 3 (Weeks 5-6): 5000/20000 - Target limits if metrics remain good
    #
    # RATIONALE: Starting conservative prevents:
    #   - Out-of-memory errors on large result sets
    #   - P95 latency spikes (analysis time grows O(n))
    #   - False positive circuit breaker stops (sampling reduces load)
    #
    # CURRENT PHASE: Phase 1 (Conservative Start)
    AGENT_QUERY_LIMIT_DEFAULT: int = 1000  # Phase 1: Conservative start
    AGENT_QUERY_LIMIT_MAX: int = 10000     # Phase 1: Memory safety cap
    AGENT_TOOL_TIMEOUT: int = 30           # Tool execution timeout in seconds
    #
    # TO INCREASE LIMITS (Future Phases):
    # 1. Update values above to Phase 2 or Phase 3 targets
    # 2. Monitor metrics for 1-2 weeks (P95 latency, OOM errors, circuit breaker rate)
    # 3. Rollback if: OOM > 0, P95 > 8s, or user complaints > 5%

    # Message History Truncation (prevents context overflow)
    AGENT_MAX_MESSAGES: int = 50  # Max messages before truncation kicks in
    AGENT_PRESERVE_RECENT: int = 20  # Recent messages to always preserve
    AGENT_MAX_TOOL_OUTPUT: int = 4000  # Max chars per tool output (truncate if larger)
    AGENT_STREAM_TOOL_OUTPUT: int = 500  # Max chars for streaming tool output (shorter for UI)

    # ============== Phase 1 Reliability Fix Flags ==============
    # AMNESTIED 2026-05-12 — the Phase 1 flags (Day 1a/1b/2a/2b/2c/4)
    # have been True-default in production since 2026-04-16 with no
    # rollback events. Per the 12-perspective review Architect + Critic
    # P1 (knob proliferation), these are now permanent code paths. See
    # docs/architecture-audit-2026-04-16.md for the underlying remediation
    # rationale; the legacy rollback branches have been removed from:
    #   - react_agent.py (FIX_JSON_ERROR_DETECTION, FIX_SUCCESS_FIELD_CHECK, FIX_DATA_LAKE_TIMEOUT)
    #   - analysis_engines/insight_detector.py (FIX_COLUMN_NAME_FIELD,
    #     FIX_INSIGHT_DEDUPLICATION, FIX_DATE_BASED_TRENDS)
    #   - analysis_engines/column_classifier.py (FIX_SMART_ID_EXCLUSION)
    # Phase 2/3/4 flags are still True-default but retained for now —
    # their rollback paths are newer and still arguably load-bearing.

    # ============== Phase 2 Reliability Fix Flags ==============
    # Phase 2 state-machine / infrastructure hardening. Same flag-gated
    # rollback pattern as Phase 1. Remove once stable.
    FIX_TWO_COUNTER_CIRCUIT_BREAKER: bool = True  # Day 1: split iterations_without_execution into exploration vs. sql_attempts_failed
    FIX_DISTRIBUTED_LOCK_FAIL_LOUD: bool = True   # Day 3: fail-loud when Redis unavailable in production (instead of silent local fallback)
    FIX_BACKGROUND_LOCK_EXTENSION: bool = True    # Day 3: extend lock in background task, not event-driven per iteration
    FIX_POOL_PREFLIGHT: bool = True               # Day 3: validate pooled connections with SELECT 1 before yielding

    # ============== Phase 3a Reliability Fix Flags ==============
    # Data-lake foundation. Replaces the Phase 1 Day 4 binary timeout
    # split with an explicit per-DB map so each engine gets a limit that
    # matches its typical query-duration profile.
    FIX_DB_SPECIFIC_TIMEOUTS: bool = True  # Day 1: explicit per-DB tool-execution timeout map
    FIX_SSE_HEARTBEAT: bool = True         # Day 2: server-side heartbeat so long queries don't time out on proxies
    FIX_AGGREGATION_DETECTION: bool = True # Day 3: flag aggregated queries in execution_result

    # Phase 3b — native-async executors
    FIX_QUERY_PROGRESS_EVENTS: bool = True  # 3b.2: emit query_progress SSE events from async drivers

    # Phase 3c — analytics excellence
    FIX_AGGREGATED_MODE_THRESHOLDS: bool = True  # 3c.1: aggregated-mode insight thresholds
    FIX_PROMPT_AGGREGATION_HINT: bool = True     # 3c.2: conditional GROUP BY hint in analyst system prompt

    # Phase 4 — size-unbounded analysis (full-dataset insights, rows cached out-of-band)
    FIX_RESULT_CACHE: bool = True      # 4.0/4.1: store full rows in ResultCache, return rows_ref from execute_and_analyze
    RESULT_CACHE_TTL_SECONDS: int = 1800  # 30 min — matches default session TTL

    # ============== Deployment Mode ==============
    # DEVELOPMENT_MODE allows certain dev-only conveniences (e.g. local
    # asyncio.Lock fallback when Redis is unavailable). Must be False in
    # production — multi-worker deployments without Redis have no cross-
    # worker lock protection and can corrupt state on concurrent runs.
    DEVELOPMENT_MODE: bool = False

    # ============== Scalability Configuration ==============
    WORKERS: int = 4  # Number of worker processes (0 = auto)
    DATABASE_URL: Optional[str] = None  # PostgreSQL for sessions/state (prod)

    # ============== OpenTelemetry Configuration ==============
    OTEL_ENABLED: bool = False  # Enable OpenTelemetry tracing
    OTEL_SERVICE_NAME: str = "queryfyai-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"  # Jaeger OTLP gRPC
    OTEL_TRACES_SAMPLER: str = "parentbased_traceidratio"
    OTEL_TRACES_SAMPLER_ARG: float = 1.0  # 1.0 = sample all traces

    # ============== Default LLM Configuration ==============
    # These can be set via environment variables to provide pre-configured defaults
    # Users can override any of these in the frontend
    DEFAULT_LLM_PROVIDER: str = (
        "oauth_gateway"  # oauth_gateway, openai, anthropic, azure, custom
    )
    DEFAULT_LLM_BASE_URL: Optional[str] = None
    DEFAULT_LLM_TOKEN_URL: Optional[str] = None
    DEFAULT_LLM_CLIENT_ID: Optional[str] = None
    DEFAULT_LLM_CLIENT_SECRET: Optional[str] = None
    DEFAULT_LLM_AUTH_SCOPE: Optional[str] = None
    DEFAULT_LLM_AUTH_TYPE: str = "client_credentials"
    DEFAULT_LLM_TENANT: Optional[str] = None
    DEFAULT_LLM_STAR: Optional[str] = None
    DEFAULT_LLM_CHAT_ENDPOINT: Optional[str] = None
    DEFAULT_LLM_API_KEY: Optional[str] = None
    DEFAULT_LLM_MODEL: str = "gpt-4"

    # ============== Default Database Configuration ==============
    DEFAULT_DB_TYPE: str = "postgresql"
    DEFAULT_DB_CONNECTION_URL: Optional[str] = None
    DEFAULT_DB_NAME: Optional[str] = None

    def get_default_llm_config(self) -> dict:
        """Get default LLM configuration as a dictionary"""
        return {
            "provider": self.DEFAULT_LLM_PROVIDER,
            "base_url": self.DEFAULT_LLM_BASE_URL or "",
            "token_url": self.DEFAULT_LLM_TOKEN_URL or "",
            "client_id": self.DEFAULT_LLM_CLIENT_ID or "",
            "client_secret": self.DEFAULT_LLM_CLIENT_SECRET or "",
            "auth_scope": self.DEFAULT_LLM_AUTH_SCOPE or "",
            "auth_type": self.DEFAULT_LLM_AUTH_TYPE,
            "tenant": self.DEFAULT_LLM_TENANT or "",
            "star": self.DEFAULT_LLM_STAR or "",
            "chat_endpoint": self.DEFAULT_LLM_CHAT_ENDPOINT or "",
            "api_key": self.DEFAULT_LLM_API_KEY or "",
            "model": self.DEFAULT_LLM_MODEL,
        }

    def get_default_db_config(self) -> dict:
        """Get default database configuration as a dictionary"""
        return {
            "db_type": self.DEFAULT_DB_TYPE,
            "connection_url": self.DEFAULT_DB_CONNECTION_URL or "",
            "name": self.DEFAULT_DB_NAME or "",
        }

    def has_default_llm_config(self) -> bool:
        """Check if meaningful default LLM config is set"""
        # For OAuth gateway, we need at least base_url and token_url
        if self.DEFAULT_LLM_PROVIDER == "oauth_gateway":
            return bool(self.DEFAULT_LLM_BASE_URL and self.DEFAULT_LLM_TOKEN_URL)
        # For direct providers, we need api_key
        return bool(self.DEFAULT_LLM_API_KEY)

    def validate_config(self) -> list[str]:
        """
        Validate configuration and return list of warnings.
        Raises ValueError for critical misconfigurations.
        """
        warnings = []

        # Validate vector DB configuration
        if self.VECTOR_DB_TYPE == "qdrant" and not self.QDRANT_URL:
            raise ValueError("QDRANT_URL required when VECTOR_DB_TYPE=qdrant")

        # Validate embedding configuration
        if self.EMBEDDING_PROVIDER == "openai" and not self.OPENAI_API_KEY:
            warnings.append(
                "EMBEDDING_PROVIDER=openai but OPENAI_API_KEY not set - falling back to local"
            )

        # Security: enforce signing secret in production
        if not self.SESSION_SIGNING_SECRET:
            if not self.DEBUG:
                raise ValueError(
                    "SESSION_SIGNING_SECRET must be set when DEBUG=False. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            else:
                warnings.append(
                    "SESSION_SIGNING_SECRET not set - sessions won't persist across restarts"
                )

        # Validate rate limit format
        valid_rate_formats = ["minute", "hour", "day", "second"]
        for limit_name in [
            "RATE_LIMIT_DEFAULT",
            "RATE_LIMIT_LLM",
            "RATE_LIMIT_QUERY",
            "RATE_LIMIT_EXPORT",
        ]:
            limit_value = getattr(self, limit_name)
            if "/" not in limit_value or not any(
                f in limit_value for f in valid_rate_formats
            ):
                warnings.append(
                    f"{limit_name}='{limit_value}' - expected format: 'N/minute', 'N/hour', etc."
                )

        # Validate numeric bounds
        if self.QUERY_TIMEOUT_SECONDS < 1 or self.QUERY_TIMEOUT_SECONDS > 3600:
            warnings.append(
                f"QUERY_TIMEOUT_SECONDS={self.QUERY_TIMEOUT_SECONDS} - consider 1-3600 range"
            )

        if self.AGENT_MAX_RETRIES < 1 or self.AGENT_MAX_RETRIES > 10:
            warnings.append(
                f"AGENT_MAX_RETRIES={self.AGENT_MAX_RETRIES} - consider 1-10 range"
            )

        return warnings

    def log_loaded_config(self) -> None:
        """Log the loaded configuration from environment variables"""
        logger.info("=" * 50)
        logger.info("QueryfyAI Configuration Loaded")
        logger.info("=" * 50)

        # Application settings
        logger.info(f"APP_NAME: {self.APP_NAME}")
        logger.info(f"DEBUG: {self.DEBUG}")
        logger.info(f"LOG_LEVEL: {self.LOG_LEVEL}")
        logger.info(f"LOG_FORMAT: {self.LOG_FORMAT}")
        logger.info(f"HOST: {self.HOST}")
        logger.info(f"PORT: {self.PORT}")

        # Redis
        logger.info(f"REDIS_URL: {self.REDIS_URL}")

        # Vector DB
        logger.info(f"VECTOR_DB_TYPE: {self.VECTOR_DB_TYPE}")
        logger.info(f"CHROMA_PERSIST_DIR: {self.CHROMA_PERSIST_DIR}")
        logger.info(f"QDRANT_URL: {self.QDRANT_URL or '(not set)'}")
        logger.info(
            f"QDRANT_API_KEY: {'***SET***' if self.QDRANT_API_KEY else '(not set)'}"
        )

        # Embeddings
        logger.info(f"EMBEDDING_PROVIDER: {self.EMBEDDING_PROVIDER}")
        logger.info(f"EMBEDDING_MODEL: {self.EMBEDDING_MODEL}")
        logger.info(
            f"OPENAI_API_KEY: {'***SET***' if self.OPENAI_API_KEY else '(not set)'}"
        )

        # Session
        logger.info(f"SESSION_EXPIRY_HOURS: {self.SESSION_EXPIRY_HOURS}")
        logger.info(
            f"TOKEN_REFRESH_BUFFER_SECONDS: {self.TOKEN_REFRESH_BUFFER_SECONDS}"
        )
        logger.info(f"MAX_CONTEXT_WINDOW: {self.MAX_CONTEXT_WINDOW}")
        logger.info(f"MAX_HISTORY_ITEMS: {self.MAX_HISTORY_ITEMS}")

        # Security
        logger.info(f"MAX_QUERY_LENGTH: {self.MAX_QUERY_LENGTH}")
        logger.info(f"MAX_SCHEMA_TOKENS: {self.MAX_SCHEMA_TOKENS}")
        logger.info(
            f"SESSION_SIGNING_SECRET: {'***SET***' if self.SESSION_SIGNING_SECRET else '(not set - sessions will not persist across restarts)'}"
        )

        # Query Execution Limits
        logger.info(f"QUERY_TIMEOUT_SECONDS: {self.QUERY_TIMEOUT_SECONDS}")
        logger.info(f"MAX_EXPORT_ROWS: {self.MAX_EXPORT_ROWS}")
        logger.info(f"MAX_RESULT_BYTES: {self.MAX_RESULT_BYTES // 1024 // 1024}MB")

        # Caching Configuration
        logger.info("-" * 50)
        logger.info("Caching Configuration:")
        logger.info(f"  CACHE_TYPE: {self.CACHE_TYPE}")
        logger.info(f"  CACHE_TTL_LLM: {self.CACHE_TTL_LLM}s")
        logger.info(f"  CACHE_TTL_QUERY: {self.CACHE_TTL_QUERY}s")
        logger.info(f"  CACHE_TTL_SCHEMA: {self.CACHE_TTL_SCHEMA}s")

        # Rate Limiting Configuration
        logger.info("-" * 50)
        logger.info("Rate Limiting Configuration:")
        logger.info(f"  RATE_LIMIT_ENABLED: {self.RATE_LIMIT_ENABLED}")
        logger.info(f"  RATE_LIMIT_DEFAULT: {self.RATE_LIMIT_DEFAULT}")
        logger.info(f"  RATE_LIMIT_LLM: {self.RATE_LIMIT_LLM}")
        logger.info(f"  RATE_LIMIT_QUERY: {self.RATE_LIMIT_QUERY}")
        logger.info(f"  RATE_LIMIT_EXPORT: {self.RATE_LIMIT_EXPORT}")

        # SQL Agent Configuration
        logger.info("-" * 50)
        logger.info("SQL Agent Configuration:")
        logger.info(f"  AGENT_MAX_RETRIES: {self.AGENT_MAX_RETRIES}")
        logger.info(f"  AGENT_USE_POSTGRES_STATE: {self.AGENT_USE_POSTGRES_STATE}")
        logger.info(f"  AGENT_TIMEOUT_SECONDS: {self.AGENT_TIMEOUT_SECONDS}")
        logger.info(f"  AGENT_MAX_MESSAGES: {self.AGENT_MAX_MESSAGES}")
        logger.info(f"  AGENT_PRESERVE_RECENT: {self.AGENT_PRESERVE_RECENT}")
        logger.info(f"  AGENT_MAX_TOOL_OUTPUT: {self.AGENT_MAX_TOOL_OUTPUT}")

        # Phase 1 Reliability Fix Flags — amnestied 2026-05-12 (permanent code paths)
        logger.info("-" * 50)
        logger.info("Phase 1 Reliability Fixes: AMNESTIED (permanent code paths)")

        # Scalability Configuration
        logger.info("-" * 50)
        logger.info("Scalability Configuration:")
        logger.info(f"  WORKERS: {self.WORKERS}")
        logger.info(
            f"  DATABASE_URL: {'***SET***' if self.DATABASE_URL else '(not set)'}"
        )

        # OpenTelemetry Configuration
        logger.info("-" * 50)
        logger.info("OpenTelemetry Configuration:")
        logger.info(f"  OTEL_ENABLED: {self.OTEL_ENABLED}")
        logger.info(f"  OTEL_SERVICE_NAME: {self.OTEL_SERVICE_NAME}")
        logger.info(
            f"  OTEL_EXPORTER_OTLP_ENDPOINT: {self.OTEL_EXPORTER_OTLP_ENDPOINT}"
        )
        logger.info(f"  OTEL_TRACES_SAMPLER: {self.OTEL_TRACES_SAMPLER}")
        logger.info(f"  OTEL_TRACES_SAMPLER_ARG: {self.OTEL_TRACES_SAMPLER_ARG}")

        # Default LLM Configuration
        logger.info("-" * 50)
        logger.info("Default LLM Configuration:")
        logger.info(f"  DEFAULT_LLM_PROVIDER: {self.DEFAULT_LLM_PROVIDER}")
        logger.info(
            f"  DEFAULT_LLM_BASE_URL: {self.DEFAULT_LLM_BASE_URL or '(not set)'}"
        )
        logger.info(
            f"  DEFAULT_LLM_TOKEN_URL: {self.DEFAULT_LLM_TOKEN_URL or '(not set)'}"
        )
        logger.info(
            f"  DEFAULT_LLM_CLIENT_ID: {self.DEFAULT_LLM_CLIENT_ID or '(not set)'}"
        )
        logger.info(
            f"  DEFAULT_LLM_CLIENT_SECRET: {'***SET***' if self.DEFAULT_LLM_CLIENT_SECRET else '(not set)'}"
        )
        logger.info(
            f"  DEFAULT_LLM_AUTH_SCOPE: {self.DEFAULT_LLM_AUTH_SCOPE or '(not set)'}"
        )
        logger.info(f"  DEFAULT_LLM_AUTH_TYPE: {self.DEFAULT_LLM_AUTH_TYPE}")
        logger.info(f"  DEFAULT_LLM_TENANT: {self.DEFAULT_LLM_TENANT or '(not set)'}")
        logger.info(f"  DEFAULT_LLM_STAR: {self.DEFAULT_LLM_STAR or '(not set)'}")
        logger.info(
            f"  DEFAULT_LLM_CHAT_ENDPOINT: {self.DEFAULT_LLM_CHAT_ENDPOINT or '(not set)'}"
        )
        logger.info(
            f"  DEFAULT_LLM_API_KEY: {'***SET***' if self.DEFAULT_LLM_API_KEY else '(not set)'}"
        )
        logger.info(f"  DEFAULT_LLM_MODEL: {self.DEFAULT_LLM_MODEL}")
        logger.info(f"  Has valid LLM defaults: {self.has_default_llm_config()}")

        # Default Database Configuration
        logger.info("-" * 50)
        logger.info("Default Database Configuration:")
        logger.info(f"  DEFAULT_DB_TYPE: {self.DEFAULT_DB_TYPE}")
        logger.info(
            f"  DEFAULT_DB_CONNECTION_URL: {'***SET***' if self.DEFAULT_DB_CONNECTION_URL else '(not set)'}"
        )
        logger.info(f"  DEFAULT_DB_NAME: {self.DEFAULT_DB_NAME or '(not set)'}")

        logger.info("=" * 50)

    @field_validator("MCP_EXPOSED_TOOLS", mode="before")
    @classmethod
    def _parse_mcp_exposed_tools(cls, v: Any) -> Any:
        """Accept either a JSON array OR a comma-separated string (the
        form documented in `.env.production.example`). Empty string →
        None (treat as unset). Whitespace stripped per entry; empty
        entries dropped.

        Strict on JSON: if the value starts with ``[`` we treat it as a
        JSON-array claim and raise on parse failure or non-list payload,
        rather than silently falling back to CSV (which would produce
        garbage like ``['[bad json']`` from a typo).

        Sentinel ``"*"`` (or ``"all"``) explicitly opts in to the full
        ToolRegistry surface — the operator-visible way to say "I want
        every tool exposed, not just the curated default."
        """
        if v is None:
            return None
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return None
            # Explicit opt-out of the curated default — operator wants
            # everything the registry knows about.
            if stripped.lower() in ("*", "all"):
                return None
            if stripped.startswith("["):
                import json

                try:
                    parsed = json.loads(stripped)
                except (ValueError, TypeError) as e:
                    raise ValueError(
                        f"MCP_EXPOSED_TOOLS looks like JSON but failed to "
                        f"parse: {e}. Either fix the JSON or drop the "
                        f"leading '[' and use comma-separated form."
                    )
                if not isinstance(parsed, list):
                    raise ValueError(
                        f"MCP_EXPOSED_TOOLS JSON must be an array; got "
                        f"{type(parsed).__name__}"
                    )
                return [
                    str(tok).strip() for tok in parsed if str(tok).strip()
                ]
            return [
                tok.strip() for tok in stripped.split(",") if tok.strip()
            ]
        return v

    class Config:
        # Look for .env file in multiple locations
        # 1. Current working directory
        # 2. Backend directory (relative to this config file)
        env_file = [".env", str(_BACKEND_DIR / ".env")]
        extra = "allow"


settings = Settings()

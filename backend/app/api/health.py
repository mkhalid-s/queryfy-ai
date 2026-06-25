"""
QueryfyAI - Health Check API Routes
"""

# ============================================
# FILE: app/api/health.py
# ============================================
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.version import __version__ as APP_VERSION
from app.models.schemas import (
    DBTypeInfo,
    DBTypesResponse,
    DetailedHealthResponse,
    DiagnosticResponse,
    HealthCheckResponse,
    LivenessResponse,
    LLMProviderInfo,
    LLMProvidersResponse,
    ReadinessResponse,
)
from app.services.session_store import session_store

router = APIRouter()
logger = get_logger(__name__)


def _measure_latency(func) -> Tuple[Any, float]:
    """Measure execution time of a function in milliseconds"""
    start = time.perf_counter()
    result = func()
    latency_ms = (time.perf_counter() - start) * 1000
    return result, round(latency_ms, 2)


# ----------------------------------------------------------------------
# Phase 2 Day 4: TTL cache for health checks so container orchestrators
# don't hammer dependencies (LLM, DB) on every readiness probe. Default
# TTL 10s — short enough that a dependency outage is detected within
# ~10s but long enough to absorb kube-probe frequencies (~5s).
# ----------------------------------------------------------------------
_health_check_cache: Dict[str, Tuple[float, Any]] = {}
_HEALTH_CACHE_DEFAULT_TTL = 10.0


def _cached_health_check(cache_key: str, ttl: float = _HEALTH_CACHE_DEFAULT_TTL):
    """
    Decorator: cache the result of an async health-check function for ``ttl``
    seconds. The cache key is explicit so multiple decorated functions
    don't collide on name reuse during reload.
    """
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            now = time.monotonic()
            entry = _health_check_cache.get(cache_key)
            if entry is not None and entry[0] > now:
                return entry[1]
            result = await fn(*args, **kwargs)
            _health_check_cache[cache_key] = (now + ttl, result)
            return result

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper

    return decorator


@_cached_health_check("llm", ttl=_HEALTH_CACHE_DEFAULT_TTL)
async def _check_llm_health() -> Dict[str, Any]:
    """
    Phase 2 Day 4: probe the configured default LLM provider. Returns
    ``{"healthy": bool, "latency_ms": float, "error": str?}``.

    Uses a cheap no-op call ('ping' via a 1-token completion). If the
    default LLM config is absent, skip gracefully — the check is only
    meaningful when the app has a configured default.
    """
    try:
        provider = getattr(settings, "DEFAULT_LLM_PROVIDER", None)
        base_url = getattr(settings, "DEFAULT_LLM_BASE_URL", None)
        if not provider or not base_url:
            return {"healthy": True, "skipped": True, "reason": "no-default-llm"}

        # Lazy import to keep health check light and avoid circular imports.
        import httpx

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=3.0) as client:
            # Simple HEAD or GET of the base URL — no auth needed, we're
            # only checking if the endpoint is reachable. A 4xx/401 is
            # fine (host is up); only connection errors are failures.
            resp = await client.get(base_url)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "healthy": True,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "provider": provider,
        }
    except Exception as e:
        logger.warning(f"LLM health check failed: {e}")
        return {"healthy": False, "error": str(e)}


@_cached_health_check("default_db", ttl=_HEALTH_CACHE_DEFAULT_TTL)
async def _check_default_db_health() -> Dict[str, Any]:
    """
    Phase 2 Day 4: probe the default user database (if DEFAULT_DB_CONNECTION_URL
    is configured). The previous /health/ready did not test DB connectivity
    at all — the load balancer routed traffic to instances that couldn't
    reach the DB and every query returned "connection closed".
    """
    try:
        db_type = getattr(settings, "DEFAULT_DB_TYPE", None)
        url = getattr(settings, "DEFAULT_DB_CONNECTION_URL", None)
        if not url:
            return {"healthy": True, "skipped": True, "reason": "no-default-db"}

        from app.models.schemas import DatabaseConfig
        from app.services.connection_pool_manager import pool_manager

        config = DatabaseConfig(
            db_type=db_type or "postgresql",
            connection_url=url,
        )

        start = time.perf_counter()
        result = await pool_manager.health_check(config)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "healthy": bool(result.get("healthy")),
            "latency_ms": latency_ms,
            "db_type": db_type,
            "message": result.get("message"),
        }
    except Exception as e:
        logger.warning(f"Default DB health check failed: {e}")
        return {"healthy": False, "error": str(e)}


async def _check_redis_health() -> Dict[str, Any]:
    """Check Redis connectivity with latency measurement"""
    try:
        if not session_store.redis_client:
            return {"healthy": True, "type": "memory", "latency_ms": None}

        # Actual PING test with latency
        result, latency_ms = _measure_latency(session_store.redis_client.ping)

        if result:
            return {"healthy": True, "type": "redis", "latency_ms": latency_ms}
        else:
            return {"healthy": False, "type": "redis", "error": "Ping failed"}

    except Exception as e:
        logger.warning("Redis health check failed", error=str(e))
        return {"healthy": True, "type": "memory", "error": str(e), "fallback": True}


async def _check_vector_db_health() -> Dict[str, Any]:
    """Check ChromaDB/Qdrant connectivity with latency measurement"""
    try:
        from app.services.vector_db import vector_db

        if not vector_db.client:
            return {"healthy": False, "error": "Client not initialized"}

        db_type = getattr(vector_db, "db_type", "chromadb")
        start = time.perf_counter()

        # Different health check methods for different backends
        if db_type == "qdrant":
            # Qdrant: use get_collections() as health check
            collections = vector_db.client.get_collections().collections
            collection_count = len(collections)
            persist_dir = getattr(settings, "QDRANT_URL", None) or "in-memory"
        else:
            # ChromaDB: use heartbeat()
            vector_db.client.heartbeat()
            collections = vector_db.client.list_collections()
            collection_count = len(collections)
            persist_dir = getattr(
                vector_db, "persist_directory", settings.CHROMA_PERSIST_DIR
            )

        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        return {
            "healthy": True,
            "backend": db_type,
            "latency_ms": latency_ms,
            "collections": collection_count,
            "persist_dir": persist_dir,
        }

    except Exception as e:
        logger.warning("Vector DB health check failed", error=str(e))
        return {"healthy": False, "error": str(e)}


async def _check_langgraph_postgres_health() -> Dict[str, Any]:
    """Check LangGraph PostgreSQL state store connectivity (if configured)"""
    try:
        # Check if LangGraph PostgreSQL is configured
        postgres_uri = getattr(settings, "LANGGRAPH_POSTGRES_URI", None) or getattr(
            settings, "DATABASE_URL", None
        )

        if not postgres_uri:
            return {"healthy": True, "configured": False, "message": "Not configured"}

        # Test connection with simple query
        import asyncpg

        start = time.perf_counter()
        conn = await asyncpg.connect(postgres_uri, timeout=5.0)
        try:
            await conn.fetchval("SELECT 1")
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return {"healthy": True, "configured": True, "latency_ms": latency_ms}
        finally:
            await conn.close()

    except ImportError:
        return {
            "healthy": True,
            "configured": False,
            "message": "asyncpg not installed",
        }
    except Exception as e:
        logger.warning("LangGraph PostgreSQL health check failed", error=str(e))
        return {"healthy": False, "configured": True, "error": str(e)}


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Health check endpoint - comprehensive status"""
    return HealthCheckResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        app=settings.APP_NAME,
        version=APP_VERSION,
        redis_connected=session_store.redis_client is not None,
    )


@router.get("/health/live", response_model=LivenessResponse)
async def liveness_check() -> LivenessResponse:
    """
    Liveness probe - checks if the application is running.
    Used by container orchestrators to determine if the app needs restart.
    """
    return LivenessResponse(status="alive", timestamp=datetime.now().isoformat())


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check():
    """
    Readiness probe - checks if the application can serve traffic.
    Used by container orchestrators to determine if the app should receive requests.

    Returns latency for each internal service check.
    """
    # Run health checks with latency measurement
    redis_health = await _check_redis_health()
    vector_db_health = await _check_vector_db_health()
    # Phase 2 Day 4: actually test LLM + default DB reachability.
    # Results are TTL-cached (10s) so kube probes don't hammer deps.
    llm_health = await _check_llm_health()
    db_health = await _check_default_db_health()

    checks = {
        "redis": redis_health.get("healthy", False),
        "redis_latency_ms": redis_health.get("latency_ms"),
        "vector_db": vector_db_health.get("healthy", False),
        "vector_db_latency_ms": vector_db_health.get("latency_ms"),
        "llm": llm_health.get("healthy", False),
        "llm_latency_ms": llm_health.get("latency_ms"),
        "default_db": db_health.get("healthy", False),
        "default_db_latency_ms": db_health.get("latency_ms"),
    }

    # Log health check results
    logger.debug(
        "Readiness check completed",
        redis_healthy=checks["redis"],
        vector_db_healthy=checks["vector_db"],
        llm_healthy=checks["llm"],
        default_db_healthy=checks["default_db"],
    )

    # Phase 2 Day 4: LLM and default DB are critical in production. If
    # either is unhealthy AND the check wasn't skipped (no config), fail
    # readiness so the LB stops sending traffic. In DEVELOPMENT_MODE or
    # when no default is configured, we allow the app to be ready for
    # custom-config flows.
    llm_critical_fail = (
        not llm_health.get("healthy", True) and not llm_health.get("skipped")
    )
    db_critical_fail = (
        not db_health.get("healthy", True) and not db_health.get("skipped")
    )
    all_critical_ok = not (llm_critical_fail or db_critical_fail)

    status_code = 200 if all_critical_ok else 503

    return JSONResponse(
        status_code=status_code,
        content=ReadinessResponse(
            ready=all_critical_ok,
            timestamp=datetime.now().isoformat(),
            checks=checks,
        ).model_dump(),
    )


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def detailed_health() -> DetailedHealthResponse:
    """
    Detailed health check for all internal services.
    Returns comprehensive status with latency measurements.

    Checks:
    - Redis/Cache (with latency)
    - Vector DB / ChromaDB (with latency)
    - LangGraph PostgreSQL state store (with latency, if configured)
    - Database connection pools
    - Cache service
    - Session store
    """
    checks = {}
    start_time = time.perf_counter()

    # Check Redis/Cache with latency
    checks["cache"] = await _check_redis_health()

    # Check ChromaDB/Vector DB with latency
    checks["vector_db"] = await _check_vector_db_health()

    # Check LangGraph PostgreSQL state store (if configured)
    checks["langgraph_postgres"] = await _check_langgraph_postgres_health()

    # Check Database Connection Pool Manager
    try:
        from app.services.connection_pool_manager import pool_manager

        pool_stats = pool_manager.get_pool_stats()
        checks["database_pools"] = {
            "healthy": True,
            "active_pools": len(pool_stats),
            "pools": pool_stats,
        }
    except Exception as e:
        checks["database_pools"] = {
            "healthy": True,  # No pools is okay at startup
            "active_pools": 0,
            "error": str(e),
        }

    # Check Cache Service
    try:
        from app.services.cache_service import cache_service

        cache_stats = cache_service.get_stats()  # Sync method
        checks["cache_service"] = {
            "healthy": True,
            "backend": cache_stats.get("backend", "unknown"),
            "stats": cache_stats,
        }
    except ImportError:
        checks["cache_service"] = {"healthy": True, "backend": "not_configured"}
    except Exception as e:
        checks["cache_service"] = {"healthy": False, "error": str(e)}

    # Check Session Store
    try:
        storage_info = session_store.get_storage_info()
        checks["session_store"] = {"healthy": True, **storage_info}
    except Exception as e:
        checks["session_store"] = {"healthy": False, "error": str(e)}

    # Calculate overall health
    all_healthy = all(c.get("healthy", False) for c in checks.values())
    check_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    logger.info(
        "Detailed health check completed",
        healthy=all_healthy,
        duration_ms=check_duration_ms,
        services_checked=len(checks),
    )

    return DetailedHealthResponse(
        healthy=all_healthy,
        timestamp=datetime.now().isoformat(),
        check_duration_ms=check_duration_ms,
        app=settings.APP_NAME,
        version=APP_VERSION,
        checks=checks,
    )


@router.get("/health/diagnostic", response_model=DiagnosticResponse)
async def diagnostic_check() -> DiagnosticResponse:
    """
    Phase 1 reliability fix diagnostic endpoint.

    Returns:
    - `fix_flags`: which Phase 1 fixes are currently enabled (from settings)
    - `fix_events`: count of bugs each fix has caught since process start

    Use this endpoint to verify that a deployed fix is actually catching bugs.
    A fix with `flag=True` and `events>0` is doing its job; `flag=True` and
    `events=0` after meaningful traffic may indicate the fix is inactive or
    the bug pattern no longer occurs.

    See docs/architecture-audit-2026-04-16.md for the full list of fixes and
    their intent.
    """
    from app.api.metrics import get_fix_events_snapshot

    return DiagnosticResponse(
        timestamp=datetime.now().isoformat(),
        fix_flags={
            # Phase 1 — amnestied 2026-05-12 (paths now permanent code).
            # Hardcoded True so dashboards reading this endpoint don't
            # show a discontinuity on the amnesty deploy.
            "json_error_detection": True,
            "success_field_check": True,
            "column_name_field": True,
            "insight_deduplication": True,
            "smart_id_exclusion": True,
            "date_based_trends": True,
            "data_lake_timeout": True,
            # Phase 2 — production resilience
            "two_counter_circuit_breaker": settings.FIX_TWO_COUNTER_CIRCUIT_BREAKER,
            "distributed_lock_fail_loud": settings.FIX_DISTRIBUTED_LOCK_FAIL_LOUD,
            "background_lock_extension": settings.FIX_BACKGROUND_LOCK_EXTENSION,
            "pool_preflight": settings.FIX_POOL_PREFLIGHT,
            # Phase 3a — data-lake foundation
            "db_specific_timeouts": settings.FIX_DB_SPECIFIC_TIMEOUTS,
            "sse_heartbeat": settings.FIX_SSE_HEARTBEAT,
            "aggregation_detection": settings.FIX_AGGREGATION_DETECTION,
            # Phase 3b — native-async executor plumbing
            "query_progress_events": settings.FIX_QUERY_PROGRESS_EVENTS,
            # Phase 3c — analytics excellence
            "aggregated_mode_thresholds": settings.FIX_AGGREGATED_MODE_THRESHOLDS,
            "prompt_aggregation_hint": settings.FIX_PROMPT_AGGREGATION_HINT,
            # Phase 4 — size-unbounded analysis
            "result_cache": settings.FIX_RESULT_CACHE,
            # Deployment mode (not a fix flag per se but useful for diag)
            "development_mode": settings.DEVELOPMENT_MODE,
        },
        fix_events=get_fix_events_snapshot(),
    )


@router.get("/api/v1/db-types", response_model=DBTypesResponse)
async def get_db_types() -> DBTypesResponse:
    """Get supported database types with icons for UI rendering"""
    return DBTypesResponse(
        db_types=[
            # SQL Databases
            DBTypeInfo(
                id="postgresql",
                name="PostgreSQL",
                port=5432,
                example="postgresql://user:pass@host:5432/dbname",
                icon="simple-icons:postgresql",
                category="SQL",
            ),
            DBTypeInfo(
                id="mysql",
                name="MySQL",
                port=3306,
                example="mysql://user:pass@host:3306/dbname",
                icon="simple-icons:mysql",
                category="SQL",
            ),
            DBTypeInfo(
                id="sqlserver",
                name="SQL Server",
                port=1433,
                example="mssql://user:pass@host:1433/dbname",
                icon="simple-icons:microsoftsqlserver",
                category="SQL",
            ),
            DBTypeInfo(
                id="oracle",
                name="Oracle",
                port=1521,
                example="oracle://user:pass@host:1521/SID",
                icon="simple-icons:oracle",
                category="SQL",
            ),
            # Cloud Data Warehouses
            DBTypeInfo(
                id="snowflake",
                name="Snowflake",
                port=None,
                example="snowflake://user:pass@account/db/schema?warehouse=WH",
                icon="simple-icons:snowflake",
                category="Cloud",
            ),
            DBTypeInfo(
                id="bigquery",
                name="BigQuery",
                port=None,
                example="bigquery://project-id/dataset",
                icon="simple-icons:googlebigquery",
                category="Cloud",
            ),
            DBTypeInfo(
                id="redshift",
                name="Redshift",
                port=5439,
                example="redshift://user:pass@cluster.region.redshift.amazonaws.com:5439/db",
                icon="simple-icons:amazonredshift",
                category="Cloud",
            ),
            DBTypeInfo(
                id="databricks",
                name="Databricks",
                port=443,
                example="databricks://token:dapi...@host/sql/1.0/warehouses/...",
                icon="simple-icons:databricks",
                category="Cloud",
            ),
            # Analytics Engines
            DBTypeInfo(
                id="clickhouse",
                name="ClickHouse",
                port=9000,
                example="clickhouse://user:pass@host:9000/database",
                icon="simple-icons:clickhouse",
                category="Analytics",
            ),
            DBTypeInfo(
                id="athena",
                name="Athena",
                port=None,
                example="athena://access_key:secret@athena.region.amazonaws.com/database",
                icon="simple-icons:amazonaws",
                category="Analytics",
            ),
            DBTypeInfo(
                id="trino",
                name="Trino",
                port=8080,
                example="trino://user@host:8080/catalog/schema",
                icon="simple-icons:trino",
                category="Analytics",
            ),
            DBTypeInfo(
                id="presto",
                name="Presto",
                port=8080,
                example="presto://user@host:8080/catalog/schema",
                icon="simple-icons:presto",
                category="Analytics",
            ),
            DBTypeInfo(
                id="hive",
                name="Hive",
                port=10000,
                example="hive://user@host:10000/database",
                icon="simple-icons:apachehive",
                category="Analytics",
            ),
            DBTypeInfo(
                id="spark",
                name="Spark SQL",
                port=10000,
                example="spark://user@host:10000/database",
                icon="simple-icons:apachespark",
                category="Analytics",
            ),
            # NoSQL
            DBTypeInfo(
                id="mongodb",
                name="MongoDB",
                port=27017,
                example="mongodb://user:pass@host:27017/dbname",
                icon="simple-icons:mongodb",
                category="NoSQL",
            ),
            DBTypeInfo(
                id="cassandra",
                name="Cassandra",
                port=9042,
                example="cassandra://user:pass@host:9042/keyspace",
                icon="simple-icons:apachecassandra",
                category="NoSQL",
            ),
            DBTypeInfo(
                id="dynamodb",
                name="DynamoDB",
                port=None,
                example="dynamodb://region/ | dynamodb://localhost:8000/",
                icon="simple-icons:amazondynamodb",
                category="NoSQL",
            ),
            # Embedded (Local databases - see deployment docs)
            DBTypeInfo(
                id="duckdb",
                name="DuckDB",
                port=None,
                example="duckdb:///path/to/db.duckdb | duckdb://:memory:",
                icon="simple-icons:duckdb",
                category="Embedded",
            ),
            DBTypeInfo(
                id="sqlite",
                name="SQLite",
                port=None,
                example="sqlite:///path/to/database.db | sqlite:///:memory:",
                icon="simple-icons:sqlite",
                category="Embedded",
            ),
        ]
    )


@router.get("/api/v1/llm-providers", response_model=LLMProvidersResponse)
async def get_llm_providers() -> LLMProvidersResponse:
    """
    Get supported LLM providers with configuration hints for UI rendering.

    Each provider includes:
    - icon: Iconify icon name for UI
    - category: Grouping for UI display
    - requiresApiKey/requiresBaseUrl/requiresOAuth: Configuration requirements
    - defaultModel: Suggested default model
    """
    return LLMProvidersResponse(
        providers=[
            # Enterprise / Corporate
            LLMProviderInfo(
                id="oauth_gateway",
                name="OAuth Gateway (Enterprise)",
                icon="mdi:shield-key",
                category="Enterprise",
                requiresApiKey=False,
                requiresBaseUrl=True,
                requiresOAuth=True,
                defaultModel="gpt-4",
                description="Corporate OAuth-protected LLM gateway",
            ),
            # Major Cloud Providers
            LLMProviderInfo(
                id="openai",
                name="OpenAI",
                icon="simple-icons:openai",
                category="Cloud",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="gpt-4",
                description="GPT-4, GPT-4o, GPT-3.5 Turbo",
            ),
            LLMProviderInfo(
                id="anthropic",
                name="Anthropic",
                icon="simple-icons:anthropic",
                category="Cloud",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="claude-sonnet-4-20250514",
                description="Claude 3.5 Sonnet, Claude 3 Opus/Haiku",
            ),
            LLMProviderInfo(
                id="azure",
                name="Azure OpenAI",
                icon="simple-icons:microsoftazure",
                category="Cloud",
                requiresApiKey=True,
                requiresBaseUrl=True,
                requiresOAuth=False,
                defaultModel="gpt-4",
                description="Azure-hosted OpenAI models",
            ),
            LLMProviderInfo(
                id="bedrock",
                name="AWS Bedrock",
                icon="simple-icons:amazonaws",
                category="Cloud",
                requiresApiKey=False,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="anthropic.claude-3-sonnet-20240229-v1:0",
                description="Claude, Llama, Titan via AWS (uses AWS credentials)",
            ),
            LLMProviderInfo(
                id="vertex_ai",
                name="Google Vertex AI",
                icon="simple-icons:googlecloud",
                category="Cloud",
                requiresApiKey=False,
                requiresBaseUrl=True,
                requiresOAuth=False,
                defaultModel="gemini-1.5-pro",
                description="Gemini via Google Cloud (uses GCP credentials)",
            ),
            LLMProviderInfo(
                id="gemini",
                name="Google Gemini",
                icon="simple-icons:google",
                category="Cloud",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="gemini-1.5-pro",
                description="Direct Gemini API access",
            ),
            # Fast Inference
            LLMProviderInfo(
                id="groq",
                name="Groq",
                icon="mdi:lightning-bolt",
                category="Fast",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="llama-3.1-70b-versatile",
                description="Ultra-fast inference for Llama, Mixtral",
            ),
            # Local / Self-hosted
            LLMProviderInfo(
                id="ollama",
                name="Ollama (Local)",
                icon="mdi:server",
                category="Local",
                requiresApiKey=False,
                requiresBaseUrl=True,
                requiresOAuth=False,
                defaultModel="llama3",
                description="Local LLM server (Llama, Mistral, etc.)",
            ),
            # Open Source Providers
            LLMProviderInfo(
                id="together",
                name="Together AI",
                icon="mdi:account-group",
                category="OpenSource",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="meta-llama/Llama-3-70b-chat-hf",
                description="Open source models (Llama, Mixtral, Qwen)",
            ),
            LLMProviderInfo(
                id="mistral",
                name="Mistral AI",
                icon="simple-icons:mistral",
                category="OpenSource",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="mistral-large-latest",
                description="Mistral Large, Medium, Small",
            ),
            LLMProviderInfo(
                id="cohere",
                name="Cohere",
                icon="mdi:alpha-c-circle",
                category="OpenSource",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="command-r-plus",
                description="Command R+, Command R",
            ),
            LLMProviderInfo(
                id="deepseek",
                name="DeepSeek",
                icon="mdi:magnify-scan",
                category="OpenSource",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="deepseek-chat",
                description="DeepSeek Chat, DeepSeek Coder",
            ),
            LLMProviderInfo(
                id="replicate",
                name="Replicate",
                icon="mdi:cloud-sync",
                category="OpenSource",
                requiresApiKey=True,
                requiresBaseUrl=False,
                requiresOAuth=False,
                defaultModel="meta/llama-2-70b-chat",
                description="Run open source models in the cloud",
            ),
            # Custom / Fallback
            LLMProviderInfo(
                id="custom",
                name="Custom Endpoint",
                icon="mdi:api",
                category="Custom",
                requiresApiKey=True,
                requiresBaseUrl=True,
                requiresOAuth=False,
                defaultModel="gpt-4",
                description="OpenAI-compatible custom endpoint",
            ),
        ]
    )


# ============================================
# FRONTEND CONFIGURATION
# ============================================


@router.get("/config/frontend")
async def get_frontend_config() -> dict:
    """
    Return frontend configuration dynamically from backend settings.
    This allows frontend to adapt to backend configuration without hardcoding values.

    Returns:
        dict: Configuration object with timeouts, limits, and feature flags
    """
    return {
        "timeouts": {
            "default": settings.AGENT_TIMEOUT_SECONDS * 1000,  # Convert to milliseconds
            "analyst": settings.effective_analyst_timeout * 1000,
            "streaming": settings.AGENT_TIMEOUT_SECONDS * 1000,
        },
        "limits": {
            "max_query_length": settings.MAX_QUERY_LENGTH,
            "max_export_rows": 1000000,  # Default max export rows
        },
        "features": {
            "dml_enabled": True,
            "suggestions_enabled": True,
            "retry_enabled": True,
        },
        "app": {
            "name": settings.APP_NAME,
            "version": APP_VERSION,
        }
    }


# ============================================
# CLEANUP ENDPOINTS
# ============================================


@router.get("/health/cleanup/stats")
async def get_cleanup_stats():
    """
    Get cleanup service statistics.
    Shows when cleanup last ran and what was cleaned.
    """
    try:
        from app.services.cleanup_service import cleanup_service

        return {"status": "ok", "cleanup": cleanup_service.get_stats()}
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )


@router.post("/health/cleanup/run")
async def run_cleanup():
    """
    Manually trigger cleanup of stale data.
    Cleans: expired sessions, SQL registry, LangGraph checkpoints, cache.

    Use this for:
    - Manual maintenance
    - Before scaling down instances
    - Testing cleanup behavior
    """
    try:
        from app.services.cleanup_service import cleanup_service

        results = await cleanup_service.run_cleanup()
        return {
            "status": "ok",
            "message": "Cleanup completed",
            "results": results,
            "stats": cleanup_service.get_stats(),
        }
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )


# ============================================
# CACHE INVALIDATION
# ============================================


@router.post("/health/cache/invalidate")
async def invalidate_cache(scope: str = "all", db_hash: Optional[str] = None):
    """
    Manually invalidate cache entries.

    Day 3 fix (see docs/architecture-audit-2026-04-16.md): exposed because the
    default cache TTLs (1 hour for LLM responses, 1 hour for schema, 5 min
    for query results) can serve stale SQL after a schema update. Wiring
    this endpoint to the frontend "Refresh Schema" button prevents the demo
    from seeing cached-wrong answers.

    Query parameters:
        scope: ``"all"`` (clear every cache entry — use sparingly),
               ``"db"`` (clear query+schema caches for one database),
               ``"llm"`` (clear LLM response cache only),
               ``"query"`` (clear query result cache only),
               ``"schema"`` (clear schema cache only). Default ``"all"``.
        db_hash: the target database's connection hash. Required when
                 ``scope="db"``.

    Returns:
        status / message / deleted count where applicable.
    """
    try:
        from app.services.cache_service import cache_service

        if scope == "db":
            if not db_hash:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "error": "db_hash query parameter is required when scope=db",
                    },
                )
            deleted = await cache_service.invalidate_db_cache(db_hash)
            return {
                "status": "ok",
                "message": f"Invalidated {deleted} cache entries for database",
                "scope": "db",
                "deleted": deleted,
            }

        if scope == "all":
            await cache_service.clear_all()
            return {
                "status": "ok",
                "message": "Cleared all cache entries",
                "scope": "all",
            }

        if scope in ("llm", "query", "schema"):
            prefix_map = {
                "llm": cache_service.PREFIX_LLM,
                "query": cache_service.PREFIX_QUERY,
                "schema": cache_service.PREFIX_SCHEMA,
            }
            # Access the backend directly for single-prefix clear; guards
            # mirror the existing invalidate_db_cache pattern.
            cache_service._ensure_initialized()  # type: ignore[attr-defined]
            backend = cache_service._backend  # type: ignore[attr-defined]
            if backend is None:
                return {
                    "status": "ok",
                    "message": "Cache not configured; nothing to clear",
                    "scope": scope,
                    "deleted": 0,
                }
            deleted = await backend.delete_prefix(prefix_map[scope])
            return {
                "status": "ok",
                "message": f"Invalidated {deleted} {scope} cache entries",
                "scope": scope,
                "deleted": deleted,
            }

        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": f"Unknown scope {scope!r}. Use one of: all, db, llm, query, schema.",
            },
        )
    except Exception as e:
        logger.error("Cache invalidation failed", error=str(e))
        return JSONResponse(
            status_code=500, content={"status": "error", "error": str(e)}
        )

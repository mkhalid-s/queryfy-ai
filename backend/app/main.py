"""
QueryfyAI - Main FastAPI Entry Point
"""

# Disable LiteLLM telemetry BEFORE any imports that might load it
import os

os.environ["LITELLM_TELEMETRY"] = "False"

import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    chat,
    consolidated,
    data_dictionary,
    dml,
    health,
    mcp,
    metrics,
    queries,
    schema,
    sessions,
)
from app.api.metrics import record_http_request
from app.core.config import settings
from app.core.database import close_database, init_database
from app.core.logging_config import (
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
)
from app.core.telemetry import get_current_trace_id, init_telemetry, shutdown_telemetry
from app.core.version import __version__ as APP_VERSION
from app.middleware.rate_limit import setup_rate_limiting
from app.services.cache_service import cache_service, initialize_cache
from app.services.checkpointer import (
    get_checkpointer_backend,
    init_checkpointer,
    is_checkpointer_available,
    shutdown_checkpointer,
)
from app.services.cleanup_service import cleanup_service
from app.services.connection_pool_manager import pool_manager
from app.services.distributed_lock import init_distributed_locking
from app.services.session_store import session_store
from app.services.vector_db import vector_db

# Configure structured logging
configure_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = get_logger(__name__)

# Log loaded configuration (after logging is configured)
settings.log_loaded_config()


def initialize_embedding_model():
    """Pre-download and verify the embedding model based on configuration"""
    provider = (
        settings.EMBEDDING_PROVIDER.lower()
        if hasattr(settings, "EMBEDDING_PROVIDER")
        else "local"
    )

    if provider == "none":
        logger.info("📝 Embeddings disabled (EMBEDDING_PROVIDER=none)")
        return True

    if provider == "openai":
        openai_key = getattr(settings, "OPENAI_API_KEY", None)
        if openai_key:
            logger.info("🌐 Using OpenAI embeddings - no local model download needed")
            return True
        else:
            logger.warning(
                "⚠️  OpenAI embeddings configured but no API key, falling back to local"
            )
            provider = "local"

    if provider == "local":
        model_name = getattr(settings, "EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        logger.info(f"📥 Initializing local embedding model ({model_name})...")

        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            # Initialize the default embedding function (downloads model if needed)
            embedding_fn = DefaultEmbeddingFunction()

            # Test the embedding with a sample text
            test_embedding = embedding_fn(["test query for initialization"])

            if (
                test_embedding
                and len(test_embedding) > 0
                and len(test_embedding[0]) > 0
            ):
                logger.info(
                    f"✓ Embedding model ready (dimension: {len(test_embedding[0])})"
                )
                return True
            else:
                logger.error("✗ Embedding model returned empty result")
                return False

        except Exception as e:
            logger.error(f"✗ Failed to initialize embedding model: {e}")
            logger.info("  Attempting direct download via sentence-transformers...")

            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(model_name)
                test = model.encode(["test"])
                logger.info(
                    f"✓ Embedding model downloaded and ready (dimension: {len(test[0])})"
                )
                return True
            except Exception as e2:
                logger.error(f"✗ Failed to download embedding model: {e2}")
                return False

    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    logger.info("=" * 60)
    logger.info("🚀 Starting QueryfyAI...")
    logger.info("=" * 60)

    # Validate configuration at startup
    try:
        config_warnings = settings.validate_config()
        for warning in config_warnings:
            logger.warning(f"⚠️  Config: {warning}")
    except ValueError as e:
        logger.error(f"✗ Configuration error: {e}")
        raise

    # Initialize directories
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)

    # Pre-download and verify embedding model
    embedding_ready = initialize_embedding_model()
    if not embedding_ready:
        logger.warning(
            "⚠️  Embedding model not ready - semantic search may be slow on first use"
        )

    # Initialize vector database
    try:
        _ = vector_db  # Trigger singleton initialization
    except Exception as e:
        logger.error(f"✗ Vector database initialization failed: {e}")

    # Initialize session store and check Redis status
    try:
        _ = session_store  # Trigger singleton initialization
        if session_store.redis_client:
            logger.info(f"✓ Redis connected ({settings.REDIS_URL})")
        else:
            logger.info(
                "📦 Using in-memory session storage (Redis not configured/available)"
            )
        # Seed the queryfyai_active_sessions Prometheus gauge with the
        # post-restart truth, so a worker that comes up with an
        # already-populated Redis doesn't start scraping zero until
        # the next lifecycle event fires.
        session_store._emit_active_sessions_metric()
    except Exception as e:
        logger.warning(f"⚠️  Session store initialization issue: {e}")

    # Initialize PostgreSQL database - run Alembic migrations
    # IMPORTANT: This will FAIL startup if migrations fail (intentional)
    if await init_database():
        logger.info("✓ PostgreSQL migrations applied")
    else:
        logger.info("📦 PostgreSQL not configured")

    # Initialize connection pool manager
    try:
        await pool_manager.start_cleanup_task()
        logger.info("✓ Connection pool manager initialized")
    except Exception as e:
        logger.warning(f"⚠️  Pool manager initialization issue: {e}")

    # Initialize cache service
    try:
        redis_url = settings.REDIS_URL if settings.CACHE_TYPE != "memory" else None
        await initialize_cache(redis_url=redis_url)
        cache_stats = cache_service.get_stats()
        logger.info(
            f"✓ Cache service initialized ({cache_stats.get('backend', 'unknown')})"
        )
    except Exception as e:
        logger.warning(f"⚠️  Cache service initialization issue: {e}")

    # Start cleanup service (background task for stale data)
    try:
        await cleanup_service.start()
        logger.info("✓ Cleanup service started (sessions, SQL registry, checkpoints)")
    except Exception as e:
        logger.warning(f"⚠️  Cleanup service initialization issue: {e}")

    # Initialize LiteLLM
    try:
        import litellm

        litellm.num_retries = 3
        litellm.request_timeout = settings.AGENT_TIMEOUT_SECONDS
        litellm.drop_params = True  # Ignore unsupported params
        logger.info("✓ LiteLLM initialized (telemetry disabled)")
    except Exception as e:
        logger.warning(f"⚠️  LiteLLM initialization issue: {e}")

    # Register AI Data Analyst tools
    try:
        from app.services.tools import (
            ToolRegistry,
            register_all_tools,
            validate_tool_registration,
        )

        register_all_tools()
        tool_count = len(ToolRegistry.get_tool_names())

        # Validate all expected tools are registered
        success, missing_tools = validate_tool_registration()
        if not success:
            logger.warning(f"⚠️  Missing tools: {', '.join(missing_tools)}")
        else:
            logger.info(f"✓ All analyst tools registered ({tool_count} tools)")
    except Exception as e:
        logger.warning(f"⚠️  Tool registration issue: {e}")

    # Initialize OpenTelemetry (if enabled)
    try:
        if init_telemetry():
            logger.info(
                f"✓ OpenTelemetry initialized (endpoint: {settings.OTEL_EXPORTER_OTLP_ENDPOINT})"
            )
        else:
            logger.info("📊 OpenTelemetry disabled or already initialized")
    except Exception as e:
        logger.warning(f"⚠️  OpenTelemetry initialization issue: {e}")

    # Initialize LangGraph checkpointer for ReAct agent state persistence
    # Enables horizontal scaling and resume-on-failure
    try:
        checkpointer = await init_checkpointer()
        if checkpointer:
            backend = get_checkpointer_backend()
            if backend == "memory":
                logger.warning(
                    "⚠️  Checkpointer using in-memory storage (not suitable for production, "
                    "no horizontal scaling, state lost on restart)"
                )
            else:
                logger.info(f"✓ LangGraph checkpointer initialized ({backend})")
        else:
            logger.warning("⚠️  LangGraph checkpointer not available (agent state not persisted)")
    except Exception as e:
        logger.warning(f"⚠️  Checkpointer initialization issue: {e}")

    # Initialize distributed locking for horizontal scaling
    # Prevents concurrent agent runs for same session across instances
    try:
        if init_distributed_locking():
            logger.info("✓ Distributed locking initialized (Redis)")
        else:
            logger.warning(
                "⚠️  Distributed locking: Redis not available "
                "(using local locks only, no cross-instance protection)"
            )
    except Exception as e:
        logger.warning(f"⚠️  Distributed locking initialization issue: {e}")

    logger.info("=" * 60)
    logger.info("✅ Server ready to accept connections")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("👋 Shutting down QueryfyAI...")

    # Phase 2 Day 4: drain in-flight HTTP requests before closing pools
    # so active SSE streams / long data-lake queries aren't interrupted
    # with "connection closed" mid-response.
    try:
        from app.core.shutdown_drain import drain_manager

        drained = await drain_manager.drain(timeout=30.0)
        if drained:
            logger.info("✓ In-flight requests drained")
        else:
            logger.warning("⚠️  Drain timed out; proceeding with shutdown")
    except Exception as e:
        logger.warning(f"⚠️  Shutdown drain failed: {e}")

    # Shutdown checkpointer (release connections)
    try:
        if is_checkpointer_available():
            await shutdown_checkpointer()
            logger.info("✓ Checkpointer shutdown complete")
    except Exception as e:
        logger.warning(f"⚠️  Error shutting down checkpointer: {e}")

    # Stop cleanup service
    try:
        await cleanup_service.stop()
        logger.info("✓ Cleanup service stopped")
    except Exception as e:
        logger.warning(f"⚠️  Error stopping cleanup service: {e}")

    # Close all connection pools
    try:
        await pool_manager.close_all()
        logger.info("✓ Connection pools closed")
    except Exception as e:
        logger.warning(f"⚠️  Error closing connection pools: {e}")

    # Close database connections
    try:
        await close_database()
        logger.info("✓ Database connections closed")
    except Exception as e:
        logger.warning(f"⚠️  Error closing database: {e}")

    # Shutdown OpenTelemetry
    try:
        shutdown_telemetry()
        logger.info("✓ OpenTelemetry shutdown complete")
    except Exception as e:
        logger.warning(f"⚠️  Error shutting down telemetry: {e}")


# OpenAPI tags metadata for better documentation
tags_metadata = [
    {
        "name": "Health",
        "description": "Health checks and readiness probes for container orchestration",
    },
    {
        "name": "Sessions",
        "description": "Session management - create, configure, and manage query sessions",
    },
    {
        "name": "Queries",
        "description": "Natural language to SQL conversion and query execution",
    },
    {
        "name": "Schema",
        "description": "Database schema extraction, caching, and vector search",
    },
    {
        "name": "Consolidated",
        "description": "Combined endpoints for efficient single-request workflows",
    },
    {
        "name": "Metrics",
        "description": "Application metrics and performance monitoring",
    },
    {
        "name": "Data Dictionary",
        "description": "Data Studio for managing business terms, query patterns, and column descriptions",
    },
]

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="""
## QueryfyAI - Natural Language to SQL

Convert natural language questions to SQL queries with:
- **Multi-database support**: PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, BigQuery, MongoDB
- **Enterprise OAuth integration**: Client credentials flow with token management
- **Schema-aware generation**: Vector-indexed schema for accurate SQL generation
- **Self-healing queries**: Automatic retry with error correction via SQL Agent

### Authentication
Sessions are authenticated via CSRF tokens returned on session creation.
Include the token in the `X-CSRF-Token` header for state-changing operations.

### Rate Limiting
API requests are rate-limited. See response headers for limit status.
""",
    version=APP_VERSION,
    lifespan=lifespan,
    openapi_tags=tags_metadata,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS middleware - SECURITY: Restrict origins in production
# Set ALLOWED_ORIGINS env var to comma-separated list of allowed origins
# Default to localhost only if not configured
allowed_origins_raw = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
)
allowed_origins = [
    origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()
]
for origin in allowed_origins:
    if not origin.startswith(("http://", "https://")):
        logger.warning(f"CORS origin '{origin}' missing http/https scheme")
logger.info(f"CORS allowed origins: {allowed_origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "X-Session-Id"],
    expose_headers=["X-CSRF-Token"],
)

# Rate limiting middleware (SlowAPI)
if settings.RATE_LIMIT_ENABLED:
    redis_url = settings.REDIS_URL if settings.CACHE_TYPE != "memory" else None
    setup_rate_limiting(
        app=app,
        redis_url=redis_url,
        enabled=settings.RATE_LIMIT_ENABLED,
        default_limit=settings.RATE_LIMIT_DEFAULT,
    )
    logger.info(f"✓ Rate limiting enabled ({settings.RATE_LIMIT_DEFAULT})")


# Correlation ID middleware for request tracing with structlog context and OpenTelemetry
# Phase 2 Day 4: track in-flight requests so shutdown can drain them.
# Registered FIRST so it wraps all other middlewares.
@app.middleware("http")
async def track_inflight_requests(request: Request, call_next):
    from app.core.shutdown_drain import drain_manager

    # Exclude health probes from the drain count — they are intentionally
    # lightweight and we don't want an orchestrator probe to extend the
    # drain window.
    if request.url.path.startswith("/health"):
        return await call_next(request)

    async with drain_manager.track_request():
        return await call_next(request)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    # Get trace ID from OpenTelemetry if available
    trace_id = get_current_trace_id()

    # Use trace ID as correlation ID (provides trace-log correlation),
    # or fall back to header or generate new one
    correlation_id = (
        trace_id or request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    )

    # Store in request state for use in error responses
    request.state.request_id = correlation_id

    # Bind request context for structured logging (includes trace_id for log correlation)
    bind_context(request_id=correlation_id, trace_id=trace_id)

    try:
        response = await call_next(request)
        # Include correlation ID in response for tracing
        response.headers["X-Request-ID"] = correlation_id
        # Include trace ID if available (for distributed tracing)
        if trace_id:
            response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        # Clear context at end of request
        clear_context()


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # SECURITY: Add security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP - adjust as needed for your frontend
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    )
    return response


# Request logging and metrics middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    duration_ms = (datetime.now() - start_time).total_seconds() * 1000
    duration_seconds = duration_ms / 1000

    # SECURITY: Don't log sensitive paths in detail
    path = request.url.path
    logger.info(
        "HTTP request completed",
        method=request.method,
        path=path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
    )

    # Record Prometheus HTTP metrics (skip metrics endpoint to avoid recursion)
    if path != "/metrics":
        record_http_request(
            method=request.method,
            endpoint=path,
            status=response.status_code,
            duration=duration_seconds,
        )

    return response


# Request body size limit middleware (10MB)
MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024  # 10MB


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large. Maximum size is {MAX_REQUEST_BODY_SIZE // (1024 * 1024)}MB"},
                )
        except ValueError:
            pass
    return await call_next(request)


# Include routers - API v1
app.include_router(health.router, tags=["Health"])
app.include_router(sessions.router, prefix="/api/v1", tags=["Sessions"])
app.include_router(queries.router, prefix="/api/v1", tags=["Queries"])
app.include_router(schema.router, prefix="/api/v1", tags=["Schema"])
app.include_router(consolidated.router, prefix="/api/v1", tags=["Consolidated"])
app.include_router(
    data_dictionary.router, prefix="/api/v1/data-dictionary", tags=["Data Dictionary"]
)
app.include_router(dml.router, prefix="/api/v1", tags=["DML"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
# A8 — MCP server: router mounted unconditionally; the runtime gate
# inside mcp.py returns 503 when settings.MCP_ENDPOINT_ENABLED is
# False. Flipping the env requires a worker restart (gunicorn SIGHUP
# re-execs the master, ~1s connection blip) because pydantic-settings
# reads env once at construction — the gate is "runtime" only in the
# sense that the check runs per-request against the in-process
# settings singleton.
# The default stays False so the first main-merge soaks in staging
# without exposing a fresh public RPC endpoint to prod traffic.
app.include_router(mcp.router, prefix="/api/v1", tags=["MCP"])
if settings.MCP_ENDPOINT_ENABLED:
    logger.info("✓ MCP endpoint enabled at /api/v1/mcp (MCP_ENDPOINT_ENABLED=true)")
else:
    logger.info(
        "📦 MCP endpoint mounted but gated (set MCP_ENDPOINT_ENABLED=true to serve)"
    )
# Seed the MCP enabled gauge so dashboards and the
# MCPEndpointEnabledNoTraffic alert can distinguish "configured but
# no traffic" from "not configured." Narrow the catch: only swallow
# the case where prometheus_client failed to import (the Gauge
# attribute won't exist on the module). A real Gauge-write failure
# should surface.
try:
    metrics.mcp_enabled.set(1 if settings.MCP_ENDPOINT_ENABLED else 0)
except AttributeError:
    pass
app.include_router(metrics.router, tags=["Metrics"])


# Root endpoint
@app.get("/")
async def root():
    result = {
        "app": settings.APP_NAME,
        "version": APP_VERSION,
        "status": "running",
    }
    if settings.DEBUG:
        result["docs"] = "/docs"
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG
    )
